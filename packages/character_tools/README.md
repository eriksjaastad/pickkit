# character_tools

Assign images to **user-supplied named bins** (single subdirectories under a
bins root) and move each image's same-stem companions together via
`lib_safety`. Optional middle tool: it never adds a spine step, never requires
an intake'd batch, and never mutates `.pickkit/project.json`. Dry-run is the
default; `--commit` performs the moves/trash.

```bash
pickkit-character list SOURCE
pickkit-character check BINS_ROOT
pickkit-character move IMAGE --bin NAME --bins-root DIR [--commit] [--audit PATH]
pickkit-character assign MAP.json --bins-root DIR [--commit] [--audit PATH]
pickkit-character reject IMAGE [--commit] [--audit PATH]
```

The authoritative behaviour reference is the module docstring of
`packages/character_tools/character.py`; `tests/test_character_tools_docs.py`
guards it against drift. The interactive web sorter UI is out of scope for
this module.
