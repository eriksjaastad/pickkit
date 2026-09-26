"""Recoverable deletes via ``send2trash``.

Production deletes go through ``send2trash`` so files land in the OS
trash/recycle bin instead of being unrecoverably unlinked. This module
never calls ``os.remove`` / ``Path.unlink``.
"""

from __future__ import annotations

from pathlib import Path

from send2trash import send2trash

from .audit import NULL_HOOK, AuditEvent, AuditHook
from .companions import find_companions


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def trash(
    path: str | Path,
    *,
    companions: bool = False,
    suffixes: object = None,
    hook: AuditHook | None = None,
) -> tuple[Path, ...]:
    """Send *path* (and optionally its same-stem companions) to the OS trash.

    With ``companions=True``, treat *path* as an image and trash its
    same-stem sidecars first, then the image. Returns the trashed paths.

    Raises :class:`FileNotFoundError` before trashing anything if any planned
    path does not exist.
    """
    target = _as_path(path)
    hook = hook or NULL_HOOK

    planned: list[Path] = []
    if companions:
        planned.extend(find_companions(target, suffixes=suffixes))
    planned.append(target)

    for item in planned:
        if not item.exists():
            raise FileNotFoundError(f"cannot trash missing path: {item}")

    try:
        for item in planned:
            send2trash(str(item))
    except Exception as exc:
        hook.record(
            AuditEvent(
                operation="trash",
                source=str(target),
                companions=tuple(str(c) for c in planned if c != target),
                ok=False,
                reason=str(exc),
            )
        )
        raise

    hook.record(
        AuditEvent(
            operation="trash",
            source=str(target),
            companions=tuple(str(c) for c in planned if c != target),
            ok=True,
        )
    )
    return tuple(planned)
