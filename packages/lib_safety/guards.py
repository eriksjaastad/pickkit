"""Guards against overwriting existing files (no in-place pixel writes).

lib_safety's position: only a future multi-crop plugin may create new crop
files, and even then only at **new** paths. These helpers are the shared
enforcement point for "never overwrite an original, never save in place".
"""

from __future__ import annotations

from pathlib import Path

from .audit import NULL_HOOK, AuditEvent, AuditHook
from .errors import RefusedWriteError


def require_new_file(path: str | Path, *, hook: AuditHook | None = None) -> Path:
    """Return *path* as a :class:`Path`, raising :class:`RefusedWriteError` if it exists.

    Call this before any pixel write / save / export to enforce the
    "create NEW files only" invariant. An in-place save such as
    ``require_new_file(original)`` is refused because the original exists.
    The guard only checks; it never creates the file itself.
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
