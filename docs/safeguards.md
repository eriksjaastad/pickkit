# Safeguards — data protection built into pickkit

pickkit grew out of large-batch image work where **speed of recovery** mattered as much as throughput. Looking back, some of these protections can feel thorough. That thoroughness is deliberate: when a step goes wrong, you want to know exactly what moved, what was discarded, and how to get a clean copy back — without rewriting the originals you still trust.

This page lists both the **visible** protections (dry-run defaults, UI previews, named stage folders) and the **invisible** ones (sidecars, companions, refuse-overwrite guards, audit logs). Tone: recovery story, not fear-mongering.

## Design rules (the contract)

1. **Move, don't modify originals.** Spine steps relocate files into stage directories; they do not rewrite pixels in place.
2. **Crop is the only pixel writer** — and it only creates **new** files under `__cropped/`. Sources in `__crop/` (or elsewhere) stay intact.
3. **Companions travel together.** Same-stem sidecars (`.yaml`, `.yml`, `.txt`, `.caption`, `.json`, `.xmp` by default) move or trash with the image.
4. **Trash, don't silent-unlink.** Production deletes go through the OS trash (`send2trash`) so they are recoverable.
5. **No clobber.** Moves refuse to overwrite an existing destination. Crop and finish refuse to overwrite outputs unless an explicit force path exists (finish: `--force` on the ZIP only).
6. **Dry-run before commit** where mutation is optional (finish, character assign, dupe thin). The finish UI always starts on a preview.
7. **Audit and manifests.** Structured logs under `.pickkit/` record what happened so you can reconstruct a session.

Implemented primarily in [`packages/lib_safety/`](../packages/lib_safety/); every spine plugin is expected to call these helpers instead of hand-rolling file ops.

## What you see on disk

| Path | Role |
|------|------|
| `.pickkit/project.json` | Batch manifest: schema, timestamps, spine `steps`, metrics slot |
| `.pickkit/allowed_ext.json` | Extension inventory snapshot from intake (finish allowlist) |
| `.pickkit/audit.jsonl` | Append-only audit baseline / events |
| `.pickkit/decisions.jsonl` | One line per review keep/crop/reject |
| `.pickkit/crops.jsonl` | One line per applied crop |
| `.pickkit/finish.jsonl` | Finish commit records |
| `.pickkit.bak.<UTC>/` | Automatic backup of a previous `.pickkit/` on re-intake (unless `--force`) |
| `__selected/` | Keepers after review (moved, not copied) |
| `__crop/` | Crop **queue** (still originals; no pixels rewritten here) |
| `__reject/` | Rejects (moved aside; not trashed by review) |
| `__cropped/` | **New** crop outputs only |
| `delivery.zip` | Copy-only package from `__selected/` + `__cropped/` by default |

Reject means "move to `__reject/`", not "send to trash". That keeps a recoverable staging area inside the batch until a later cleanup chooses trash.

## Invisible protections (easy to miss)

### Sidecar / manifest tracking

Intake does not invent client IDs. It writes a small JSON state directory so later steps can prove the batch was initialized, count images, and update step timestamps. Re-running intake **backs up** the existing `.pickkit/` to a sibling `.pickkit.bak.<UTC>` before writing a fresh one (`--force` skips the backup and overwrites in place).

### Companions move together

A keep/crop/reject decision moves the image **and** every same-stem companion in one `lib_safety.move_with_companions` call. If any destination already exists, the whole move is refused **before** anything is relocated — no half-moved orphans.

### Recoverable deletes

`lib_safety.trash` uses `send2trash`. Duplicate thinning and character reject use that path (with dry-run default). Review itself does not trash; it stages rejects under `__reject/`.

### Backup-then-overwrite (intake)

Accidentally re-intaking a finished batch does not silently erase the old manifest: you get a timestamped `.pickkit.bak.*` sibling first.

### Crop writes NEW files only

`lib_safety.require_new_file` runs before every pixel write. If `__cropped/img_002.png` already exists, the crop is refused — no silent rename, no in-place overwrite of the source. The queue file under `__crop/` remains for retry or inspection.

### Finish: dry-run vs commit, copy-only ZIP

- Default CLI and the UI landing page are **dry-run**: eligible/excluded report only.
- `--commit` / **Commit ZIP** writes `delivery.zip` then closes the manifest (`finished_at`, finish step, stager metrics).
- Sources are **read**, never modified, when building the ZIP.
- Default scan is `__selected/` + `__cropped/` only — not `__crop/`, `__reject/`, or `.pickkit/`.
- Existing ZIP is refused unless `--force` (force overwrites the ZIP only, never source bytes).

### Audit hooks

Moves, trash, and refused writes can emit structured `AuditEvent`s. Plugins append JSONL under `.pickkit/` so a bad session is a log you can read, not a mystery.

## Why this density exists

Large batches make "undo" expensive if the tool rewrote pixels or deleted quietly. The kit biases toward:

- **Always having a copy-back story** (stage folders, trash, ZIP as a copy, crop as a new file).
- **Knowing exactly what was lost or moved** (decisions/crops/finish JSONL + audit).
- **Failing closed** on overwrite and partial companion moves.

If a default feels strict (refused crop destination, dry-run finish, backup on re-intake), that is the recovery bias talking.

## Related reading

- [docs/setup.md](setup.md) — install and spine recipes
- [packages/lib_safety/README.md](../packages/lib_safety/README.md) — API table
- [docs/case-study-journal-index.md](case-study-journal-index.md) — incident→guardrail research index (no private prose)
