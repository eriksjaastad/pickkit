"""Tests for the finish-package interactive web wizard (headless Flask client).

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path`` and intake'd with ``intake_init`` before the UI is exercised; the
committed sandbox is never mutated. No real browser is required.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from finish_package import (
    DEFAULT_ZIP_NAME,
    EXCLUDED_BUCKETS,
    SELECTED_DIR_NAME,
    main,
)
from finish_package import ui
from intake_init import intake_init

from conftest import BATCH_A, snapshot, stage_batch_a


def stage_selected_batch(tmp_path: Path) -> Path:
    """Stage + intake batch_a and put three eligible files into ``__selected/``."""
    root = stage_batch_a(tmp_path)
    intake_init(root)
    selected = root / SELECTED_DIR_NAME
    selected.mkdir()
    shutil.copy(BATCH_A / "img_001.png", selected / "img_001.png")
    shutil.copy(BATCH_A / "img_001.yaml", selected / "img_001.yaml")
    shutil.copy(BATCH_A / "img_002.png", selected / "img_002.png")
    return root


def _manifest(root: Path) -> dict[str, object]:
    return json.loads((root / ".pickkit" / "project.json").read_text(encoding="utf-8"))


# --- helpers -----------------------------------------------------------------


def test_planned_zip_path_default_and_override(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)

    assert ui.planned_zip_path(root) == root / DEFAULT_ZIP_NAME
    assert ui.planned_zip_path(root, "out/custom.zip") == (
        root / "out" / "custom.zip"
    ).resolve()


def test_planned_zip_path_refuses_non_intaked_batch(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    with pytest.raises(FileNotFoundError, match="intake"):
        ui.planned_zip_path(root)


def test_content_roots_for_ui_default_and_override(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)

    assert ui.content_roots_for_ui(root) == [root / SELECTED_DIR_NAME]
    assert ui.content_roots_for_ui(root, SELECTED_DIR_NAME) == [
        (root / SELECTED_DIR_NAME).resolve()
    ]

    with pytest.raises(ValueError, match="outside batch root"):
        ui.content_roots_for_ui(root, tmp_path)
    with pytest.raises(FileNotFoundError, match="content"):
        ui.content_roots_for_ui(root, "__cropped")


def test_sample_paths_lists_relative_posix_paths(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)

    samples = ui.sample_paths(root)

    assert samples == {
        "eligible": [
            f"{SELECTED_DIR_NAME}/img_001.png",
            f"{SELECTED_DIR_NAME}/img_001.yaml",
            f"{SELECTED_DIR_NAME}/img_002.png",
        ],
        "excluded": [],
    }


# --- Flask app ---------------------------------------------------------------


def test_create_app_refuses_non_intaked_batch(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    with pytest.raises(FileNotFoundError, match="intake"):
        ui.create_app(root)


def test_flask_index_shows_eligible_count_and_planned_zip(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    page = client.get("/")

    assert page.status_code == 200
    assert b"pickkit finish" in page.data
    assert b'id="eligible-count">3<' in page.data
    assert DEFAULT_ZIP_NAME.encode() in page.data


def test_flask_status_dry_run_shape_and_no_writes(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    status = client.get("/api/status")

    assert status.status_code == 200
    payload = status.get_json()
    assert payload["batch_name"] == "batch_a"
    assert payload["eligible_count"] == 3
    assert payload["by_ext_included"] == {"png": 2, "yaml": 1}
    assert payload["excluded_counts"] == {bucket: 0 for bucket in EXCLUDED_BUCKETS}
    assert payload["incoming_by_ext"] == {"png": 2, "yaml": 1}
    assert payload["planned_zip"] == DEFAULT_ZIP_NAME
    assert payload["content_roots"] == [SELECTED_DIR_NAME]
    assert payload["samples"] == {
        "eligible": [
            f"{SELECTED_DIR_NAME}/img_001.png",
            f"{SELECTED_DIR_NAME}/img_001.yaml",
            f"{SELECTED_DIR_NAME}/img_002.png",
        ],
        "excluded": [],
    }
    assert payload["committed"] is False
    assert payload["finished_at"] is None
    assert payload["zip_exists"] is False

    # Dry-run wrote nothing.
    assert not (root / DEFAULT_ZIP_NAME).exists()
    manifest = _manifest(root)
    assert manifest["finished_at"] is None
    assert manifest["metrics"]["stager"]["eligible_count"] == 0


def test_flask_status_query_overrides(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    status = client.get(
        f"/api/status?content={SELECTED_DIR_NAME}&output=out%2Fcustom.zip"
    )

    assert status.status_code == 200
    payload = status.get_json()
    assert payload["planned_zip"] == "out/custom.zip"
    assert payload["eligible_count"] == 3


def test_flask_refresh_reruns_dry_run_with_overrides(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    refresh = client.post("/api/refresh", json={})
    assert refresh.status_code == 200
    assert refresh.get_json()["eligible_count"] == 3
    assert not (root / DEFAULT_ZIP_NAME).exists()

    overridden = client.post(
        "/api/refresh",
        json={"content": SELECTED_DIR_NAME, "output": "out/custom.zip"},
    )
    assert overridden.status_code == 200
    payload = overridden.get_json()
    assert payload["planned_zip"] == "out/custom.zip"
    assert payload["eligible_count"] == 3
    assert not (root / "out" / "custom.zip").exists()


def test_flask_commit_writes_zip_and_closes_manifest(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    commit = client.post("/api/commit", json={})

    assert commit.status_code == 200
    data = commit.get_json()
    assert data["zip_path"] == DEFAULT_ZIP_NAME
    assert data["finished_at"] is not None and data["finished_at"].endswith("Z")
    assert data["committed"] is True
    assert data["zip_exists"] is True
    assert data["eligible_count"] == 3

    assert (root / DEFAULT_ZIP_NAME).is_file()
    manifest = _manifest(root)
    assert manifest["finished_at"] == data["finished_at"]

    with zipfile.ZipFile(root / DEFAULT_ZIP_NAME) as archive:
        assert archive.namelist() == [
            f"{SELECTED_DIR_NAME}/img_001.png",
            f"{SELECTED_DIR_NAME}/img_001.yaml",
            f"{SELECTED_DIR_NAME}/img_002.png",
        ]

    status = client.get("/api/status").get_json()
    assert status["committed"] is True
    assert status["finished_at"] == data["finished_at"]
    assert status["zip_exists"] is True


def test_flask_recommit_without_force_409_and_with_force_ok(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    first = client.post("/api/commit", json={})
    assert first.status_code == 200
    zip_bytes = (root / DEFAULT_ZIP_NAME).read_bytes()

    again = client.post("/api/commit", json={})
    assert again.status_code == 409
    assert "already exists" in again.get_json()["error"]
    assert (root / DEFAULT_ZIP_NAME).read_bytes() == zip_bytes

    forced = client.post("/api/commit", json={"force": True})
    assert forced.status_code == 200
    assert forced.get_json()["zip_path"] == DEFAULT_ZIP_NAME


def test_flask_commit_with_output_override(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    commit = client.post("/api/commit", json={"output": "out/custom.zip"})

    assert commit.status_code == 200
    data = commit.get_json()
    assert data["zip_path"] == "out/custom.zip"
    assert (root / "out" / "custom.zip").is_file()
    assert not (root / DEFAULT_ZIP_NAME).exists()
    assert _manifest(root)["finished_at"] == data["finished_at"]


def test_flask_commit_refuses_bad_input_and_bad_overrides(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    not_json = client.post("/api/commit", data=b"not json")
    assert not_json.status_code == 400

    bad_force = client.post("/api/commit", json={"force": "yes"})
    assert bad_force.status_code == 400

    missing_content = client.post("/api/commit", json={"content": "__missing"})
    assert missing_content.status_code == 404

    outside_content = client.post("/api/commit", json={"content": str(tmp_path)})
    assert outside_content.status_code == 400


def test_ui_never_mutates_committed_sandbox(tmp_path: Path) -> None:
    before = snapshot(BATCH_A)

    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    client.post("/api/commit", json={})

    assert snapshot(BATCH_A) == before


# --- CLI wiring --------------------------------------------------------------


def test_cli_refuses_ui_combined_with_one_shot_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_selected_batch(tmp_path)
    cases = [
        [str(root), "--ui", "--commit"],
        [str(root), "--ui", "--force"],
        [str(root), "--ui", "--content", "__selected"],
        [str(root), "--ui", "--output", "custom.zip"],
    ]

    for argv in cases:
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 2
        assert "--ui cannot be combined" in capsys.readouterr().err


def test_cli_refuses_host_port_without_ui(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_selected_batch(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--host", "0.0.0.0"])
    assert exc.value.code == 2
    assert "--host and --port" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--port", "9999"])
    assert exc.value.code == 2
    assert "--host and --port" in capsys.readouterr().err


def _break_manifest(root: Path, kind: str) -> Path:
    """Damage ``.pickkit/project.json`` in one of the read-failure ways."""
    manifest = root / ".pickkit" / "project.json"
    if kind == "missing":
        manifest.unlink()  # governance: allow-delete DS001: pytest tmp_path copy of the intake manifest
    elif kind == "unreadable":
        manifest.chmod(0)
    elif kind == "directory":
        manifest.unlink()  # governance: allow-delete DS001: pytest tmp_path copy replaced by a directory
        manifest.mkdir()
    elif kind == "bad_json":
        manifest.write_text("{not json", encoding="utf-8")
    elif kind == "non_object":
        manifest.write_text("[]", encoding="utf-8")
    elif kind == "bad_encoding":
        manifest.write_bytes(b"\xff\xfe{")
    else:
        raise AssertionError(kind)
    return manifest


def _assert_manifest_error_json(
    response, manifest: Path, status: int, message: str
) -> dict[str, object]:
    """Assert a JSON (never HTML) error that names *manifest* and *message*."""
    assert response.is_json, response.data[:200]
    assert response.status_code == status
    lowered = response.data.lower()
    assert b"<html" not in lowered
    assert b"<!doctype" not in lowered
    body = response.get_json()
    assert str(manifest) in body["error"]
    assert message in body["error"]
    return body


# Manifest read failures take two paths through the app: ``/api/status``,
# ``/api/refresh`` and ``GET /`` all go through the app-level error handlers;
# ``POST /api/commit`` has its own except clauses. Each distinct message is
# checked once on ``/api/status``; commit is checked once per status code it
# maps. ``GET /`` reaching the handlers is checked by
# ``test_index_returns_json_for_a_bad_inventory``.


@pytest.mark.parametrize("kind,status,message", [
    ("missing", 404, "missing manifest"),
    ("directory", 400, "path is a directory"),
    ("bad_json", 400, "not valid JSON"),
    ("non_object", 400, "not a JSON object"),
    ("bad_encoding", 400, "UTF-8"),
])
def test_status_reports_a_manifest_read_failure_as_json(
    tmp_path: Path, kind: str, status: int, message: str
) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    manifest = _break_manifest(root, kind)

    response = client.get("/api/status")

    _assert_manifest_error_json(response, manifest, status, message)


def test_status_reports_an_unreadable_manifest_as_json(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    manifest = _break_manifest(root, "unreadable")
    try:
        response = client.get("/api/status")

        _assert_manifest_error_json(response, manifest, 400, "cannot read manifest")
    finally:
        manifest.chmod(0o644)


@pytest.mark.parametrize("kind,status,message", [
    ("missing", 404, "missing manifest"),  # except FileNotFoundError
    ("bad_json", 400, "not valid JSON"),  # except ValueError (ManifestError)
])
def test_commit_reports_a_bad_manifest_as_not_committed(
    tmp_path: Path, kind: str, status: int, message: str
) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    manifest = _break_manifest(root, kind)

    commit = client.post("/api/commit", json={})

    body = _assert_manifest_error_json(commit, manifest, status, message)
    assert body["committed"] is False
    assert not (root / DEFAULT_ZIP_NAME).exists()


def test_load_manifest_names_the_path_for_a_missing_file(tmp_path: Path) -> None:
    from finish_package.finish import ManifestError, load_manifest

    missing = tmp_path / "project.json"
    with pytest.raises(ManifestError, match="cannot read manifest") as exc:
        load_manifest(missing)
    assert str(missing) in str(exc.value)


def test_commit_reports_json_when_the_summary_reread_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()

    def unreadable(*_args: object, **_kwargs: object) -> str | None:
        raise ui.ManifestError("cannot read manifest: injected after commit")

    monkeypatch.setattr(ui, "_read_finished_at", unreadable)
    commit = client.post("/api/commit", json={})
    assert commit.status_code == 500
    assert commit.is_json
    body = commit.get_json()
    assert "committed, but the batch summary could not be re-read" in body["error"]
    assert body["committed"] is True
    assert body["finished_at"]
    assert body["zip_path"] == DEFAULT_ZIP_NAME
    assert _manifest(root)["finished_at"] == body["finished_at"]
    lowered = commit.data.lower()
    assert b"<html" not in lowered


def test_index_returns_json_for_a_bad_inventory(tmp_path: Path) -> None:
    """A bad allowlist must not turn the landing page into an HTML 500."""
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    inventory = root / ".pickkit" / "allowed_ext.json"
    inventory.write_text("{not json", encoding="utf-8")

    page = client.get("/")
    status = client.get("/api/status")

    assert page.is_json
    assert page.status_code == 400
    assert b"<html" not in page.data.lower()
    assert "Expecting property name" in page.get_json()["error"]
    assert status.is_json
    assert status.status_code == 400
    assert status.get_json()["error"] == page.get_json()["error"]


def test_fifo_manifest_returns_json_without_blocking(tmp_path: Path) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    manifest = root / ".pickkit" / "project.json"
    manifest.unlink()  # governance: allow-delete DS001: pytest tmp_path copy replaced by a FIFO
    os.mkfifo(manifest)

    status = client.get("/api/status")

    assert status.is_json
    assert status.status_code == 400
    assert str(manifest) in status.get_json()["error"]
    assert "not a regular file" in status.get_json()["error"]
    assert b"<html" not in status.data.lower()


def test_commit_stays_committed_when_the_finish_log_cannot_be_written(
    tmp_path: Path,
) -> None:
    root = stage_selected_batch(tmp_path)
    client = ui.create_app(root).test_client()
    audit = root / ".pickkit" / "audit.jsonl"
    if audit.exists() or audit.is_symlink():
        audit.unlink()  # governance: allow-delete DS001: pytest tmp_path audit replaced by a broken symlink
    audit.symlink_to(tmp_path / "missing-log-dir" / "audit.jsonl")

    commit = client.post("/api/commit", json={})

    assert commit.status_code == 500
    assert commit.is_json
    body = commit.get_json()
    assert body["committed"] is True
    assert body["finished_at"]
    assert "committed, but the finish log could not be written" in body["error"]
    assert body["zip_path"] == DEFAULT_ZIP_NAME
    assert (root / DEFAULT_ZIP_NAME).is_file()
    assert _manifest(root)["finished_at"] == body["finished_at"]
    assert b"<html" not in commit.data.lower()
