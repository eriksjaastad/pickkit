"""Tests for intake_init against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from intake_init import (
    DEFAULT_IMAGE_SUFFIXES,
    ManifestExistsError,
    intake_init,
)
from lib_safety import AuditEvent

from conftest import read_json, stage_batch_a


#: ``.pickkit.bak.20260926T192530Z`` — compact UTC, sibling of ``.pickkit/``.
BACKUP_NAME_RE = re.compile(r"\.pickkit\.bak\.\d{8}T\d{6}Z")


class RecordingHook:
    """Collects AuditEvents for assertions."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def test_intake_writes_manifest_with_expected_keys(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    result = intake_init(root)

    manifest = read_json(root / ".pickkit" / "project.json")
    assert manifest["schema_version"] == 2
    assert manifest["started_at"].endswith("Z")
    assert manifest["finished_at"] is None
    assert manifest["root"] == str(root.resolve())
    assert manifest["image_count"] == 4

    steps = manifest["steps"]
    assert [step["name"] for step in steps] == [
        "intake",
        "review_select",
        "multi_crop",
        "finish_package",
    ]
    assert steps[0] == {
        "name": "intake",
        "started_at": manifest["started_at"],
        "finished_at": manifest["started_at"],
        "images_processed": manifest["image_count"],
    }
    assert steps[1] == {
        "name": "review_select",
        "started_at": None,
        "finished_at": None,
        "images_processed": None,
    }
    assert steps[2] == {
        "name": "multi_crop",
        "started_at": None,
        "finished_at": None,
        "images_processed": None,
    }
    assert steps[3] == {
        "name": "finish_package",
        "started_at": None,
        "finished_at": None,
        "images_processed": None,
    }

    metrics = manifest["metrics"]
    assert metrics["images_per_hour_end_to_end"] is None
    assert metrics["step_rates"] == {}
    assert metrics["stager"] == {
        "zip": "",
        "eligible_count": 0,
        "by_ext_included": {},
        "excluded_counts": {},
        "incoming_by_ext": {},
    }

    assert result.manifest_path == root / ".pickkit" / "project.json"
    assert result.backup_path is None
    assert result.image_count == 4
    assert result.started_at.endswith("Z")
    assert result.extensions == {"png": 4, "txt": 2, "yaml": 3}


def test_inventory_snapshot_is_allowlist_ready(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    result = intake_init(root)

    inventory = read_json(root / ".pickkit" / "allowed_ext.json")
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


def test_second_intake_backs_up_then_overwrites(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    first = intake_init(root)
    original_manifest = read_json(first.manifest_path)
    hook = RecordingHook()

    second = intake_init(root, hook=hook)

    # Re-intake succeeds by default and reports the backup it made.
    assert second.manifest_path == first.manifest_path
    assert second.backup_path is not None
    assert second.backup_path.is_dir()
    assert second.backup_path.parent == root.resolve()
    assert BACKUP_NAME_RE.fullmatch(second.backup_path.name)

    # The old .pickkit is preserved whole under the timestamped sibling.
    backup_manifest = second.backup_path / "project.json"
    assert backup_manifest.exists()
    assert read_json(backup_manifest) == original_manifest
    assert (second.backup_path / "allowed_ext.json").exists()
    assert (second.backup_path / "audit.jsonl").exists()

    # The new .pickkit is written fresh.
    fresh = read_json(second.manifest_path)
    assert fresh["schema_version"] == 2
    assert fresh["root"] == str(root.resolve())
    assert fresh["started_at"].endswith("Z")

    # Audit baseline (fresh) records success and mentions the backup.
    lines = second.audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["operation"] == "intake_init"
    assert event["ok"] is True
    assert str(second.backup_path) in event["reason"]

    # The supplied hook sees the same successful event with the backup path.
    assert len(hook.events) == 1
    assert hook.events[0].ok is True
    assert str(second.backup_path) in (hook.events[0].reason or "")

    # Still no stage directories.
    assert not (root / "__selected").exists()
    assert not (root / "__crop").exists()


def test_force_overwrites_in_place_without_backup(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    first = intake_init(root)

    second = intake_init(root, force=True)

    assert second.manifest_path == first.manifest_path
    assert second.backup_path is None
    assert list(root.glob(".pickkit.bak.*")) == []
    assert second.image_count == 4
    lines = second.audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["operation"] == "intake_init"
    assert json.loads(lines[0])["ok"] is True
    assert json.loads(lines[1])["operation"] == "intake_init"
    assert json.loads(lines[1])["ok"] is True


def test_manifest_exists_error_is_legacy_but_still_exported() -> None:
    # Kept for API stability; normal re-intake no longer raises it.
    assert issubclass(ManifestExistsError, FileExistsError)


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
