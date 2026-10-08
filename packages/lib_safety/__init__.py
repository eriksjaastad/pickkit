"""lib_safety: shared safety primitives for pickkit plugins.

Every pickkit tool that touches files goes through these, so the same rules
hold everywhere:

1. Move, don't modify: originals are relocated, never rewritten in place.
2. Companions stay together: an image's same-stem sidecars (``.yaml``,
   ``.yml``, ``.txt``, ``.caption``, ``.json``, ``.xmp``) move and trash
   with it.
3. No clobber: a move or write refuses any existing destination.
4. Trash, don't unlink: deletes go to the OS trash and can be recovered.
5. New files only: pixel writes such as crops need a path that does not
   exist yet (``require_new_file``).
6. Audit: moves, trash deletes and refused writes can emit an ``AuditEvent``.

The names in ``__all__`` come from ``audit``, ``batch``, ``companions``,
``errors``, ``guards`` and ``trash``; each submodule's docstring documents
its own. ``lib_safety.webui`` holds the Flask helpers for the web UIs and is
not imported here, so ``import lib_safety`` stays Flask-free.
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
