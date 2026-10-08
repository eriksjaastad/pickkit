"""Companion discovery and move-with-companions for pickkit image batches.

A companion is a file in the image's directory with the same stem and a
suffix in :data:`DEFAULT_COMPANION_SUFFIXES` (any case). The image itself is
never its own companion. Next to ``shot_001.png``::

    shot_001.yaml    -> companion
    shot_001.txt     -> companion
    shot_002.yaml    -> not a companion (different stem)

A move takes the image and every companion together, and refuses the whole
move before anything moves if any destination already exists. Files are
relocated with ``shutil.move``; their bytes are never rewritten.

Public API
----------
``DEFAULT_COMPANION_SUFFIXES``
``find_companions(image_path, *, suffixes=None)``
``MoveResult``
``move_with_companions(image_path, destination, *, suffixes=None, hook=None)``
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

    ``suffixes`` (a string or iterable) overrides
    :data:`DEFAULT_COMPANION_SUFFIXES`. The image itself is never included.
    """
    image = Path(image_path).expanduser()
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

    If any target exists, raises :class:`DestinationExistsError` before
    anything moves. The image moves last, so a failed companion move never
    leaves it in the destination while its sidecars are still at the source.
    Records one ``move`` event on *hook* on success or refusal.
    """
    image = Path(image_path).expanduser()
    if not image.is_file():
        raise FileNotFoundError(f"image not found: {image}")

    hook = hook or NULL_HOOK
    companions = find_companions(image, suffixes=suffixes)

    dest = Path(destination).expanduser()
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
