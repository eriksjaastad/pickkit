# Why `packages/` and not `src/`

pickkit is one repo with several small sibling packages (`lib_safety`,
`intake_init`, `review_select`, ...) that share one `pyproject.toml` and one
test suite.

- Each package sits at a predictable path (`packages/lib_safety/...`) with no
  extra `src/` level in front of every import.
- setuptools `packages.find` points at `packages/`, so a new package is picked
  up with no `pyproject.toml` edit.
- Directory names use underscores so they map straight to imports
  (`lib_safety` -> `import lib_safety`).
