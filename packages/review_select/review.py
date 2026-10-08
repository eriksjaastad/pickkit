"""Apply review triage decisions to an intake'd pickkit batch.

``pickkit-review <batch_root>`` sorts images into keep / crop / reject. Each
decision moves the image and its same-stem companions together into a
destination directory under the batch root; files are never copied,
overwritten or rewritten. Reject is a move to ``__reject``, not a delete.
It prints a JSON summary.

Usage::

    pickkit-review tmp/batch_a --ui                        # local web UI
    pickkit-review tmp/batch_a --decisions decisions.jsonl --finish
    pickkit-review tmp/batch_a --keep img_001.png --crop img_002.png --reject img_003.png

Options
-------
``--decisions PATH``
    A JSON array, or a ``.jsonl`` file with one object per line, of
    ``{"source": ..., "action": "keep|crop|reject", "note": ...}``.
``--keep PATH`` / ``--crop PATH`` / ``--reject PATH``
    One image (relative to the batch root) per flag; each is repeatable.
    Use these or ``--decisions``, not both.
``--finish``
    Set the step's ``finished_at`` after at least one decision is applied.
``--ui``
    Start the local review page (``review_select.ui``); keys K/C/R or 1/2/3.
    ``--host`` / ``--port`` override its 127.0.0.1:8765 bind and are only
    valid with ``--ui``, which cannot be combined with the flags above.

Destinations
------------
keep moves to ``__selected``, crop queues to ``__crop`` (for multi-crop) and
reject moves to ``__reject`` (:data:`KEEP_DIR_NAME`, :data:`CROP_DIR_NAME`,
:data:`REJECT_DIR_NAME`; the valid actions are :data:`ACTIONS`). A directory
is created the first time it is needed.

Every decision is checked before anything moves: an unknown action, a
duplicate or missing source, a source outside the batch root, or an existing
destination refuses the whole run.

Files
-----
The batch must be intake'd (``.pickkit/project.json`` must exist). Each
applied decision appends one record to ``.pickkit/decisions.jsonl`` with
``timestamp``, ``action``, ``source``, ``destination`` and ``companions``
(paths relative to the batch root), plus ``note`` when given; one event to
``.pickkit/audit.jsonl``; and updates the ``review_select`` step
(``started_at`` on the first decision, ``images_processed`` per decision).

Public API
----------
``apply_decisions(batch_root, decisions, *, finish=False, hook=None)``
    Validate, then apply every :class:`Decision`; returns an
    :class:`ApplyResult`.
``Decision``
``ApplyResult``
``load_decisions(path)``
    Read a ``--decisions`` file into a list of :class:`Decision`.
``KEEP_DIR_NAME`` / ``CROP_DIR_NAME`` / ``REJECT_DIR_NAME``
``KEEP`` / ``CROP`` / ``REJECT`` / ``ACTIONS``
``build_parser()``
``main(argv=None)``
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from lib_safety import (
    NULL_HOOK,
    AuditEvent,
    AuditHook,
    DestinationExistsError,
    FanoutHook,
    JsonlAuditHook,
    append_jsonl,
    find_companions,
    find_step,
    load_json_records,
    move_with_companions,
    rel_path,
    require_new_file,
    write_manifest,
)
from lib_safety.audit import utc_now

#: Names the ``review_select`` package re-exports.
__all__ = [
    "ACTIONS",
    "CROP",
    "CROP_DIR_NAME",
    "KEEP",
    "KEEP_DIR_NAME",
    "REJECT",
    "REJECT_DIR_NAME",
    "ApplyResult",
    "Decision",
    "apply_decisions",
    "build_parser",
    "load_decisions",
    "main",
]

#: Shared pickkit state directory and file names (matching intake-init).
PICKKIT_DIR_NAME = ".pickkit"
MANIFEST_NAME = "project.json"
AUDIT_NAME = "audit.jsonl"

#: Append-only decision log written under ``<batch_root>/.pickkit/``.
DECISIONS_LOG_NAME = "decisions.jsonl"

#: Name of the public spine step this plugin owns in ``project.json``.
REVIEW_SELECT_STEP_NAME = "review_select"

#: Locked public destination directory names under the batch root.
KEEP_DIR_NAME = "__selected"
CROP_DIR_NAME = "__crop"
REJECT_DIR_NAME = "__reject"

#: Snake_case decision actions.
KEEP = "keep"
CROP = "crop"
REJECT = "reject"

#: Tuple of all valid decision actions.
ACTIONS: tuple[str, ...] = (KEEP, CROP, REJECT)

#: Destination directory name for each action.
ACTION_DEST_DIRS: dict[str, str] = {
    KEEP: KEEP_DIR_NAME,
    CROP: CROP_DIR_NAME,
    REJECT: REJECT_DIR_NAME,
}

#: Audit operation recorded for each applied decision.
OPERATION = "review_select"


@dataclass(frozen=True)
class Decision:
    """One triage decision: a source image, an action, and optional metadata.

    ``source`` is relative to the batch root or an absolute path under it.
    ``timestamp`` defaults to creation time (UTC ``Z``). Unknown actions are
    refused at construction.
    """

    source: str
    action: str
    note: str | None = None
    timestamp: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.source, Path):
            object.__setattr__(self, "source", str(self.source))
        if not self.source:
            raise ValueError("decision source must not be empty")
        if self.action not in ACTIONS:
            raise ValueError(
                f"unknown action {self.action!r}; expected one of {ACTIONS}"
            )


@dataclass(frozen=True)
class ApplyResult:
    """What :func:`apply_decisions` applied.

    ``destinations_touched`` holds the destination directory names that were
    created or used (e.g. ``("__selected",)``), sorted. ``finished`` is True
    only when ``finish=True`` was passed and at least one decision was applied.
    """

    batch_root: Path
    decisions_applied: int
    destinations_touched: tuple[str, ...]
    finished: bool
    manifest_path: Path
    decisions_log_path: Path


def _resolve_source(root: Path, source: str | Path) -> Path:
    """Resolve a decision source under *root*, refusing paths outside it."""
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"decision source is outside batch root: {source}")
    return resolved


def _plan_decisions(
    root: Path, decisions: list[Decision]
) -> list[tuple[Decision, Path, Path, Path]]:
    """Validate every decision before anything is moved or created.

    Returns ``(decision, source, dest_dir, dest_image)`` tuples. Refuses
    unknown actions, duplicate sources, missing sources, sources outside the
    batch root, and any destination path that already exists.
    """
    planned: list[tuple[Decision, Path, Path, Path]] = []
    seen_sources: set[Path] = set()
    for decision in decisions:
        if decision.action not in ACTIONS:
            raise ValueError(
                f"unknown action {decision.action!r}; expected one of {ACTIONS}"
            )
        source = _resolve_source(root, decision.source)
        if source in seen_sources:
            raise ValueError(f"duplicate source in decisions: {decision.source}")
        seen_sources.add(source)
        if not source.is_file():
            raise FileNotFoundError(f"decision source not found: {source}")

        dest_dir = root / ACTION_DEST_DIRS[decision.action]
        if dest_dir.exists() and not dest_dir.is_dir():
            raise NotADirectoryError(f"destination is not a directory: {dest_dir}")

        companions = tuple(find_companions(source))
        dest_image = dest_dir / source.name
        for target in (dest_image, *(dest_dir / c.name for c in companions)):
            if target.exists():
                raise DestinationExistsError(
                    f"refusing to move {source.name}: destination already exists: {target}"
                )
        planned.append((decision, source, dest_dir, dest_image))
    return planned


def apply_decisions(
    batch_root: str | Path,
    decisions: Iterable[Decision],
    *,
    finish: bool = False,
    hook: AuditHook | None = None,
) -> ApplyResult:
    """Apply *decisions* to an already intake'd batch under *batch_root*.

    Moves each source and its companions into its action's directory and
    writes the log, audit and manifest records described in the module
    docstring; events also go to *hook* when given. ``finish=True`` sets the
    step's ``finished_at``. All decisions are validated first, so a refusal
    moves nothing and creates no directory. Raises :class:`FileNotFoundError`
    for a missing or un-intake'd batch root.
    """
    root = Path(batch_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()

    pickkit_dir = root / PICKKIT_DIR_NAME
    manifest_path = pickkit_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"batch is not intake'd: missing manifest {manifest_path}; "
            f"run pickkit-intake first"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    step = find_step(manifest, REVIEW_SELECT_STEP_NAME, manifest_path)

    decisions = list(decisions)
    hook = hook or NULL_HOOK
    audit_path = pickkit_dir / AUDIT_NAME
    decisions_log_path = pickkit_dir / DECISIONS_LOG_NAME
    fanout = FanoutHook(JsonlAuditHook(audit_path), hook)

    # Pre-flight: validate everything before any directory or file changes.
    planned = _plan_decisions(root, decisions)

    applied = 0
    touched: set[str] = set()
    for decision, source, dest_dir, dest_image in planned:
        # Create the destination dir only when this action is first needed.
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Shared no-overwrite guard (pre-flight already checked, but keep the
        # invariant explicit at the moment of the move).
        require_new_file(dest_image, hook=fanout)
        move_result = move_with_companions(source, dest_dir, hook=fanout)

        record: dict[str, object] = {
            "timestamp": decision.timestamp,
            "action": decision.action,
            "source": rel_path(root, source),
            "destination": rel_path(root, move_result.image),
            "companions": [rel_path(root, c) for c in move_result.companions],
        }
        if decision.note is not None:
            record["note"] = decision.note
        append_jsonl(decisions_log_path, record)

        fanout.record(
            AuditEvent(
                operation=OPERATION,
                source=str(source),
                destination=str(move_result.image),
                companions=tuple(rel_path(root, c) for c in move_result.companions),
                ok=True,
                reason=f"action={decision.action}",
            )
        )

        if step.get("started_at") is None:
            step["started_at"] = utc_now()
        step["images_processed"] = int(step.get("images_processed") or 0) + 1
        applied += 1
        touched.add(dest_dir.name)

    finished = False
    if finish and applied:
        step["finished_at"] = utc_now()
        finished = True

    if applied:
        write_manifest(manifest_path, manifest)

    return ApplyResult(
        batch_root=root,
        decisions_applied=applied,
        destinations_touched=tuple(sorted(touched)),
        finished=finished,
        manifest_path=manifest_path,
        decisions_log_path=decisions_log_path,
    )


def _record_to_decision(
    record: object, path: Path, index: int
) -> Decision:
    if not isinstance(record, dict):
        raise ValueError(f"decision #{index} in {path} must be a JSON object")
    if "source" not in record or "action" not in record:
        raise ValueError(
            f"decision #{index} in {path} must have 'source' and 'action' keys"
        )
    source = record["source"]
    action = record["action"]
    note = record.get("note")
    if not isinstance(source, str) or not isinstance(action, str):
        raise ValueError(
            f"decision #{index} in {path} must have string 'source' and 'action'"
        )
    if note is not None and not isinstance(note, str):
        raise ValueError(f"decision #{index} in {path} has a non-string 'note'")
    return Decision(source=source, action=action, note=note)


def load_decisions(path: str | Path) -> list[Decision]:
    """Load decisions from a JSON array file or a ``.jsonl`` file.

    Each object needs ``source`` and ``action`` and may have ``note``. Extra
    keys are ignored, so a ``decisions.jsonl`` log can be read back.
    """
    return load_json_records(path, "decisions file", _record_to_decision)


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-review`` CLI."""
    from .ui import DEFAULT_HOST, DEFAULT_PORT

    parser = argparse.ArgumentParser(
        prog="pickkit-review",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "batch_root",
        help="Path to an already intake'd batch directory",
    )
    parser.add_argument(
        "--decisions",
        metavar="PATH",
        help="JSON or JSONL decisions file (objects with 'source' and 'action')",
    )
    parser.add_argument(
        "--finish",
        action="store_true",
        help="Mark the review_select step finished after applying decisions",
    )
    parser.add_argument(
        "--keep",
        metavar="PATH",
        action="append",
        default=[],
        help="Keep one image path (relative to batch_root); repeatable",
    )
    parser.add_argument(
        "--crop",
        metavar="PATH",
        action="append",
        default=[],
        help="Queue one image path for crop; repeatable",
    )
    parser.add_argument(
        "--reject",
        metavar="PATH",
        action="append",
        default=[],
        help="Reject one image path; repeatable",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Start the local interactive review web UI (Flask) instead of applying decisions",
    )
    parser.add_argument(
        "--host",
        metavar="HOST",
        default=DEFAULT_HOST,
        help=(
            "Host interface for the --ui web server "
            f"(default: {DEFAULT_HOST})"
        ),
    )
    parser.add_argument(
        "--port",
        metavar="PORT",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port for the --ui web server (default: {DEFAULT_PORT})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args and calls :func:`apply_decisions`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from lib_safety.webui import check_ui_args

    from .ui import DEFAULT_HOST, DEFAULT_PORT, run_ui

    check_ui_args(
        parser,
        args,
        default_host=DEFAULT_HOST,
        default_port=DEFAULT_PORT,
        conflicts="--decisions/--keep/--crop/--reject/--finish",
        conflicting=bool(
            args.decisions or args.keep or args.crop or args.reject or args.finish
        ),
    )
    if args.ui:
        run_ui(args.batch_root, host=args.host, port=args.port)
        return 0

    flag_paths = list(args.keep) + list(args.crop) + list(args.reject)
    if args.decisions and flag_paths:
        parser.error("use either --decisions or --keep/--crop/--reject, not both")

    try:
        if args.decisions:
            decisions = load_decisions(args.decisions)
        else:
            decisions = [
                *(Decision(path, KEEP) for path in args.keep),
                *(Decision(path, CROP) for path in args.crop),
                *(Decision(path, REJECT) for path in args.reject),
            ]
        result = apply_decisions(args.batch_root, decisions, finish=args.finish)
    except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError) as exc:
        parser.exit(1, f"pickkit-review: error: {exc}\n")

    print(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "decisions_applied": result.decisions_applied,
                "destinations_touched": list(result.destinations_touched),
                "finished": result.finished,
                "manifest_path": str(result.manifest_path),
                "decisions_log_path": str(result.decisions_log_path),
            },
            indent=2,
        )
    )
    return 0
