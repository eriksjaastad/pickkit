"""Tests for duplicate_finder against synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated. Exact duplicates are
created by copying an image (and optionally a companion) to a second
filename/path. Core invariants under test: sha256 content hashes agree on
identical bytes, exact groups form only for shared digests, near mode
clusters identical files at threshold 0, average hashes of a resized
near-identical Pillow pair stay within the default threshold, dry-run
thinning writes nothing, commit thins drops (and their companions) into the
OS trash while the keeper stays, keep policies are deterministic, bad keep
policies raise ValueError, and the spine manifest is never mutated.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from duplicate_finder import (
    DEFAULT_IMAGE_SUFFIXES,
    DEFAULT_KEEP_POLICY,
    DEFAULT_NEAR_THRESHOLD,
    HASH_SIZE,
    KEEP_POLICIES,
    OPERATION,
    DuplicateGroup,
    ThinPlan,
    ThinResult,
    average_hash,
    content_hash,
    find_exact_duplicates,
    find_near_duplicates,
    hamming_distance,
    list_images,
    main,
    plan_thin,
    thin_groups,
)
from lib_safety import AuditEvent

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_A = REPO_ROOT / "sandbox" / "batch_a"


class RecordingHook:
    """Collects AuditEvents for assertions."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def stage_batch_a(tmp_path: Path) -> Path:
    """Copy sandbox/batch_a into tmp_path and return the staged root."""
    root = tmp_path / "batch_a"
    shutil.copytree(BATCH_A, root)
    return root


def make_dup_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Stage batch_a plus a copied image + companion; return (root, keep, drop)."""
    root = stage_batch_a(tmp_path)
    keeper = root / "img_001.png"
    drop = root / "zzz_dup.png"
    shutil.copy(keeper, drop)
    shutil.copy(root / "img_001.yaml", root / "zzz_dup.yaml")
    return root, keeper, drop


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- locked defaults ----------------------------------------------------------


def test_locked_defaults_are_exported() -> None:
    assert set(DEFAULT_IMAGE_SUFFIXES) == {
        ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    }
    assert HASH_SIZE == 8
    assert DEFAULT_NEAR_THRESHOLD == 5
    assert KEEP_POLICIES == ("keep_first", "keep_largest", "keep_oldest")
    assert DEFAULT_KEEP_POLICY == "keep_first"
    assert OPERATION == "duplicate_finder"


# --- content_hash --------------------------------------------------------------


def test_content_hash_equal_and_different(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    other = root / "img_001_copy.png"
    shutil.copy(root / "img_001.png", other)

    assert content_hash(root / "img_001.png") == content_hash(other)
    assert content_hash(root / "img_001.png") != content_hash(root / "img_002.png")
    assert len(content_hash(other)) == 64
    assert content_hash(other) == content_hash(other).lower()


def test_content_hash_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="image not found"):
        content_hash(tmp_path / "missing.png")


# --- list_images ---------------------------------------------------------------


def test_list_images_non_recursive_default_and_recursive(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    sub = root / "sub"
    sub.mkdir()
    shutil.copy(root / "img_004.png", sub / "img_005.png")
    hidden_dir = root / ".hidden"
    hidden_dir.mkdir()
    shutil.copy(root / "img_004.png", hidden_dir / "hidden.png")
    (root / ".hidden.png").write_bytes((root / "img_003.png").read_bytes())

    top = list_images(root)
    assert [path.name for path in top] == [
        "img_001.png", "img_002.png", "img_003.png", "img_004.png",
    ]

    walked = list_images(root, recursive=True)
    assert [path.name for path in walked] == [
        "img_001.png", "img_002.png", "img_003.png", "img_004.png",
        "img_005.png",
    ]

    assert list_images(root / "img_001.png") == [root / "img_001.png"]
    assert list_images(root / "img_001.yaml") == []


def test_list_images_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="source not found"):
        list_images(tmp_path / "missing.png")


# --- exact duplicates -----------------------------------------------------------


def test_find_exact_duplicates_returns_one_group_of_size_two(tmp_path: Path) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)

    groups = find_exact_duplicates(root)

    assert len(groups) == 1
    group = groups[0]
    assert group.kind == "exact"
    assert group.threshold is None
    assert group.key == content_hash(keeper)
    assert set(group.paths) == {keeper, drop}


def test_find_exact_duplicates_accepts_single_path_and_sequence(
    tmp_path: Path,
) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)

    as_str = find_exact_duplicates(str(root))
    as_files = find_exact_duplicates([keeper, drop])

    assert as_str == as_files
    assert len(as_files) == 1
    assert set(as_files[0].paths) == {keeper, drop}


def test_find_exact_duplicates_empty_when_no_dups(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    assert find_exact_duplicates(root) == []


# --- near duplicates ------------------------------------------------------------


def test_average_hash_identical_files_hamming_zero(tmp_path: Path) -> None:
    near_dir = tmp_path / "near"
    near_dir.mkdir()
    shutil.copy(BATCH_A / "img_001.png", near_dir / "a.png")
    shutil.copy(BATCH_A / "img_001.png", near_dir / "b.png")

    assert average_hash(near_dir / "a.png") == average_hash(near_dir / "b.png")
    assert hamming_distance(
        average_hash(near_dir / "a.png"), average_hash(near_dir / "b.png")
    ) == 0


def test_average_hash_resized_pair_stays_within_threshold(tmp_path: Path) -> None:
    near_dir = tmp_path / "near"
    near_dir.mkdir()
    a = near_dir / "a.png"
    b = near_dir / "b.png"
    image = Image.new("L", (64, 64), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 8, 40, 40], fill=0)
    image.save(a)
    Image.open(a).convert("L").resize(
        (60, 60), Image.Resampling.LANCZOS
    ).resize((64, 64), Image.Resampling.LANCZOS).save(b)

    assert hamming_distance(average_hash(a), average_hash(b)) <= DEFAULT_NEAR_THRESHOLD


def test_average_hash_different_images_exceed_threshold(tmp_path: Path) -> None:
    near_dir = tmp_path / "near"
    near_dir.mkdir()
    a = near_dir / "a.png"
    b = near_dir / "b.png"
    image_a = Image.new("L", (64, 64), 255)
    ImageDraw.Draw(image_a).rectangle([8, 8, 40, 40], fill=0)
    image_a.save(a)
    image_b = Image.new("L", (64, 64), 255)
    ImageDraw.Draw(image_b).ellipse([24, 24, 56, 56], fill=0)
    image_b.save(b)

    assert hamming_distance(average_hash(a), average_hash(b)) > DEFAULT_NEAR_THRESHOLD


def test_find_near_duplicates_clusters_identical_files(tmp_path: Path) -> None:
    near_dir = tmp_path / "near"
    near_dir.mkdir()
    shutil.copy(BATCH_A / "img_001.png", near_dir / "a.png")
    shutil.copy(BATCH_A / "img_001.png", near_dir / "b.png")

    groups = find_near_duplicates(near_dir, threshold=0)

    assert len(groups) == 1
    group = groups[0]
    assert group.kind == "near"
    assert group.threshold == 0
    assert group.key == f"{average_hash(near_dir / 'a.png'):016x}"
    assert set(group.paths) == {near_dir / "a.png", near_dir / "b.png"}


def test_find_near_duplicates_does_not_cluster_distinct_images(tmp_path: Path) -> None:
    near_dir = tmp_path / "near"
    near_dir.mkdir()
    image_a = Image.new("L", (64, 64), 255)
    ImageDraw.Draw(image_a).rectangle([8, 8, 40, 40], fill=0)
    image_a.save(near_dir / "a.png")
    image_b = Image.new("L", (64, 64), 255)
    ImageDraw.Draw(image_b).ellipse([24, 24, 56, 56], fill=0)
    image_b.save(near_dir / "b.png")

    assert find_near_duplicates(near_dir, threshold=DEFAULT_NEAR_THRESHOLD) == []


def test_average_hash_bad_hash_size_raises(tmp_path: Path) -> None:
    image = tmp_path / "img.png"
    image.write_bytes((BATCH_A / "img_001.png").read_bytes())

    for bad in (0, -1, 1.5, "8"):
        with pytest.raises(ValueError, match="hash_size"):
            average_hash(image, hash_size=bad)


def test_hamming_distance_validation() -> None:
    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0b1010, 0b0010) == 1
    with pytest.raises(ValueError, match="non-negative"):
        hamming_distance(-1, 0)
    with pytest.raises(ValueError, match="integers"):
        hamming_distance("a", 0)  # type: ignore[arg-type]


# --- keep policies --------------------------------------------------------------


def test_plan_thin_keep_first_is_deterministic(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"y" * 200)
    group = DuplicateGroup("exact", "key", (b, a))

    first = plan_thin(group)
    second = plan_thin(group)

    assert isinstance(first, ThinPlan)
    assert first == second
    assert first.keep == a
    assert first.drop == (b,)


def test_plan_thin_keep_largest_and_keep_oldest(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"y" * 200)
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    group = DuplicateGroup("exact", "key", (a, b))

    assert plan_thin(group, keep_policy="keep_largest").keep == b
    assert plan_thin(group, keep_policy="keep_oldest").keep == a


def test_plan_thin_bad_keep_policy_raises(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    group = DuplicateGroup("exact", "key", (a, b))

    with pytest.raises(ValueError, match="keep_policy"):
        plan_thin(group, keep_policy="keep_newest")
    with pytest.raises(ValueError, match="keep_policy"):
        thin_groups([group], keep_policy="keep_newest")


def test_plan_thin_singleton_group_raises(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    a.write_bytes(b"x")
    with pytest.raises(ValueError, match="at least two"):
        plan_thin(DuplicateGroup("exact", "key", (a,)))


# --- thinning --------------------------------------------------------------------


def test_thin_groups_dry_run_writes_nothing(tmp_path: Path) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)
    group = find_exact_duplicates(root)[0]
    hook = RecordingHook()

    result = thin_groups([group], hook=hook)

    assert isinstance(result, ThinResult)
    assert result.committed is False
    assert result.groups_planned == 1
    assert result.kept == (keeper,)
    assert result.dropped == (drop,)
    assert drop.is_file()
    assert (root / "zzz_dup.yaml").is_file()
    assert keeper.is_file()
    assert [event.operation for event in hook.events] == [OPERATION]
    assert [event.reason for event in hook.events] == ["thin; dry_run"]


def test_thin_groups_commit_trashes_drops_and_companions(tmp_path: Path) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)
    group = find_exact_duplicates(root)[0]

    result = thin_groups([group], commit=True)

    assert result.committed is True
    assert result.kept == (keeper,)
    assert result.dropped == (drop,)
    assert not drop.exists()
    assert not (root / "zzz_dup.yaml").exists()
    assert keeper.is_file()
    assert (root / "img_001.yaml").is_file()


def test_thin_groups_keep_largest_commit(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    small = root / "img_002.png"
    large = root / "zzz_large.png"
    shutil.copy(root / "img_001.png", large)
    with large.open("ab") as handle:
        handle.write(b"extra bytes make this the largest")
    group = DuplicateGroup("near", "seed", (small, large), threshold=5)

    result = thin_groups([group], commit=True, keep_policy="keep_largest")

    assert result.kept == (large,)
    assert not small.exists()
    assert large.is_file()


# --- spine manifest is never touched ----------------------------------------------


def test_no_spine_manifest_mutation(tmp_path: Path) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)
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
    group = find_exact_duplicates(root)[0]

    find_near_duplicates(root)
    thin_groups([group], commit=True)

    assert manifest_path.read_bytes() == before
    assert _read_json(manifest_path)["finished_at"] is None
    assert sorted(path.name for path in pickkit_dir.iterdir()) == ["project.json"]


# --- CLI ----------------------------------------------------------------------------


def test_cli_exact_prints_json_groups(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)

    assert main(["exact", str(root), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["mode"] == "exact"
    assert len(out["groups"]) == 1
    assert out["groups"][0]["key"] == content_hash(keeper)
    assert set(out["groups"][0]["paths"]) == {str(keeper), str(drop)}


def test_cli_near_prints_json_groups(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    near_dir = tmp_path / "near"
    near_dir.mkdir()
    shutil.copy(BATCH_A / "img_001.png", near_dir / "a.png")
    shutil.copy(BATCH_A / "img_001.png", near_dir / "b.png")

    assert main(["near", str(near_dir), "--threshold", "0"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["mode"] == "near"
    assert out["threshold"] == 0
    assert len(out["groups"]) == 1


def test_cli_thin_dry_run_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)

    assert main(["thin", str(root), "--mode", "exact"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["mode"] == "exact"
    assert out["committed"] is False
    assert out["kept"] == [str(keeper)]
    assert out["dropped"] == [str(drop)]
    assert drop.is_file()


def test_cli_thin_commit_and_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, keeper, drop = make_dup_pair(tmp_path)
    audit_path = tmp_path / "audit.jsonl"

    assert main(
        ["thin", str(root), "--mode", "exact", "--commit", "--audit", str(audit_path)]
    ) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["committed"] is True
    assert not drop.exists()
    assert keeper.is_file()
    audit_lines = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [line["operation"] for line in audit_lines] == [
        OPERATION, "trash", OPERATION,
    ]
    assert audit_lines[0]["reason"] == "find_exact"
    assert audit_lines[2]["reason"] == "thin; committed=True"


def test_cli_error_when_source_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["exact", str(tmp_path / "missing")])
    assert exc_info.value.code == 1
    assert "pickkit-dupes: error:" in capsys.readouterr().err
