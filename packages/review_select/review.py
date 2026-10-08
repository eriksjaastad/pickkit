"""Apply review triage decisions to an intake'd pickkit batch.

This module is the single source of truth for review-select behaviour: how a
batch is validated as intake'd, how ``keep`` / ``crop`` / ``reject`` decisions
are routed into the locked public destination directories, how the append-only
decision log is written, how the ``review_select`` step in ``project.json`` is
updated, and how each decision is audited. The private precursor reviewer was
an interactive web tool with client-specific IDs, taxonomies, and training
wiring; pickkit's review-select is a small batch library that only moves files
and appends logs — it never rewrites pixels and never invents recommendations.

Principles
----------
Library first
    :func:`apply_decisions` is the whole behaviour; the CLI in this module is a
    thin wrapper around it.
Interactive UI
    ``pickkit-review <batch_root> --ui`` starts the local Flask review page in
    ``review_select.ui`` (``--host`` / ``--port`` override the 127.0.0.1:8765
    defaults). The UI calls :func:`apply_decisions` for every action — it
    never reimplements moves, logs, or manifest updates. Keyboard shortcuts
    on that page are ``K`` / ``1`` keep, ``C`` / ``2`` crop, and ``R`` / ``3``
    reject.
Batch must be intake'd
    ``<batch_root>/.pickkit/project.json`` must already exist (created by
    intake-init). Anything else is refused with :class:`FileNotFoundError`
    before any file is moved or any destination directory is created.
Public destinations
    keep routes to ``__selected``, crop queues to ``__crop`` (no pixel rewrite
    here), and reject routes to ``__reject`` — see :data:`KEEP_DIR_NAME`,
    :data:`CROP_DIR_NAME`, and :data:`REJECT_DIR_NAME`. Destination directories
    are created only on first need by this plugin; intake never creates them.
Move, never modify
    Each decision moves the image plus its same-stem companions with
    ``lib_safety.move_with_companions`` into the destination directory.
    Originals are never overwritten in place and pixels are never rewritten.
    Reject means move to ``__reject``, not trash — trash is for a later
    cleanup plugin.
Decision log
    One JSON object per applied decision is appended to
    ``<batch_root>/.pickkit/decisions.jsonl`` with snake_case keys:
    ``timestamp``, ``action``, ``source``, ``destination``, ``companions``
    (relative paths from the batch root), plus ``note`` only when a note was
    given. Existing lines are never read or rewritten.
Manifest step update
    The existing ``review_select`` entry in ``project.json`` ``steps`` is
    updated in place: ``started_at`` is set on the first applied decision when
    null, ``images_processed`` increments per applied decision, and
    ``finished_at`` is set only when the caller passes the explicit ``finish``
    flag (CLI ``--finish``). No finish ZIP is created here.
Audit
    Every applied decision is recorded through a ``JsonlAuditHook`` on
    ``<batch_root>/.pickkit/audit.jsonl`` and on the optional caller hook.
Refuse, never invent
    Unknown actions, sources outside the batch root, missing sources, and
    destinations that already exist are all refused before anything is moved.
    review-select never invents AI recommendations.

Public API
----------
``apply_decisions(batch_root, decisions, *, finish=False, hook=None)``
    Validate *batch_root* is intake'd, then move each :class:`Decision`'s
    source (with companions) into the destination directory for its action,
    append decision-log records, audit, and update the manifest
    ``review_select`` step. With ``finish=True`` (CLI ``--finish``) the
    step's ``finished_at`` is set after the decisions are applied. Returns an
    :class:`ApplyResult`.
``Decision``
    Frozen dataclass describing one triage decision: ``source`` (image path or
    relative name under the batch root), ``action`` (one of :data:`ACTIONS`),
    optional ``note``, and ``timestamp`` (UTC ``Z`` by default). Unknown
    actions are refused at construction.
``ApplyResult``
    Frozen dataclass describing an applied run: ``batch_root``,
    ``decisions_applied``, ``destinations_touched``, ``finished``,
    ``manifest_path``, and ``decisions_log_path``.
``load_decisions(path)``
    Read decisions from a JSON array file or a JSONL file (one
    ``{"source": ..., "action": ..., "note": ...}`` object per line) and
    return them as a list of :class:`Decision`.
``KEEP_DIR_NAME`` / ``CROP_DIR_NAME`` / ``REJECT_DIR_NAME``
    Locked public destination directory names: ``__selected`` / ``__crop`` /
    ``__reject``.
``KEEP`` / ``CROP`` / ``REJECT`` / ``ACTIONS``
    Snake_case action constants and the tuple of all valid actions
    (``("keep", "crop", "reject")``).
``build_parser()``
    Return the argparse parser for the ``pickkit-review`` CLI. The parser
    description is this module docstring. ``--decisions`` loads a JSON/JSONL
    decisions file; ``--keep`` / ``--crop`` / ``--reject`` accept one image
    path each and are repeatable; ``--finish`` marks the step finished after
    applying; ``--ui`` starts the interactive web UI from ``review_select.ui``
    (with optional ``--host`` / ``--port`` overrides for its 127.0.0.1:8765
    defaults).
``main(argv=None)``
    CLI entry point; parses args and calls :func:`apply_decisions` (or
    :func:`review_select.ui.run_ui` when ``--ui`` is set).

Examples
--------
Apply one keep decision from the library::

    from review_select import Decision, apply_decisions

    result = apply_decisions("tmp/batch_a", [Decision("img_001.png", "keep")])
    result.decisions_applied        # 1
    result.destinations_touched     # ("__selected",)

Triage a batch from the CLI::

    pickkit-review tmp/batch_a --decisions decisions.jsonl --finish

Out of scope
------------
Pixel crops (multi-crop), trash/recycle of rejects (a later cleanup plugin),
AI recommendations, finish ZIP packaging (finish-package), and
client-specific taxonomy/prompts are **not** this module's job. Interactive
UI is **no longer** out of scope: ``review_select.ui`` implements the local
Flask review page and ``pickkit-review <batch_root> --ui`` starts it (see
that module's docstring for UI behaviour, host/port, keyboard shortcuts, and
UI-specific deferrals).
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

    ``source`` may be a path relative to the batch root (``img_001.png``) or
    an absolute path under the batch root. ``timestamp`` defaults to the UTC
    time the :class:`Decision` was created; callers may pass their own ISO-8601
    ``Z`` time. Unknown actions are refused at construction.
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

    For each decision the source image and its same-stem companions are moved
    (never copied, never rewritten) into the destination directory for the
    action: ``__selected`` / ``__crop`` / ``__reject``. One JSON record is
    appended to ``<batch_root>/.pickkit/decisions.jsonl`` per applied decision,
    the ``review_select`` step in ``<batch_root>/.pickkit/project.json`` is
    updated (``started_at`` on first decision, ``images_processed`` bumped,
    ``finished_at`` only with ``finish=True``), and events are recorded on
    ``<batch_root>/.pickkit/audit.jsonl`` plus the optional caller *hook*.

    Refuses with :class:`FileNotFoundError` if *batch_root* is missing, not a
    directory, or not intake'd (no ``project.json`` manifest). All decisions
    are validated before anything is moved; a missing source, unknown action,
    duplicate source, or existing destination aborts the whole call without
    creating destination directories.
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
    """Load decisions from a JSON array file or a JSONL file.

    A ``.jsonl`` file is read one JSON object per line; any other file is read
    as a JSON array of ``{"source": ..., "action": ..., "note": ...}`` objects.
    Blank JSONL lines are skipped. Extra keys (such as the decision-log fields
    written by :func:`apply_decisions`) are ignored.
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

    from .ui import DEFAULT_HOST, DEFAULT_PORT

    if not args.ui and (args.host != DEFAULT_HOST or args.port != DEFAULT_PORT):
        parser.error("--host and --port may only be used together with --ui")

    if args.ui:
        from .ui import run_ui

        if args.decisions or args.keep or args.crop or args.reject or args.finish:
            parser.error(
                "--ui cannot be combined with "
                "--decisions/--keep/--crop/--reject/--finish"
            )
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
