# review_select

Triage an intake'd batch into keep / crop / reject, moving each image with its
companions into `__selected/`, `__crop/` or `__reject/`. Includes a local web
UI (`--ui`, port 8765).

Command: `pickkit-review`. See `pickkit-review --help`; the web UI is
documented in `review_select/ui.py`.
