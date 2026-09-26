# multi_crop

Create NEW cropped image files from axis-aligned pixel boxes — never
overwriting originals. Batch mode requires an already intake'd batch
(`pickkit-intake` first); crops land under `__cropped/`, one append-only
record per crop goes to `.pickkit/crops.jsonl`, and the `multi_crop` step in
`.pickkit/project.json` is updated. Sources are never moved or rewritten.

The authoritative behaviour reference is the module docstring of
`packages/multi_crop/crop.py`; `tests/test_multi_crop_docs.py` guards it
against drift.

Run it with `python -m multi_crop <batch_root> --crops crops.jsonl` or the
`pickkit-crop` console script. Interactive desktop UI is a follow-on; this
package is the batch library + thin CLI only.
