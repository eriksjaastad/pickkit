"""Tests for multi_crop against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path`` and intake'd with ``intake_init`` before crops are applied; the
committed sandbox is never mutated. The core invariant under test: crops
write NEW raster files only — originals and companions are never overwritten,
moved, or rewritten.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from intake_init import intake_init
from lib_safety import AuditEvent, RefusedWriteError
from multi_crop import (
    CROPPED_DIR_NAME,
    CROP_QUEUE_DIR_NAME,
    CROPS_LOG_NAME,
    ApplyResult,
    CropSpec,
    apply_crop,
    clamp_box,
    crop_batch,
    load_crop_specs,
    main,
)
from review_select import CROP, Decision, apply_decisions

from conftest import BATCH_A, jsonl_lines, read_json, snapshot, stage_batch_a


class RecordingHook:
    """Collects AuditEvents for assertions."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _crop_lines(root: Path) -> list[dict[str, object]]:
    return jsonl_lines(root / ".pickkit" / CROPS_LOG_NAME)


def _multi_crop_step(root: Path) -> dict[str, object]:
    manifest = read_json(root / ".pickkit" / "project.json")
    for step in manifest["steps"]:
        if step["name"] == "multi_crop":
            return step
    raise AssertionError("multi_crop step missing")


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


# --- clamp_box --------------------------------------------------------------


def test_clamp_box_clamps_out_of_bounds_coordinates() -> None:
    assert clamp_box((10, 10, 100, 100), 64, 48) == (10, 10, 64, 48)
    assert clamp_box((-5, -5, 10, 10), 64, 48) == (0, 0, 10, 10)
    assert clamp_box((100, 100, 200, 200), 64, 48) == (63, 47, 64, 48)


def test_clamp_box_ensures_at_least_1px() -> None:
    assert clamp_box((10, 10, 10, 10), 64, 48) == (10, 10, 11, 11)
    assert clamp_box((0, 0, 0, 0), 64, 48) == (0, 0, 1, 1)
    assert clamp_box((64, 48, 64, 48), 64, 48) == (63, 47, 64, 48)
    assert clamp_box((0, 0, 64, 0), 64, 48) == (0, 0, 64, 1)


def test_clamp_box_refuses_bad_dimensions_and_boxes() -> None:
    with pytest.raises(ValueError, match="positive"):
        clamp_box((0, 0, 10, 10), 0, 48)
    with pytest.raises(ValueError, match="positive"):
        clamp_box((0, 0, 10, 10), 64, -1)
    with pytest.raises(ValueError, match="exactly 4"):
        clamp_box((0, 0, 10), 64, 48)
    with pytest.raises(ValueError, match="integers"):
        clamp_box((0, 0, 10.5, 10), 64, 48)
    with pytest.raises(ValueError, match="must be"):
        clamp_box("0,0,10,10", 64, 48)


# --- apply_crop (standalone, no intake) -------------------------------------


def test_apply_crop_writes_new_file_and_leaves_source_unchanged(
    tmp_path: Path,
) -> None:
    root = stage_batch_a(tmp_path)
    source = root / "img_002.png"
    dest = root / CROPPED_DIR_NAME / "img_002.png"
    before = source.read_bytes()

    result = apply_crop(source, (0, 0, 32, 48), dest)

    assert result == dest
    assert dest.is_file()
    assert _image_size(dest) == (32, 48)
    assert source.read_bytes() == before
    # Companion sidecars are left alone.
    assert (root / "img_002.yaml").is_file()
    assert list((root / CROPPED_DIR_NAME).iterdir()) == [dest]


def test_apply_crop_refuses_existing_destination(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    source = root / "img_001.png"
    dest = root / CROPPED_DIR_NAME / "img_001.png"
    dest.parent.mkdir()
    dest.write_bytes(b"occupied")

    with pytest.raises(RefusedWriteError, match="already exists"):
        apply_crop(source, (0, 0, 16, 16), dest)

    assert dest.read_bytes() == b"occupied"
    assert source.read_bytes() == (BATCH_A / "img_001.png").read_bytes()


def test_apply_crop_refuses_destination_equal_to_source(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    source = root / "img_001.png"
    before = source.read_bytes()

    with pytest.raises(RefusedWriteError, match="source image"):
        apply_crop(source, (0, 0, 16, 16), source)

    assert source.read_bytes() == before


def test_apply_crop_audits_success_to_caller_hook(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    hook = RecordingHook()

    apply_crop(
        root / "img_001.png",
        (0, 0, 16, 16),
        root / CROPPED_DIR_NAME / "img_001.png",
        hook=hook,
    )

    assert [event.operation for event in hook.events] == ["multi_crop"]
    assert hook.events[0].ok is True
    assert hook.events[0].reason == "box=0,0,16,16"


# --- crop_batch -------------------------------------------------------------


def test_crop_batch_default_destination_log_and_step(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    source = root / "img_001.png"
    before = source.read_bytes()

    result = crop_batch(root, [CropSpec("img_001.png", (0, 0, 32, 48))])

    assert isinstance(result, ApplyResult)
    assert result.crops_applied == 1
    assert result.destinations == (f"{CROPPED_DIR_NAME}/img_001.png",)
    assert result.finished is False
    assert result.manifest_path == root / ".pickkit" / "project.json"
    assert result.crops_log_path == root / ".pickkit" / CROPS_LOG_NAME

    dest = root / CROPPED_DIR_NAME / "img_001.png"
    assert dest.is_file()
    assert _image_size(dest) == (32, 48)
    assert source.read_bytes() == before

    records = _crop_lines(root)
    assert len(records) == 1
    record = records[0]
    assert record["timestamp"].endswith("Z")
    assert record["source"] == "img_001.png"
    assert record["destination"] == f"{CROPPED_DIR_NAME}/img_001.png"
    assert record["box"] == [0, 0, 32, 48]
    assert "note" not in record

    step = _multi_crop_step(root)
    assert step["started_at"].endswith("Z")
    assert step["images_processed"] == 1
    assert step["finished_at"] is None


def test_crop_batch_from_crop_queue_leaves_companions_alone(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    apply_decisions(root, [Decision("img_002.png", CROP)])
    queued = root / CROP_QUEUE_DIR_NAME / "img_002.png"
    assert queued.is_file()
    assert (root / CROP_QUEUE_DIR_NAME / "img_002.yaml").is_file()

    result = crop_batch(root, [CropSpec(f"{CROP_QUEUE_DIR_NAME}/img_002.png", (0, 0, 32, 48))])

    dest = root / CROPPED_DIR_NAME / "img_002.png"
    assert result.destinations == (f"{CROPPED_DIR_NAME}/img_002.png",)
    assert dest.is_file()
    # The crop queue companion stays where review-select put it; multi-crop
    # never copies or rewrites sidecars.
    assert (root / CROP_QUEUE_DIR_NAME / "img_002.yaml").is_file()
    assert list((root / CROPPED_DIR_NAME).iterdir()) == [dest]
    assert _crop_lines(root)[0]["source"] == f"{CROP_QUEUE_DIR_NAME}/img_002.png"


def test_crop_batch_explicit_destinations_for_multiple_crops_of_one_source(
    tmp_path: Path,
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = crop_batch(
        root,
        [
            CropSpec("img_003.png", (0, 0, 16, 16), destination="img_003_a.png", note="top-left"),
            CropSpec("img_003.png", (48, 32, 64, 48), destination="img_003_b.png"),
        ],
    )

    assert result.crops_applied == 2
    assert result.destinations == (
        f"{CROPPED_DIR_NAME}/img_003_a.png",
        f"{CROPPED_DIR_NAME}/img_003_b.png",
    )
    assert (root / CROPPED_DIR_NAME / "img_003_a.png").is_file()
    assert (root / CROPPED_DIR_NAME / "img_003_b.png").is_file()
    assert _image_size(root / CROPPED_DIR_NAME / "img_003_b.png") == (16, 16)

    records = _crop_lines(root)
    assert [r["source"] for r in records] == ["img_003.png", "img_003.png"]
    assert records[0]["note"] == "top-left"
    assert "note" not in records[1]
    assert _multi_crop_step(root)["images_processed"] == 2


def test_crop_batch_refuses_destination_collision_without_writing(
    tmp_path: Path,
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    occupied = root / CROPPED_DIR_NAME / "img_001.png"
    occupied.parent.mkdir()
    occupied.write_bytes(b"occupied")

    with pytest.raises(RefusedWriteError, match="already exists"):
        crop_batch(root, [CropSpec("img_001.png", (0, 0, 16, 16))])

    assert occupied.read_bytes() == b"occupied"
    assert (root / "img_001.png").read_bytes() == (BATCH_A / "img_001.png").read_bytes()
    assert not (root / ".pickkit" / CROPS_LOG_NAME).exists()
    step = _multi_crop_step(root)
    assert step["started_at"] is None
    assert step["images_processed"] is None
    # The refusal is audited through the batch audit JSONL.
    audit_ops = [e["operation"] for e in jsonl_lines(root / ".pickkit" / "audit.jsonl")]
    assert audit_ops == ["intake_init", "refuse_write"]


def test_crop_batch_refuses_without_prior_intake(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    with pytest.raises(FileNotFoundError, match="intake"):
        crop_batch(root, [CropSpec("img_001.png", (0, 0, 16, 16))])

    assert not (root / ".pickkit").exists()
    assert not (root / CROPPED_DIR_NAME).exists()


def test_crop_batch_refuses_missing_source_before_any_write(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    with pytest.raises(FileNotFoundError, match="source not found"):
        crop_batch(root, [CropSpec("missing.png", (0, 0, 16, 16))])

    assert not (root / CROPPED_DIR_NAME).exists()
    assert not (root / ".pickkit" / CROPS_LOG_NAME).exists()
    step = _multi_crop_step(root)
    assert step["started_at"] is None
    assert step["images_processed"] is None


def test_crop_batch_refuses_source_outside_batch_root(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    outside = tmp_path / "outside.png"
    shutil.copy(BATCH_A / "img_001.png", outside)

    with pytest.raises(ValueError, match="outside batch root"):
        crop_batch(root, [CropSpec(str(outside), (0, 0, 16, 16))])


def test_crop_batch_finish_sets_finished_at_and_creates_no_zip(
    tmp_path: Path,
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = crop_batch(
        root,
        [CropSpec("img_001.png", (0, 0, 32, 48))],
        finish=True,
    )

    assert result.finished is True
    step = _multi_crop_step(root)
    assert step["started_at"].endswith("Z")
    assert step["images_processed"] == 1
    assert step["finished_at"].endswith("Z")
    assert list(root.rglob("*.zip")) == []


def test_crop_batch_finish_with_no_crops_is_a_noop(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = crop_batch(root, [], finish=True)

    assert result.crops_applied == 0
    assert result.destinations == ()
    assert result.finished is False
    assert not (root / CROPPED_DIR_NAME).exists()
    assert not (root / ".pickkit" / CROPS_LOG_NAME).exists()
    step = _multi_crop_step(root)
    assert step["started_at"] is None
    assert step["images_processed"] is None
    assert step["finished_at"] is None


def test_crop_batch_audits_jsonl_and_caller_hook(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    hook = RecordingHook()

    crop_batch(root, [CropSpec("img_004.png", (0, 0, 16, 16))], hook=hook)

    audit_lines = jsonl_lines(root / ".pickkit" / "audit.jsonl")
    assert [e["operation"] for e in audit_lines] == ["intake_init", "multi_crop"]
    assert all(e["ok"] for e in audit_lines[1:])

    assert [e.operation for e in hook.events] == ["multi_crop"]
    assert hook.events[0].ok is True
    assert hook.events[0].reason == "box=0,0,16,16"


def test_never_mutates_committed_sandbox(tmp_path: Path) -> None:
    before = snapshot(BATCH_A)

    root = stage_batch_a(tmp_path)
    intake_init(root)
    crop_batch(root, [CropSpec("img_001.png", (0, 0, 32, 48))])
    apply_crop(
        root / "img_002.png",
        (0, 0, 16, 16),
        root / CROPPED_DIR_NAME / "img_002_extra.png",
    )

    assert snapshot(BATCH_A) == before


# --- load_crop_specs --------------------------------------------------------


def test_load_crop_specs_reads_json_array(tmp_path: Path) -> None:
    path = tmp_path / "crops.json"
    path.write_text(
        json.dumps(
            [
                {"source": "img_001.png", "box": [0, 0, 32, 48]},
                {
                    "source": "img_002.png",
                    "box": [10, 10, 50, 40],
                    "destination": "img_002_tight.png",
                    "note": "tight",
                },
            ]
        ),
        encoding="utf-8",
    )

    specs = load_crop_specs(path)

    assert specs == [
        CropSpec("img_001.png", (0, 0, 32, 48)),
        CropSpec("img_002.png", (10, 10, 50, 40), destination="img_002_tight.png", note="tight"),
    ]


def test_load_crop_specs_reads_jsonl_and_skips_blanks(tmp_path: Path) -> None:
    path = tmp_path / "crops.jsonl"
    path.write_text(
        '{"source": "img_001.png", "box": [0, 0, 32, 48]}\n\n'
        '{"source": "img_003.png", "box": [16, 16, 48, 48]}\n',
        encoding="utf-8",
    )

    specs = load_crop_specs(path)

    assert [s.source for s in specs] == ["img_001.png", "img_003.png"]
    assert [s.box for s in specs] == [(0, 0, 32, 48), (16, 16, 48, 48)]


def test_load_crop_specs_refuses_malformed_records(tmp_path: Path) -> None:
    missing_box = tmp_path / "missing.json"
    missing_box.write_text('[{"source": "img_001.png"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="box"):
        load_crop_specs(missing_box)

    bad_box = tmp_path / "bad_box.json"
    bad_box.write_text('[{"source": "img_001.png", "box": [0, 0, 32]}]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="4 integers"):
        load_crop_specs(bad_box)

    not_an_array = tmp_path / "object.json"
    not_an_array.write_text('{"source": "img_001.png"}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_crop_specs(not_an_array)


def test_crop_spec_refuses_invalid_boxes_at_construction() -> None:
    with pytest.raises(ValueError, match="exactly 4"):
        CropSpec("img_001.png", (0, 0, 32))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="integers"):
        CropSpec("img_001.png", (0, 0, 32.5, 48))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="source must not be empty"):
        CropSpec("", (0, 0, 32, 48))


# --- CLI --------------------------------------------------------------------


def test_cli_crops_file_applies_and_finishes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    crops_file = tmp_path / "crops.jsonl"
    crops_file.write_text(
        json.dumps({"source": "img_001.png", "box": [0, 0, 32, 48]}) + "\n",
        encoding="utf-8",
    )

    code = main([str(root), "--crops", str(crops_file), "--finish"])

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["crops_applied"] == 1
    assert summary["destinations"] == [f"{CROPPED_DIR_NAME}/img_001.png"]
    assert summary["finished"] is True
    assert (root / CROPPED_DIR_NAME / "img_001.png").is_file()
    assert _multi_crop_step(root)["finished_at"].endswith("Z")


def test_cli_one_shot_source_and_box(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    code = main([str(root), "--source", "img_001.png", "--box", "0,0,32,48"])

    assert code == 0
    assert (root / CROPPED_DIR_NAME / "img_001.png").is_file()
    assert _multi_crop_step(root)["images_processed"] == 1


def test_cli_repeated_source_and_box_pair_positionally(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    code = main(
        [
            str(root),
            "--source",
            "img_001.png",
            "--box",
            "0,0,16,16",
            "--source",
            "img_003.png",
            "--box",
            "16,16,32,32",
        ]
    )

    assert code == 0
    assert (root / CROPPED_DIR_NAME / "img_001.png").is_file()
    assert (root / CROPPED_DIR_NAME / "img_003.png").is_file()
    assert _multi_crop_step(root)["images_processed"] == 2
