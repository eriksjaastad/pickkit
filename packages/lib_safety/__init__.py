"""lib_safety: shared safety primitives for pickkit plugins.

Submodule docstrings are the single source of truth for behaviour:

* ``lib_safety.companions`` — companion discovery and move-with-companions.
* ``lib_safety.trash`` — recoverable deletes via ``send2trash``.
* ``lib_safety.guards`` — no-overwrite / no-in-place-write enforcement.
* ``lib_safety.audit`` — audit events and hook interfaces.
* ``lib_safety.batch`` — small helpers shared by the batch engines.
* ``lib_safety.errors`` — exception types.
* ``lib_safety.webui`` — Flask helpers shared by the web UIs. Not imported
  here, so ``import lib_safety`` stays Flask-free.

This package re-exports the public names listed in :data:`__all__` (see
the tuple below) so plugins can import them from ``lib_safety`` directly.
"""

from .audit import (
    NULL_HOOK,
    AuditEvent,
    AuditHook,
    FanoutHook,
    JsonlAuditHook,
    NullAuditHook,
    optional_jsonl_hook,
)
from .batch import (
    append_jsonl,
    find_step,
    load_json_records,
    normalise_suffix_set,
    rel_path,
    write_manifest,
)
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
    "FanoutHook",
    "JsonlAuditHook",
    "MoveResult",
    "NULL_HOOK",
    "NullAuditHook",
    "RefusedWriteError",
    "SafetyError",
    "append_jsonl",
    "find_companions",
    "find_step",
    "load_json_records",
    "move_with_companions",
    "normalise_suffix_set",
    "optional_jsonl_hook",
    "rel_path",
    "require_new_file",
    "trash",
    "write_manifest",
]
