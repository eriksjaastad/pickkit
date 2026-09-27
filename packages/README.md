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
| `character_tools/` | assign images to user-supplied named bins + companions | implemented (library+CLI) |
| `duplicate_finder/` | find exact/near-duplicate images; thin extras into OS trash | implemented (library+CLI) |

TBD middle tools: `directory_viewer`, `lib_metrics`.
