"""lib_safety: shared safety primitives for pickkit plugins.

Public API:

* :func:`move_with_companions` — move an image and its same-stem sidecars
  together; refuses to clobber existing destinations.
* :func:`find_companions` / :data:`DEFAULT_COMPANION_SUFFIXES` — companion
  discovery.
* :func:`trash` — recoverable delete via ``send2trash``.
* :func:`require_new_file` — refuse writes that would overwrite an existing
  path.
* Audit types — :class:`AuditEvent`, :class:`AuditHook`,
  :class:`NullAuditHook`, :class:`JsonlAuditHook`.
"""

from .audit import NULL_HOOK, AuditEvent, AuditHook, JsonlAuditHook, NullAuditHook
from .companions import (
    DEFAULT_COMPANION_SUFFIXES,
    MoveResult,
    find_companions,
    move_with_companions,
)
from .errors import DestinationExistsError, RefusedWriteError, SafetyError
from .guards import require_new_file
from .trash import trash

__version__ = "0.1.0"

__all__ = [
    "AuditEvent",
    "AuditHook",
    "DEFAULT_COMPANION_SUFFIXES",
    "DestinationExistsError",
    "JsonlAuditHook",
    "MoveResult",
    "NULL_HOOK",
    "NullAuditHook",
    "RefusedWriteError",
    "SafetyError",
    "find_companions",
    "move_with_companions",
    "require_new_file",
    "trash",
]
