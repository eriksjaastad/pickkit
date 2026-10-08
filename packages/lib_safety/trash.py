"""Recoverable deletes via ``send2trash``.

Files go to the OS trash, never through ``os.remove`` or ``Path.unlink``.
With ``companions=True`` the image's same-stem sidecars go first and the
image last, so the image never disappears while its sidecars remain. Every
planned path is checked first: if any is missing, nothing is trashed.

Public API
----------
``trash(path, *, companions=False, suffixes=None, hook=None)``
    Returns the trashed paths; raises :class:`FileNotFoundError` before
    trashing anything if a planned path is missing.
"""

from __future__ import annotations

from pathlib import Path

from send2trash import send2trash

from .audit import NULL_HOOK, AuditEvent, AuditHook
from .companions import find_companions


def trash(
    path: str | Path,
    *,
    companions: bool = False,
    suffixes: object = None,
    hook: AuditHook | None = None,
) -> tuple[Path, ...]:
    """Send *path* (and optionally its same-stem companions) to the OS trash.

    Records one ``trash`` event on *hook* on success or failure.
    """
    target = Path(path).expanduser()
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
