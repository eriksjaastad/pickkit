"""Inventory image-bearing directories across one or more roots.

This module is the single source of truth for directory-viewer behaviour: how
a root is discovered (flat-if-direct-images else one-level subdirs), how image
files are recognised (the shared intake suffix set), how per-directory
inventories are sampled and summarised, and how the thin CLI wraps the
library. The private precursor was a Flask grid UI over a parent directory
with crop/trash actions; pickkit's directory-viewer is a **library + thin
CLI** that only reads the filesystem and reports — it never mutates a file,
never writes an audit file, and never touches the spine manifest.

Principles
----------
Read-only
    Every public operation is pure inspection. No commit, no trash, no
    move-to-crop, no audit file; the module never writes to the filesystem.
Library first
    :func:`list_images_in` / :func:`inventory` / :func:`compare_roots` are the
    whole behaviour; the CLI is a thin wrapper around them.
Optional middle tool, not a spine step
    :data:`intake_init.PUBLIC_SPINE_STEPS` stays ``intake`` /
    ``review_select`` / ``multi_crop`` / ``finish_package``.
    directory-viewer never adds a step, never requires an intake'd batch, and
    never touches ``.pickkit/project.json`` (``finished_at``, ``steps``, or
    ``metrics``).
No cross-plugin hard dependency
    This module mirrors the small listing helper locally so it runs without
    importing any other pickkit plugin.

Discovery semantics
-------------------
Given a root directory, :func:`inventory` locks this public-safe discovery:

1. If the root itself contains at least one image file (non-recursive,
   recognised suffixes) the root is treated as **one** image directory
   (``mode="flat"``). Subdirectories are **not** scanned in that case.
2. Otherwise only the root's **immediate** subdirectories are scanned (one
   level). Every non-hidden subdirectory that contains at least one image
   (non-recursive in that subdirectory) becomes a :class:`DirInventory`
   entry, sorted by subdirectory name. Empty and non-image subdirectories are
   omitted from the inventory list. Hidden names (starting with ``.``) are
   skipped at every level.

Images are recognised by :data:`DEFAULT_IMAGE_SUFFIXES` — the same set as
``intake_init`` / ``character_tools`` / ``duplicate_finder``: ``.png .jpg
.jpeg .webp .tif .tiff .bmp .gif`` (lowercase, with dots). The set is not
PNG-only. Suffix matching is case-insensitive.

Sampling
--------
Each :class:`DirInventory` stores ``image_count`` as the full non-recursive
image count for that directory, and ``images`` as a sorted tuple of
**basenames** (never full paths). ``sample_limit`` caps how many basenames
are stored:

``None`` or negative
    Store every basename (``None`` means all).
``0``
    Store no basenames (counts-only inventory).
``N > 0``
    Store the first ``N`` sorted basenames.

The default is :data:`DEFAULT_SAMPLE_LIMIT` = 20 for CLI friendliness; pass
``sample_limit=None`` to include every basename.

by_ext
------
``by_ext`` maps lowercase extension **without** the dot to the full image
count for that extension, e.g. ``{"png": 3, "jpg": 2}``. Keys are kept in
sorted order when serialising.

Public API
----------
``DEFAULT_IMAGE_SUFFIXES``
    Tuple of raster-image suffixes (lowercase, with dots); the same set as
    intake_init / character_tools / duplicate_finder.
``OPERATION``
    Operation name for this middle tool: ``directory_viewer``. Read-only
    tooling, so no audit event is ever recorded.
``DEFAULT_SAMPLE_LIMIT``
    Default ``sample_limit`` (20).
``list_images_in(dir, *, suffixes=None) -> list[Path]``
    Non-recursive image files directly inside *dir* (hidden names skipped,
    sorted by name). ``suffixes=None`` uses ``DEFAULT_IMAGE_SUFFIXES``.
``inventory(root, *, suffixes=None, sample_limit=DEFAULT_SAMPLE_LIMIT) -> RootReport``
    Inventory one root directory using the discovery semantics above.
``compare_roots(roots, *, suffixes=None, sample_limit=DEFAULT_SAMPLE_LIMIT) -> list[RootReport]``
    Inventory each root in order; refuses with FileNotFoundError /
    NotADirectoryError for a missing or non-directory root.
``DirInventory``
    Frozen dataclass: ``name`` (directory basename), ``path`` (the directory
    as given, ``~`` expanded), ``image_count`` (full non-recursive count),
    ``images`` (sorted basename sample, see Sampling), and ``by_ext``
    (lowercase extension without dot -> full count).
``RootReport``
    Frozen dataclass: ``root`` (as given, ``~`` expanded), ``mode``
    (``"flat"`` or ``"subdirs"``), ``directories`` (DirInventory entries in
    deterministic order), and ``total_images`` (sum of image_count over the
    entries).
``build_parser()``
    Return the argparse parser for the ``pickkit-viewer`` CLI. The parser
    description is this module docstring; subcommands are ``inventory`` and
    ``compare``.
``main(argv=None)``
    CLI entry point; parses args, dispatches, prints text or JSON, and
    returns 0 on success / exits 1 on missing roots.

CLI
---
    pickkit-viewer inventory ROOT [--sample N] [--json]
    pickkit-viewer compare ROOT [ROOT ...] [--sample N] [--json]

Default output is human-readable text: per directory the name, image_count,
and a by_ext summary. ``--json`` prints serialisable report(s): ``inventory``
prints one report object and ``compare`` prints a JSON array of report
objects. ``--sample N`` maps to ``sample_limit`` (default 20); ``--sample 0``
gives a counts-only inventory (empty images tuples) and ``--sample -1`` is
treated as ``None`` (store all basenames). Exit status is 0 on success and 1
when a root is missing or not a directory. ``python -m directory_viewer``
runs the same CLI.

Examples
--------
    from directory_viewer import inventory, compare_roots

    report = inventory("sandbox/batch_a")
    report.mode                                     # "flat"
    report.directories[0].by_ext                    # {"png": 4}
    reports = compare_roots(["sandbox/batch_a", "sandbox/other"])
    reports[0].total_images                         # 4

Out of scope
------------
The Flask/Tk grid UI (multi-directory viewer with click-to-crop and trash
actions) is **out of scope** — no web server, templates, or browser UI, and
no Flask import. Mutations of any kind (move-to-crop-queue, trash) are future
work, not this module's job. directory-viewer never extends
``PUBLIC_SPINE_STEPS``, never requires intake, never mutates the spine
manifest, and never writes an audit file (read-only tooling).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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
    """Return the non-recursive image files directly inside *dir*.

    Hidden names (starting with ``.``) are skipped and results are sorted by
    name. ``suffixes=None`` uses :data:`DEFAULT_IMAGE_SUFFIXES`. Raises
    :class:`FileNotFoundError` for a missing path and
    :class:`NotADirectoryError` when *dir* is not a directory.
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
    """Inventory one root directory using the locked discovery semantics.

    If *root* itself contains at least one image file (non-recursive) the
    report is flat mode with the root as the single :class:`DirInventory`;
    otherwise immediate non-hidden subdirectories are scanned one level and
    every subdirectory with at least one image becomes an entry (empty and
    non-image subdirectories are omitted). ``sample_limit`` caps the stored
    basenames per entry (None or negative = all, 0 = none, N = first N); the
    default is :data:`DEFAULT_SAMPLE_LIMIT` (20). Raises
    :class:`FileNotFoundError` for a missing root and
    :class:`NotADirectoryError` when *root* is not a directory.
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
    """Inventory each root in order and return one :class:`RootReport` each.

    *roots* may be a single path or a sequence of paths. Each root is handed
    to :func:`inventory`, so a missing root raises :class:`FileNotFoundError`
    and a non-directory root raises :class:`NotADirectoryError`.
    """
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
