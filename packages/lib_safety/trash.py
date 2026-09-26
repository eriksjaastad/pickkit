"""Recoverable deletes via ``send2trash``.

This module is the single source of truth for trash behaviour: how files
are deleted, how companions are handled, and what is refused before
anything is trashed. Hard deletes and pixel writes are deliberately out of
scope here; ``lib_safety`` only moves and trashes files (write protection
lives in ``guards.py``).

Principles
----------
Recoverable, never permanent
    Production deletes go through ``send2trash`` so files land in the OS
    trash/recycle bin instead of being unrecoverably unlinked. This module
    never calls ``os.remove`` / ``Path.unlink``.
Companions stay together
    With ``companions=True`` the image and every recognised same-stem
    sidecar are trashed together: sidecars go first, then the image, so
    the primary file never disappears while its sidecars are still on
    disk.
Refuse missing paths up front
    Every planned path is checked before the first ``send2trash`` call;
    if any planned path is missing, :class:`FileNotFoundError` is raised
    before anything is trashed.

Public API
----------
``trash(path, companions=False, suffixes=None, hook=None)``
    Send *path* — and, with ``companions=True``, its same-stem sidecars —
    to the OS trash via ``send2trash``. Sidecars are discovered with
    :func:`find_companions`; ``suffixes`` overrides the default set.
    Returns the trashed paths. Raises :class:`FileNotFoundError` before
    trashing anything if any planned path does not exist. With ``hook``
    given, one :class:`AuditEvent` is recorded on success or failure.

Examples
--------
Trash one image, leaving its sidecars in place::

    from lib_safety import trash

    trashed = trash("sandbox/batch_a/img_004.png")

Trash an image and its ``.yaml`` / ``.txt`` sidecars together::

    from lib_safety import trash

    trashed = trash("sandbox/batch_a/img_004.png", companions=True)

Out of scope
------------
Hard deletes (``os.remove`` / ``Path.unlink``), pixel writes, and
inventing trash destinations are **not** this module's job. ``send2trash``
decides where each file goes; this module only feeds it the planned paths.
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
