"""Tests for the review-select interactive web UI (headless Flask client).

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path`` and intake'd with ``intake_init`` before the UI is exercised; the
committed sandbox is never mutated. No real browser is required.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from intake_init import intake_init
from review_select import (
    CROP,
    CROP_DIR_NAME,
    KEEP,
    KEEP_DIR_NAME,
    REJECT,
    REJECT_DIR_NAME,
    Decision,
    apply_decisions,
    main,
)
from review_select import ui

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_A = REPO_ROOT / "sandbox" / "batch_a"


def stage_batch_a(tmp_path: Path) -> Path:
    """Copy sandbox/batch_a into tmp_path and return the staged root."""
    root = tmp_path / "batch_a"
    shutil.copytree(BATCH_A, root)
    return root


def _snapshot(directory: Path) -> dict[str, bytes]:
    """Relative path -> bytes for every file under *directory*."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# --- list_pending_images ----------------------------------------------------


def test_list_pending_images_flat_batch_sorted(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    pending = ui.list_pending_images(root)

    assert [p.name for p in pending] == [
        "img_001.png",
        "img_002.png",
        "img_003.png",
        "img_004.png",
    ]
    assert all(p.is_absolute() for p in pending)
    assert all(p.suffix == ".png" for p in pending)


def test_list_pending_images_skips_hidden_and_stage_dirs(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    (root / ".hidden.png").write_bytes(b"hidden")
    for dir_name in (KEEP_DIR_NAME, CROP_DIR_NAME, REJECT_DIR_NAME):
        (root / dir_name).mkdir()
        (root / dir_name / "staged.png").write_bytes(b"x")

    pending = ui.list_pending_images(root)

    assert [p.name for p in pending] == [
        "img_001.png",
        "img_002.png",
        "img_003.png",
        "img_004.png",
    ]
    assert all(not any(part.startswith(".") for part in p.parts) for p in pending)
    assert all(not any(part in ui.STAGE_DIR_NAMES for part in p.parts) for p in pending)


def test_list_pending_images_excludes_decided_images(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    apply_decisions(root, [Decision("img_001.png", KEEP)])

    pending = ui.list_pending_images(root)
    assert [p.name for p in pending] == ["img_002.png", "img_003.png", "img_004.png"]
    assert all(KEEP_DIR_NAME not in p.parts for p in pending)
    assert (root / KEEP_DIR_NAME / "img_001.png").is_file()


def test_list_pending_images_refuses_non_intaked_batch(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    with pytest.raises(FileNotFoundError, match="intake"):
        ui.list_pending_images(root)


# --- map_ui_action ----------------------------------------------------------


def test_map_ui_action_maps_keys_numbers_and_synonyms() -> None:
    assert ui.map_ui_action("k") == KEEP
    assert ui.map_ui_action("K") == KEEP
    assert ui.map_ui_action("1") == KEEP
    assert ui.map_ui_action("keep") == KEEP
    assert ui.map_ui_action("c") == CROP
    assert ui.map_ui_action("C") == CROP
    assert ui.map_ui_action("2") == CROP
    assert ui.map_ui_action("crop") == CROP
    assert ui.map_ui_action("r") == REJECT
    assert ui.map_ui_action("R") == REJECT
    assert ui.map_ui_action("3") == REJECT
    assert ui.map_ui_action("reject") == REJECT


def test_map_ui_action_refuses_unknown_tokens() -> None:
    for token in ("x", "archive", "4", ""):
        with pytest.raises(ValueError, match="unknown UI action"):
            ui.map_ui_action(token)


def test_ui_action_maps_to_decision_actions() -> None:
    assert Decision("img_001.png", ui.map_ui_action("k")).action == KEEP
    assert Decision("img_001.png", ui.map_ui_action("2")).action == CROP
    assert Decision("img_001.png", ui.map_ui_action("r")).action == REJECT


# --- safe_image_path --------------------------------------------------------


def test_safe_image_path_resolves_relative_and_in_root_absolute(
    tmp_path: Path,
) -> None:
    root = tmp_path / "batch"
    root.mkdir()
    image = root / "img.png"
    image.write_bytes(b"x")

    assert ui.safe_image_path(root, "img.png") == image.resolve()
    assert ui.safe_image_path(root, str(image)) == image.resolve()


def test_safe_image_path_refuses_dotdot_and_absolute_escapes(tmp_path: Path) -> None:
    root = tmp_path / "batch"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")

    with pytest.raises(ValueError, match="escapes batch root"):
        ui.safe_image_path(root, "../outside.png")
    with pytest.raises(ValueError, match="escapes batch root"):
        ui.safe_image_path(root, str(outside))


# --- Flask app --------------------------------------------------------------


def test_create_app_refuses_non_intaked_batch(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    with pytest.raises(FileNotFoundError, match="intake"):
        ui.create_app(root)


def test_create_app_seeds_session_decided(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    client = ui.create_app(root, session_decided=7).test_client()

    payload = client.get("/api/status").get_json()
    assert payload["decided_this_session"] == 7


def test_flask_index_status_and_decide_keep_moves_file(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    client = ui.create_app(root).test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b"img_001.png" in page.data

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.get_json() == {
        "remaining": 4,
        "decided_this_session": 0,
        "current": "img_001.png",
    }

    decide = client.post(
        "/api/decide", json={"source": "img_001.png", "action": "keep"}
    )
    assert decide.status_code == 200
    assert decide.get_json() == {
        "remaining": 3,
        "decided_this_session": 1,
        "current": "img_002.png",
    }

    assert (root / KEEP_DIR_NAME / "img_001.png").is_file()
    assert (root / KEEP_DIR_NAME / "img_001.yaml").is_file()
    assert not (root / "img_001.png").exists()
    assert not (root / "img_001.yaml").exists()

    lines = (root / ".pickkit" / "decisions.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "keep"
    assert record["source"] == "img_001.png"
    assert record["destination"] == f"{KEEP_DIR_NAME}/img_001.png"


def test_flask_decide_all_images_reaches_queue_empty(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    client = ui.create_app(root).test_client()

    for index, action in enumerate(["keep", "crop", "reject", "keep"], start=1):
        resp = client.post(
            "/api/decide",
            json={"source": f"img_00{index}.png", "action": action},
        )
        assert resp.status_code == 200

    final = client.get("/api/status").get_json()
    assert final == {"remaining": 0, "decided_this_session": 4, "current": None}

    page = client.get("/")
    assert page.status_code == 200
    assert b"Queue empty" in page.data


def test_flask_decide_refuses_bad_input(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    client = ui.create_app(root).test_client()

    bad_action = client.post(
        "/api/decide", json={"source": "img_001.png", "action": "archive"}
    )
    assert bad_action.status_code == 400

    escape = client.post(
        "/api/decide", json={"source": "../img_001.png", "action": "keep"}
    )
    assert escape.status_code == 400

    missing = client.post(
        "/api/decide", json={"source": "missing.png", "action": "keep"}
    )
    assert missing.status_code == 404


def test_image_route_serves_original_bytes_and_refuses_escapes(
    tmp_path: Path,
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    client = ui.create_app(root).test_client()
    original = (root / "img_001.png").read_bytes()

    ok = client.get("/image/img_001.png")
    assert ok.status_code == 200
    assert ok.data == original

    assert client.get("/image/../img_001.png").status_code == 404
    assert client.get("/image/missing.png").status_code == 404


def test_ui_never_mutates_committed_sandbox(tmp_path: Path) -> None:
    before = _snapshot(BATCH_A)

    root = stage_batch_a(tmp_path)
    intake_init(root)
    client = ui.create_app(root).test_client()
    client.post("/api/decide", json={"source": "img_001.png", "action": "keep"})

    assert _snapshot(BATCH_A) == before


# --- CLI wiring -------------------------------------------------------------


def test_cli_refuses_ui_combined_with_decision_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--ui", "--keep", "img_001.png"])

    assert exc.value.code == 2
    assert "--ui cannot be combined" in capsys.readouterr().err


def test_cli_refuses_host_port_without_ui(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--host", "0.0.0.0"])

    assert exc.value.code == 2
    assert "--host and --port" in capsys.readouterr().err
