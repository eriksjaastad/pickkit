"""Smoke tests for the synthetic sandbox fixtures."""

from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = REPO_ROOT / "sandbox"
BATCH_A = SANDBOX / "batch_a"


def _image_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.png"))


def test_sandbox_directory_exists():
    assert SANDBOX.is_dir()
    assert BATCH_A.is_dir()


def test_batch_a_has_images():
    images = _image_files(BATCH_A)
    assert len(images) >= 3


def test_images_are_readable_pngs():
    images = _image_files(BATCH_A)
    assert images
    for image in images:
        with Image.open(image) as im:
            assert im.format == "PNG"
            assert im.size[0] > 0 and im.size[1] > 0
            im.load()  # force a full decode


def test_every_image_has_a_companion_sidecar():
    images = _image_files(BATCH_A)
    assert images
    for image in images:
        companions = [
            c
            for c in BATCH_A.glob(f"{image.stem}.*")
            if c.suffix in {".yaml", ".txt"}
        ]
        assert companions, f"{image.name} has no companion sidecar"
