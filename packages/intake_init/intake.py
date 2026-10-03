"""Initialize a pickkit batch: manifest, extension inventory, audit baseline.

This module is the single source of truth for intake behaviour: how a batch
root is validated, which files count as images, what is written under
``.pickkit/``, how re-intake is made safe, and how the audit baseline is
started. The private precursor project-starter was a monolithic client script
with client-specific IDs and pre-made stage paths; pickkit's intake is a
small library that writes only its own JSON state under the batch root.

Principles
----------
Library first
    :func:`intake_init` is the whole behaviour; the CLI in this module is a
    thin wrapper around it.
Point at a directory
    The batch root must exist and be a directory. Anything else is refused
    with :class:`FileNotFoundError` / :class:`NotADirectoryError` before any
    file is written.
Create ``.pickkit/`` only
    Intake creates exactly one state directory, ``<batch_root>/.pickkit/``,
    and three files inside it: ``project.json``, ``allowed_ext.json``, and
    ``audit.jsonl``. On re-intake it may also create one backup directory,
    ``<batch_root>/.pickkit.bak.<UTC>`` (see Backup-then-overwrite). Stage
    directory names such as ``__selected`` and ``__crop`` are
    pickkit-public conventions reserved for future review/crop plugins;
    intake never creates them (or any character-group directories).
JSON manifest
    ``project.json`` records ``schema_version`` (currently 2), ``started_at``
    (UTC with a ``Z`` suffix), ``finished_at`` (null at intake), ``root``
    (resolved absolute string), ``image_count``, the public spine ``steps``,
    and an empty ``metrics`` slot for later plugins.
Image count
    Raster images are matched case-insensitively by suffix against
    :data:`DEFAULT_IMAGE_SUFFIXES` and counted recursively under the batch
    root. The current default set is ``.png``, ``.jpg``, ``.jpeg``,
    ``.webp``, ``.tif``, ``.tiff``, ``.bmp``, ``.gif``.
Extension inventory
    ``allowed_ext.json`` snapshots the files present at intake time (before
    any ``.pickkit/`` artifacts exist): lowercase extensions without leading
    dots, per-extension counts, a sorted ``allowedExtensions`` list for the
    future finish-package allowlist, and a ``snapshot_at`` UTC timestamp.
    Hidden files and directories (any path part starting with a dot,
    including ``.pickkit`` itself) are skipped.
Audit baseline
    ``audit.jsonl`` is an append-only JSONL audit started via
    ``lib_safety.JsonlAuditHook``; intake records one successful
    ``intake_init`` event there. With a caller-supplied ``hook``, the same
    events are also recorded to that hook.
Backup-then-overwrite
    If ``<batch_root>/.pickkit/`` already exists and ``force`` is false,
    intake first moves the whole directory to a sibling timestamped backup
    such as ``.pickkit.bak.20260926T192530Z`` (``Path.rename``), then writes
    a fresh ``.pickkit/``. With ``force=True`` (CLI ``--force``) the backup
    is skipped and ``.pickkit/`` is overwritten in place. The audit event
    records the backup destination when one was made. The legacy
    :class:`ManifestExistsError` is no longer raised.

Public API
----------
``intake_init(batch_root, *, force=False, hook=None)``
    Validate *batch_root*, then write the manifest, extension inventory, and
    audit baseline under ``<batch_root>/.pickkit/``. On re-intake the
    existing ``.pickkit/`` is backed up to ``.pickkit.bak.<UTC>`` before a
    fresh one is written, unless ``force=True`` (or CLI ``--force``), which
    skips the backup and overwrites in place. Returns an
    :class:`IntakeResult`. With ``hook`` given, the same events are also
    recorded there.
``IntakeResult``
    Frozen dataclass describing what intake wrote: ``batch_root``,
    ``manifest_path``, ``inventory_path``, ``audit_path``, ``image_count``,
    ``started_at``, ``extensions``, and ``backup_path`` (``Path | None``;
    null/None when no backup was made).
``ManifestExistsError``
    Reserved/legacy exception (a :class:`FileExistsError`). Current
    ``intake_init`` never raises it: re-intake backs up and overwrites by
    default, and ``--force`` overwrites in place. Kept exported for API
    stability.
``DEFAULT_IMAGE_SUFFIXES``
    Tuple of raster-image suffixes counted by intake (lowercase, with dots).
``build_parser()``
    Return the argparse parser for the ``pickkit-intake`` CLI. The parser
    description is this module docstring; ``--force`` skips the backup and
    wipes ``.pickkit/`` in place.
``main(argv=None)``
    CLI entry point; parses args and calls :func:`intake_init`.

Examples
--------
Initialize a staged sandbox batch from the library::

    from intake_init import intake_init

    result = intake_init("tmp/batch_a")
    result.manifest_path   # tmp/batch_a/.pickkit/project.json
    result.backup_path     # None (no existing .pickkit to back up)
    result.image_count     # 4

Re-initialize a batch from the CLI (backs up first; ``--force`` wipes in place)::

    python -m intake_init sandbox/batch_a --force

Before intake
-------------
Quote a batch root that contains spaces. Keep each image in the same
directory as its same-stem sidecars before you run intake. Companions are
paired by filename stem, not by mtime, so ``foo_stage1.png`` and
``foo_stage1.5.png`` are different stems (see ``lib_safety.companions``).

To intake only one stem family from a large ZIP, extract the matching names
into one directory first (image and sidecars side by side), then point
intake at that directory::

    mkdir -p ".scratch/subset batch"
    unzip "/path/to/delivery.zip" "path/inside/zip/*stage1*" -d ".scratch/subset batch"
    pickkit-intake ".scratch/subset batch"

Out of scope
------------
Stage directories (``__selected``, ``__crop``, character groups), pixel
writes, review/crop/finish steps, and client-specific manifests are **not**
this module's job. Those belong to future plugins; intake only records the
initial snapshot and reserves public spine step/metrics slots.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lib_safety import NULL_HOOK, AuditEvent, AuditHook, JsonlAuditHook
from lib_safety.audit import utc_now

#: Directory intake writes under the batch root (and nowhere else).
PICKKIT_DIR_NAME = ".pickkit"

#: Manifest, inventory, and audit baseline filenames under ``.pickkit/``.
MANIFEST_NAME = "project.json"
INVENTORY_NAME = "allowed_ext.json"
AUDIT_NAME = "audit.jsonl"

#: Version of the ``project.json`` schema; later plugins bump this to evolve.
SCHEMA_VERSION = 2

#: Public spine step names recorded in ``project.json`` ``steps`` (snake_case,
#: matching the PLAN spine: intake-init, review-select, multi-crop,
#: finish-package). Plugins own their own step/metrics slots.
PUBLIC_SPINE_STEPS: tuple[str, ...] = (
    "intake",
    "review_select",
    "multi_crop",
    "finish_package",
)

#: Audit operation recorded for a successful (or refused) intake.
OPERATION = "intake_init"

#: Raster-image suffixes counted by :func:`intake_init` (lowercase, with dots).
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
)


class ManifestExistsError(FileExistsError):
    """Reserved/legacy exception; not raised by current :func:`intake_init`.

    Kept exported for API stability. Earlier intake releases raised this when
    ``project.json`` already existed and ``force`` was false; current intake
    backs up ``.pickkit/`` and overwrites by default instead.
    """


@dataclass(frozen=True)
class IntakeResult:
    """What :func:`intake_init` wrote.

    ``extensions`` is the lowercase, dot-free extension -> count snapshot
    recorded in ``allowed_ext.json`` (sorted by extension name).
    ``backup_path`` is the timestamped backup directory when an existing
    ``.pickkit/`` was backed up, else ``None``.
    """

    batch_root: Path
    manifest_path: Path
    inventory_path: Path
    audit_path: Path
    image_count: int
    started_at: str
    extensions: dict[str, int]
    backup_path: Path | None = None


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def _iter_visible_files(root: Path) -> Iterator[Path]:
    """Yield files under *root*, skipping any path with a hidden part."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        yield path


def _count_images(root: Path) -> int:
    return sum(
        1
        for path in _iter_visible_files(root)
        if path.suffix.lower() in DEFAULT_IMAGE_SUFFIXES
    )


def _scan_extensions(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _iter_visible_files(root):
        ext = path.suffix.lower().lstrip(".")
        if not ext:
            continue
        counts[ext] = counts.get(ext, 0) + 1
    return dict(sorted(counts.items()))


def _backup_stamp() -> str:
    """Return a compact UTC stamp (``YYYYMMDDTHHMMSSZ``) for backup names.

    Same clock style as :func:`lib_safety.audit.utc_now`, formatted compactly
    for a filesystem-friendly directory name.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unique_backup_path(root: Path, stamp: str) -> Path:
    """Return a non-existing ``.pickkit.bak.<stamp>`` sibling under *root*."""
    candidate = root / f"{PICKKIT_DIR_NAME}.bak.{stamp}"
    suffix = 2
    while candidate.exists():
        candidate = root / f"{PICKKIT_DIR_NAME}.bak.{stamp}.{suffix}"
        suffix += 1
    return candidate


def _build_steps(started_at: str, image_count: int) -> list[dict[str, object]]:
    """Build the public spine ``steps`` list for a fresh manifest.

    ``intake`` is filled in from the current run; the remaining spine steps
    are reserved (null) for their owning plugins.
    """
    steps: list[dict[str, object]] = []
    for name in PUBLIC_SPINE_STEPS:
        if name == "intake":
            steps.append(
                {
                    "name": name,
                    "started_at": started_at,
                    "finished_at": started_at,
                    "images_processed": image_count,
                }
            )
        else:
            steps.append(
                {
                    "name": name,
                    "started_at": None,
                    "finished_at": None,
                    "images_processed": None,
                }
            )
    return steps


def _build_metrics() -> dict[str, object]:
    """Build the empty ``metrics`` slot for a fresh manifest.

    Plugins own these slots; intake only reserves the public shape.
    """
    return {
        "images_per_hour_end_to_end": None,
        "step_rates": {},
        "stager": {
            "zip": "",
            "eligible_count": 0,
            "by_ext_included": {},
            "excluded_counts": {},
            "incoming_by_ext": {},
        },
    }


def intake_init(
    batch_root: str | Path,
    *,
    force: bool = False,
    hook: AuditHook | None = None,
) -> IntakeResult:
    """Initialize *batch_root*: manifest, extension inventory, audit baseline.

    Writes, under ``<batch_root>/.pickkit/``:

    * ``project.json`` — schema version 2, UTC-Z ``started_at``,
      ``finished_at`` null, resolved root path, image count, public spine
      ``steps``, and ``metrics``;
    * ``allowed_ext.json`` — extension snapshot for a later finish-package
      allowlist;
    * ``audit.jsonl`` — append-only JSONL baseline with one successful
      ``intake_init`` event.

    If ``<batch_root>/.pickkit/`` already exists:

    * with ``force`` false (default), the directory is moved to a sibling
      timestamped backup ``<batch_root>/.pickkit.bak.<UTC>`` before a fresh
      ``.pickkit/`` is written;
    * with ``force=True``, the backup is skipped and ``.pickkit/`` is
      overwritten in place.

    Refuses with :class:`FileNotFoundError` / :class:`NotADirectoryError` if
    *batch_root* is missing or not a directory. No stage directories
    (``__selected`` / ``__crop``) are created. With ``hook`` given, events
    are also recorded there.
    """
    root = _as_path(batch_root)
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()

    pickkit_dir = root / PICKKIT_DIR_NAME
    manifest_path = pickkit_dir / MANIFEST_NAME
    inventory_path = pickkit_dir / INVENTORY_NAME
    audit_path = pickkit_dir / AUDIT_NAME
    hook = hook or NULL_HOOK

    # Scan before writing anything so .pickkit artifacts are not inventoried.
    started_at = utc_now()
    image_count = _count_images(root)
    extensions = _scan_extensions(root)

    # Backup-then-overwrite: move the existing .pickkit aside unless force
    # asks for an in-place wipe.
    backup_path: Path | None = None
    if pickkit_dir.exists() and not force:
        backup_path = _unique_backup_path(root, _backup_stamp())
        pickkit_dir.rename(backup_path)

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at,
        "finished_at": None,
        "root": str(root),
        "image_count": image_count,
        "steps": _build_steps(started_at, image_count),
        "metrics": _build_metrics(),
    }
    inventory = {
        "snapshot_at": started_at,
        "source_path": str(root),
        "total_files": sum(extensions.values()),
        "extensions": extensions,
        "allowedExtensions": sorted(extensions),
    }

    pickkit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    inventory_path.write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )

    reason_bits = [
        f"image_count={image_count}; "
        f"extensions={','.join(sorted(extensions))}"
    ]
    if backup_path is not None:
        reason_bits.insert(0, f"backup_path={backup_path}; ")
    event = AuditEvent(
        operation=OPERATION,
        source=str(root),
        destination=str(manifest_path),
        ok=True,
        reason="".join(reason_bits),
    )
    JsonlAuditHook(audit_path).record(event)
    hook.record(event)

    return IntakeResult(
        batch_root=root,
        manifest_path=manifest_path,
        inventory_path=inventory_path,
        audit_path=audit_path,
        image_count=image_count,
        started_at=started_at,
        extensions=extensions,
        backup_path=backup_path,
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-intake`` CLI."""
    parser = argparse.ArgumentParser(
        prog="pickkit-intake",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "batch_root",
        help="Path to the batch directory to initialize",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip backup and overwrite .pickkit/ in place (wipes in place)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args and calls :func:`intake_init`."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = intake_init(args.batch_root, force=args.force)
    except (FileNotFoundError, NotADirectoryError, ManifestExistsError) as exc:
        parser.exit(1, f"pickkit-intake: error: {exc}\n")

    print(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "manifest_path": str(result.manifest_path),
                "inventory_path": str(result.inventory_path),
                "audit_path": str(result.audit_path),
                "image_count": result.image_count,
                "started_at": result.started_at,
                "backup_path": (
                    str(result.backup_path) if result.backup_path is not None else None
                ),
            },
            indent=2,
        )
    )
    return 0
