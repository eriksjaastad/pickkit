"""Guard against overwriting existing files.

Every pixel write (a crop, save or export) must target a path that does not
exist yet, so an original can never be overwritten in place.
:func:`require_new_file` is the one check for that; it only inspects the
path and the caller writes the file afterwards.

Public API
----------
``require_new_file(path, *, hook=None)``
    Return *path* as a :class:`Path`; raise :class:`RefusedWriteError` if it
    exists.
"""

from __future__ import annotations

from pathlib import Path

from .audit import NULL_HOOK, AuditEvent, AuditHook
from .errors import RefusedWriteError


def require_new_file(path: str | Path, *, hook: AuditHook | None = None) -> Path:
    """Return *path* as a :class:`Path`, raising :class:`RefusedWriteError` if it exists.

    On refusal one ``refuse_write`` event is recorded on *hook*.
    """
    target = Path(path).expanduser()
    hook = hook or NULL_HOOK
    if target.exists():
        hook.record(
            AuditEvent(
                operation="refuse_write",
                source=str(target),
                ok=False,
                reason="refusing to write: path already exists",
            )
        )
        raise RefusedWriteError(f"refusing to write: file already exists: {target}")
    return target
