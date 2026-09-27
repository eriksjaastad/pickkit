# duplicate_finder

Find **exact duplicates** (sha256 content hash) and optional **near
duplicates** (Pillow average hash / aHash with a tunable Hamming threshold),
then thin the extras safely: dry-run by default, `--commit` trashes each drop
via `lib_safety.trash(..., companions=True)`. Optional middle tool: it never
adds a spine step, never requires an intake'd batch, and never mutates
`.pickkit/project.json`.

```bash
pickkit-dupes exact DIR [DIR ...] [--recursive] [--json]
pickkit-dupes near DIR [DIR ...] [--recursive] [--threshold N] [--json]
pickkit-dupes thin DIR [DIR ...] --mode exact|near [--recursive] \
             [--threshold N] [--keep keep_first|keep_largest|keep_oldest] \
             [--commit] [--audit PATH]
```

The authoritative behaviour reference is the module docstring of
`packages/duplicate_finder/dupes.py`; `tests/test_duplicate_finder_docs.py`
guards it against drift. The interactive two-directory visual UI is out of
scope for this module.
