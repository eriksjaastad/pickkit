# intake_init

Point at a directory and initialize a pickkit batch: JSON project manifest,
extension inventory snapshot, and append-only audit baseline under
`.pickkit/`. Only `.pickkit/` is created — never `__selected`, `__crop`, or
other stage directories (those belong to future review/crop plugins).

The authoritative behaviour reference is the module docstring of
`packages/intake_init/intake.py`; `tests/test_intake_init_docs.py` guards it
against drift.

Run it with `python -m intake_init <batch_root>` or the `pickkit-intake`
console script (`--force` overwrites an existing manifest). See the module
docstring for the full public API and invariants.
