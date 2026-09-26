# intake_init

Point at a directory and initialize a pickkit batch: JSON project manifest,
extension inventory snapshot, and append-only audit baseline under
`.pickkit/`. Only `.pickkit/` is created — never `__selected`, `__crop`, or
other stage directories (those belong to future review/crop plugins).

The authoritative behaviour reference is the module docstring of
`packages/intake_init/intake.py`; `tests/test_intake_init_docs.py` guards it
against drift.

Run it with `python -m intake_init <batch_root>` or the `pickkit-intake`
console script. Re-intake is safe by default: an existing `.pickkit/` is
backed up to a sibling `.pickkit.bak.<UTC>` before a fresh one is written;
`--force` skips the backup and overwrites in place. See the module docstring
for the full public API and invariants.
