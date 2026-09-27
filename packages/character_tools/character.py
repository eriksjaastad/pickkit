"""Assign images to user-supplied named bins, moving same-stem companions together.

This module is the single source of truth for character-tools behaviour: how
images are listed, how named bins are validated and reported, how an image and
its same-stem companions are moved into a user-supplied bin under a bins root,
how batch assignment maps are loaded and applied, how rejects are trashed, and
how the thin CLI wraps the library. The private precursor sorter was a Flask
UI with LoRA cast lists, demographic extractors, hard-coded
``__character_group_N/`` bins, and FileTracker SQLite; pickkit's
character-tools is a **library + thin CLI** that only moves/trashes files
through ``lib_safety`` and never invents a taxonomy, group name, or
recommendation.

Principles
----------
Library first
    :func:`move_to_bin` / :func:`assign_batch` / :func:`reject_image` are the
    whole behaviour; the CLI in this module is a thin wrapper around them.
User-supplied named bins
    A bin is just a subdirectory name under a caller-supplied *bins_root*. Bin
    names are validated with :func:`normalise_bin_name`; they are never
    auto-slugged and the literal normalised name becomes the directory name
    (spaces are fine on macOS/Linux).
Move, never modify
    Moves go through ``lib_safety.move_with_companions``; rejects go through
    ``lib_safety.trash``. Pixels are never read, decoded, or rewritten.
Dry-run vs commit
    Default is dry-run (``commit=False``) everywhere a mutation would happen:
    plans are validated and **nothing** is written. ``--commit`` /
    ``commit=True`` performs the moves/trash.
Audit
    One :class:`~lib_safety.AuditEvent` with operation :data:`OPERATION`
    (``character_tools``) is recorded per action; ``reason`` distinguishes
    ``move`` from ``reject`` and records ``dry_run`` / ``committed=True``.
    ``lib_safety`` additionally records its own ``move`` / ``trash`` events on
    the same hook. Library default ``hook=None`` means
    :data:`lib_safety.NULL_HOOK` (no audit file); the CLI creates an audit
    file only when ``--audit PATH`` is given, via
    ``lib_safety.JsonlAuditHook``.
Optional middle tool, not a spine step
    :data:`intake_init.PUBLIC_SPINE_STEPS` stays ``intake`` / ``review_select``
    / ``multi_crop`` / ``finish_package``. character-tools never adds a step,
    never requires an intake'd batch, and never touches ``.pickkit/project.json``
    (``finished_at``, ``steps``, or ``metrics``).

Bin naming
----------
:func:`normalise_bin_name` strips surrounding whitespace and refuses a name
that is empty, contains ``/``, ``\\``, or ``..``, is exactly ``.``, or
contains any character outside the allowed set (ASCII letters, ASCII digits,
space, ``_``, ``-``, ``.``); refusals raise :class:`ValueError`. Destination
for an image: ``<bins_root>/<bin_name>/<basename>`` with each same-stem
companion beside it. The bin directory is created on first commit move if
missing. Collision: if any destination path already exists the whole move is
refused (:class:`~lib_safety.DestinationExistsError`) before anything is moved
— never overwrite.

Operations
----------
``list_images(source, *, suffixes=None)``
    A file that looks like an image returns ``[source]`` (a non-image file
    returns ``[]``); a directory returns the non-recursive image list, hidden
    names skipped, sorted by name. ``suffixes=None`` uses
    :data:`DEFAULT_IMAGE_SUFFIXES`.

``check_bins(bins_root, *, suffixes=None)``
    Scans immediate subdirectories of *bins_root* (one level). Every immediate
    subdirectory is reported as a :class:`BinSummary` — including empty ones
    (``image_count`` 0) so ``check`` shows structure. ``images`` is the sorted
    tuple of image basenames directly inside it. Hidden subdirectories are
    skipped.

``move_to_bin(image, bin_name, *, bins_root, commit=False, hook=None)``
    Validates *image* (existing file) and *bins_root* (existing directory),
    normalises *bin_name*, discovers companions via
    ``lib_safety.find_companions``, and plans destinations. Dry-run returns the
    plan with ``committed=False`` and writes nothing. Commit creates the bin
    directory if needed and calls ``lib_safety.move_with_companions(image,
    bin_dir, hook=hook)``.

``assign_batch(assignments, *, bins_root, commit=False, hook=None)``
    Applies :class:`Assignment` items (or ``(image_path, bin_name)`` pairs) in
    order. On the first hard failure (missing file, bad bin name, existing
    destination) it stops and raises. Dry-run validates every plan without
    moving; commit keeps earlier successful moves if a later one fails.

``reject_image(image, *, commit=False, hook=None)``
    Trashes the image **and** its same-stem companions. Dry-run lists what
    would be trashed; commit calls ``lib_safety.trash(image, companions=True)``
    so companions go first, then the image — no orphans.

``load_assignments(path)``
    Reads a JSON array of ``{"source": "...", "bin": "..."}`` objects, or a
    JSONL file (``.jsonl``) with one object per line. Objects must have exactly
    the ``source`` and ``bin`` keys; anything else raises :class:`ValueError`.
    Relative ``source`` paths resolve against the current working directory.

Public API
----------
``normalise_bin_name(name) -> str``
    Validate and return the normalised bin directory name (see Bin naming).
``list_images(source, *, suffixes=None) -> list[Path]``
    List image files from a source file or directory (see Operations).
``check_bins(bins_root, *, suffixes=None) -> list[BinSummary]``
    Report every immediate subdirectory of *bins_root* as a BinSummary.
``move_to_bin(image, bin_name, *, bins_root, commit=False, hook=None) -> MoveToBinResult``
    Plan (dry-run) or perform (commit) one move into a named bin.
``assign_batch(assignments, *, bins_root, commit=False, hook=None) -> AssignResult``
    Plan or perform many moves in order; stops on the first hard failure.
``reject_image(image, *, commit=False, hook=None) -> RejectResult``
    Plan (dry-run) or perform (commit) a trash of an image and its companions.
``load_assignments(path) -> list[Assignment]``
    Load a JSON-array or JSONL assignment map (see Operations).
``Assignment``
    Frozen dataclass: ``source`` (image path, ``str`` or :class:`Path`) and
    ``bin_name`` (:class:`str`).
``BinSummary``
    Frozen dataclass: ``name``, ``path``, ``image_count``, ``images`` (sorted
    basename strings).
``MoveToBinResult``
    Frozen dataclass: ``image`` (source), ``bin_name``, ``bins_root``,
    ``destination_image``, ``companions`` (destination paths; planned on
    dry-run, final on commit), ``committed``.
``AssignResult``
    Frozen dataclass: ``bins_root``, ``planned_count``, ``moved_count``,
    ``committed``, ``results`` (per-move results in order).
``RejectResult``
    Frozen dataclass: ``image``, ``companions``, ``trashed`` (the
    ``lib_safety.trash`` return on commit, empty on dry-run), ``committed``.
``DEFAULT_IMAGE_SUFFIXES``
    Tuple of raster-image suffixes used by list/check (lowercase, with dots);
    same set as :data:`intake_init.DEFAULT_IMAGE_SUFFIXES`.
``OPERATION``
    Audit operation recorded for every action: ``character_tools`` (``reason``
    distinguishes ``move`` vs ``reject``).
``build_parser()``
    Return the argparse parser for the ``pickkit-character`` CLI. The parser
    description is this module docstring; subcommands are ``list``, ``check``,
    ``move``, ``assign``, and ``reject``.
``main(argv=None)``
    CLI entry point; parses args, dispatches, and prints a JSON summary.

CLI
---
The ``pickkit-character`` CLI uses subcommands and prints a JSON summary to
stdout:

    pickkit-character list SOURCE
    pickkit-character check BINS_ROOT
    pickkit-character move IMAGE --bin NAME --bins-root DIR [--commit] [--audit PATH]
    pickkit-character assign MAP.json --bins-root DIR [--commit] [--audit PATH]
    pickkit-character reject IMAGE [--commit] [--audit PATH]

``--commit`` performs the move/trash (default is dry-run). ``--audit PATH``
appends audit events to PATH via ``lib_safety.JsonlAuditHook``; without it no
audit file is created. ``--bin`` names the destination bin and ``--bins-root``
points at the bins root for ``move`` / ``assign``. ``python -m
character_tools`` runs the same CLI.

Examples
--------
    from character_tools import list_images, check_bins, move_to_bin

    list_images("sandbox/batch_a")                    # 4 pngs, sorted
    plan = move_to_bin("sandbox/batch_a/img_004.png", "alice",
                       bins_root="sandbox/bins")
    plan.committed                                     # False
    done = move_to_bin("sandbox/batch_a/img_004.png", "alice",
                       bins_root="sandbox/bins", commit=True)
    done.committed                                     # True

Out of scope
------------
The interactive web sorter UI (Flask/Tk) is **out of scope** — no web server,
templates, or browser UI. LoRA cast lists, demographic extractors
(ethnicity/age/body/hair), ``_underscore`` private bins, similarity-map / face
grouper, prompt/YAML AI analysis, FileTracker SQLite, client project paths, and
hard-coded ``__character_group_N/`` names are **not** this module's job (users
may choose any valid bin name, including those strings, but none are
required). character-tools never extends ``PUBLIC_SPINE_STEPS``, never requires
intake, and never mutates the spine manifest.
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
    JsonlAuditHook,
    find_companions,
    move_with_companions,
    trash,
)

#: Raster-image suffixes used by list/check (lowercase, with dots); same set as
#: ``intake_init.DEFAULT_IMAGE_SUFFIXES``.
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
)

#: Audit operation recorded for every action; ``reason`` distinguishes
#: ``move`` from ``reject``.
OPERATION = "character_tools"

_BIN_NAME_RE = re.compile(r"[A-Za-z0-9 _.-]+\Z")


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def normalise_bin_name(name: str) -> str:
    """Validate *name* and return the normalised bin directory name.

    Strips surrounding whitespace; refuses empty names, names containing
    ``/``, ``\\``, or ``..``, the name ``.``, and any character outside the
    allowed set (ASCII letters, ASCII digits, space, ``_``, ``-``, ``.``).
    Returns the stripped name unchanged — never auto-slugged.
    """
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


def list_images(source: str | Path, *, suffixes: object = None) -> list[Path]:
    """List image files from a source file or directory.

    A file that looks like an image returns ``[source]`` (a non-image file
    returns ``[]``); a directory returns the non-recursive image list, hidden
    names skipped, sorted by name. ``suffixes=None`` uses
    :data:`DEFAULT_IMAGE_SUFFIXES`.
    """
    src = _as_path(source)
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")
    allowed = _normalise_suffix_set(suffixes)
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
    """Report every immediate subdirectory of *bins_root* as a BinSummary.

    Scans one level only; empty subdirectories are included with
    ``image_count`` 0, hidden subdirectories are skipped, and ``images`` holds
    sorted image basenames found directly inside each subdirectory.
    """
    root = _as_path(bins_root)
    if not root.exists():
        raise FileNotFoundError(f"bins root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"bins root is not a directory: {root}")
    root = root.resolve()
    allowed = _normalise_suffix_set(suffixes)

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
    ``<bins_root>/<bin_name>/`` if needed and calls
    ``lib_safety.move_with_companions(image, bin_dir, hook=hook)``. Refuses
    with :class:`FileNotFoundError` / :class:`NotADirectoryError` for bad
    paths, :class:`ValueError` for a bad bin name, and
    :class:`~lib_safety.DestinationExistsError` when any destination exists.
    """
    source = _as_path(image)
    root = _as_path(bins_root)
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
    """One assignment: an image source path and a destination bin name.

    ``source`` is the image path (``str`` or :class:`Path`); relative paths
    resolve against the current working directory when applied. ``bin_name``
    is a string and is validated by :func:`normalise_bin_name` when the
    assignment is applied.
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
            coerced.append(Assignment(source=_as_path(source), bin_name=bin_name))
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

    Accepts :class:`Assignment` items or ``(image_path, bin_name)`` pairs. On
    the first hard failure (missing file, bad bin name, existing destination)
    it stops and raises; dry-run validates every plan without moving, while
    commit keeps earlier successful moves when a later one fails.
    """
    root = _as_path(bins_root)
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

    Dry-run lists what would be trashed and writes nothing. Commit calls
    ``lib_safety.trash(image, companions=True, hook=hook)`` so companions go
    first, then the image — no orphans are left behind.
    """
    source = _as_path(image)
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
    return Assignment(source=_as_path(source), bin_name=bin_name)


def load_assignments(path: str | Path) -> list[Assignment]:
    """Load assignments from a JSON array file or a JSONL file.

    A ``.jsonl`` file is read one JSON object per line; any other file is read
    as a JSON array of ``{"source": "...", "bin": "..."}`` objects. Objects
    must have exactly the ``source`` and ``bin`` keys; blank JSONL lines are
    skipped and anything else is refused with :class:`ValueError`.
    """
    map_path = _as_path(path)
    if not map_path.is_file():
        raise FileNotFoundError(f"assignments file not found: {map_path}")

    if map_path.suffix.lower() == ".jsonl":
        loaded: list[Assignment] = []
        for line_no, raw in enumerate(
            map_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL in {map_path} at line {line_no}: {exc}"
                ) from exc
            loaded.append(_record_to_assignment(record, map_path, line_no))
        return loaded

    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {map_path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"assignments file must contain a JSON array: {map_path}")
    return [
        _record_to_assignment(record, map_path, index)
        for index, record in enumerate(data, start=1)
    ]


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


def _audit_hook(path: str | None) -> AuditHook | None:
    return JsonlAuditHook(path) if path else None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args, dispatches, and prints JSON to stdout."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            images = list_images(args.source)
            summary: dict[str, object] = {
                "source": str(_as_path(args.source)),
                "images": [str(path) for path in images],
            }
        elif args.command == "check":
            bins = check_bins(args.bins_root)
            summary = {
                "bins_root": str(_as_path(args.bins_root)),
                "bins": [_bin_summary_dict(item) for item in bins],
            }
        elif args.command == "move":
            summary = _move_result_dict(
                move_to_bin(
                    args.image,
                    args.bin,
                    bins_root=args.bins_root,
                    commit=args.commit,
                    hook=_audit_hook(args.audit),
                )
            )
        elif args.command == "assign":
            summary = _assign_result_dict(
                assign_batch(
                    load_assignments(args.map_path),
                    bins_root=args.bins_root,
                    commit=args.commit,
                    hook=_audit_hook(args.audit),
                )
            )
        elif args.command == "reject":
            summary = _reject_result_dict(
                reject_image(
                    args.image,
                    commit=args.commit,
                    hook=_audit_hook(args.audit),
                )
            )
        else:  # pragma: no cover - argparse guarantees a known subcommand
            parser.error(f"unknown command: {args.command}")
    except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError) as exc:
        parser.exit(1, f"pickkit-character: error: {exc}\n")

    print(json.dumps(summary, indent=2))
    return 0
