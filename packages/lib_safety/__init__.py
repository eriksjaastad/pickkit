"""lib_safety: shared safety primitives for pickkit plugins.

Submodule docstrings are the single source of truth for behaviour:

* ``lib_safety.companions`` — companion discovery and move-with-companions.
* ``lib_safety.trash`` — recoverable deletes via ``send2trash``.
* ``lib_safety.guards`` — no-overwrite / no-in-place-write enforcement.
* ``lib_safety.audit`` — audit events and hook interfaces.
* ``lib_safety.errors`` — exception types.

This package re-exports the public names listed in :data:`__all__` (see
the tuple below) so plugins can import them from ``lib_safety`` directly.
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
