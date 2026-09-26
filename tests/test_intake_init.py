"""Tests for intake_init against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from intake_init import (
    DEFAULT_IMAGE_SUFFIXES,
    ManifestExistsError,
    intake_init,
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


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_intake_writes_manifest_with_expected_keys(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    result = intake_init(root)

    manifest = _read_json(root / ".pickkit" / "project.json")
    assert manifest["schema_version"] == 1
    assert manifest["started_at"].endswith("Z")
    assert manifest["root"] == str(root.resolve())
    assert manifest["image_count"] == 4

    assert result.manifest_path == root / ".pickkit" / "project.json"
    assert result.image_count == 4
    assert result.started_at.endswith("Z")
    assert result.extensions == {"png": 4, "txt": 2, "yaml": 3}


def test_inventory_snapshot_is_allowlist_ready(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    result = intake_init(root)

    inventory = _read_json(root / ".pickkit" / "allowed_ext.json")
    assert inventory["snapshot_at"].endswith("Z")
    assert inventory["source_path"] == str(root.resolve())
    assert inventory["extensions"] == {"png": 4, "txt": 2, "yaml": 3}
    assert inventory["allowedExtensions"] == ["png", "txt", "yaml"]
    # Lowercase and free of leading dots by construction.
    assert all(ext == ext.lower() and not ext.startswith(".") for ext in inventory["extensions"])


def test_audit_baseline_records_intake_event(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    result = intake_init(root)

    lines = result.audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    first = json.loads(lines[0])
    assert first["operation"] == "intake_init"
    assert first["ok"] is True
    assert first["source"] == str(root.resolve())
    assert first["timestamp"].endswith("Z")


def test_second_intake_refuses_without_force(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    manifest_path = root / ".pickkit" / "project.json"
    original = manifest_path.read_text(encoding="utf-8")

    with pytest.raises(ManifestExistsError):
        intake_init(root)
    # ManifestExistsError is a FileExistsError for callers catching OSError.
    with pytest.raises(FileExistsError):
        intake_init(root)

    assert manifest_path.read_text(encoding="utf-8") == original


def test_force_overwrites_existing_manifest_and_appends_audit(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    first = intake_init(root)

    second = intake_init(root, force=True)

    assert second.manifest_path == first.manifest_path
    assert second.image_count == 4
    lines = second.audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["operation"] == "intake_init"
    assert json.loads(lines[1])["operation"] == "intake_init"


def test_intake_creates_only_pickkit_dir(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    intake_init(root)

    assert sorted(p.name for p in (root / ".pickkit").iterdir()) == [
        "allowed_ext.json",
        "audit.jsonl",
        "project.json",
    ]
    assert not (root / "__selected").exists()
    assert not (root / "__crop").exists()


def test_intake_refuses_missing_or_non_directory_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        intake_init(tmp_path / "missing")

    file_path = tmp_path / "not_a_dir.png"
    file_path.write_bytes(b"x")
    with pytest.raises(NotADirectoryError, match="not a directory"):
        intake_init(file_path)


def test_supplied_hook_receives_intake_event(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    hook = RecordingHook()

    intake_init(root, hook=hook)

    assert len(hook.events) == 1
    assert hook.events[0].operation == "intake_init"
    assert hook.events[0].ok is True


def test_default_image_suffixes_cover_sandbox_pngs() -> None:
    assert ".png" in DEFAULT_IMAGE_SUFFIXES
    assert all(suffix == suffix.lower() for suffix in DEFAULT_IMAGE_SUFFIXES)
    assert all(suffix.startswith(".") for suffix in DEFAULT_IMAGE_SUFFIXES)
