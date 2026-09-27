# Repository layout

pickkit is a single-project workspace (monorepo) for the plugin toolkit. All
installable packages live under `packages/`, one directory per plugin/library.

## Why `packages/` (not `src/`)

- The toolkit is a set of small, sibling packages (`pickkit_core`, `lib_safety`,
  `intake_init`, ...) that share one repo, one pyproject, and one test suite.
- `packages/` keeps each plugin at a predictable, grep-friendly path
  (`packages/lib_safety/...`) without adding a `src/` nesting level to every
  import.
- setuptools `packages.find` is pointed at `packages/`, so new plugin packages
  are discovered automatically with no pyproject edits.

## Current tree

    pickkit/
    ├── packages/
    │   ├── pickkit_core/        # shared version / constants stub
    │   ├── lib_safety/          # move-with-companions, trash, no-overwrite guards, audit
    │   ├── intake_init/         # point at a directory; manifest; audit baseline
    │   ├── review_select/       # keep/crop/reject triage; decision log
    │   ├── multi_crop/          # NEW crops under __cropped/; never overwrite originals
    │   ├── finish_package/      # close manifest; stage copy-only delivery ZIP
    │   └── README.md            # planned plugin list
    ├── sandbox/                 # synthetic fixtures (no client content)
    ├── tests/                   # repo-level smoke + plugin tests
    └── docs/

## Adding a package

Create `packages/<name>/` with an `__init__.py`. Use underscore-separated names
so the directory maps to a normal import (`lib_safety` -> `import lib_safety`).
Update `packages/README.md` and add tests under `tests/`.
