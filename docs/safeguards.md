# Why the safeguards are this strict

pickkit grew out of large-batch image work where **speed of recovery** mattered as much as throughput. Looking back, some of these protections can feel thorough. That thoroughness is deliberate: when a step goes wrong, you want to know exactly what moved, what was discarded, and how to get a clean copy back — without rewriting the originals you still trust.

The rules themselves are not kept in this file. They live next to the code that enforces them: the `lib_safety` module docstrings, and the `--help` text of `pickkit-intake`, `pickkit-review`, `pickkit-crop`, and `pickkit-finish` (those commands use their module docstrings as `--help`).

## Why this density exists

Large batches make "undo" expensive if the tool rewrote pixels or deleted quietly. The kit biases toward:

- **Always having a copy-back story** (stage folders, trash, ZIP as a copy, crop as a new file).
- **Knowing exactly what was lost or moved** (decisions/crops/finish JSONL + audit).
- **Failing closed** on overwrite and partial companion moves.

If a default feels strict (refused crop destination, dry-run finish, backup on re-intake), that is the recovery bias talking.
