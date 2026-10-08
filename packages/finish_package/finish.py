r"""Close a pickkit batch: finish the manifest and stage a copy-only delivery ZIP.

``pickkit-finish <batch_root>`` scans the batch's delivery content, sorts every
file into eligible or an excluded bucket, and prints the report. It writes
nothing unless ``--commit`` is given. Source files are only ever read.

Usage::

    pickkit-finish tmp/batch_a                    # dry-run report; writes nothing
    pickkit-finish tmp/batch_a --commit           # write delivery.zip, close the manifest
    pickkit-finish tmp/batch_a --commit --force   # overwrite an existing ZIP
    pickkit-finish tmp/batch_a --ui               # local web wizard

Options
-------
``--commit``
    Write the ZIP, then close the manifest. Without it nothing is written: no
    ZIP, no manifest change, no audit.jsonl or finish.jsonl.
``--force``
    Overwrite an existing ZIP. Refused if the ZIP path is one of the scanned
    source files, so a source is never overwritten.
``--content DIR``
    Scan this one directory instead of the default roots. It must resolve
    under the batch root; the allowlist, bans and hidden rule still apply.
``--output PATH``
    Write the ZIP to PATH instead of ``<batch_root>/delivery.zip``. Relative
    paths resolve under the batch root; absolute paths are allowed.
``--ui``
    Start the local finish wizard (``finish_package.ui``). It opens on a
    dry-run preview and writes nothing until Commit ZIP. ``--host`` /
    ``--port`` override its 127.0.0.1:8767 bind and are only valid with
    ``--ui``, which cannot be combined with the flags above.

Files
-----
The batch must be intake'd: ``.pickkit/project.json`` and the inventory
``.pickkit/allowed_ext.json`` (its ``allowedExtensions`` list is the
allowlist) must exist, or the run is refused before any ZIP is written.

The scan covers ``__selected/`` and ``__cropped/`` when they exist.
``__crop/``, ``__reject/`` and ``.pickkit/`` are never scanned by default.

On commit the ZIP is written with ``ZIP_STORED``; member names are paths
relative to the batch root (``__selected/img_001.png``). Then the manifest
gets top-level ``finished_at``; the ``finish_package`` step gets
``started_at`` (if null), ``finished_at`` and ``images_processed`` (eligible
images); and ``metrics.stager`` gets ``zip``, ``eligible_count``,
``by_ext_included``, ``excluded_counts`` and ``incoming_by_ext``. Finally one
``finish_package`` event is appended to ``.pickkit/audit.jsonl`` and a
summary record to ``.pickkit/finish.jsonl``.

Classification
--------------
Each scanned file takes the first bucket that matches, in this order:

* ``hidden``: a path part starts with ``.``;
* ``no_extension``;
* ``banned_ext``: json, md, log, csv, sqlite, db, lock;
* ``banned_pattern``: the basename matches ``.*\.project\.(json|yml)$``;
* ``not_allowed``: the extension is not in the allowlist;
* otherwise eligible.

Bans win over the allowlist. Same-stem companions are classified like any
other file.

Public API
----------
``finish_package(batch_root, *, commit=False, force=False, content=None, output_zip=None, hook=None)``
    Dry-run report or commit; returns a :class:`FinishResult`.
``FinishResult``
``load_manifest(path)``
    Read ``project.json`` as a dict; raises :class:`ManifestError`.
``load_allowlist(path)``
    Read an inventory's ``allowedExtensions`` as a lowercase, dot-free set.
``classify_file(path, batch_root, *, allowed)``
    One of :data:`EXCLUDED_BUCKETS`, or ``"eligible"``.
``default_content_roots(batch_root)``
    The existing ``__selected`` and ``__cropped`` directories, in that order.
``build_parser()``
``main(argv=None)``
``EXCLUDED_BUCKETS``
``PICKKIT_DIR_NAME = ".pickkit"``
``MANIFEST_NAME = "project.json"``
``INVENTORY_NAME = "allowed_ext.json"``
``AUDIT_NAME = "audit.jsonl"``
``FINISH_LOG_NAME = "finish.jsonl"``
``FINISH_PACKAGE_STEP_NAME = "finish_package"``
``DEFAULT_ZIP_NAME = "delivery.zip"``
``SELECTED_DIR_NAME = "__selected"``
``CROPPED_DIR_NAME = "__cropped"``
``CROP_QUEUE_DIR_NAME = "__crop"``
``REJECT_DIR_NAME = "__reject"``
``DEFAULT_BANNED_EXTENSIONS``
``DEFAULT_BANNED_PATTERNS``
``OPERATION = "finish_package"``
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from intake_init import DEFAULT_IMAGE_SUFFIXES
from lib_safety import (
    NULL_HOOK,
    AuditEvent,
    AuditHook,
    FanoutHook,
    JsonlAuditHook,
    RefusedWriteError,
    append_jsonl,
    find_step,
    rel_path,
    require_new_file,
    write_manifest,
)
from lib_safety.audit import utc_now

#: Names the ``finish_package`` package re-exports.
__all__ = [
    "AUDIT_NAME",
    "CROPPED_DIR_NAME",
    "CROP_QUEUE_DIR_NAME",
    "DEFAULT_BANNED_EXTENSIONS",
    "DEFAULT_BANNED_PATTERNS",
    "DEFAULT_ZIP_NAME",
    "EXCLUDED_BUCKETS",
    "FINISH_LOG_NAME",
    "FINISH_PACKAGE_STEP_NAME",
    "INVENTORY_NAME",
    "MANIFEST_NAME",
    "OPERATION",
    "PICKKIT_DIR_NAME",
    "REJECT_DIR_NAME",
    "SELECTED_DIR_NAME",
    "FinishResult",
    "build_parser",
    "classify_file",
    "default_content_roots",
    "finish_package",
    "load_allowlist",
    "main",
]

#: Shared pickkit state directory and file names (matching intake-init).
PICKKIT_DIR_NAME = ".pickkit"
MANIFEST_NAME = "project.json"
INVENTORY_NAME = "allowed_ext.json"
AUDIT_NAME = "audit.jsonl"

#: Optional append-only finish summary written under ``<batch_root>/.pickkit/``.
FINISH_LOG_NAME = "finish.jsonl"

#: Name of the public spine step this plugin owns in ``project.json``.
FINISH_PACKAGE_STEP_NAME = "finish_package"

#: Default delivery ZIP filename under the batch root.
DEFAULT_ZIP_NAME = "delivery.zip"

#: Locked public content directory names under the batch root (matching
#: review-select / multi-crop). ``__crop`` and ``__reject`` are documented as
#: never-scanned-by-default conventions.
SELECTED_DIR_NAME = "__selected"
CROPPED_DIR_NAME = "__cropped"
CROP_QUEUE_DIR_NAME = "__crop"
REJECT_DIR_NAME = "__reject"

#: Default banned extensions (lowercase, no dots). Bans win over the allowlist.
DEFAULT_BANNED_EXTENSIONS: tuple[str, ...] = (
    "json",
    "md",
    "log",
    "csv",
    "sqlite",
    "db",
    "lock",
)

#: Default banned basename regex patterns. Any match excludes the file as
#: ``banned_pattern``.
DEFAULT_BANNED_PATTERNS: tuple[str, ...] = (r".*\.project\.(json|yml)$",)

#: Audit operation recorded for a successful finish-package run.
OPERATION = "finish_package"

#: Excluded-count bucket names, in documented report order.
EXCLUDED_BUCKETS: tuple[str, ...] = (
    "hidden",
    "banned_ext",
    "banned_pattern",
    "not_allowed",
    "no_extension",
)

_COMPILED_BANNED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern) for pattern in DEFAULT_BANNED_PATTERNS
)


@dataclass(frozen=True)
class FinishResult:
    """What :func:`finish_package` computed (dry-run) or wrote (commit).

    ``zip_path`` and ``finished_at`` are ``None`` on dry-run.
    ``by_ext_included`` counts eligible files per lowercase, dot-free
    extension; ``excluded_counts`` always carries every
    :data:`EXCLUDED_BUCKETS` key; ``incoming_by_ext`` counts every non-hidden
    scanned file with an extension, before the allow/ban filter.
    """

    batch_root: Path
    commit: bool
    zip_path: Path | None
    eligible_count: int
    by_ext_included: dict[str, int]
    excluded_counts: dict[str, int]
    incoming_by_ext: dict[str, int]
    finished_at: str | None
    manifest_path: Path
    audit_path: Path
    finish_log_path: Path


def _matches_banned_pattern(basename: str) -> bool:
    return any(regex.search(basename) for regex in _COMPILED_BANNED_PATTERNS)


def _excluded_template() -> dict[str, int]:
    return {bucket: 0 for bucket in EXCLUDED_BUCKETS}


class FinishLogError(Exception):
    """The ZIP and manifest close finished, but a follow-up log write failed.

    ``result`` is the :class:`FinishResult` for the commit that did complete.
    The message names the failure. Callers must report the commit as done.
    """

    def __init__(self, message: str, result: "FinishResult") -> None:
        super().__init__(message)
        self.result = result


class ManifestError(ValueError):
    """``project.json`` could not be read as a JSON object.

    The message always names the manifest path. Callers (the CLI and the
    finish wizard) map this to an error response instead of a traceback.
    """


def load_manifest(path: str | Path) -> dict[str, object]:
    """Read *path* and return the manifest as a JSON object.

    Raises :class:`ManifestError` naming *path* when the path is missing, not
    a regular file, unreadable, not valid UTF-8, not valid JSON, or not an
    object.
    """
    manifest_path = Path(path).expanduser()
    try:
        if manifest_path.is_dir():
            raise ManifestError(
                f"cannot read manifest {manifest_path}: path is a directory"
            )
        # is_file() is false for a FIFO or other special file. Reading those
        # can block forever, so reject them before read_text.
        if not manifest_path.is_file():
            raise ManifestError(
                f"cannot read manifest {manifest_path}: not a regular file"
            )
        text = manifest_path.read_text(encoding="utf-8")
    except ManifestError:
        raise
    except UnicodeDecodeError as exc:
        raise ManifestError(
            f"manifest is not valid UTF-8: {manifest_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise ManifestError(
            f"cannot read manifest {manifest_path}: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(
            f"manifest is not valid JSON: {manifest_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ManifestError(
            f"manifest is not a JSON object: {manifest_path}"
        )
    return data


def load_allowlist(path: str | Path) -> set[str]:
    """Read an intake inventory JSON and return its ``allowedExtensions`` set.

    Extensions are normalized to lowercase without leading dots. Refuses with
    :class:`FileNotFoundError` when *path* is missing and with
    :class:`ValueError` when ``allowedExtensions`` is not a list.
    """
    inventory_path = Path(path).expanduser()
    if not inventory_path.is_file():
        raise FileNotFoundError(
            f"allowlist inventory not found: {inventory_path}; "
            f"run pickkit-intake first"
        )
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    raw = data.get("allowedExtensions")
    if not isinstance(raw, list):
        raise ValueError(
            f"inventory has no 'allowedExtensions' list: {inventory_path}"
        )
    allowed: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(
                f"inventory 'allowedExtensions' entries must be strings: {entry!r}"
            )
        ext = entry.lower().lstrip(".")
        if ext:
            allowed.add(ext)
    return allowed


def classify_file(
    path: str | Path,
    batch_root: str | Path,
    *,
    allowed: set[str],
) -> str:
    """Classify one file against the default bans and the *allowed* set.

    Returns the first matching bucket in the order hidden -> no_extension ->
    banned_ext -> banned_pattern -> not_allowed, else ``"eligible"``.
    """
    file_path = Path(path).expanduser()
    root = Path(batch_root).expanduser()
    try:
        parts = file_path.relative_to(root).parts
    except ValueError:
        parts = file_path.parts
    if any(part.startswith(".") for part in parts):
        return "hidden"
    ext = file_path.suffix.lower().lstrip(".")
    if not ext:
        return "no_extension"
    if ext in DEFAULT_BANNED_EXTENSIONS:
        return "banned_ext"
    if _matches_banned_pattern(file_path.name):
        return "banned_pattern"
    if ext not in allowed:
        return "not_allowed"
    return "eligible"


def default_content_roots(batch_root: str | Path) -> list[Path]:
    """Return the existing ``__selected`` and ``__cropped`` dirs, in that order."""
    root = Path(batch_root).expanduser().resolve()
    candidates = (root / SELECTED_DIR_NAME, root / CROPPED_DIR_NAME)
    return [path for path in candidates if path.is_dir()]


def _resolve_content_override(root: Path, content: str | Path) -> Path:
    candidate = Path(content).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"content directory is outside batch root: {content}")
    if not resolved.exists():
        raise FileNotFoundError(f"content directory not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"content is not a directory: {resolved}")
    return resolved


def _resolve_zip_path(root: Path, output_zip: str | Path | None) -> Path:
    if output_zip is None:
        return root / DEFAULT_ZIP_NAME
    candidate = Path(output_zip).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _scan(
    batch_root: Path,
    content_roots: list[Path],
    allowed: set[str],
) -> tuple[
    list[Path], dict[str, int], dict[str, int], dict[str, int], list[Path]
]:
    """Walk *content_roots* and classify every file.

    Returns ``(eligible, by_ext_included, excluded_counts, incoming_by_ext,
    all_seen)``. ``all_seen`` is every file encountered (including hidden and
    excluded ones) and is used to guarantee ``--force`` never unlinks a source.
    """
    eligible: list[Path] = []
    by_ext_included: dict[str, int] = {}
    excluded_counts = _excluded_template()
    incoming_by_ext: dict[str, int] = {}
    all_seen: list[Path] = []

    for content_root in content_roots:
        for path in sorted(content_root.rglob("*")):
            if not path.is_file():
                continue
            all_seen.append(path)
            category = classify_file(path, batch_root, allowed=allowed)
            if category == "eligible":
                eligible.append(path)
                ext = path.suffix.lower().lstrip(".")
                by_ext_included[ext] = by_ext_included.get(ext, 0) + 1
            else:
                excluded_counts[category] += 1

            # incoming_by_ext counts non-hidden files with an extension before
            # the allow/ban filter; hidden and extensionless files are not
            # counted there (they have no usable extension).
            if category == "hidden" or category == "no_extension":
                continue
            ext = path.suffix.lower().lstrip(".")
            incoming_by_ext[ext] = incoming_by_ext.get(ext, 0) + 1

    eligible.sort(key=lambda p: rel_path(batch_root, p))
    return (
        eligible,
        dict(sorted(by_ext_included.items())),
        excluded_counts,
        dict(sorted(incoming_by_ext.items())),
        all_seen,
    )


def _count_eligible_images(eligible: list[Path]) -> int:
    return sum(
        1 for path in eligible if path.suffix.lower() in DEFAULT_IMAGE_SUFFIXES
    )


def _write_zip(zip_path: Path, batch_root: Path, eligible: list[Path]) -> None:
    """Stream *eligible* files into a copy-only ``ZIP_STORED`` archive."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in eligible:
            archive.write(path, arcname=rel_path(batch_root, path))


def _update_manifest(
    manifest_path: Path,
    root: Path,
    zip_path: Path,
    finished_at: str,
    eligible: list[Path],
    by_ext_included: dict[str, int],
    excluded_counts: dict[str, int],
    incoming_by_ext: dict[str, int],
) -> None:
    manifest = load_manifest(manifest_path)
    step = find_step(manifest, FINISH_PACKAGE_STEP_NAME, manifest_path)

    manifest["finished_at"] = finished_at
    if step.get("started_at") is None:
        step["started_at"] = finished_at
    step["finished_at"] = finished_at
    step["images_processed"] = _count_eligible_images(eligible)

    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    stager = metrics.get("stager")
    if not isinstance(stager, dict):
        stager = {}
    stager["zip"] = rel_path(root, zip_path)
    stager["eligible_count"] = len(eligible)
    stager["by_ext_included"] = by_ext_included
    stager["excluded_counts"] = excluded_counts
    stager["incoming_by_ext"] = incoming_by_ext
    metrics["stager"] = stager
    manifest["metrics"] = metrics

    write_manifest(manifest_path, manifest)


def finish_package(
    batch_root: str | Path,
    *,
    commit: bool = False,
    force: bool = False,
    content: str | Path | None = None,
    output_zip: str | Path | None = None,
    hook: AuditHook | None = None,
) -> FinishResult:
    """Finish *batch_root*: stage a copy-only delivery ZIP and close the manifest.

    Dry-run by default: returns the report and writes nothing, though the
    caller *hook* still gets one dry-run event. ``commit=True`` writes the ZIP,
    closes the manifest and appends to audit.jsonl and finish.jsonl (see the
    module docstring). ``force=True`` overwrites an existing ZIP, never a
    scanned source.

    Raises :class:`FileNotFoundError` / :class:`NotADirectoryError` for a bad
    batch root, a batch that is not intake'd or a missing inventory;
    :class:`ManifestError` when ``project.json`` is not a JSON object;
    :class:`ValueError` when ``content`` is outside the batch root;
    :class:`RefusedWriteError` when the ZIP exists without ``force``; and
    :class:`FinishLogError` when the commit succeeded but a log write failed.
    """
    root = Path(batch_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()

    pickkit_dir = root / PICKKIT_DIR_NAME
    manifest_path = pickkit_dir / MANIFEST_NAME
    inventory_path = pickkit_dir / INVENTORY_NAME
    audit_path = pickkit_dir / AUDIT_NAME
    finish_log_path = pickkit_dir / FINISH_LOG_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"batch is not intake'd: missing manifest {manifest_path}; "
            f"run pickkit-intake first"
        )
    # Validate before any scan or ZIP write so a bad manifest cannot leave
    # a delivery ZIP behind. ManifestError names the path.
    load_manifest(manifest_path)

    allowed = load_allowlist(inventory_path)

    if content is None:
        content_roots = default_content_roots(root)
    else:
        content_roots = [_resolve_content_override(root, content)]

    hook = hook or NULL_HOOK
    eligible, by_ext_included, excluded_counts, incoming_by_ext, all_seen = _scan(
        root, content_roots, allowed
    )
    eligible_count = len(eligible)

    if not commit:
        # Dry-run: report only. Record on the caller hook (no audit.jsonl).
        hook.record(
            AuditEvent(
                operation=OPERATION,
                source=str(root),
                ok=True,
                reason=f"dry_run; eligible_count={eligible_count}",
            )
        )
        return FinishResult(
            batch_root=root,
            commit=False,
            zip_path=None,
            eligible_count=eligible_count,
            by_ext_included=by_ext_included,
            excluded_counts=excluded_counts,
            incoming_by_ext=incoming_by_ext,
            finished_at=None,
            manifest_path=manifest_path,
            audit_path=audit_path,
            finish_log_path=finish_log_path,
        )

    zip_path = _resolve_zip_path(root, output_zip)
    fanout = FanoutHook(JsonlAuditHook(audit_path), hook)

    if zip_path.exists():
        if not force:
            require_new_file(zip_path, hook=fanout)
        # force: overwrite the ZIP only, never a scanned source file.
        resolved_zip = zip_path.resolve()
        if any(resolved_zip == path.resolve() for path in all_seen):
            raise RefusedWriteError(
                f"refusing to overwrite source file with delivery ZIP: {zip_path}"
            )
        zip_path.unlink()

    _write_zip(zip_path, root, eligible)

    finished_at = utc_now()
    _update_manifest(
        manifest_path,
        root,
        zip_path,
        finished_at,
        eligible,
        by_ext_included,
        excluded_counts,
        incoming_by_ext,
    )

    result = FinishResult(
        batch_root=root,
        commit=True,
        zip_path=zip_path,
        eligible_count=eligible_count,
        by_ext_included=by_ext_included,
        excluded_counts=excluded_counts,
        incoming_by_ext=incoming_by_ext,
        finished_at=finished_at,
        manifest_path=manifest_path,
        audit_path=audit_path,
        finish_log_path=finish_log_path,
    )
    try:
        fanout.record(
            AuditEvent(
                operation=OPERATION,
                source=str(root),
                destination=str(zip_path),
                ok=True,
                reason=f"commit=True; eligible_count={eligible_count}",
            )
        )
        append_jsonl(
            finish_log_path,
            {
                "timestamp": finished_at,
                "zip": rel_path(root, zip_path),
                "eligible_count": eligible_count,
                "committed": True,
            },
        )
    except OSError as exc:
        raise FinishLogError(
            f"committed, but the finish log could not be written: {exc}",
            result,
        ) from exc
    return result


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-finish`` CLI."""
    from .ui import DEFAULT_HOST, DEFAULT_PORT

    parser = argparse.ArgumentParser(
        prog="pickkit-finish",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "batch_root",
        help="Path to an already intake'd batch directory",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write the delivery ZIP and close the manifest (default is dry-run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing delivery ZIP (never overwrites source images)",
    )
    parser.add_argument(
        "--content",
        metavar="DIR",
        help=(
            "Scan a single explicit content directory instead of the default "
            "__selected/ + __cropped/ roots; must resolve under batch_root"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Write the ZIP to PATH instead of <batch_root>/delivery.zip; "
            "relative paths resolve under batch_root"
        ),
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Start the local interactive finish web wizard (Flask) instead of finishing",
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
    """CLI entry point; parses args and calls :func:`finish_package`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from lib_safety.webui import check_ui_args

    from .ui import DEFAULT_HOST, DEFAULT_PORT, run_ui

    check_ui_args(
        parser,
        args,
        default_host=DEFAULT_HOST,
        default_port=DEFAULT_PORT,
        conflicts="--commit/--force/--content/--output",
        conflicting=bool(args.commit or args.force or args.content or args.output),
    )
    if args.ui:
        run_ui(args.batch_root, host=args.host, port=args.port)
        return 0

    try:
        result = finish_package(
            args.batch_root,
            commit=args.commit,
            force=args.force,
            content=args.content,
            output_zip=args.output,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError, FinishLogError) as exc:
        parser.exit(1, f"pickkit-finish: error: {exc}\n")

    excluded = " ".join(
        f"{bucket}={result.excluded_counts[bucket]}" for bucket in EXCLUDED_BUCKETS
    )
    if result.commit:
        print(f"pickkit-finish: wrote zip {result.zip_path}")
        print(f"  finished_at: {result.finished_at}")
        print(f"  eligible_count: {result.eligible_count}")
        print(f"  excluded: {excluded}")
    else:
        print("pickkit-finish: dry-run complete (nothing written)")
        print(f"  batch_root: {result.batch_root}")
        print(f"  eligible_count: {result.eligible_count}")
        print(f"  excluded: {excluded}")
    return 0
