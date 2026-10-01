# Precursor (read-only)

| | |
|--|--|
| **Private precursor** | `~/projects/_archive/image-workflow` (archived 2026-10-01) |
| **Public extract** | this repo (`pickkit`) |
| **Rule** | Rewrite clean for the *job*. Do **not** bulk-copy scripts, client dirs, prompts, or git history into pickkit. |

## What you may take from the precursor

- Job order and safety invariants (move-don’t-modify; companions together; trash deletes; only crop writes new pixels)
- Ideas for plugin contracts and sandbox layouts
- Pointers into `Documents/` for architecture and file-safety rationale
- AI journal era (~2025) for case-study incidents → guardrails (cite; don’t paste secrets)

## What you must not bring over

- Client project trees (`mojo*`, production `__crop` / `__selected` content)
- Performer names, hot prompts, private taxonomies
- Scrubbed-forward git history from `github.com/eriksjaastad/image-workflow` (privacy track #6650 is separate and needs Erik’s explicit go)

## Related private board cards (stay on image-workflow board)

- #7084 — delete GitHub, keep code, extract clean plugins
- #7090 — extract reusable subsystems
- #6650 — privacy delete of the old public GitHub repo
- #7584 / #6900 — silent-failure triage (parked relative to split)

Day-to-day **pickkit** build cards live on the pickkit board.
