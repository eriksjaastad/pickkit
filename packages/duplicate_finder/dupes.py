"""Find exact and near-duplicate images and thin the extras into the OS trash.

``pickkit-dupes`` reports groups of duplicate images and can thin each group
down to one keeper. Finding never changes anything. Thinning is a dry-run
unless ``--commit`` is given; it then sends each extra to the OS trash with
its same-stem companions (``lib_safety.trash(..., companions=True)``), so
every drop is recoverable and the keeper is never touched. The batch need
not be intake'd. Output is JSON.

Usage::

    pickkit-dupes exact DIR [DIR ...] [--recursive] [--json]
    pickkit-dupes near DIR [DIR ...] [--recursive] [--threshold N] [--json]
    pickkit-dupes thin DIR [DIR ...] --mode exact|near [--recursive]
                 [--threshold N] [--keep keep_first|keep_largest|keep_oldest]
                 [--commit] [--audit PATH]

``exact`` and ``near`` exit 0 with an empty ``groups`` list when nothing is
found. ``thin`` finds groups with ``--mode`` and prints the keep/drop plan.

Options
-------
``--recursive``
    Walk subdirectories, skipping hidden paths. The default is non-recursive:
    the images directly inside each DIR, sorted by name.
``--threshold N``
    Near mode: the largest Hamming distance that still counts as a match
    (default :data:`DEFAULT_NEAR_THRESHOLD`, 5).
``--keep``
    The keeper in each group: ``keep_first`` (first by full path; the
    default :data:`DEFAULT_KEEP_POLICY`), ``keep_largest`` (biggest file) or
    ``keep_oldest`` (oldest mtime); ties go to the path name. See
    :data:`KEEP_POLICIES`.
``--commit``
    Trash the drops. All plans are checked first; the first failed trash
    stops the run, and earlier drops stay trashed.
``--audit PATH``
    Append audit events to PATH: :data:`OPERATION` events for the find and
    each drop, plus lib_safety's ``trash`` event per committed drop. Without
    it no audit file is written.
``--json``
    Accepted for symmetry; JSON is already the output.

Matching
--------
Exact
    Same sha256 of the full file bytes.
Near
    Pillow average hash (aHash): greyscale, resize to :data:`HASH_SIZE` x
    :data:`HASH_SIZE` (64 bits), one bit per pixel above the mean. Groups are
    built by greedy seed-neighbour clustering: images sorted by name, each
    unassigned image seeds a group and takes every unassigned image within
    the threshold of the seed (not transitively).

Only groups of two or more are reported. Image suffixes are
:data:`DEFAULT_IMAGE_SUFFIXES`.

Public API
----------
``DEFAULT_IMAGE_SUFFIXES``
``HASH_SIZE = 8``
``DEFAULT_NEAR_THRESHOLD = 5``
``KEEP_POLICIES``
``DEFAULT_KEEP_POLICY = "keep_first"``
``OPERATION = "duplicate_finder"``
``content_hash(path) -> str``
``average_hash(path, *, hash_size=HASH_SIZE) -> int``
``hamming_distance(a, b) -> int``
``list_images(source, *, recursive=False, suffixes=None) -> list[Path]``
``find_exact_duplicates(sources, *, recursive=False, suffixes=None) -> list[DuplicateGroup]``
``find_near_duplicates(sources, *, recursive=False, threshold=DEFAULT_NEAR_THRESHOLD, hash_size=HASH_SIZE, suffixes=None) -> list[DuplicateGroup]``
``plan_thin(group, *, keep_policy=DEFAULT_KEEP_POLICY) -> ThinPlan``
``thin_groups(groups, *, commit=False, keep_policy=DEFAULT_KEEP_POLICY, hook=None) -> ThinResult``
``DuplicateGroup``
``ThinPlan``
``ThinResult``
``build_parser()``
``main(argv=None)``
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

#: Names the ``duplicate_finder`` package re-exports.
__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "DEFAULT_KEEP_POLICY",
    "DEFAULT_NEAR_THRESHOLD",
    "HASH_SIZE",
    "KEEP_POLICIES",
    "OPERATION",
    "DuplicateGroup",
    "ThinPlan",
    "ThinResult",
    "average_hash",
    "build_parser",
    "content_hash",
    "find_exact_duplicates",
    "find_near_duplicates",
    "hamming_distance",
    "list_images",
    "main",
    "plan_thin",
    "thin_groups",
]

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

    A directory lists its direct images by name, or with ``recursive=True``
    every image outside hidden paths by path. ``suffixes=None`` uses
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
    """Return the lowercase sha256 hex digest of the full file bytes."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"image not found: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def average_hash(path: str | Path, *, hash_size: int = HASH_SIZE) -> int:
    """Return the Pillow average hash (aHash) of an image as an int."""
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

    *sources* is one path or a sequence of them. Groups are sorted by digest.
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

    See "Matching" in the module docstring. Only clusters of two or more are
    returned.
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

    Paths are resolved and must exist. Raises :class:`ValueError` for a
    policy not in :data:`KEEP_POLICIES` or a group of fewer than two paths.
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

    Every plan is validated before the first trash. On commit each drop is
    trashed with its companions; the first failure stops and raises, and
    earlier drops stay trashed.
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
