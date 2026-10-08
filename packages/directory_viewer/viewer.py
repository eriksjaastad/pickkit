"""Inventory image-bearing directories across one or more roots.

``pickkit-viewer`` reports which directories under a root hold images, how
many, and of which types. It is read-only: it never writes, moves or trashes
a file, writes no audit log and needs no intake'd batch.

Usage::

    pickkit-viewer inventory ROOT [--sample N] [--json]
    pickkit-viewer compare ROOT [ROOT ...] [--sample N] [--json]

The default output is text: per directory its name, image count and count per
extension. Exit status is 1 when a root is missing or not a directory.

Options
-------
``--sample N``
    How many image names to include per directory in the ``--json``
    ``images`` list (``sample_limit``; default :data:`DEFAULT_SAMPLE_LIMIT`,
    20). ``0`` includes none and ``-1`` all; counts are always complete. The
    text output shows no names.
``--json``
    Print JSON instead: one report object for ``inventory``, an array for
    ``compare``.

Discovery
---------
If the root itself holds at least one image, it is the only directory
reported (mode ``flat``) and subdirectories are not scanned. Otherwise each
non-hidden immediate subdirectory that holds images is reported, sorted by
name (mode ``subdirs``). Scans are never recursive below that one level.
``by_ext`` maps each lowercase extension without the dot to its count, e.g.
``{"png": 3, "jpg": 2}``. Images are files with a suffix in
:data:`DEFAULT_IMAGE_SUFFIXES`, in any case; hidden names are skipped.

Public API
----------
``DEFAULT_IMAGE_SUFFIXES``
``OPERATION = "directory_viewer"``
    Named for symmetry with the other tools; no audit event is recorded.
``DEFAULT_SAMPLE_LIMIT = 20``
``list_images_in(dir, *, suffixes=None) -> list[Path]``
``inventory(root, *, suffixes=None, sample_limit=DEFAULT_SAMPLE_LIMIT) -> RootReport``
``compare_roots(roots, *, suffixes=None, sample_limit=DEFAULT_SAMPLE_LIMIT) -> list[RootReport]``
``DirInventory``
``RootReport``
``build_parser()``
``main(argv=None)``
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: Names the ``directory_viewer`` package re-exports.
__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "DEFAULT_SAMPLE_LIMIT",
    "OPERATION",
    "DirInventory",
    "RootReport",
    "build_parser",
    "compare_roots",
    "inventory",
    "list_images_in",
    "main",
]

#: Raster-image suffixes used by list/inventory (lowercase, with dots); same
#: set as ``intake_init.DEFAULT_IMAGE_SUFFIXES`` / character_tools /
#: duplicate_finder.
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
)

#: Operation name for this middle tool. Read-only tooling records no audit
#: event; this constant exists for symmetry with the other middle tools.
OPERATION = "directory_viewer"

#: Default sample_limit: store at most 20 basenames per DirInventory.images.
DEFAULT_SAMPLE_LIMIT = 20


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def _normalise_suffix_set(suffixes: object) -> set[str]:
    if suffixes is None:
        raw: Iterable[str] = DEFAULT_IMAGE_SUFFIXES
    elif isinstance(suffixes, str):
        raw = (suffixes,)
    else:
        raw = tuple(suffixes)  # type: ignore[arg-type]
    allowed: set[str] = set()
    for suffix in raw:
        lowered = suffix.lower()
        if not lowered.startswith("."):
            lowered = f".{lowered}"
        if lowered != ".":
            allowed.add(lowered)
    return allowed


def _sample_cap(sample_limit: object) -> int | None:
    """Return the basename cap encoded by *sample_limit* (None means all)."""
    if sample_limit is None:
        return None
    if isinstance(sample_limit, bool) or not isinstance(sample_limit, int):
        raise ValueError(
            f"sample_limit must be None or an integer, got {sample_limit!r}"
        )
    return None if sample_limit < 0 else sample_limit


def list_images_in(dir: str | Path, *, suffixes: object = None) -> list[Path]:
    """Return the non-hidden image files directly inside *dir*, sorted by name.

    ``suffixes=None`` uses :data:`DEFAULT_IMAGE_SUFFIXES`.
    """
    target = _as_path(dir)
    if not target.exists():
        raise FileNotFoundError(f"directory not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"not a directory: {target}")
    allowed = _normalise_suffix_set(suffixes)
    return sorted(
        (
            path
            for path in target.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in allowed
        ),
        key=lambda path: path.name,
    )


@dataclass(frozen=True)
class DirInventory:
    """One image-bearing directory discovered by :func:`inventory`.

    ``images`` is the sorted tuple of image basenames directly inside the
    directory, capped by ``sample_limit``; ``image_count`` is the full count
    regardless of the sample. ``by_ext`` maps lowercase extension without the
    dot to the full count for that extension.
    """

    name: str
    path: Path
    image_count: int
    images: tuple[str, ...]
    by_ext: dict[str, int]


@dataclass(frozen=True)
class RootReport:
    """The inventory of one root directory.

    ``mode`` is ``"flat"`` (the root itself is the single image directory) or
    ``"subdirs"`` (image-bearing immediate subdirectories). ``directories`` is
    deterministic (flat mode has one entry; subdirs mode is sorted by name),
    and ``total_images`` is the sum of the entries' ``image_count``.
    """

    root: Path
    mode: str
    directories: tuple[DirInventory, ...]
    total_images: int


def _make_dir_inventory(
    path: Path,
    name: str,
    allowed: set[str],
    cap: int | None,
) -> DirInventory | None:
    """Build a DirInventory for *path*, or None when it has no images."""
    found = list_images_in(path, suffixes=allowed)
    if not found:
        return None
    images = tuple(sorted(image.name for image in found))
    by_ext: dict[str, int] = {}
    for image in found:
        ext = image.suffix.lower().lstrip(".")
        by_ext[ext] = by_ext.get(ext, 0) + 1
    stored = images if cap is None else images[:cap]
    return DirInventory(name, path, len(found), stored, dict(sorted(by_ext.items())))


def inventory(
    root: str | Path,
    *,
    suffixes: object = None,
    sample_limit: object = DEFAULT_SAMPLE_LIMIT,
) -> RootReport:
    """Inventory one root directory (see "Discovery" in the module docstring).

    ``sample_limit`` caps the stored names per entry: None or negative for
    all, 0 for none, N for the first N. Raises :class:`FileNotFoundError` /
    :class:`NotADirectoryError` for a missing or non-directory root.
    """
    target = _as_path(root)
    if not target.exists():
        raise FileNotFoundError(f"root not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"root is not a directory: {target}")
    allowed = _normalise_suffix_set(suffixes)
    cap = _sample_cap(sample_limit)

    direct = list_images_in(target, suffixes=allowed)
    if direct:
        entry = _make_dir_inventory(target, target.name, allowed, cap)
        assert entry is not None  # direct is non-empty by construction
        return RootReport(target, "flat", (entry,), entry.image_count)

    entries: list[DirInventory] = []
    subdirs = (
        path for path in target.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    for subdir in sorted(subdirs, key=lambda path: path.name):
        entry = _make_dir_inventory(subdir, subdir.name, allowed, cap)
        if entry is not None:
            entries.append(entry)
    total = sum(entry.image_count for entry in entries)
    return RootReport(target, "subdirs", tuple(entries), total)


def compare_roots(
    roots: object,
    *,
    suffixes: object = None,
    sample_limit: object = DEFAULT_SAMPLE_LIMIT,
) -> list[RootReport]:
    """Run :func:`inventory` on each of *roots* (one path or a sequence), in order."""
    if isinstance(roots, (str, Path)):
        raw: list[object] = [roots]
    else:
        try:
            raw = list(roots)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(
                f"roots must be a path or a sequence of paths, got {roots!r}"
            ) from exc
    return [
        inventory(item, suffixes=suffixes, sample_limit=sample_limit)
        for item in raw
    ]


def _dir_dict(entry: DirInventory) -> dict[str, object]:
    return {
        "name": entry.name,
        "path": str(entry.path),
        "image_count": entry.image_count,
        "images": list(entry.images),
        "by_ext": dict(sorted(entry.by_ext.items())),
    }


def _report_dict(report: RootReport) -> dict[str, object]:
    return {
        "root": str(report.root),
        "mode": report.mode,
        "directories": [_dir_dict(entry) for entry in report.directories],
        "total_images": report.total_images,
    }


def _format_report(report: RootReport) -> str:
    lines = [
        f"root: {report.root} (mode={report.mode}, "
        f"total={report.total_images} images)",
    ]
    for entry in report.directories:
        lines.append(f"- {entry.name}: {entry.image_count} images [{entry.path}]")
        for ext in sorted(entry.by_ext):
            lines.append(f"    {ext}: {entry.by_ext[ext]}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-viewer`` CLI."""
    parser = argparse.ArgumentParser(
        prog="pickkit-viewer",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--sample", type=int, default=DEFAULT_SAMPLE_LIMIT, metavar="N",
            help="Cap stored basenames per directory (default 20; 0 = none; -1 = all)",
        )
        target.add_argument(
            "--json", action="store_true",
            help="Print serialisable JSON report(s) instead of text",
        )

    inventory_parser = subparsers.add_parser(
        "inventory", help="Inventory one root directory"
    )
    inventory_parser.add_argument("root", help="Root directory to inventory")
    add_common_flags(inventory_parser)

    compare_parser = subparsers.add_parser(
        "compare", help="Inventory and compare multiple root directories"
    )
    compare_parser.add_argument(
        "roots", nargs="+", metavar="ROOT",
        help="Root directories to inventory, in order",
    )
    add_common_flags(compare_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args, dispatches, and prints text or JSON."""
    parser = build_parser()
    args = parser.parse_args(argv)
    sample_limit: object = None if args.sample < 0 else args.sample

    try:
        if args.command == "inventory":
            report = inventory(args.root, sample_limit=sample_limit)
            output: str | object
            output = (
                json.dumps(_report_dict(report), indent=2)
                if args.json
                else _format_report(report)
            )
        elif args.command == "compare":
            reports = compare_roots(args.roots, sample_limit=sample_limit)
            output = (
                json.dumps([_report_dict(report) for report in reports], indent=2)
                if args.json
                else "\n\n".join(_format_report(report) for report in reports)
            )
        else:  # pragma: no cover - argparse guarantees a known subcommand
            parser.error(f"unknown command: {args.command}")
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        parser.exit(1, f"pickkit-viewer: error: {exc}\n")

    print(output)
    return 0
