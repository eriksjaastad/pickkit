"""Regenerate the synthetic sandbox fixtures in sandbox/batch_a.

Run from the repo root:

    .venv/bin/python scripts/generate_sandbox_fixtures.py

Everything produced here is synthetic: tiny Pillow-generated PNGs plus
companion sidecars. No client/performer content.
"""

from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_A = REPO_ROOT / "sandbox" / "batch_a"

SPECS = {
    "img_001": {"color": (210, 90, 90), "stripes": (255, 255, 255)},
    "img_002": {"color": (90, 160, 210), "stripes": (255, 255, 255)},
    "img_003": {"color": (110, 190, 120), "stripes": (255, 255, 255)},
    "img_004": {"color": (200, 170, 90), "stripes": (255, 255, 255)},
}

SIDECAR_PLAN = {
    "img_001": [".yaml"],
    "img_002": [".yaml"],
    "img_003": [".txt"],
    "img_004": [".yaml", ".txt"],
}

SIZE = (64, 48)


def _yaml_sidecar(stem: str) -> str:
    return (
        "# pickkit synthetic sandbox sidecar\n"
        "batch: batch_a\n"
        f"image: {stem}.png\n"
        "kind: synthetic\n"
        "purpose: companion-move testing\n"
    )


def _txt_sidecar(stem: str) -> str:
    return (
        "# pickkit synthetic sandbox sidecar\n"
        "batch=batch_a\n"
        f"image={stem}.png\n"
        "kind=synthetic\n"
        "purpose=companion-move testing\n"
    )


def main() -> None:
    BATCH_A.mkdir(parents=True, exist_ok=True)

    for stem, spec in SPECS.items():
        image = Image.new("RGB", SIZE, spec["color"])
        draw = ImageDraw.Draw(image)
        for x in range(0, SIZE[0], 16):
            draw.rectangle([x, 0, x + 7, SIZE[1] - 1], fill=spec["stripes"])
        image.save(BATCH_A / f"{stem}.png")

    for stem, suffixes in SIDECAR_PLAN.items():
        for suffix in suffixes:
            text = _yaml_sidecar(stem) if suffix == ".yaml" else _txt_sidecar(stem)
            (BATCH_A / f"{stem}{suffix}").write_text(text, encoding="utf-8")

    for path in sorted(BATCH_A.iterdir()):
        print(f"{path.relative_to(REPO_ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
