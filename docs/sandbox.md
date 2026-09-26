# Sandbox fixtures — how tests find them

Tests locate fixtures relative to the repository root, never relative to the
current working directory, so `pytest` can run from anywhere:

    repo_root = Path(__file__).resolve().parents[1]
    sandbox = repo_root / "sandbox"

See `tests/test_sandbox_fixtures.py` for the canonical smoke check.

To regenerate fixtures from scratch, run
`python scripts/generate_sandbox_fixtures.py` from the repo root (uses Pillow).

## Rules

- Only generated/synthetic images belong in `sandbox/`. No client/performer
  content, ever.
- Sidecars share the image stem (`img_001.png` + `img_001.yaml`) so the future
  lib-safety companion rules have deterministic fixtures.
- If a test needs different shapes/sizes, generate them with Pillow in a
  fixture rather than committing binaries by hand.
