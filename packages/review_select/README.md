# review_select

Triage an already intake'd pickkit batch into keep / crop / reject: move each
image plus its companions into `__selected/`, `__crop/`, or `__reject/`, append
one decision record to `.pickkit/decisions.jsonl`, update the `review_select`
step in `.pickkit/project.json`, and audit via `lib_safety`.

The authoritative behaviour reference is the module docstring of
`packages/review_select/review.py`; `tests/test_review_select_docs.py` guards it
against drift. The interactive UI is documented in
`packages/review_select/ui.py`; `tests/test_review_select_ui_docs.py` guards it.

## How humans run review

The local web UI is the primary human workflow:

```bash
pickkit-review <batch_root> --ui
```

It binds `127.0.0.1:8765` by default (`--host` / `--port` override it) and shows
one pending image at a time with **Keep / Crop / Reject** actions. Keyboard
shortcuts are **K/C/R** and **1/2/3**. The batch must already be intake'd
(`pickkit-intake` first).

## Library / CLI for scripts

Batch and script usage stays available through the library and CLI flags:

```bash
pickkit-review <batch_root> --decisions decisions.jsonl
pickkit-review <batch_root> --keep img_001.png --crop img_002.png --reject img_003.png
pickkit-review <batch_root> --finish
```

`--ui` cannot be combined with `--decisions` / `--keep` / `--crop` /
`--reject` / `--finish`.
