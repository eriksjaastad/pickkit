# lib_safety

Shared safety primitives for pickkit plugins. This is the first template
plugin: later plugins import these helpers instead of hand-rolling risky file
operations.

The authoritative behaviour references are the module docstrings of
`packages/lib_safety/companions.py`, `trash.py`, `guards.py`, `audit.py`, and
`batch.py` (helpers shared by the batch engines); `tests/test_module_docs.py`
guards them against drift. `webui.py` holds the Flask helpers shared by the
three web UIs; `import lib_safety` does not load it, so it stays Flask-free.

## Invariants

1. **Move, don't modify.** Originals are relocated, never rewritten in place.
2. **Companions stay together.** Moving an image also moves every same-stem
   sidecar (`.yaml`, `.yml`, `.txt`, `.caption`, `.json`, `.xmp`) next to it.
3. **No clobber.** A move refuses to overwrite any existing destination file.
4. **Trash, don't unlink.** Production deletes go through `send2trash`, so
   they are recoverable from the OS trash.
5. **New files only.** Pixel writes (e.g. crops) must target a path that does
   not exist yet. Only the future `multi_crop` plugin may create new crop
   files, and it must go through `require_new_file`.
6. **Audit everything.** Moves, trash deletes, and refused writes can emit
   structured events to any `AuditHook`.

## API summary

| Name | Purpose |
|------|---------|
| `move_with_companions(image, destination, *, suffixes=None, hook=None)` | Move an image and its same-stem sidecars together. Refuses before moving anything if any target exists. Returns `MoveResult(image=..., companions=...)`. |
| `find_companions(image, *, suffixes=None)` | List same-stem sidecars next to an image (sorted, image excluded). |
| `trash(path, *, companions=False, suffixes=None, hook=None)` | Send a path — and optionally its companions — to the OS trash via `send2trash`. |
| `require_new_file(path, *, hook=None)` | Return the path, raising `RefusedWriteError` (a `FileExistsError`) if it already exists. Call before any pixel write. |
| `AuditEvent` | Frozen dataclass: `operation`, `source`, `destination`, `companions`, `ok`, `reason`, `timestamp`. |
| `AuditHook` / `NullAuditHook` | Protocol for audit sinks; the default is a no-op. |
| `JsonlAuditHook(log_path)` | Small append-only JSONL audit sink. |
| `DEFAULT_COMPANION_SUFFIXES` | `(".yaml", ".yml", ".txt", ".caption", ".json", ".xmp")` |

## Examples (sandbox paths)

Run from the repo root with `.venv/bin/python`:

```python
from pathlib import Path
from lib_safety import JsonlAuditHook, move_with_companions, require_new_file, trash

hook = JsonlAuditHook("sandbox/.audit.jsonl")  # caller-supplied log path

# Move an image plus its .yaml/.txt sidecars into a staging directory.
staging = Path("sandbox/batch_a_staging")
staging.mkdir(exist_ok=True)
move_with_companions("sandbox/batch_a/img_004.png", staging, hook=hook)

# Recoverable delete of the image and its companions.
trash(staging / "img_004.png", companions=True, hook=hook)

# Refuse an in-place / overwriting pixel write.
require_new_file("sandbox/batch_a/img_001.png")  # raises RefusedWriteError
```

`require_new_file` is the enforcement point for the "no in-place pixel
writes" rule: a crop tool must call it with a **new** output path and let the
exception propagate if that path already exists.
