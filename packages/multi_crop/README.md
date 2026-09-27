# multi_crop

Create NEW cropped image files from axis-aligned pixel boxes — never
overwriting originals. Batch mode requires an already intake'd batch
(`pickkit-intake` first); crops land under `__cropped/`, one append-only
record per crop goes to `.pickkit/crops.jsonl`, and the `multi_crop` step in
`.pickkit/project.json` is updated. Sources are never moved or rewritten.

The authoritative behaviour reference is the module docstring of
`packages/multi_crop/crop.py`; `tests/test_multi_crop_docs.py` guards it
against drift. The interactive UI is documented in
`packages/multi_crop/ui.py`; `tests/test_multi_crop_ui_docs.py` guards it.

## How humans crop

The local web UI is the primary human workflow:

```bash
pickkit-crop <batch_root> --ui
```

It binds `127.0.0.1:8766` by default (`--host` / `--port` override it) and
shows one pending `__crop/` image at a time: drag an axis-aligned rectangle,
watch the live `(left, top, right, bottom)` readout in full-image pixels, then
**Apply crop**. Shortcuts are **Enter** (apply), **S** (skip), **R** (reset
rect). The batch must already be intake'd (`pickkit-intake` first).

## Library / CLI for scripts

Batch and script usage stays available through the library and CLI flags:

```bash
pickkit-crop <batch_root> --crops crops.jsonl
pickkit-crop <batch_root> --source img_001.png --box 0,0,32,48
pickkit-crop <batch_root> --finish
```

`--ui` cannot be combined with `--crops` / `--source` / `--box` / `--finish`;
`--host` / `--port` are only valid together with `--ui`.
