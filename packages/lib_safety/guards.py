"""Guards against overwriting existing files (no in-place pixel writes).

This module is the single source of truth for write protection: which
writes are allowed, and which are refused before any bytes change. Only a
future multi-crop plugin may create new pixel files, and even then only at
**new** paths; this module never writes pixels itself.

Principles
----------
New files only
    Pixel writes (crops, saves, exports) must target a path that does not
    exist yet. :func:`require_new_file` is the shared enforcement point
    for that invariant.
Never overwrite an original
    An original already exists by definition, so any write that resolves
    to an existing path — especially an in-place save of the original —
    is refused.
Checks, never creates
    :func:`require_new_file` only inspects the path; it never creates
    files, directories, or pixels. Callers create the file after the
    guard passes.

Public API
----------
``require_new_file(path, *, hook=None)``
    Return *path* as a :class:`Path` if it does not exist, raising
    :class:`RefusedWriteError` (a :class:`FileExistsError`) if it does.
    With ``hook`` given, one :class:`AuditEvent` is recorded on refusal.

Examples
--------
Refuse an in-place / overwriting pixel write::

    from lib_safety import require_new_file

    require_new_file("sandbox/batch_a/img_001.png")  # raises RefusedWriteError

Allow a not-yet-existing crop path::

    from lib_safety import require_new_file

    crop_path = require_new_file("sandbox/crops/img_001_crop.png")

Out of scope
------------
Actually writing pixels, opening PIL, and creating crop directories are
**not** this module's job. ``require_new_file`` only checks the path; the
future multi-crop plugin (or any caller) does the writing.
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
