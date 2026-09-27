# finish_package

Close the batch manifest and stage a **copy-only** delivery ZIP. Requires an
already intake'd batch (`pickkit-intake` first). Dry-run is the default;
`--commit` writes `<batch_root>/delivery.zip` (allowlisted, non-banned files
only — `.pickkit/`, `__crop/`, and `__reject/` are never scanned by default)
and then closes the manifest (`finished_at`, `finish_package` step,
`metrics.stager`).

The authoritative behaviour reference is the module docstring of
`packages/finish_package/finish.py`; `tests/test_finish_package_docs.py`
guards it against drift. The interactive wizard is documented in
`packages/finish_package/ui.py`; `tests/test_finish_package_ui_docs.py` guards
it.

## How humans finish

The local web wizard is the primary human workflow:

```bash
pickkit-finish <batch_root> --ui
```

It binds `127.0.0.1:8767` by default (`--host` / `--port` override it) and
opens on a **dry-run preview** of the eligible / excluded report — nothing is
written until you press **Commit ZIP**. The page offers a **Force** checkbox
(for overwriting an existing ZIP) plus optional content / output overrides.
The batch must already be intake'd (`pickkit-intake` first).

## Library / CLI for scripts

Batch and script usage stays available through the library and CLI flags:

```bash
pickkit-finish <batch_root>                 # dry-run report
pickkit-finish <batch_root> --commit        # write ZIP + close manifest
pickkit-finish <batch_root> --commit --force
```

`--ui` cannot be combined with `--commit` / `--force` / `--content` /
`--output`; `--host` / `--port` are only valid together with `--ui`.
