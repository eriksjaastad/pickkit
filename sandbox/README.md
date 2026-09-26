# Sandbox

Synthetic fixture data for pickkit tests and demos. Everything in here is
generated, tiny, and free of client/performer content.

## Layout

    sandbox/
    └── batch_a/        # one intake-style batch
        ├── img_001.png + img_001.yaml
        ├── img_002.png + img_002.yaml
        ├── img_003.png + img_003.txt
        └── img_004.png + img_004.yaml + img_004.txt

- Each `.png` is a tiny Pillow-generated image (solid color + stripe pattern).
- Sidecars (`.yaml` / `.txt`) share the image stem so companion-aware moves
  (move image + sidecars together) can be tested later.
- Sidecar contents are minimal synthetic metadata (batch, kind, purpose).

Regenerate with `python scripts/generate_sandbox_fixtures.py` from the repo root.
