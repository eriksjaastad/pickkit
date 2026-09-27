# pickkit packages

Planned plugins (from PLAN.md §2). The first template plugin is **lib-safety**.

| Directory | Plugin | Status |
|-----------|--------|--------|
| `pickkit_core/` | shared core (version, constants) | stub — this scaffold |
| `lib_safety/` | move-not-modify originals, companions together, trash deletes, audit | implemented (#7650) |
| `intake_init/` | point at a directory; manifest; sidecars/tracking; step recording; safety baseline | implemented |
| `review_select/` | triage into keep / crop / reject; log decisions | implemented |
| `multi_crop/` | create NEW crops only; never overwrite originals | implemented |
| `finish_package/` | close manifest; stage delivery ZIP | implemented |

TBD middle tools: `character_tools`, `directory_viewer`, `duplicate_finder`,
`lib_metrics`.
