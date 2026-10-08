# pickkit packages

One directory per plugin or shared library.

| Directory | What it does |
|-----------|--------------|
| `lib_safety/` | Shared safety primitives: companions, trash, no-overwrite, audit |
| `intake_init/` | `pickkit-intake`: manifest, inventory and audit baseline under `.pickkit/` |
| `review_select/` | `pickkit-review`: keep / crop / reject triage, with a web UI |
| `multi_crop/` | `pickkit-crop`: NEW crop files only, with a web UI |
| `finish_package/` | `pickkit-finish`: close the manifest and stage a delivery ZIP, with a web wizard |
| `character_tools/` | `pickkit-character`: sort images into named bins |
| `duplicate_finder/` | `pickkit-dupes`: find duplicates and trash the extras |
| `directory_viewer/` | `pickkit-viewer`: read-only directory inventory |
