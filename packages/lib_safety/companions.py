"""Companion discovery and move-with-companions.

Invariants enforced here:

* A move relocates an image **and** every recognised same-stem sidecar next
  to it, so the pair/group never gets split across directories.
* The destination is never allowed to clobber an existing file: if any
  target path already exists, the whole operation is refused before any
  file is moved.
* Files are moved, never rewritten in place: ``shutil.move`` only changes
  location, not bytes.
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

    The image itself is never included, even if its suffix is in
    ``suffixes``. ``suffixes=None`` uses :data:`DEFAULT_COMPANION_SUFFIXES`.
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
    """Where a move-with-companions landed."""

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
