# directory_viewer

Read-only **multi-directory inspection**: inventory image-bearing directories,
counts, extension breakdown, sample listings, and compare multiple roots.
Optional middle tool: it never adds a spine step, never requires an intake'd
batch, never mutates `.pickkit/project.json`, and never writes an audit file.

```bash
pickkit-viewer inventory ROOT [--sample N] [--json]
pickkit-viewer compare ROOT [ROOT ...] [--sample N] [--json]
```

The authoritative behaviour reference is the module docstring of
`packages/directory_viewer/viewer.py`; `tests/test_directory_viewer_docs.py`
guards it against drift. The Flask/Tk grid UI and any mutations are out of
scope for this module.
