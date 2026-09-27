"""Tests for directory_viewer against synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated. Core invariants under
test: flat mode when the root holds direct images (subdirs not scanned),
subdirs mode when the root only has image-bearing subdirs (empty / non-image /
hidden subdirs omitted), ``by_ext`` counts lowercase extension keys,
``sample_limit`` truncates the stored basenames while ``image_count`` stays
full, ``compare_roots`` inventories each root in order, missing roots raise
``FileNotFoundError``, the spine manifest is never mutated, and the thin CLI
prints text or JSON and exits non-zero on missing roots.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest

from directory_viewer import (
    DEFAULT_IMAGE_SUFFIXES,
    DEFAULT_SAMPLE_LIMIT,
    OPERATION,
    DirInventory,
    RootReport,
    build_parser,
    compare_roots,
    inventory,
    list_images_in,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_A = REPO_ROOT / "sandbox" / "batch_a"


def stage_batch_a(tmp_path: Path) -> Path:
    """Copy sandbox/batch_a into tmp_path and return the staged root."""
    root = tmp_path / "batch_a"
    shutil.copytree(BATCH_A, root)
    return root


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- locked defaults ----------------------------------------------------------


def test_locked_defaults_are_exported() -> None:
    assert set(DEFAULT_IMAGE_SUFFIXES) == {
        ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    }
    assert OPERATION == "directory_viewer"
    assert DEFAULT_SAMPLE_LIMIT == 20


# --- list_images_in ------------------------------------------------------------


def test_list_images_in_finds_and_sorts_pngs(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    images = list_images_in(root)

    assert images == [
        root / "img_001.png",
        root / "img_002.png",
        root / "img_003.png",
        root / "img_004.png",
    ]


def test_list_images_in_skips_hidden_and_respects_suffixes(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    (root / ".hidden.png").write_bytes((root / "img_003.png").read_bytes())

    assert ".hidden.png" not in [path.name for path in list_images_in(root)]
    assert list_images_in(root, suffixes=".yaml") == [
        root / "img_001.yaml",
        root / "img_002.yaml",
        root / "img_004.yaml",
    ]


def test_list_images_in_refuses_missing_or_non_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="directory not found"):
        list_images_in(tmp_path / "missing")

    file_path = tmp_path / "plain.txt"
    file_path.write_text("not a dir", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="not a directory"):
        list_images_in(file_path)


# --- flat mode -----------------------------------------------------------------


def test_flat_mode_root_with_direct_images(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    sub = root / "sub"
    sub.mkdir()
    shutil.copy(root / "img_001.png", sub / "img_005.png")

    report = inventory(root)

    assert isinstance(report, RootReport)
    assert report.root == root
    assert report.mode == "flat"
    assert report.total_images == 4
    assert len(report.directories) == 1
    entry = report.directories[0]
    assert isinstance(entry, DirInventory)
    assert entry.name == root.name
    assert entry.path == root
    assert entry.image_count == 4
    assert entry.images == ("img_001.png", "img_002.png", "img_003.png", "img_004.png")
    assert entry.by_ext == {"png": 4}


# --- subdirs mode ---------------------------------------------------------------


def make_parent(tmp_path: Path) -> Path:
    """Build a root whose only images live in immediate subdirectories."""
    parent = tmp_path / "parent"
    (parent / "alpha").mkdir(parents=True)
    (parent / "beta").mkdir()
    (parent / "empty").mkdir()
    (parent / ".hidden_dir").mkdir()
    shutil.copy(BATCH_A / "img_001.png", parent / "alpha" / "a.png")
    shutil.copy(BATCH_A / "img_002.png", parent / "alpha" / "b.png")
    shutil.copy(BATCH_A / "img_001.png", parent / "alpha" / "c.jpg")
    (parent / "alpha" / "notes.txt").write_text("sidecar", encoding="utf-8")
    (parent / "alpha" / ".hidden.png").write_bytes(
        (BATCH_A / "img_001.png").read_bytes()
    )
    shutil.copy(BATCH_A / "img_004.png", parent / "beta" / "d.png")
    shutil.copy(BATCH_A / "img_001.png", parent / ".hidden_dir" / "e.png")
    return parent


def test_subdirs_mode_lists_image_bearing_subdirs_only(tmp_path: Path) -> None:
    parent = make_parent(tmp_path)

    report = inventory(parent)

    assert report.root == parent
    assert report.mode == "subdirs"
    assert report.total_images == 4
    assert [entry.name for entry in report.directories] == ["alpha", "beta"]
    assert [entry.image_count for entry in report.directories] == [3, 1]
    assert [entry.path for entry in report.directories] == [
        parent / "alpha",
        parent / "beta",
    ]


def test_subdirs_by_ext_counts_lowercase_without_dot(tmp_path: Path) -> None:
    parent = make_parent(tmp_path)

    report = inventory(parent)

    alpha, beta = report.directories
    assert alpha.by_ext == {"jpg": 1, "png": 2}
    assert beta.by_ext == {"png": 1}


# --- by_ext across the full suffix set -----------------------------------------


def test_by_ext_covers_default_suffixes_and_uppercase(tmp_path: Path) -> None:
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    shutil.copy(BATCH_A / "img_001.png", mixed / "a.png")
    shutil.copy(BATCH_A / "img_002.png", mixed / "b.png")
    shutil.copy(BATCH_A / "img_001.png", mixed / "c.JPG")
    shutil.copy(BATCH_A / "img_001.png", mixed / "d.jpeg")
    shutil.copy(BATCH_A / "img_001.png", mixed / "e.webp")
    shutil.copy(BATCH_A / "img_001.png", mixed / "f.tif")
    shutil.copy(BATCH_A / "img_001.png", mixed / "g.tiff")
    shutil.copy(BATCH_A / "img_001.png", mixed / "h.bmp")
    shutil.copy(BATCH_A / "img_001.png", mixed / "i.gif")

    report = inventory(mixed)

    assert report.mode == "flat"
    assert report.total_images == 9
    assert report.directories[0].by_ext == {
        "bmp": 1, "gif": 1, "jpeg": 1, "jpg": 1, "png": 2, "tif": 1,
        "tiff": 1, "webp": 1,
    }


# --- sample_limit ---------------------------------------------------------------


def test_sample_limit_truncates_images_but_not_image_count(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    report = inventory(root, sample_limit=2)

    entry = report.directories[0]
    assert entry.image_count == 4
    assert entry.images == ("img_001.png", "img_002.png")


def test_sample_limit_zero_stores_no_basenames(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    report = inventory(root, sample_limit=0)

    assert report.directories[0].image_count == 4
    assert report.directories[0].images == ()


def test_sample_limit_none_or_negative_stores_all_basenames(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    for limit in (None, -1):
        report = inventory(root, sample_limit=limit)
        assert report.directories[0].images == (
            "img_001.png", "img_002.png", "img_003.png", "img_004.png",
        )


def test_sample_limit_bad_type_raises(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    with pytest.raises(ValueError, match="sample_limit"):
        inventory(root, sample_limit="20")  # type: ignore[arg-type]


# --- compare_roots ---------------------------------------------------------------


def test_compare_roots_inventories_each_root_in_order(tmp_path: Path) -> None:
    flat_root = stage_batch_a(tmp_path)
    parent = make_parent(tmp_path)

    reports = compare_roots([flat_root, parent])

    assert len(reports) == 2
    assert reports[0].root == flat_root
    assert reports[0].mode == "flat"
    assert reports[0].total_images == 4
    assert reports[1].root == parent
    assert reports[1].mode == "subdirs"
    assert reports[1].total_images == 4


def test_compare_roots_accepts_single_path(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    reports = compare_roots(root)

    assert len(reports) == 1
    assert reports[0].root == root


def test_inventory_missing_root_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="root not found"):
        inventory(tmp_path / "missing")


def test_compare_roots_refuses_missing_or_non_directory(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    with pytest.raises(FileNotFoundError, match="root not found"):
        compare_roots([root, tmp_path / "missing"])

    file_path = tmp_path / "plain.txt"
    file_path.write_text("not a dir", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="root is not a directory"):
        compare_roots([root, file_path])


# --- spine manifest is never touched ----------------------------------------------


def test_no_spine_manifest_mutation(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    pickkit_dir = root / ".pickkit"
    pickkit_dir.mkdir()
    manifest_path = pickkit_dir / "project.json"
    manifest = {
        "schema_version": 2,
        "started_at": "2026-09-26T00:00:00Z",
        "finished_at": None,
        "root": str(root),
        "image_count": 4,
        "steps": [
            {"name": "intake", "started_at": "2026-09-26T00:00:00Z",
             "finished_at": "2026-09-26T00:00:00Z", "images_processed": 4},
            {"name": "review_select", "started_at": None,
             "finished_at": None, "images_processed": None},
            {"name": "multi_crop", "started_at": None,
             "finished_at": None, "images_processed": None},
            {"name": "finish_package", "started_at": None,
             "finished_at": None, "images_processed": None},
        ],
        "metrics": {},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    before = manifest_path.read_bytes()

    inventory(root)
    inventory(root, sample_limit=0)
    compare_roots([root])

    assert manifest_path.read_bytes() == before
    assert _read_json(manifest_path)["finished_at"] is None
    assert sorted(path.name for path in pickkit_dir.iterdir()) == ["project.json"]


# --- CLI -------------------------------------------------------------------------


def test_cli_inventory_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = stage_batch_a(tmp_path)

    assert main(["inventory", str(root), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["root"] == str(root)
    assert out["mode"] == "flat"
    assert out["total_images"] == 4
    assert out["directories"][0]["name"] == root.name
    assert out["directories"][0]["images"] == [
        "img_001.png", "img_002.png", "img_003.png", "img_004.png",
    ]
    assert out["directories"][0]["by_ext"] == {"png": 4}


def test_cli_compare_json_sample_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flat_root = stage_batch_a(tmp_path)
    parent = make_parent(tmp_path)

    assert main(
        ["compare", str(flat_root), str(parent), "--json", "--sample", "0"]
    ) == 0
    out = json.loads(capsys.readouterr().out)

    assert isinstance(out, list)
    assert [report["mode"] for report in out] == ["flat", "subdirs"]
    assert out[0]["directories"][0]["images"] == []
    assert out[0]["directories"][0]["image_count"] == 4
    assert out[1]["directories"][0]["images"] == []
    assert out[1]["directories"][0]["image_count"] == 3


def test_cli_sample_negative_one_means_all(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)

    assert main(["inventory", str(root), "--json", "--sample", "-1"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["directories"][0]["images"] == [
        "img_001.png", "img_002.png", "img_003.png", "img_004.png",
    ]


def test_cli_human_readable_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)

    assert main(["inventory", str(root)]) == 0
    text = capsys.readouterr().out

    assert "mode=flat" in text
    assert f"- {root.name}: 4 images" in text
    assert "png: 4" in text


def test_cli_compare_human_readable_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flat_root = stage_batch_a(tmp_path)
    parent = make_parent(tmp_path)

    assert main(["compare", str(flat_root), str(parent)]) == 0
    text = capsys.readouterr().out

    assert "mode=flat" in text
    assert "mode=subdirs" in text
    assert "- alpha: 3 images" in text
    assert "- beta: 1 images" in text


def test_cli_error_when_root_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["inventory", str(tmp_path / "missing")])
    assert exc_info.value.code == 1
    assert "pickkit-viewer: error:" in capsys.readouterr().err


def test_build_parser_has_inventory_and_compare_subcommands() -> None:
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)

    help_text = parser.format_help()
    assert "inventory" in help_text
    assert "compare" in help_text
