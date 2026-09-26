"""Companion discovery and move-with-companions for pickkit image batches.

This module is the single source of truth for companion-file behaviour:
what counts as a companion, how companions are discovered, and how they
move with their image. Pixel writes and cropping are deliberately out of
scope here; ``lib_safety`` only moves and trashes files (write protection
lives in ``guards.py``).

Core principles
---------------
Always together
    A move relocates an image **and** every recognised same-stem sidecar
    next to it, so a pair/group is never split across directories.
Stem discovery
    Companions are found by matching the image's stem (filename without
    extension). Nothing else about the files is inspected.
No clobber
    If any destination path already exists, the whole move is refused
    before anything is moved.
Move relocates bytes, never rewrites pixels
    Files are relocated with ``shutil.move``; their bytes are never read,
    decoded, re-encoded, or written back. Pixel output such as crops is
    out of scope for this module.

What counts as a companion
--------------------------
A companion is a file in the image's directory whose stem equals the
image's stem and whose suffix (case-insensitive) is recognised. The
recognised suffixes come from ``DEFAULT_COMPANION_SUFFIXES`` — see that
constant for the current default set. The image itself is never treated
as a companion, even if its suffix matches.

For example, next to ``shot_001.png``::

    shot_001.yaml    -> companion
    shot_001.txt     -> companion
    shot_001.png     -> the image; never returned
    shot_002.yaml    -> not a companion (different stem)

Public API
----------
``find_companions(image_path, *, suffixes=None)``
    Return same-stem sidecar files next to *image_path*, sorted by name.
    ``suffixes=None`` uses :data:`DEFAULT_COMPANION_SUFFIXES`; a string
    or iterable of suffixes overrides it.

``MoveResult``
    Frozen dataclass describing where a move-with-companions landed:
    ``image`` is the final image path and ``companions`` are the final
    sidecar paths.

``move_with_companions(image_path, destination, *, suffixes=None, hook=None)``
    Move *image_path* and its same-stem companions to *destination*.
    Returns a :class:`MoveResult` and refuses with
    :class:`DestinationExistsError` before moving anything if any target
    already exists.

Examples
--------
Discover companions without touching the filesystem::

    from lib_safety import find_companions

    companions = find_companions("sandbox/batch_a/shot_001.png")

Move an image and its sidecars into an existing directory::

    from lib_safety import move_with_companions

    result = move_with_companions(
        "sandbox/batch_a/shot_001.png",
        "sandbox/batch_a_staging",
    )
    result.image       # staging path of shot_001.png
    result.companions  # staging paths of shot_001.yaml, shot_001.txt

Out of scope
------------
Pixel writes, crops, and image save/export are **not** this module's job.
``lib_safety`` only moves and trashes files; write protection is enforced
separately by ``guards.require_new_file``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .audit import NULL_HOOK, AuditEvent, AuditHook
from .errors import DestinationExistsError

#: Sidecar suffixes recognised as companions by default.
DEFAULT_COMPANION_SUFFIXES: tuple[str, ...] = (
    ".yaml",
    ".yml",
    ".txt",
    ".caption",
    ".json",
    ".xmp",
)


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def _normalise_suffixes(suffixes: object) -> tuple[str, ...] | None:
    if suffixes is None:
        return None
    if isinstance(suffixes, str):
        return (suffixes,)
    return tuple(suffixes)  # type: ignore[arg-type]


def find_companions(
    image_path: str | Path,
    *,
    suffixes: object = None,
) -> list[Path]:
    """Return same-stem sidecar files next to *image_path*, sorted by name.

    A candidate must share the image's stem and have a recognised suffix;
    see the module docstring for the full companion rule. The image itself
    is never included, even if its suffix is in ``suffixes``.
    ``suffixes=None`` uses :data:`DEFAULT_COMPANION_SUFFIXES`; pass a
    string or iterable of suffixes to override it.
    """
    image = _as_path(image_path)
    wanted = _normalise_suffixes(suffixes)
    allowed = {s.lower() for s in (DEFAULT_COMPANION_SUFFIXES if wanted is None else wanted)}
    companions = [
        candidate
        for candidate in image.parent.iterdir()
        if candidate.is_file()
        and candidate != image
        and candidate.stem == image.stem
        and candidate.suffix.lower() in allowed
    ]
    return sorted(companions, key=lambda p: p.name)


@dataclass(frozen=True)
class MoveResult:
    """Where a move-with-companions landed.

    ``image`` is the final image path and ``companions`` are the final
    sidecar paths, in the same sorted order as discovery.
    """

    image: Path
    companions: tuple[Path, ...]


def _move_one_no_clobber(source: Path, destination: Path) -> None:
    if destination.exists():
        raise DestinationExistsError(f"destination already exists: {destination}")
    shutil.move(str(source), str(destination))


def move_with_companions(
    image_path: str | Path,
    destination: str | Path,
    *,
    suffixes: object = None,
    hook: AuditHook | None = None,
) -> MoveResult:
    """Move *image_path* and its same-stem companions to *destination*.

    ``destination`` may be:

    * an **existing directory** — the image and companions keep their names
      and land inside it; or
    * a **non-existing file path** — the image gets exactly that path and
      companions follow the image's new stem.

    If any target path already exists the operation is refused with
    :class:`DestinationExistsError` before anything is moved. The image is
    moved last, so a failed companion move never leaves the primary file in
    the destination while its sidecars are still at the source.

    Files are relocated, never rewritten in place: ``shutil.move`` changes
    location, not bytes. With ``hook`` given, one :class:`AuditEvent` is
    recorded on success or refusal.
    """
    image = _as_path(image_path)
    if not image.is_file():
        raise FileNotFoundError(f"image not found: {image}")

    hook = hook or NULL_HOOK
    companions = find_companions(image, suffixes=suffixes)

    dest = _as_path(destination)
    if dest.is_dir():
        destination_image = dest / image.name
        destination_companions = tuple(dest / c.name for c in companions)
    else:
        destination_image = dest
        destination_companions = tuple(
            dest.with_name(dest.stem + c.suffix) for c in companions
        )

    if not destination_image.parent.is_dir():
        raise FileNotFoundError(
            f"destination directory does not exist: {destination_image.parent}"
        )

    # Pre-flight: refuse the whole move if any target already exists.
    targets = (destination_image, *destination_companions)
    for target in targets:
        if target.exists():
            event = AuditEvent(
                operation="move",
                source=str(image),
                destination=str(destination_image),
                companions=tuple(str(c) for c in companions),
                ok=False,
                reason=f"destination already exists: {target}",
            )
            hook.record(event)
            raise DestinationExistsError(
                f"refusing to move {image.name}: destination already exists: {target}"
            )

    # Move companions first, then the image.
    for companion, target in zip(companions, destination_companions):
        _move_one_no_clobber(companion, target)
    _move_one_no_clobber(image, destination_image)

    hook.record(
        AuditEvent(
            operation="move",
            source=str(image),
            destination=str(destination_image),
            companions=tuple(str(c) for c in companions),
            ok=True,
        )
    )
    return MoveResult(image=destination_image, companions=destination_companions)
