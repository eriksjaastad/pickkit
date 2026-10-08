"""Tests for the multi-crop interactive web UI (headless Flask client).

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path`` and intake'd with ``intake_init`` before the UI is exercised; the
committed sandbox is never mutated. No real browser is required.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from intake_init import intake_init
from multi_crop import (
    CROPPED_DIR_NAME,
    CROP_QUEUE_DIR_NAME,
    CROPS_LOG_NAME,
    CropSpec,
    crop_batch,
    main,
)
from multi_crop import ui

from conftest import BATCH_A, jsonl_lines, snapshot, stage_batch_a


def stage_crop_queue(tmp_path: Path) -> Path:
    """Stage + intake batch_a and put two sandbox pngs into ``__crop/``."""
    root = stage_batch_a(tmp_path)
    intake_init(root)
    crop_dir = root / CROP_QUEUE_DIR_NAME
    crop_dir.mkdir()
    shutil.copy(BATCH_A / "img_001.png", crop_dir / "img_001.png")
    shutil.copy(BATCH_A / "img_002.png", crop_dir / "img_002.png")
    return root


# --- list_pending_images ----------------------------------------------------


def test_list_pending_images_finds_queue_sorted(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)

    pending = ui.list_pending_images(root)

    assert [p.name for p in pending] == ["img_001.png", "img_002.png"]
    assert all(p.is_absolute() for p in pending)
    assert all(p.suffix == ".png" for p in pending)


def test_list_pending_images_excludes_already_cropped(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)

    crop_batch(root, [CropSpec(f"{CROP_QUEUE_DIR_NAME}/img_001.png", (0, 0, 16, 16))])

    assert (root / CROPPED_DIR_NAME / "img_001.png").is_file()
    assert (root / CROP_QUEUE_DIR_NAME / "img_001.png").is_file()
    pending = ui.list_pending_images(root)
    assert [p.name for p in pending] == ["img_002.png"]


def test_list_pending_images_skips_hidden_parts_and_non_images(
    tmp_path: Path,
) -> None:
    root = stage_crop_queue(tmp_path)
    crop_dir = root / CROP_QUEUE_DIR_NAME
    hidden_dir = crop_dir / ".hidden"
    hidden_dir.mkdir()
    shutil.copy(BATCH_A / "img_003.png", hidden_dir / "img_003.png")
    (crop_dir / "img_001.yaml").write_text("sidecar", encoding="utf-8")
    (crop_dir / ".hidden.png").write_bytes(b"hidden")

    pending = ui.list_pending_images(root)

    assert [p.name for p in pending] == ["img_001.png", "img_002.png"]
    assert all(
        not any(part.startswith(".") for part in p.relative_to(root).parts)
        for p in pending
    )


def test_list_pending_images_missing_crop_dir_is_empty(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    assert ui.list_pending_images(root) == []


def test_list_pending_images_refuses_non_intaked_batch(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    with pytest.raises(FileNotFoundError, match="intake"):
        ui.list_pending_images(root)


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


def test_create_app_seeds_session_cropped(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)

    client = ui.create_app(root, session_cropped=7).test_client()

    payload = client.get("/api/status").get_json()
    assert payload["cropped_this_session"] == 7


def test_flask_index_status_crop_and_image_route(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()
    original = (root / CROP_QUEUE_DIR_NAME / "img_001.png").read_bytes()

    page = client.get("/")
    assert page.status_code == 200
    assert b"img_001.png" in page.data

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.get_json() == {
        "remaining": 2,
        "cropped_this_session": 0,
        "current": f"{CROP_QUEUE_DIR_NAME}/img_001.png",
        "natural_size": {"width": 64, "height": 48},
    }

    crop = client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png", "box": [0, 0, 32, 48]},
    )
    assert crop.status_code == 200
    assert crop.get_json() == {
        "remaining": 1,
        "cropped_this_session": 1,
        "current": f"{CROP_QUEUE_DIR_NAME}/img_002.png",
        "natural_size": {"width": 64, "height": 48},
    }

    assert (root / CROPPED_DIR_NAME / "img_001.png").is_file()
    assert (root / CROP_QUEUE_DIR_NAME / "img_001.png").is_file()

    records = jsonl_lines(root / ".pickkit" / CROPS_LOG_NAME)
    assert len(records) == 1
    assert records[0]["source"] == f"{CROP_QUEUE_DIR_NAME}/img_001.png"
    assert records[0]["destination"] == f"{CROPPED_DIR_NAME}/img_001.png"
    assert records[0]["box"] == [0, 0, 32, 48]

    served = client.get(f"/image/{CROP_QUEUE_DIR_NAME}/img_001.png")
    assert served.status_code == 200
    assert served.data == original


def test_flask_crop_all_images_reaches_queue_empty(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()

    for name in ("img_001.png", "img_002.png"):
        resp = client.post(
            "/api/crop",
            json={"source": f"{CROP_QUEUE_DIR_NAME}/{name}", "box": [0, 0, 16, 16]},
        )
        assert resp.status_code == 200

    final = client.get("/api/status").get_json()
    assert final == {
        "remaining": 0,
        "cropped_this_session": 2,
        "current": None,
        "natural_size": None,
    }

    page = client.get("/")
    assert page.status_code == 200
    assert b"Queue empty" in page.data


def test_flask_crop_duplicate_destination_surfaces_409(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()

    first = client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png", "box": [0, 0, 16, 16]},
    )
    assert first.status_code == 200

    again = client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png", "box": [0, 0, 32, 48]},
    )
    assert again.status_code == 409
    assert "already exists" in again.get_json()["error"]

    status = client.get("/api/status").get_json()
    assert status["cropped_this_session"] == 1
    assert status["remaining"] == 1


def test_flask_skip_advances_and_is_session_only(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()

    skipped = client.post(
        "/api/skip", json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png"}
    )
    assert skipped.status_code == 200
    assert skipped.get_json() == {
        "remaining": 1,
        "cropped_this_session": 0,
        "current": f"{CROP_QUEUE_DIR_NAME}/img_002.png",
        "natural_size": {"width": 64, "height": 48},
    }

    # Skip is in-memory only: both sources remain pending on disk.
    assert len(ui.list_pending_images(root)) == 2
    assert (root / CROP_QUEUE_DIR_NAME / "img_001.png").is_file()
    assert (root / CROP_QUEUE_DIR_NAME / "img_002.png").is_file()


def test_flask_crop_refuses_bad_input_and_escapes(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()

    bad_box = client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png", "box": [0, 0, 32]},
    )
    assert bad_box.status_code == 400

    non_int_box = client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png", "box": [0, 0, 32.5, 48]},
    )
    assert non_int_box.status_code == 400

    escape = client.post(
        "/api/crop",
        json={"source": "../img_001.png", "box": [0, 0, 32, 48]},
    )
    assert escape.status_code == 400

    missing = client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/missing.png", "box": [0, 0, 32, 48]},
    )
    assert missing.status_code == 404

    not_json = client.post("/api/crop", data=b"not json")
    assert not_json.status_code == 400


def test_image_route_refuses_escapes_and_missing_files(tmp_path: Path) -> None:
    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()

    ok = client.get(f"/image/{CROP_QUEUE_DIR_NAME}/img_002.png")
    assert ok.status_code == 200

    assert client.get("/image/../img_001.png").status_code == 404
    assert client.get(f"/image/{CROP_QUEUE_DIR_NAME}/missing.png").status_code == 404


def test_ui_never_mutates_committed_sandbox(tmp_path: Path) -> None:
    before = snapshot(BATCH_A)

    root = stage_crop_queue(tmp_path)
    client = ui.create_app(root).test_client()
    client.post(
        "/api/crop",
        json={"source": f"{CROP_QUEUE_DIR_NAME}/img_001.png", "box": [0, 0, 16, 16]},
    )

    assert snapshot(BATCH_A) == before


# --- CLI wiring -------------------------------------------------------------


def test_cli_refuses_ui_combined_with_crop_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_crop_queue(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--ui", "--crops", "crops.jsonl"])
    assert exc.value.code == 2
    assert "--ui cannot be combined" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--ui", "--source", "img_001.png", "--box", "0,0,16,16"])
    assert exc.value.code == 2
    assert "--ui cannot be combined" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--ui", "--finish"])
    assert exc.value.code == 2
    assert "--ui cannot be combined" in capsys.readouterr().err


def test_cli_refuses_host_port_without_ui(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_crop_queue(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--host", "0.0.0.0"])
    assert exc.value.code == 2
    assert "--host and --port" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--port", "9999"])
    assert exc.value.code == 2
    assert "--host and --port" in capsys.readouterr().err
