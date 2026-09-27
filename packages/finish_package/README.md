# finish_package

Close the batch manifest and stage a **copy-only** delivery ZIP. Requires an
already intake'd batch (`pickkit-intake` first). Dry-run is the default;
`--commit` writes `<batch_root>/delivery.zip` (allowlisted, non-banned files
only — `.pickkit/`, `__crop/`, and `__reject/` are never scanned by default)
and then closes the manifest (`finished_at`, `finish_package` step,
`metrics.stager`).

The authoritative behaviour reference is the module docstring of
`packages/finish_package/finish.py`; `tests/test_finish_package_docs.py`
guards it against drift.

Run it with `python -m finish_package <batch_root>` or the `pickkit-finish`
console script. Interactive wizard UI is a follow-on; this package is the
batch library + thin CLI only.
