"""Assign images to user-supplied named bins, moving same-stem companions together.

``pickkit-character`` sorts images into bins you name: a bin is one
subdirectory of a bins root. Each move takes the image and its same-stem
companions together, and a reject sends them to the OS trash. Every command
is a dry-run unless ``--commit`` is given. Nothing reads or rewrites pixels,
and the batch need not be intake'd (``.pickkit/`` is never touched). Each
command prints a JSON summary.

Usage::

    pickkit-character list SOURCE
    pickkit-character check BINS_ROOT
    pickkit-character move IMAGE --bin NAME --bins-root DIR [--commit] [--audit PATH]
    pickkit-character assign MAP.json --bins-root DIR [--commit] [--audit PATH]
    pickkit-character reject IMAGE [--commit] [--audit PATH]

Commands
--------
``list``
    The images in SOURCE: the file itself if it is an image, or the
    non-hidden images directly inside a directory, sorted by name.
``check``
    Every non-hidden immediate subdirectory of BINS_ROOT, empty ones
    included, with its image count and image names.
``move``
    Move IMAGE and its companions to ``<bins_root>/<bin>/``, creating the bin
    on commit.
``assign``
    Apply a map of moves in order: a JSON array, or a ``.jsonl`` file with
    one object per line, of ``{"source": ..., "bin": ...}`` (exactly those
    keys; relative sources resolve against the current directory). Stops at
    the first failure; on commit, earlier moves stay done.
``reject``
    Trash IMAGE and its companions (companions first, then the image).

Options
-------
``--bin NAME`` / ``--bins-root DIR``
    The destination bin and the directory that holds the bins.
``--commit``
    Do the move or trash. Without it the plan is checked and printed.
``--audit PATH``
    Append audit events (operation ``character_tools``) to PATH. Without it
    no audit file is written.

Bin names
---------
A name is stripped of surrounding whitespace and used as is, never slugged.
It may contain only ASCII letters, digits, space, ``_``, ``-`` and ``.``, and
must not be empty, ``.`` or contain ``..``. If any destination file already
exists, the whole move is refused before anything moves.

Public API
----------
``normalise_bin_name(name) -> str``
``list_images(source, *, suffixes=None) -> list[Path]``
``check_bins(bins_root, *, suffixes=None) -> list[BinSummary]``
``move_to_bin(image, bin_name, *, bins_root, commit=False, hook=None) -> MoveToBinResult``
``assign_batch(assignments, *, bins_root, commit=False, hook=None) -> AssignResult``
``reject_image(image, *, commit=False, hook=None) -> RejectResult``
``load_assignments(path) -> list[Assignment]``
``Assignment``
``BinSummary``
``MoveToBinResult``
``AssignResult``
``RejectResult``
``DEFAULT_IMAGE_SUFFIXES``
    Same set as ``intake_init.DEFAULT_IMAGE_SUFFIXES``.
``OPERATION = "character_tools"``
``build_parser()``
``main(argv=None)``
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from lib_safety import (
    NULL_HOOK,
    AuditEvent,
    AuditHook,
    DestinationExistsError,
    find_companions,
    load_json_records,
    move_with_companions,
    normalise_suffix_set,
    optional_jsonl_hook,
    trash,
)

#: Names the ``character_tools`` package re-exports.
__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "OPERATION",
    "Assignment",
    "AssignResult",
    "BinSummary",
    "MoveToBinResult",
    "RejectResult",
    "assign_batch",
    "build_parser",
    "check_bins",
    "list_images",
    "load_assignments",
    "main",
    "move_to_bin",
    "normalise_bin_name",
    "reject_image",
]

#: Raster-image suffixes used by list/check (lowercase, with dots); same set as
#: ``intake_init.DEFAULT_IMAGE_SUFFIXES``.
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
)

#: Audit operation recorded for every action; ``reason`` distinguishes
#: ``move`` from ``reject``.
OPERATION = "character_tools"

_BIN_NAME_RE = re.compile(r"[A-Za-z0-9 _.-]+\Z")


def normalise_bin_name(name: str) -> str:
    """Return *name* stripped, or raise :class:`ValueError` (see "Bin names")."""
    if not isinstance(name, str):
        raise ValueError(f"bin name must be a string, got {type(name).__name__}")
    normalised = name.strip()
    if not normalised:
        raise ValueError("bin name must not be empty")
    if "/" in normalised or "\\" in normalised:
        raise ValueError(f"bin name must not contain path separators: {normalised!r}")
    if ".." in normalised or normalised == ".":
        raise ValueError(
            f"bin name must be a single subdirectory under bins_root "
            f"(no '..', not '.'): {normalised!r}"
        )
    if _BIN_NAME_RE.fullmatch(normalised) is None:
        raise ValueError(
            f"bin name contains characters outside the allowed set "
            f"(letters, digits, space, '_', '-', '.'): {normalised!r}"
        )
    return normalised


def list_images(source: str | Path, *, suffixes: object = None) -> list[Path]:
    """List image files from a source file or directory (not recursive).

    ``suffixes=None`` uses :data:`DEFAULT_IMAGE_SUFFIXES`.
    """
    src = Path(source).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")
    allowed = normalise_suffix_set(suffixes, DEFAULT_IMAGE_SUFFIXES)
    if src.is_file():
        return [src] if src.suffix.lower() in allowed else []
    if not src.is_dir():
        raise NotADirectoryError(f"source is not a directory: {src}")
    return sorted(
        (
            path
            for path in src.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in allowed
        ),
        key=lambda path: path.name,
    )


@dataclass(frozen=True)
class BinSummary:
    """One immediate subdirectory of a bins root.

    ``images`` is the sorted tuple of image basenames directly inside the
    subdirectory; empty bins are reported with ``image_count`` 0.
    """

    name: str
    path: Path
    image_count: int
    images: tuple[str, ...]


def check_bins(bins_root: str | Path, *, suffixes: object = None) -> list[BinSummary]:
    """Report every non-hidden immediate subdirectory of *bins_root*, empty or not."""
    root = Path(bins_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"bins root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"bins root is not a directory: {root}")
    root = root.resolve()
    allowed = normalise_suffix_set(suffixes, DEFAULT_IMAGE_SUFFIXES)

    summaries: list[BinSummary] = []
    subdirs = [
        path for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    for subdir in sorted(subdirs, key=lambda path: path.name):
        images = tuple(
            sorted(
                path.name
                for path in subdir.iterdir()
                if path.is_file()
                and not path.name.startswith(".")
                and path.suffix.lower() in allowed
            )
        )
        summaries.append(
            BinSummary(subdir.name, subdir, len(images), images)
        )
    return summaries


@dataclass(frozen=True)
class MoveToBinResult:
    """What :func:`move_to_bin` planned (dry-run) or performed (commit).

    ``image`` is the source image path. ``destination_image`` and
    ``companions`` are destination paths: planned on dry-run, final on commit.
    """

    image: Path
    bin_name: str
    bins_root: Path
    destination_image: Path
    companions: tuple[Path, ...]
    committed: bool


def _plan_move(
    source: Path,
    name: str,
    root: Path,
    hook: AuditHook,
) -> tuple[Path, Path, tuple[Path, ...]]:
    """Validate one move and return ``(bin_dir, dest_image, dest_companions)``."""
    if not source.is_file():
        hook.record(
            AuditEvent(operation=OPERATION, source=str(source), ok=False,
                       reason="move; image not found")
        )
        raise FileNotFoundError(f"image not found: {source}")
    bin_dir = root / name
    if bin_dir.exists() and not bin_dir.is_dir():
        raise NotADirectoryError(f"bin path is not a directory: {bin_dir}")

    companions = tuple(find_companions(source))
    destination_image = bin_dir / source.name
    destination_companions = tuple(bin_dir / c.name for c in companions)
    for target in (destination_image, *destination_companions):
        if target.exists():
            hook.record(
                AuditEvent(
                    operation=OPERATION,
                    source=str(source),
                    destination=str(destination_image),
                    companions=tuple(str(c) for c in companions),
                    ok=False,
                    reason=f"move; destination already exists: {target.name}",
                )
            )
            raise DestinationExistsError(
                f"refusing to move {source.name}: destination already exists: "
                f"{target}"
            )
    return bin_dir, destination_image, destination_companions


def move_to_bin(
    image: str | Path,
    bin_name: str,
    *,
    bins_root: str | Path,
    commit: bool = False,
    hook: AuditHook | None = None,
) -> MoveToBinResult:
    """Move *image* (and its same-stem companions) into the named bin.

    Dry-run (default) validates the plan and writes nothing; commit creates
    the bin if needed and moves. Raises :class:`FileNotFoundError` /
    :class:`NotADirectoryError` for bad paths, :class:`ValueError` for a bad
    bin name, and :class:`~lib_safety.DestinationExistsError` when any
    destination exists.
    """
    source = Path(image).expanduser()
    root = Path(bins_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"bins root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"bins root is not a directory: {root}")
    root = root.resolve()
    hook = hook or NULL_HOOK
    name = normalise_bin_name(bin_name)
    source = source.resolve()

    bin_dir, destination_image, destination_companions = _plan_move(
        source, name, root, hook
    )

    if not commit:
        hook.record(
            AuditEvent(
                operation=OPERATION,
                source=str(source),
                destination=str(destination_image),
                companions=tuple(str(c) for c in destination_companions),
                ok=True,
                reason="move; dry_run",
            )
        )
        return MoveToBinResult(
            source, name, root, destination_image, destination_companions, False
        )

    bin_dir.mkdir(parents=True, exist_ok=True)
    move_result = move_with_companions(source, bin_dir, hook=hook)
    hook.record(
        AuditEvent(
            operation=OPERATION,
            source=str(source),
            destination=str(move_result.image),
            companions=tuple(str(c) for c in move_result.companions),
            ok=True,
            reason="move; committed=True",
        )
    )
    return MoveToBinResult(
        source, name, root, move_result.image, move_result.companions, True
    )


@dataclass(frozen=True)
class Assignment:
    """One assignment: an image path and a bin name, both checked when applied.

    A relative ``source`` resolves against the current working directory.
    """

    source: str | Path
    bin_name: str


@dataclass(frozen=True)
class AssignResult:
    """What :func:`assign_batch` planned or performed.

    ``planned_count`` is the number of assignments, ``moved_count`` counts the
    assignments actually moved (0 on dry-run), and ``results`` holds one
    :class:`MoveToBinResult` per assignment in order.
    """

    bins_root: Path
    planned_count: int
    moved_count: int
    committed: bool
    results: tuple[MoveToBinResult, ...]


def _coerce_assignments(
    assignments: Iterable[Assignment | tuple[str | Path, str]],
) -> list[Assignment]:
    coerced: list[Assignment] = []
    for index, item in enumerate(assignments, start=1):
        if isinstance(item, Assignment):
            coerced.append(item)
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            source, bin_name = item
            coerced.append(Assignment(source=Path(source).expanduser(), bin_name=bin_name))
        else:
            raise ValueError(
                f"assignment #{index} must be an Assignment or a "
                f"(image_path, bin_name) pair, got {item!r}"
            )
    return coerced


def assign_batch(
    assignments: Iterable[Assignment | tuple[str | Path, str]],
    *,
    bins_root: str | Path,
    commit: bool = False,
    hook: AuditHook | None = None,
) -> AssignResult:
    """Apply *assignments* in order into named bins under *bins_root*.

    Accepts :class:`Assignment` items or ``(image_path, bin_name)`` pairs.
    Stops and raises at the first failure; on commit, earlier moves stay done.
    """
    root = Path(bins_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"bins root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"bins root is not a directory: {root}")
    root = root.resolve()
    hook = hook or NULL_HOOK

    batch = _coerce_assignments(assignments)
    results: list[MoveToBinResult] = []
    moved_count = 0
    for assignment in batch:
        result = move_to_bin(
            assignment.source,
            assignment.bin_name,
            bins_root=root,
            commit=commit,
            hook=hook,
        )
        results.append(result)
        if result.committed:
            moved_count += 1

    return AssignResult(root, len(batch), moved_count, commit, tuple(results))


@dataclass(frozen=True)
class RejectResult:
    """What :func:`reject_image` planned (dry-run) or trashed (commit).

    ``companions`` are the same-stem sidecar paths discovered next to the
    image; ``trashed`` is the tuple returned by ``lib_safety.trash`` on commit
    (companions first, then the image) and is empty on dry-run.
    """

    image: Path
    companions: tuple[Path, ...]
    trashed: tuple[Path, ...]
    committed: bool


def reject_image(
    image: str | Path,
    *,
    commit: bool = False,
    hook: AuditHook | None = None,
) -> RejectResult:
    """Trash *image* and its same-stem companions (dry-run default).

    On commit, companions go first and then the image, so no sidecar is left
    without its image.
    """
    source = Path(image).expanduser()
    hook = hook or NULL_HOOK
    if not source.is_file():
        hook.record(
            AuditEvent(operation=OPERATION, source=str(source), ok=False,
                       reason="reject; image not found")
        )
        raise FileNotFoundError(f"image not found: {source}")
    source = source.resolve()

    if not commit:
        companions = tuple(find_companions(source))
        hook.record(
            AuditEvent(
                operation=OPERATION,
                source=str(source),
                companions=tuple(str(c) for c in companions),
                ok=True,
                reason="reject; dry_run",
            )
        )
        return RejectResult(source, companions, (), False)

    trashed = trash(source, companions=True, hook=hook)
    companions = tuple(path for path in trashed if path != source)
    hook.record(
        AuditEvent(
            operation=OPERATION,
            source=str(source),
            companions=tuple(str(c) for c in companions),
            ok=True,
            reason="reject; committed=True",
        )
    )
    return RejectResult(source, companions, trashed, True)


def _record_to_assignment(record: object, path: Path, index: int) -> Assignment:
    if not isinstance(record, dict):
        raise ValueError(f"assignment #{index} in {path} must be a JSON object")
    if set(record) != {"source", "bin"}:
        raise ValueError(
            f"assignment #{index} in {path} must have exactly 'source' and "
            f"'bin' keys"
        )
    source = record["source"]
    bin_name = record["bin"]
    if not isinstance(source, str) or not source:
        raise ValueError(
            f"assignment #{index} in {path} must have a non-empty string "
            f"'source'"
        )
    if not isinstance(bin_name, str):
        raise ValueError(f"assignment #{index} in {path} must have a string 'bin'")
    return Assignment(source=Path(source).expanduser(), bin_name=bin_name)


def load_assignments(path: str | Path) -> list[Assignment]:
    """Load assignments from a JSON array file or a ``.jsonl`` file.

    Each object must have exactly the ``source`` and ``bin`` keys; anything
    else raises :class:`ValueError`.
    """
    return load_json_records(path, "assignments file", _record_to_assignment)


def _move_result_dict(result: MoveToBinResult) -> dict[str, object]:
    return {
        "image": str(result.image),
        "bin_name": result.bin_name,
        "bins_root": str(result.bins_root),
        "destination_image": str(result.destination_image),
        "companions": [str(path) for path in result.companions],
        "committed": result.committed,
    }


def _bin_summary_dict(summary: BinSummary) -> dict[str, object]:
    return {
        "name": summary.name,
        "path": str(summary.path),
        "image_count": summary.image_count,
        "images": list(summary.images),
    }


def _assign_result_dict(result: AssignResult) -> dict[str, object]:
    return {
        "bins_root": str(result.bins_root),
        "planned_count": result.planned_count,
        "moved_count": result.moved_count,
        "committed": result.committed,
        "results": [_move_result_dict(item) for item in result.results],
    }


def _reject_result_dict(result: RejectResult) -> dict[str, object]:
    return {
        "image": str(result.image),
        "companions": [str(path) for path in result.companions],
        "trashed": [str(path) for path in result.trashed],
        "committed": result.committed,
    }


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-character`` CLI."""
    parser = argparse.ArgumentParser(
        prog="pickkit-character",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_mutation_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--commit", action="store_true",
            help="Perform the move/trash (default is dry-run)",
        )
        target.add_argument(
            "--audit", metavar="PATH",
            help="Append audit events to PATH via lib_safety.JsonlAuditHook",
        )

    list_parser = subparsers.add_parser(
        "list", help="List image files in a source file or directory"
    )
    list_parser.add_argument("source", help="Image file or directory to list")

    check_parser = subparsers.add_parser(
        "check", help="Report named bins under a bins root"
    )
    check_parser.add_argument(
        "bins_root", help="Directory whose immediate subdirectories are bins"
    )

    move_parser = subparsers.add_parser(
        "move", help="Move one image and its companions into a named bin"
    )
    move_parser.add_argument("image", help="Image file to move")
    move_parser.add_argument(
        "--bin", required=True, metavar="NAME",
        help="Destination bin name (a single subdirectory under --bins-root)",
    )
    move_parser.add_argument(
        "--bins-root", required=True, metavar="DIR",
        help="Root directory containing the named bins",
    )
    add_mutation_flags(move_parser)

    assign_parser = subparsers.add_parser(
        "assign", help="Apply a JSON/JSONL assignment map"
    )
    assign_parser.add_argument(
        "map_path", metavar="MAP.json",
        help="JSON array or JSONL file of {'source': ..., 'bin': ...} objects",
    )
    assign_parser.add_argument(
        "--bins-root", required=True, metavar="DIR",
        help="Root directory containing the named bins",
    )
    add_mutation_flags(assign_parser)

    reject_parser = subparsers.add_parser(
        "reject", help="Trash one image and its companions"
    )
    reject_parser.add_argument("image", help="Image file to trash")
    add_mutation_flags(reject_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args, dispatches, and prints JSON to stdout."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            images = list_images(args.source)
            summary: dict[str, object] = {
                "source": str(Path(args.source).expanduser()),
                "images": [str(path) for path in images],
            }
        elif args.command == "check":
            bins = check_bins(args.bins_root)
            summary = {
                "bins_root": str(Path(args.bins_root).expanduser()),
                "bins": [_bin_summary_dict(item) for item in bins],
            }
        elif args.command == "move":
            summary = _move_result_dict(
                move_to_bin(
                    args.image,
                    args.bin,
                    bins_root=args.bins_root,
                    commit=args.commit,
                    hook=optional_jsonl_hook(args.audit),
                )
            )
        elif args.command == "assign":
            summary = _assign_result_dict(
                assign_batch(
                    load_assignments(args.map_path),
                    bins_root=args.bins_root,
                    commit=args.commit,
                    hook=optional_jsonl_hook(args.audit),
                )
            )
        elif args.command == "reject":
            summary = _reject_result_dict(
                reject_image(
                    args.image,
                    commit=args.commit,
                    hook=optional_jsonl_hook(args.audit),
                )
            )
        else:  # pragma: no cover - argparse guarantees a known subcommand
            parser.error(f"unknown command: {args.command}")
    except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError) as exc:
        parser.exit(1, f"pickkit-character: error: {exc}\n")

    print(json.dumps(summary, indent=2))
    return 0
