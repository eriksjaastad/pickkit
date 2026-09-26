# review_select

Triage an already intake'd pickkit batch into keep / crop / reject: move each
image plus its companions into `__selected/`, `__crop/`, or `__reject/`, append
one decision record to `.pickkit/decisions.jsonl`, update the `review_select`
step in `.pickkit/project.json`, and audit via `lib_safety`.

The authoritative behaviour reference is the module docstring of
`packages/review_select/review.py`; `tests/test_review_select_docs.py` guards it
against drift.

Run it with `python -m review_select <batch_root> --decisions decisions.jsonl`
or the `pickkit-review` console script. The batch must already be intake'd
(`pickkit-intake` first). Interactive UI is a follow-on; this package is the
batch library + thin CLI only.
