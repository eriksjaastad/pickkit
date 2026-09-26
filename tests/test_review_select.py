"""Tests for review_select against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path`` and intake'd with ``intake_init`` before decisions are applied;
the committed sandbox is never mutated.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from intake_init import intake_init
from lib_safety import AuditEvent
from review_select import (
    ACTIONS,
    CROP,
    CROP_DIR_NAME,
    KEEP,
    KEEP_DIR_NAME,
    REJECT,
    REJECT_DIR_NAME,
    Decision,
    apply_decisions,
    load_decisions,
    main,
)

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


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _decision_lines(root: Path) -> list[dict[str, object]]:
    path = root / ".pickkit" / "decisions.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _review_select_step(root: Path) -> dict[str, object]:
    manifest = _read_json(root / ".pickkit" / "project.json")
    for step in manifest["steps"]:
        if step["name"] == "review_select":
            return step
    raise AssertionError("review_select step missing")


def _snapshot(directory: Path) -> dict[str, bytes]:
    """Relative path -> bytes for every file under *directory*."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# --- keep / crop / reject routing ------------------------------------------


def test_keep_moves_image_and_companions_into_selected(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(root, [Decision("img_001.png", KEEP)])

    assert result.decisions_applied == 1
    assert result.destinations_touched == (KEEP_DIR_NAME,)
    assert (root / KEEP_DIR_NAME / "img_001.png").is_file()
    assert (root / KEEP_DIR_NAME / "img_001.yaml").is_file()
    assert not (root / "img_001.png").exists()
    assert not (root / "img_001.yaml").exists()
    # Other destination dirs are not created.
    assert not (root / CROP_DIR_NAME).exists()
    assert not (root / REJECT_DIR_NAME).exists()


def test_crop_routes_to_crop_queue_without_pixel_rewrite(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(root, [Decision("img_002.png", CROP)])

    assert result.destinations_touched == (CROP_DIR_NAME,)
    assert (root / CROP_DIR_NAME / "img_002.png").is_file()
    assert (root / CROP_DIR_NAME / "img_002.yaml").is_file()
    assert not (root / "img_002.png").exists()
    assert not (root / KEEP_DIR_NAME).exists()
    assert not (root / REJECT_DIR_NAME).exists()


def test_reject_moves_to_reject_dir_not_trash(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(root, [Decision("img_003.png", REJECT)])

    assert result.destinations_touched == (REJECT_DIR_NAME,)
    assert (root / REJECT_DIR_NAME / "img_003.png").is_file()
    assert (root / REJECT_DIR_NAME / "img_003.txt").is_file()
    assert not (root / "img_003.png").exists()
    assert not (root / "img_003.txt").exists()
    assert not (root / KEEP_DIR_NAME).exists()
    assert not (root / CROP_DIR_NAME).exists()


def test_all_three_actions_touch_their_own_dirs(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(
        root,
        [
            Decision("img_001.png", KEEP),
            Decision("img_002.png", CROP),
            Decision("img_003.png", REJECT),
        ],
    )

    assert result.decisions_applied == 3
    assert result.destinations_touched == (
        CROP_DIR_NAME,
        REJECT_DIR_NAME,
        KEEP_DIR_NAME,
    )


# --- decision log ----------------------------------------------------------


def test_decisions_jsonl_appends_one_relative_record_per_decision(
    tmp_path: Path,
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    apply_decisions(
        root,
        [
            Decision("img_001.png", KEEP),
            Decision("img_002.png", CROP, note="needs crop"),
        ],
    )

    records = _decision_lines(root)
    assert len(records) == 2

    keep_record, crop_record = records
    assert keep_record["timestamp"].endswith("Z")
    assert keep_record["action"] == "keep"
    assert keep_record["source"] == "img_001.png"
    assert keep_record["destination"] == f"{KEEP_DIR_NAME}/img_001.png"
    assert keep_record["companions"] == [f"{KEEP_DIR_NAME}/img_001.yaml"]
    assert "note" not in keep_record

    assert crop_record["action"] == "crop"
    assert crop_record["source"] == "img_002.png"
    assert crop_record["destination"] == f"{CROP_DIR_NAME}/img_002.png"
    assert crop_record["companions"] == [f"{CROP_DIR_NAME}/img_002.yaml"]
    assert crop_record["note"] == "needs crop"


# --- manifest step update --------------------------------------------------


def test_manifest_review_select_step_updated_without_finish(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    assert _review_select_step(root)["started_at"] is None
    assert _review_select_step(root)["images_processed"] is None

    apply_decisions(
        root,
        [Decision("img_001.png", KEEP), Decision("img_004.png", REJECT)],
    )

    step = _review_select_step(root)
    assert step["started_at"].endswith("Z")
    assert step["images_processed"] == 2
    assert step["finished_at"] is None


def test_finish_sets_finished_at_and_creates_no_zip(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(root, [Decision("img_001.png", KEEP)], finish=True)

    assert result.finished is True
    step = _review_select_step(root)
    assert step["started_at"].endswith("Z")
    assert step["images_processed"] == 1
    assert step["finished_at"].endswith("Z")
    assert list(root.rglob("*.zip")) == []


def test_finish_with_no_decisions_is_a_noop(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(root, [], finish=True)

    assert result.decisions_applied == 0
    assert result.finished is False
    step = _review_select_step(root)
    assert step["started_at"] is None
    assert step["images_processed"] is None
    assert step["finished_at"] is None


# --- refusal and safety ----------------------------------------------------


def test_apply_refuses_without_prior_intake(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    with pytest.raises(FileNotFoundError, match="intake"):
        apply_decisions(root, [Decision("img_001.png", KEEP)])

    assert not (root / ".pickkit").exists()
    assert not (root / KEEP_DIR_NAME).exists()


def test_apply_refuses_missing_or_non_directory_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        apply_decisions(tmp_path / "missing", [Decision("img_001.png", KEEP)])

    file_path = tmp_path / "not_a_dir.png"
    file_path.write_bytes(b"x")
    with pytest.raises(NotADirectoryError, match="not a directory"):
        apply_decisions(file_path, [Decision("img_001.png", KEEP)])


def test_unknown_action_refused_at_decision_construction() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        Decision("img_001.png", "archive")

    assert ACTIONS == (KEEP, CROP, REJECT)


def test_missing_source_refuses_before_any_move_or_dir(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    with pytest.raises(FileNotFoundError, match="source not found"):
        apply_decisions(root, [Decision("missing.png", KEEP)])

    assert not (root / KEEP_DIR_NAME).exists()
    assert not (root / CROP_DIR_NAME).exists()
    assert not (root / REJECT_DIR_NAME).exists()
    assert (root / "img_001.png").is_file()
    assert not (root / ".pickkit" / "decisions.jsonl").exists()
    step = _review_select_step(root)
    assert step["started_at"] is None
    assert step["images_processed"] is None


def test_existing_destination_refuses_before_moving(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    selected = root / KEEP_DIR_NAME
    selected.mkdir()
    (selected / "img_001.png").write_bytes(b"already here")

    with pytest.raises(FileExistsError, match="destination already exists"):
        apply_decisions(root, [Decision("img_001.png", KEEP)])

    # The pair is still intact at the source and no decision was logged.
    assert (root / "img_001.png").is_file()
    assert (root / "img_001.yaml").is_file()
    assert (selected / "img_001.png").read_bytes() == b"already here"
    assert not (selected / "img_001.yaml").exists()
    assert not (root / ".pickkit" / "decisions.jsonl").exists()


def test_does_not_create_dest_dirs_until_needed(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    result = apply_decisions(root, [])

    assert result.decisions_applied == 0
    assert not (root / KEEP_DIR_NAME).exists()
    assert not (root / CROP_DIR_NAME).exists()
    assert not (root / REJECT_DIR_NAME).exists()

    apply_decisions(root, [Decision("img_001.png", KEEP)])
    assert (root / KEEP_DIR_NAME).is_dir()
    assert not (root / CROP_DIR_NAME).exists()
    assert not (root / REJECT_DIR_NAME).exists()


def test_never_mutates_committed_sandbox(tmp_path: Path) -> None:
    before = _snapshot(BATCH_A)

    root = stage_batch_a(tmp_path)
    intake_init(root)
    apply_decisions(
        root,
        [
            Decision("img_001.png", KEEP),
            Decision("img_002.png", CROP),
            Decision("img_003.png", REJECT),
        ],
    )

    assert _snapshot(BATCH_A) == before


# --- audit ----------------------------------------------------------------


def test_audit_jsonl_and_caller_hook_receive_events(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    hook = RecordingHook()

    apply_decisions(root, [Decision("img_001.png", KEEP)], hook=hook)

    audit_lines = [
        json.loads(line)
        for line in (root / ".pickkit" / "audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    # intake baseline plus the review_select run (move + review_select events).
    operations = [event["operation"] for event in audit_lines]
    assert operations[0] == "intake_init"
    assert "move" in operations[1:]
    assert "review_select" in operations[1:]
    assert all(event["ok"] for event in audit_lines[1:])

    assert [event.operation for event in hook.events] == ["move", "review_select"]
    review_event = hook.events[-1]
    assert review_event.ok is True
    assert review_event.reason == "action=keep"


# --- load_decisions --------------------------------------------------------


def test_load_decisions_reads_json_array(tmp_path: Path) -> None:
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            [
                {"source": "img_001.png", "action": "keep"},
                {"source": "img_002.png", "action": "crop", "note": "tight"},
            ]
        ),
        encoding="utf-8",
    )

    decisions = load_decisions(path)

    assert decisions == [
        Decision("img_001.png", "keep"),
        Decision("img_002.png", "crop", note="tight"),
    ]


def test_load_decisions_reads_jsonl_and_skips_blanks(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    path.write_text(
        '{"source": "img_001.png", "action": "keep"}\n\n'
        '{"source": "img_003.png", "action": "reject"}\n',
        encoding="utf-8",
    )

    decisions = load_decisions(path)

    assert [d.source for d in decisions] == ["img_001.png", "img_003.png"]
    assert [d.action for d in decisions] == ["keep", "reject"]


def test_load_decisions_refuses_malformed_records(tmp_path: Path) -> None:
    missing_keys = tmp_path / "missing.json"
    missing_keys.write_text('[{"source": "img_001.png"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="source"):
        load_decisions(missing_keys)

    not_an_array = tmp_path / "object.json"
    not_an_array.write_text('{"source": "img_001.png"}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_decisions(not_an_array)


# --- CLI -------------------------------------------------------------------


def test_cli_decisions_file_applies_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    decisions_file = tmp_path / "decisions.jsonl"
    decisions_file.write_text(
        json.dumps({"source": "img_001.png", "action": "keep"}) + "\n",
        encoding="utf-8",
    )

    code = main([str(root), "--decisions", str(decisions_file)])

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["decisions_applied"] == 1
    assert summary["destinations_touched"] == [KEEP_DIR_NAME]
    assert summary["finished"] is False
    assert (root / KEEP_DIR_NAME / "img_001.png").is_file()


def test_cli_repeated_flags_and_finish(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    code = main([str(root), "--reject", "img_003.png", "--finish"])

    assert code == 0
    assert (root / REJECT_DIR_NAME / "img_003.png").is_file()
    assert _review_select_step(root)["images_processed"] == 1
    assert _review_select_step(root)["finished_at"].endswith("Z")
