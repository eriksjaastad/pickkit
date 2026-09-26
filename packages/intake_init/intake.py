"""Initialize a pickkit batch: manifest, extension inventory, audit baseline.

This module is the single source of truth for intake behaviour: how a batch
root is validated, which files count as images, what is written under
``.pickkit/``, and how the audit baseline is started. The private precursor
project-starter was a monolithic client script with client-specific IDs and
pre-made stage paths; pickkit's intake is a small library that writes only
its own JSON state under the batch root.

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
    Intake creates exactly one directory, ``<batch_root>/.pickkit/``, and
    three files inside it: ``project.json``, ``allowed_ext.json``, and
    ``audit.jsonl``. Stage directory names such as ``__selected`` and
    ``__crop`` are pickkit-public conventions reserved for future
    review/crop plugins; intake never creates them (or any character-group
    directories).
JSON manifest
    ``project.json`` records ``schema_version``, ``started_at`` (UTC with a
    ``Z`` suffix), ``root`` (resolved absolute string), and ``image_count``.
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
Safe by default
    If ``project.json`` already exists, intake refuses with
    :class:`ManifestExistsError` (a :class:`FileExistsError`) and does not
    overwrite anything. ``force=True`` is the only way to overwrite.

Public API
----------
``intake_init(batch_root, *, force=False, hook=None)``
    Validate *batch_root*, then write the manifest, extension inventory, and
    audit baseline under ``<batch_root>/.pickkit/``. Returns an
    :class:`IntakeResult`. With ``force=True`` an existing manifest is
    overwritten. With ``hook`` given, the same events are also recorded
    there.
``IntakeResult``
    Frozen dataclass describing what intake wrote: ``batch_root``,
    ``manifest_path``, ``inventory_path``, ``audit_path``, ``image_count``,
    ``started_at``, and ``extensions``.
``ManifestExistsError``
    Raised when ``project.json`` already exists and ``force`` is false.
``DEFAULT_IMAGE_SUFFIXES``
    Tuple of raster-image suffixes counted by intake (lowercase, with dots).
``build_parser()``
    Return the argparse parser for the ``pickkit-intake`` CLI. The parser
    description is this module docstring.
``main(argv=None)``
    CLI entry point; parses args and calls :func:`intake_init`.

Examples
--------
Initialize a staged sandbox batch from the library::

    from intake_init import intake_init

    result = intake_init("tmp/batch_a")
    result.manifest_path   # tmp/batch_a/.pickkit/project.json
    result.image_count     # 4

Initialize a batch from the CLI (overwrite if one exists)::

    python -m intake_init sandbox/batch_a --force

Out of scope
------------
Stage directories (``__selected``, ``__crop``, character groups), pixel
writes, review/crop/finish steps, and client-specific manifests are **not**
this module's job. Those belong to future plugins; intake only records the
initial snapshot.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from dataclasses import dataclass
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
SCHEMA_VERSION = 1

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
    """Raised when the intake manifest already exists and ``force`` is false."""


@dataclass(frozen=True)
class IntakeResult:
    """What :func:`intake_init` wrote.

    ``extensions`` is the lowercase, dot-free extension -> count snapshot
    recorded in ``allowed_ext.json`` (sorted by extension name).
    """

    batch_root: Path
    manifest_path: Path
    inventory_path: Path
    audit_path: Path
    image_count: int
    started_at: str
    extensions: dict[str, int]


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


def intake_init(
    batch_root: str | Path,
    *,
    force: bool = False,
    hook: AuditHook | None = None,
) -> IntakeResult:
    """Initialize *batch_root*: manifest, extension inventory, audit baseline.

    Writes, under ``<batch_root>/.pickkit/``:

    * ``project.json`` — schema version, UTC-Z ``started_at``, resolved root
      path, and image count;
    * ``allowed_ext.json`` — extension snapshot for a later finish-package
      allowlist;
    * ``audit.jsonl`` — append-only JSONL baseline with one successful
      ``intake_init`` event.

    Refuses with :class:`FileNotFoundError` / :class:`NotADirectoryError` if
    *batch_root* is missing or not a directory, and with
    :class:`ManifestExistsError` (a :class:`FileExistsError`) if the manifest
    already exists unless ``force=True``. No stage directories
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

    if manifest_path.exists() and not force:
        hook.record(
            AuditEvent(
                operation=OPERATION,
                source=str(root),
                destination=str(manifest_path),
                ok=False,
                reason="manifest already exists; pass force=True to overwrite",
            )
        )
        raise ManifestExistsError(
            f"refusing to overwrite existing manifest: {manifest_path} "
            f"(pass force=True to overwrite)"
        )

    # Scan before writing anything so .pickkit artifacts are not inventoried.
    started_at = utc_now()
    image_count = _count_images(root)
    extensions = _scan_extensions(root)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at,
        "root": str(root),
        "image_count": image_count,
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

    event = AuditEvent(
        operation=OPERATION,
        source=str(root),
        destination=str(manifest_path),
        ok=True,
        reason=(
            f"image_count={image_count}; "
            f"extensions={','.join(sorted(extensions))}"
        ),
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
        help="Overwrite an existing .pickkit/project.json manifest",
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
            },
            indent=2,
        )
    )
    return 0
