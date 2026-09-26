"""Tests for lib_safety against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated.
"""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest

import lib_safety
from lib_safety import (
    AuditEvent,
    JsonlAuditHook,
    find_companions,
    move_with_companions,
    require_new_file,
    trash,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_A = REPO_ROOT / "sandbox" / "batch_a"

# ``lib_safety.trash`` the attribute is the public function (re-exported in
# __init__), so reach the submodule through importlib for monkeypatching.
TRASH_MODULE = importlib.import_module("lib_safety.trash")


class RecordingHook:
    """Collects AuditEvents for assertions."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def stage_fixture(
    tmp_path: Path,
    stem: str,
    *,
    extra: dict[str, str] | None = None,
) -> Path:
    """Copy one image + its sidecars from sandbox/batch_a into tmp_path/src."""
    src = tmp_path / "src"
    src.mkdir()
    for path in sorted(BATCH_A.glob(f"{stem}.*")):
        shutil.copy2(path, src / path.name)
    for name, text in (extra or {}).items():
        (src / name).write_text(text, encoding="utf-8")
    return src


# --- move with companions -------------------------------------------------


def test_move_image_and_companions_together(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_004")
    dst = tmp_path / "dst"
    dst.mkdir()

    result = move_with_companions(src / "img_004.png", dst)

    assert result.image == dst / "img_004.png"
    assert set(result.companions) == {dst / "img_004.txt", dst / "img_004.yaml"}
    for name in ("img_004.png", "img_004.yaml", "img_004.txt"):
        assert (dst / name).is_file()
        assert not (src / name).exists()


def test_move_moves_caption_sidecar_too(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_003", extra={"img_003.caption": "caption: synthetic"})
    dst = tmp_path / "dst"
    dst.mkdir()

    move_with_companions(src / "img_003.png", dst)

    assert (dst / "img_003.png").is_file()
    assert (dst / "img_003.txt").is_file()
    assert (dst / "img_003.caption").is_file()
    assert not (src / "img_003.caption").exists()


def test_move_to_file_path_renames_companions_to_match(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_002")
    dst = tmp_path / "dst"
    dst.mkdir()

    result = move_with_companions(src / "img_002.png", dst / "renamed.png")

    assert result.image == dst / "renamed.png"
    assert result.companions == (dst / "renamed.yaml",)
    assert (dst / "renamed.png").is_file()
    assert (dst / "renamed.yaml").is_file()
    assert not (src / "img_002.png").exists()
    assert not (src / "img_002.yaml").exists()


def test_move_with_custom_suffixes_only_moves_those_sidecars(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_004")
    dst = tmp_path / "dst"
    dst.mkdir()

    move_with_companions(src / "img_004.png", dst, suffixes=(".txt",))

    assert (dst / "img_004.png").is_file()
    assert (dst / "img_004.txt").is_file()
    assert (src / "img_004.yaml").is_file()  # stayed behind


def test_move_refuses_overwrite_when_destination_exists(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_001")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "img_001.png").write_bytes(b"already here")

    with pytest.raises(FileExistsError, match="destination already exists"):
        move_with_companions(src / "img_001.png", dst)

    # Nothing moved: the pair is still intact at the source.
    assert (src / "img_001.png").is_file()
    assert (src / "img_001.yaml").is_file()
    assert (dst / "img_001.png").read_bytes() == b"already here"
    assert not (dst / "img_001.yaml").exists()


def test_move_refuses_when_a_companion_destination_exists(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_004")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "img_004.txt").write_text("occupied", encoding="utf-8")

    with pytest.raises(FileExistsError):
        move_with_companions(src / "img_004.png", dst)

    assert (src / "img_004.png").is_file()
    assert (src / "img_004.yaml").is_file()
    assert (src / "img_004.txt").is_file()
    assert not (dst / "img_004.png").exists()
    assert not (dst / "img_004.yaml").exists()


# --- trash deletes --------------------------------------------------------


def test_trash_sends_single_path_to_trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = stage_fixture(tmp_path, "img_001")
    trashed: list[Path] = []

    def fake_send2trash(path: str) -> None:
        trashed.append(Path(path))
        Path(path).unlink()

    monkeypatch.setattr(TRASH_MODULE, "send2trash", fake_send2trash)

    result = trash(src / "img_001.png")

    assert result == (src / "img_001.png",)
    assert trashed == [src / "img_001.png"]
    assert not (src / "img_001.png").exists()
    assert (src / "img_001.yaml").is_file()  # companions untouched by default


def test_trash_with_companions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = stage_fixture(tmp_path, "img_004")
    trashed: list[Path] = []

    def fake_send2trash(path: str) -> None:
        trashed.append(Path(path))
        Path(path).unlink()

    monkeypatch.setattr(TRASH_MODULE, "send2trash", fake_send2trash)

    result = trash(src / "img_004.png", companions=True)

    expected = {src / "img_004.png", src / "img_004.yaml", src / "img_004.txt"}
    assert set(result) == expected
    assert set(trashed) == expected
    assert not any(path.exists() for path in expected)


def test_trash_missing_path_raises_before_any_trash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = stage_fixture(tmp_path, "img_001")
    called: list[str] = []
    monkeypatch.setattr(TRASH_MODULE, "send2trash", lambda path: called.append(path))

    with pytest.raises(FileNotFoundError):
        trash(src / "missing.png")

    assert called == []


# --- no-overwrite / no-in-place-write guards ------------------------------


def test_require_new_file_rejects_existing_path(tmp_path: Path) -> None:
    existing = tmp_path / "exists.png"
    existing.write_bytes(b"original pixels")

    with pytest.raises(FileExistsError, match="already exists"):
        require_new_file(existing)

    assert existing.read_bytes() == b"original pixels"


def test_require_new_file_allows_new_path_without_creating_it(tmp_path: Path) -> None:
    new_file = tmp_path / "sub" / "new_crop.png"

    returned = require_new_file(new_file)

    assert returned == new_file
    assert not new_file.exists()  # guard checks only; it never creates the file


def test_require_new_file_blocks_in_place_save(tmp_path: Path) -> None:
    original = tmp_path / "original.png"
    original.write_bytes(b"keep me")

    with pytest.raises(FileExistsError):
        require_new_file(original)  # same path = in-place write attempt


# --- companion discovery --------------------------------------------------


def test_find_companions_returns_sidecars_only(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_004")
    (src / "img_005.yaml").write_text("unrelated stem", encoding="utf-8")

    companions = find_companions(src / "img_004.png")

    assert [p.name for p in companions] == ["img_004.txt", "img_004.yaml"]


# --- audit hooks ----------------------------------------------------------


def test_audit_hook_receives_move_refuse_and_trash_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = stage_fixture(tmp_path, "img_004")
    dst = tmp_path / "dst"
    dst.mkdir()
    hook = RecordingHook()

    move_with_companions(src / "img_004.png", dst, hook=hook)

    occupied = tmp_path / "occupied.png"
    occupied.write_bytes(b"x")
    with pytest.raises(FileExistsError):
        require_new_file(occupied, hook=hook)

    monkeypatch.setattr(TRASH_MODULE, "send2trash", lambda path: Path(path).unlink())
    trash(dst / "img_004.png", companions=True, hook=hook)

    assert [event.operation for event in hook.events] == ["move", "refuse_write", "trash"]

    move_event, refuse_event, trash_event = hook.events
    assert move_event.ok is True
    assert move_event.source == str(src / "img_004.png")
    assert move_event.destination == str(dst / "img_004.png")
    assert set(move_event.companions) == {str(src / "img_004.yaml"), str(src / "img_004.txt")}

    assert refuse_event.ok is False
    assert refuse_event.source == str(occupied)

    assert trash_event.ok is True
    assert trash_event.source == str(dst / "img_004.png")
    assert set(trash_event.companions) == {str(dst / "img_004.yaml"), str(dst / "img_004.txt")}


def test_move_refusal_emits_audit_event(tmp_path: Path) -> None:
    src = stage_fixture(tmp_path, "img_001")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "img_001.png").write_bytes(b"taken")
    hook = RecordingHook()

    with pytest.raises(FileExistsError):
        move_with_companions(src / "img_001.png", dst, hook=hook)

    assert hook.events
    event = hook.events[-1]
    assert event.operation == "move"
    assert event.ok is False
    assert "already exists" in (event.reason or "")


def test_jsonl_audit_hook_appends_structured_lines(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "audit.jsonl"
    hook = JsonlAuditHook(log)

    hook.record(AuditEvent(operation="move", source="a.png", destination="b.png", ok=True))
    hook.record(AuditEvent(operation="refuse_write", source="a.png", ok=False, reason="exists"))

    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["operation"] == "move"
    assert first["ok"] is True
    second = json.loads(lines[1])
    assert second["operation"] == "refuse_write"
    assert second["ok"] is False
    assert second["reason"] == "exists"
