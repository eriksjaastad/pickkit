"""Find exact and near-duplicate images and thin the extras into the OS trash.

This module is the single source of truth for duplicate-finder behaviour: how
images are listed (non-recursive by default), how exact duplicates are hashed
(sha256 over the full file bytes), how near duplicates are hashed (Pillow
average hash / aHash), how near-duplicate clusters are built (deterministic
greedy seed-neighbour clustering), how one keeper is chosen per group, and
how the thin CLI wraps the library. The private precursor was a visual
two-directory Flask UI with no perceptual-hash engine; pickkit's
duplicate-finder is a **library + thin CLI** that only reports groups and
trashes drop candidates through ``lib_safety``.

Principles
----------
Library first
    :func:`find_exact_duplicates` / :func:`find_near_duplicates` /
    :func:`thin_groups` are the whole behaviour; the CLI in this module is a
    thin wrapper around them.
Report, then thin
    Finding duplicates never mutates anything. Thinning is dry-run by
    default (``commit=False``) and only ``--commit`` / ``commit=True``
    trashes drop candidates.
Recoverable deletes only
    Thinning trashes each drop through ``lib_safety.trash(...,
    companions=True)`` so the image and its same-stem sidecars go to the OS
    trash together. The keeper is never trashed and nothing is overwritten.
Audit
    One :class:`~lib_safety.AuditEvent` with operation :data:`OPERATION`
    (``duplicate_finder``) is recorded per thin decision and per committed
    trash; ``reason`` distinguishes ``find_exact`` / ``find_near`` /
    ``thin; dry_run`` / ``thin; committed=True``. Library default
    ``hook=None`` means :data:`lib_safety.NULL_HOOK` (no audit file); the
    CLI creates an audit file only when ``--audit PATH`` is given, via
    ``lib_safety.JsonlAuditHook``.
Optional middle tool, not a spine step
    :data:`intake_init.PUBLIC_SPINE_STEPS` stays ``intake`` /
    ``review_select`` / ``multi_crop`` / ``finish_package``.
    duplicate-finder never adds a step, never requires an intake'd batch,
    and never touches ``.pickkit/project.json`` (``finished_at``, ``steps``,
    or ``metrics``).

Scope and defaults
------------------
Scan one or more directories (or individual image files) for duplicates. The
default listing is **non-recursive**: each given root lists the images
directly inside it, hidden names skipped, sorted by name — the same spirit as
``character_tools.list_images``. ``--recursive`` / ``recursive=True`` walks
subdirectories with ``Path.rglob`` and skips hidden path parts (any path part
starting with ``.``). Image suffixes come from
:data:`DEFAULT_IMAGE_SUFFIXES` (the same set as intake_init /
character_tools). duplicate_finder mirrors the small listing helper locally
so it has no cross-plugin hard dependency.

Exact duplicates
----------------
Content hash is **SHA-256** of the full file bytes, read in 1 MiB chunks via
:func:`hashlib.sha256`. Files that share the same digest form a group when
the group has at least two members. :func:`content_hash` returns the
lowercase hex digest string.

Near duplicates
---------------
Near mode uses a lightweight perceptual hash via **Pillow only** (already a
dependency): the **average hash (aHash)**. :func:`average_hash` opens the
image, converts it to greyscale, resizes it to ``hash_size x hash_size``
(default :data:`HASH_SIZE` = 8, so a 64-bit hash), compares each pixel to the
mean, and packs the comparison bits into an :class:`int` (1 when the pixel is
above the mean, else 0). :func:`hamming_distance` returns the number of
differing bits between two hashes. The default threshold is
:data:`DEFAULT_NEAR_THRESHOLD` = 5 Hamming bits for a 64-bit hash; it is
tunable via ``threshold=`` / ``--threshold N``.

Clustering
----------
:func:`find_near_duplicates` locks this simple deterministic approach:

1. Compute aHash for every image.
2. Greedy seed-neighbour clustering: sort paths by name (ties by resolved
   path string); for each unassigned image, start a cluster and pull in every
   other unassigned image whose Hamming distance to the **seed** is ≤
   ``threshold`` (not transitive full closure — documented as
   seed-neighbour clustering).
3. Only report clusters with at least two members.

Exact-dup groups that are also near-dups may appear in both modes; that is
fine. Modes are selected by the caller, never mixed in one call — prefer the
separate :func:`find_exact_duplicates` and :func:`find_near_duplicates`
functions.

Keep policy for thinning
------------------------
When a group is thinned, **one file is kept and the rest are trashed** (with
companions). Policies live in :data:`KEEP_POLICIES`:

``keep_first``
    Keep the lexicographically first path by resolved absolute path string
    (deterministic; the default :data:`DEFAULT_KEEP_POLICY`).
``keep_largest``
    Keep the largest file size in bytes; tie-break by path name.
``keep_oldest``
    Keep the oldest ``st_mtime``; tie-break by path name.

The keeper is never trashed; nothing is ever overwritten.

Thinning
--------
:func:`thin_groups(groups, *, commit=False, keep_policy=..., hook=None)` plans
a keep/drop decision for every group via :func:`plan_thin`. Dry-run (default)
computes and validates every plan and writes nothing. With ``commit=True``
each drop is trashed via ``lib_safety.trash(path, companions=True,
hook=hook)``. All plans are validated before the first trash; on the first
trash failure the function stops and raises (earlier drops stay trashed). A
quarantine folder is out of scope — trash is the locked thinning action
(recoverable).

Scanning
--------
``list_images(source, *, recursive=False, suffixes=None)``
    Local mirror of the character_tools listing helper. A file that looks
    like an image returns ``[source]`` (a non-image file returns ``[]``); a
    directory returns the non-recursive image list by default (hidden names
    skipped, sorted by name). With ``recursive=True`` the directory is
    walked with ``Path.rglob``, hidden path parts are skipped, and results
    are sorted by path string. ``suffixes=None`` uses
    :data:`DEFAULT_IMAGE_SUFFIXES`.

Public API
----------
``DEFAULT_IMAGE_SUFFIXES``
    Tuple of raster-image suffixes used by list/scan (lowercase, with dots);
    the same set as intake_init / character_tools.
``HASH_SIZE``
    Default aHash side length (8 → a 64-bit hash).
``DEFAULT_NEAR_THRESHOLD``
    Default Hamming-distance threshold for near-duplicate clustering (5).
``KEEP_POLICIES``
    Tuple of supported keep policies: ``keep_first``, ``keep_largest``,
    ``keep_oldest``.
``DEFAULT_KEEP_POLICY``
    Default keep policy: ``keep_first``.
``OPERATION``
    Audit operation recorded for every thin action: ``duplicate_finder``
    (``reason`` distinguishes ``find_exact`` / ``find_near`` /
    ``thin; dry_run`` / ``thin; committed=True``).
``content_hash(path) -> str``
    Return the lowercase sha256 hex digest of the full file bytes.
``average_hash(path, *, hash_size=HASH_SIZE) -> int``
    Return the Pillow average hash (aHash) of an image as an int.
``hamming_distance(a, b) -> int``
    Return the number of differing bits between two non-negative ints.
``list_images(source, *, recursive=False, suffixes=None) -> list[Path]``
    List image files from a source file or directory (see Scanning).
``find_exact_duplicates(sources, *, recursive=False, suffixes=None) -> list[DuplicateGroup]``
    Group images with identical sha256 digests into groups of size ≥ 2.
    *sources* may be a single path or a sequence of directories/files.
``find_near_duplicates(sources, *, recursive=False, threshold=DEFAULT_NEAR_THRESHOLD, hash_size=HASH_SIZE, suffixes=None) -> list[DuplicateGroup]``
    Cluster images by aHash seed-neighbour greedy clustering (groups of
    size ≥ 2).
``plan_thin(group, *, keep_policy=DEFAULT_KEEP_POLICY) -> ThinPlan``
    Choose the keeper and drop paths for one DuplicateGroup.
``thin_groups(groups, *, commit=False, keep_policy=DEFAULT_KEEP_POLICY, hook=None) -> ThinResult``
    Plan (dry-run) or perform (commit) thinning for many groups.
``DuplicateGroup``
    Frozen dataclass: ``kind`` (``"exact"`` | ``"near"``), ``key`` (hex
    digest or seed hash hex string), ``paths`` (member image paths), and
    optional ``threshold`` for near groups.
``ThinPlan``
    Frozen dataclass: ``keep`` (keeper path) and ``drop`` (paths to trash).
``ThinResult``
    Frozen dataclass: ``committed``, ``groups_planned``, ``kept``,
    ``dropped``, and ``plans`` (the per-group ThinPlans).
``build_parser()``
    Return the argparse parser for the ``pickkit-dupes`` CLI. The parser
    description is this module docstring; subcommands are ``exact``,
    ``near``, and ``thin``.
``main(argv=None)``
    CLI entry point; parses args, dispatches, and prints JSON to stdout.

CLI
---
The ``pickkit-dupes`` CLI uses subcommands and prints JSON to stdout:

    pickkit-dupes exact DIR [DIR ...] [--recursive] [--json]
    pickkit-dupes near DIR [DIR ...] [--recursive] [--threshold N] [--json]
    pickkit-dupes thin DIR [DIR ...] --mode exact|near [--recursive]
                 [--threshold N] [--keep keep_first|keep_largest|keep_oldest]
                 [--commit] [--audit PATH]

``exact`` / ``near`` print a JSON report of duplicate groups (paths + key)
and exit 0 even when no duplicates are found (an empty ``groups`` list).
``thin`` finds groups with the chosen ``--mode`` and then thins them; dry-run
is the default and prints the keep/drop plan JSON. ``--commit`` trashes the
drops (with companions) via ``lib_safety``. ``--recursive`` walks
directories instead of the default non-recursive listing. ``--threshold N``
sets the near-mode Hamming threshold. ``--keep`` selects the keep policy.
``--audit PATH`` appends audit events via ``lib_safety.JsonlAuditHook``.
``--json`` is accepted on ``exact`` / ``near`` for script symmetry (JSON is
already the default output format). ``python -m duplicate_finder`` runs the
same CLI.

Examples
--------
    from duplicate_finder import find_exact_duplicates, thin_groups

    groups = find_exact_duplicates("sandbox/batch_a")
    groups[0].kind                                     # "exact"
    result = thin_groups(groups)
    result.committed                                   # False
    done = thin_groups(groups, commit=True)
    done.committed                                     # True

Out of scope
------------
The interactive two-directory visual UI (Flask/Tk) is **out of scope** — no
web server, templates, or browser UI. Client ``duplicate_group_*`` delivery
layouts, training CSV hooks, and silent permanent deletes are **not** this
module's job. duplicate-finder never extends ``PUBLIC_SPINE_STEPS``, never
requires intake, and never mutates the spine manifest. A quarantine folder is
future work; trash is the locked thinning action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from lib_safety import (
    NULL_HOOK,
    AuditEvent,
    AuditHook,
    normalise_suffix_set,
    optional_jsonl_hook,
    trash,
)

#: Raster-image suffixes used by list/scan (lowercase, with dots); same set as
#: ``intake_init.DEFAULT_IMAGE_SUFFIXES`` / ``character_tools.DEFAULT_IMAGE_SUFFIXES``.
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
)

#: Default aHash side length (8 x 8 → a 64-bit hash).
HASH_SIZE = 8

#: Default Hamming-distance threshold for near-duplicate clustering (tunable).
DEFAULT_NEAR_THRESHOLD = 5

#: Supported keep policies for :func:`plan_thin` / :func:`thin_groups`.
KEEP_POLICIES = ("keep_first", "keep_largest", "keep_oldest")

#: Default keep policy: lexicographically first resolved absolute path.
DEFAULT_KEEP_POLICY = "keep_first"

#: Audit operation recorded for every thin action; ``reason`` distinguishes
#: ``find_exact`` / ``find_near`` / ``thin; dry_run`` / ``thin; committed=True``.
OPERATION = "duplicate_finder"


def _validate_hash_size(hash_size: object) -> int:
    if isinstance(hash_size, bool) or not isinstance(hash_size, int) or hash_size < 1:
        raise ValueError(f"hash_size must be a positive integer, got {hash_size!r}")
    return hash_size


def _validate_threshold(threshold: object) -> int:
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
        raise ValueError(f"threshold must be a non-negative integer, got {threshold!r}")
    return threshold


def list_images(
    source: str | Path,
    *,
    recursive: bool = False,
    suffixes: object = None,
) -> list[Path]:
    """List image files from a source file or directory.

    A file that looks like an image returns ``[source]`` (a non-image file
    returns ``[]``); a directory returns the non-recursive image list by
    default (hidden names skipped, sorted by name). With ``recursive=True``
    the directory is walked with ``Path.rglob``, hidden path parts are
    skipped, and results are sorted by path string. ``suffixes=None`` uses
    :data:`DEFAULT_IMAGE_SUFFIXES`.
    """
    src = Path(source).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")
    allowed = normalise_suffix_set(suffixes, DEFAULT_IMAGE_SUFFIXES)

    def _is_image(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in allowed

    if src.is_file():
        return [src] if src.suffix.lower() in allowed else []
    if not src.is_dir():
        raise NotADirectoryError(f"source is not a directory: {src}")

    if recursive:
        return sorted(
            (
                path
                for path in src.rglob("*")
                if _is_image(path)
                and not any(
                    part.startswith(".") for part in path.relative_to(src).parts
                )
            ),
            key=lambda path: str(path),
        )

    return sorted(
        (
            path
            for path in src.iterdir()
            if _is_image(path) and not path.name.startswith(".")
        ),
        key=lambda path: path.name,
    )


def _coerce_sources(sources: object) -> list[Path]:
    if isinstance(sources, (str, Path)):
        raw: list[object] = [sources]
    else:
        try:
            raw = list(sources)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(
                f"sources must be a path or a sequence of paths, got {sources!r}"
            ) from exc
    return [Path(item).expanduser() for item in raw]  # type: ignore[arg-type]


def _collect_images(
    sources: object,
    *,
    recursive: bool,
    suffixes: object,
) -> list[Path]:
    """Expand *sources* into a de-duplicated image list, preserving order."""
    images: list[Path] = []
    seen: set[str] = set()
    for source in _coerce_sources(sources):
        for path in list_images(source, recursive=recursive, suffixes=suffixes):
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                images.append(path)
    return images


def content_hash(path: str | Path) -> str:
    """Return the lowercase sha256 hex digest of the full file bytes.

    The file is read in 1 MiB chunks so large images never need to be held
    fully in memory. Raises :class:`FileNotFoundError` if *path* is not a
    file.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"image not found: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def average_hash(path: str | Path, *, hash_size: int = HASH_SIZE) -> int:
    """Return the Pillow average hash (aHash) of an image as an int.

    Opens *path*, converts it to greyscale, resizes it to
    ``hash_size x hash_size`` (default 8 → 64-bit hash), compares each pixel
    to the mean (1 when above the mean, else 0), and packs the bits into an
    int. Only Pillow is used; the image is never written. Raises
    :class:`FileNotFoundError` if *path* is not a file and :class:`ValueError`
    for a non-positive ``hash_size``.
    """
    size = _validate_hash_size(hash_size)
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"image not found: {target}")
    with Image.open(target) as image:
        grey = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        pixels = list(grey.tobytes())
    mean = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | (1 if pixel > mean else 0)
    return value


def hamming_distance(a: int, b: int) -> int:
    """Return the number of differing bits between two non-negative ints."""
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int) or not isinstance(b, int):
        raise ValueError(f"a and b must be integers, got {a!r} and {b!r}")
    if a < 0 or b < 0:
        raise ValueError(f"a and b must be non-negative, got {a!r} and {b!r}")
    return bin(a ^ b).count("1")


@dataclass(frozen=True)
class DuplicateGroup:
    """One duplicate cluster.

    ``kind`` is ``"exact"`` or ``"near"``; ``key`` is the sha256 hex digest
    (exact) or the seed aHash hex string (near); ``paths`` holds the member
    image paths; ``threshold`` is set for near groups and ``None`` for exact
    groups.
    """

    kind: str
    key: str
    paths: tuple[Path, ...]
    threshold: int | None = None


def find_exact_duplicates(
    sources: object,
    *,
    recursive: bool = False,
    suffixes: object = None,
) -> list[DuplicateGroup]:
    """Group images with identical sha256 digests into groups of size ≥ 2.

    *sources* may be a single path or a sequence of directories/files.
    Groups are returned sorted by digest; each group's ``paths`` follow the
    deterministic listing order.
    """
    images = _collect_images(sources, recursive=recursive, suffixes=suffixes)
    by_digest: dict[str, list[Path]] = {}
    for path in images:
        by_digest.setdefault(content_hash(path), []).append(path)

    return [
        DuplicateGroup("exact", digest, tuple(paths), None)
        for digest, paths in sorted(by_digest.items())
        if len(paths) >= 2
    ]


def find_near_duplicates(
    sources: object,
    *,
    recursive: bool = False,
    threshold: int = DEFAULT_NEAR_THRESHOLD,
    hash_size: int = HASH_SIZE,
    suffixes: object = None,
) -> list[DuplicateGroup]:
    """Cluster images by aHash seed-neighbour greedy clustering.

    Locks the documented approach: compute aHash for every image, sort paths
    by name (ties by resolved path string), then greedily build clusters
    around each remaining seed, pulling in every unassigned image within
    ``threshold`` Hamming bits of the seed (not transitive full closure).
    Only clusters with at least two members are reported.
    """
    limit = _validate_threshold(threshold)
    size = _validate_hash_size(hash_size)
    images = _collect_images(sources, recursive=recursive, suffixes=suffixes)
    ordered = sorted(images, key=lambda path: (path.name, str(path.resolve())))
    hashes = {path: average_hash(path, hash_size=size) for path in ordered}

    remaining = list(ordered)
    groups: list[DuplicateGroup] = []
    digits = size * size // 4
    while remaining:
        seed = remaining.pop(0)
        seed_hash = hashes[seed]
        members = [seed]
        rest: list[Path] = []
        for path in remaining:
            if hamming_distance(seed_hash, hashes[path]) <= limit:
                members.append(path)
            else:
                rest.append(path)
        remaining = rest
        if len(members) >= 2:
            groups.append(
                DuplicateGroup("near", f"{seed_hash:0{digits}x}", tuple(members), limit)
            )
    return groups


@dataclass(frozen=True)
class ThinPlan:
    """One keep/drop decision for a :class:`DuplicateGroup`.

    ``keep`` is the single keeper path (resolved absolute) and ``drop`` is
    the tuple of paths that would be trashed, in group order.
    """

    keep: Path
    drop: tuple[Path, ...]


def _validate_keep_policy(keep_policy: object) -> str:
    if not isinstance(keep_policy, str) or keep_policy not in KEEP_POLICIES:
        raise ValueError(
            f"keep_policy must be one of {KEEP_POLICIES}, got {keep_policy!r}"
        )
    return keep_policy


def plan_thin(
    group: DuplicateGroup,
    *,
    keep_policy: str = DEFAULT_KEEP_POLICY,
) -> ThinPlan:
    """Choose the keeper and drop paths for one :class:`DuplicateGroup`.

    All member paths are resolved to absolute paths and checked to exist.
    ``keep_policy`` must be one of :data:`KEEP_POLICIES`; see the module
    docstring for each policy's rule. Raises :class:`ValueError` for a bad
    policy or a group with fewer than two paths.
    """
    policy = _validate_keep_policy(keep_policy)
    resolved = tuple(Path(path).expanduser().resolve() for path in group.paths)
    if len(resolved) < 2:
        raise ValueError("a duplicate group must contain at least two paths")
    for path in resolved:
        if not path.is_file():
            raise FileNotFoundError(f"image not found: {path}")

    if policy == "keep_largest":
        keeper = max(resolved, key=lambda p: (p.stat().st_size, p.name, str(p)))
    elif policy == "keep_oldest":
        keeper = min(resolved, key=lambda p: (p.stat().st_mtime, p.name, str(p)))
    else:  # keep_first
        keeper = min(resolved, key=str)
    drop = tuple(path for path in resolved if path != keeper)
    return ThinPlan(keeper, drop)


@dataclass(frozen=True)
class ThinResult:
    """What :func:`thin_groups` planned (dry-run) or performed (commit).

    ``groups_planned`` is the number of groups, ``kept`` one keeper per
    group, ``dropped`` the flattened drop paths in plan order, and ``plans``
    the per-group :class:`ThinPlan` objects.
    """

    committed: bool
    groups_planned: int
    kept: tuple[Path, ...]
    dropped: tuple[Path, ...]
    plans: tuple[ThinPlan, ...]


def thin_groups(
    groups: Iterable[DuplicateGroup] | DuplicateGroup,
    *,
    commit: bool = False,
    keep_policy: str = DEFAULT_KEEP_POLICY,
    hook: AuditHook | None = None,
) -> ThinResult:
    """Plan (dry-run) or perform (commit) thinning for many groups.

    Dry-run (default) validates every keep/drop plan and writes nothing.
    Commit trashes every drop via ``lib_safety.trash(path, companions=True,
    hook=hook)`` — companions first, then the image. All plans are validated
    before the first trash; on the first trash failure the function stops and
    raises (earlier drops stay trashed).
    """
    hook = hook or NULL_HOOK
    batch = (groups,) if isinstance(groups, DuplicateGroup) else groups
    plans = tuple(plan_thin(group, keep_policy=keep_policy) for group in batch)
    kept = tuple(plan.keep for plan in plans)
    dropped = tuple(path for plan in plans for path in plan.drop)

    if not commit:
        for plan in plans:
            for path in plan.drop:
                hook.record(
                    AuditEvent(
                        operation=OPERATION,
                        source=str(path),
                        ok=True,
                        reason="thin; dry_run",
                    )
                )
        return ThinResult(False, len(plans), kept, dropped, plans)

    for plan in plans:
        for path in plan.drop:
            try:
                trash(path, companions=True, hook=hook)
            except Exception:
                hook.record(
                    AuditEvent(
                        operation=OPERATION,
                        source=str(path),
                        ok=False,
                        reason="thin; trash failed",
                    )
                )
                raise
            hook.record(
                AuditEvent(
                    operation=OPERATION,
                    source=str(path),
                    ok=True,
                    reason="thin; committed=True",
                )
            )
    return ThinResult(True, len(plans), kept, dropped, plans)


def _group_dict(group: DuplicateGroup) -> dict[str, object]:
    data: dict[str, object] = {
        "kind": group.kind,
        "key": group.key,
        "paths": [str(path) for path in group.paths],
    }
    if group.threshold is not None:
        data["threshold"] = group.threshold
    return data


def _plan_dict(plan: ThinPlan) -> dict[str, object]:
    return {
        "keep": str(plan.keep),
        "drop": [str(path) for path in plan.drop],
    }


def _thin_result_dict(result: ThinResult) -> dict[str, object]:
    return {
        "committed": result.committed,
        "groups_planned": result.groups_planned,
        "kept": [str(path) for path in result.kept],
        "dropped": [str(path) for path in result.dropped],
        "plans": [_plan_dict(plan) for plan in result.plans],
    }


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-dupes`` CLI."""
    parser = argparse.ArgumentParser(
        prog="pickkit-dupes",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_scan_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "dirs", nargs="+", metavar="DIR",
            help="Directories (or image files) to scan",
        )
        target.add_argument(
            "--recursive", action="store_true",
            help="Walk directories recursively (hidden path parts skipped)",
        )
        target.add_argument(
            "--json", action="store_true",
            help="Print the JSON report (already the default output format)",
        )

    exact_parser = subparsers.add_parser(
        "exact", help="Find exact duplicates by sha256 content hash"
    )
    add_scan_flags(exact_parser)

    near_parser = subparsers.add_parser(
        "near", help="Find near duplicates by Pillow average hash"
    )
    add_scan_flags(near_parser)
    near_parser.add_argument(
        "--threshold", type=int, default=DEFAULT_NEAR_THRESHOLD, metavar="N",
        help="Maximum aHash Hamming distance for a near-duplicate cluster",
    )

    thin_parser = subparsers.add_parser(
        "thin", help="Thin duplicate groups (dry-run default; --commit trashes drops)"
    )
    thin_parser.add_argument(
        "dirs", nargs="+", metavar="DIR",
        help="Directories (or image files) to scan",
    )
    thin_parser.add_argument(
        "--mode", required=True, choices=("exact", "near"),
        help="Duplicate mode to find and thin: exact (sha256) or near (aHash)",
    )
    thin_parser.add_argument(
        "--recursive", action="store_true",
        help="Walk directories recursively (hidden path parts skipped)",
    )
    thin_parser.add_argument(
        "--threshold", type=int, default=DEFAULT_NEAR_THRESHOLD, metavar="N",
        help="Maximum aHash Hamming distance (near mode only)",
    )
    thin_parser.add_argument(
        "--keep", choices=KEEP_POLICIES, default=DEFAULT_KEEP_POLICY,
        help="Keep policy for each group",
    )
    thin_parser.add_argument(
        "--commit", action="store_true",
        help="Trash drop paths with companions via lib_safety (default is dry-run)",
    )
    thin_parser.add_argument(
        "--audit", metavar="PATH",
        help="Append audit events to PATH via lib_safety.JsonlAuditHook",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args, dispatches, and prints JSON to stdout."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "exact":
            groups = find_exact_duplicates(args.dirs, recursive=args.recursive)
            summary: dict[str, object] = {
                "mode": "exact",
                "groups": [_group_dict(group) for group in groups],
            }
        elif args.command == "near":
            groups = find_near_duplicates(
                args.dirs, recursive=args.recursive, threshold=args.threshold
            )
            summary = {
                "mode": "near",
                "threshold": args.threshold,
                "groups": [_group_dict(group) for group in groups],
            }
        elif args.command == "thin":
            hook = optional_jsonl_hook(args.audit)
            if args.mode == "exact":
                groups = find_exact_duplicates(args.dirs, recursive=args.recursive)
            else:
                groups = find_near_duplicates(
                    args.dirs, recursive=args.recursive, threshold=args.threshold
                )
            if hook is not None:
                hook.record(
                    AuditEvent(
                        operation=OPERATION,
                        source=", ".join(str(Path(d).expanduser()) for d in args.dirs),
                        ok=True,
                        reason=f"find_{args.mode}",
                    )
                )
            result = thin_groups(
                groups,
                commit=args.commit,
                keep_policy=args.keep,
                hook=hook,
            )
            summary = {"mode": args.mode, **_thin_result_dict(result)}
        else:  # pragma: no cover - argparse guarantees a known subcommand
            parser.error(f"unknown command: {args.command}")
    except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError, OSError) as exc:
        parser.exit(1, f"pickkit-dupes: error: {exc}\n")

    print(json.dumps(summary, indent=2))
    return 0
