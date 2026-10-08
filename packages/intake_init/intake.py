"""Initialize a pickkit batch: manifest, extension inventory, audit baseline.

``pickkit-intake <batch_root>`` snapshots a directory of images and writes
pickkit's state for it. It creates only ``<batch_root>/.pickkit/``; it never
moves or changes an image and never creates stage directories such as
``__selected``. It prints a JSON summary of what it wrote.

Usage::

    pickkit-intake tmp/batch_a
    pickkit-intake tmp/batch_a --force

Options
-------
``--force``
    Overwrite an existing ``.pickkit/`` in place, without the backup below.

Files
-----
``.pickkit/project.json``
    The manifest: ``schema_version`` (2), ``started_at`` (UTC ``Z``),
    ``finished_at`` (null), ``root``, ``image_count``, the spine ``steps``
    and an empty ``metrics`` slot for the later tools.
``.pickkit/allowed_ext.json``
    Extension snapshot: per-extension counts and a sorted
    ``allowedExtensions`` list (lowercase, no dots), which finish-package
    uses as its allowlist.
``.pickkit/audit.jsonl``
    Append-only audit log, started with one ``intake_init`` event.

Images are files whose suffix is in :data:`DEFAULT_IMAGE_SUFFIXES`
(case-insensitive), counted recursively. Hidden files and directories are
skipped.

Re-intake is safe by default: an existing ``.pickkit/`` is first renamed to
a sibling ``.pickkit.bak.<UTC>`` (for example
``.pickkit.bak.20260926T192530Z``) and a fresh one is written.

Before intake
-------------
Quote a batch root that contains spaces. Keep each image in the same
directory as its same-stem sidecars: companions are paired by filename stem,
so ``foo_stage1.png`` and ``foo_stage1.5.png`` are different stems. To intake
one stem family from a large ZIP, extract the matching names into one
directory first::

    mkdir -p ".scratch/subset batch"
    unzip "/path/to/delivery.zip" "path/inside/zip/*stage1*" -d ".scratch/subset batch"
    pickkit-intake ".scratch/subset batch"

Public API
----------
``intake_init(batch_root, *, force=False, hook=None)``
    Write the three files above; returns an :class:`IntakeResult`.
``IntakeResult``
``ManifestExistsError``
    Legacy; no longer raised.
``DEFAULT_IMAGE_SUFFIXES``
``build_parser()``
``main(argv=None)``
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

#: Names the ``intake_init`` package re-exports.
__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "IntakeResult",
    "ManifestExistsError",
    "build_parser",
    "intake_init",
    "main",
]

#: Directory intake writes under the batch root (and nowhere else).
PICKKIT_DIR_NAME = ".pickkit"

#: Manifest, inventory, and audit baseline filenames under ``.pickkit/``.
MANIFEST_NAME = "project.json"
INVENTORY_NAME = "allowed_ext.json"
AUDIT_NAME = "audit.jsonl"

#: Version of the ``project.json`` schema; later plugins bump this to evolve.
SCHEMA_VERSION = 2

#: Public spine step names recorded in ``project.json`` ``steps``, in order.
#: Each later tool owns its own step and metrics slot.
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
    """Legacy exception, kept exported; :func:`intake_init` no longer raises it."""


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
    """Return a compact UTC stamp (``YYYYMMDDTHHMMSSZ``) for backup names."""
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

    Writes ``project.json``, ``allowed_ext.json`` and ``audit.jsonl`` under
    ``<batch_root>/.pickkit/`` (see the module docstring). An existing
    ``.pickkit/`` is renamed to ``.pickkit.bak.<UTC>`` first, unless
    ``force=True`` overwrites it in place. Raises :class:`FileNotFoundError` /
    :class:`NotADirectoryError` if *batch_root* is missing or not a directory.
    The audit event also goes to *hook* when given.
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
