"""Tests for finish_package against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path`` and intake'd with ``intake_init`` before content trees are
arranged; the committed sandbox is never mutated. The core invariants under
test: dry-run writes nothing, commit writes a copy-only delivery ZIP whose
members are exactly the allowlisted non-banned files from ``__selected/`` and
``__cropped/``, bans win over the allowlist, ``.pickkit/`` / ``__crop/`` /
``__reject/`` never appear in the ZIP, sources are byte-unchanged, and the
manifest/audit are updated only on commit.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from finish_package import (
    CROPPED_DIR_NAME,
    DEFAULT_ZIP_NAME,
    EXCLUDED_BUCKETS,
    FINISH_LOG_NAME,
    SELECTED_DIR_NAME,
    FinishResult,
    classify_file,
    default_content_roots,
    finish_package,
    load_allowlist,
    main,
)
from intake_init import intake_init
from lib_safety import AuditEvent, RefusedWriteError

from conftest import BATCH_A, jsonl_lines, read_json, snapshot, stage_batch_a


class RecordingHook:
    """Collects AuditEvents for assertions."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def arrange_content(root: Path) -> dict[str, Path]:
    """Create __selected / __cropped trees plus junk roots to prove exclusion.

    Must be called AFTER ``intake_init(root)`` so the intake allowlist snapshot
    only contains the sandbox extensions (png/yaml/txt) and the extra files
    below exercise the ban buckets.
    """
    selected = root / SELECTED_DIR_NAME
    cropped = root / CROPPED_DIR_NAME
    selected.mkdir()
    cropped.mkdir()

    paths = {
        "selected_png": selected / "img_001.png",
        "selected_yaml": selected / "img_001.yaml",
        "cropped_png": cropped / "img_002.png",
        "cropped_yaml": cropped / "img_002.yaml",
        "cropped_txt": cropped / "img_002.txt",
    }
    shutil.copy(BATCH_A / "img_001.png", paths["selected_png"])
    shutil.copy(BATCH_A / "img_001.yaml", paths["selected_yaml"])
    shutil.copy(BATCH_A / "img_002.png", paths["cropped_png"])
    shutil.copy(BATCH_A / "img_002.yaml", paths["cropped_yaml"])
    paths["cropped_txt"].write_text("cropped companion\n", encoding="utf-8")

    # Ban / exclusion probes inside the scanned content trees.
    (selected / "img_001.md").write_text("# banned companion\n", encoding="utf-8")
    (selected / "data.json").write_text("{}\n", encoding="utf-8")
    (selected / "img.project.yml").write_text(
        "project: matches banned pattern\n", encoding="utf-8"
    )
    (selected / ".hidden.png").write_bytes((BATCH_A / "img_003.png").read_bytes())
    (selected / "README").write_text("extensionless\n", encoding="utf-8")
    (selected / "extra.xyz").write_text("not in allowlist\n", encoding="utf-8")
    (cropped / "img_002.md").write_text("# banned cropped companion\n", encoding="utf-8")

    # Junk roots that the default scan must never include.
    crop_queue = root / "__crop"
    reject = root / "__reject"
    crop_queue.mkdir()
    reject.mkdir()
    shutil.copy(BATCH_A / "img_004.png", crop_queue / "img_999.png")
    shutil.copy(BATCH_A / "img_003.png", reject / "img_998.png")
    return paths


def _finish_step(root: Path) -> dict[str, object]:
    manifest = read_json(root / ".pickkit" / "project.json")
    for step in manifest["steps"]:
        if step["name"] == "finish_package":
            return step
    raise AssertionError("finish_package step missing")


def _zip_names(root: Path) -> list[str]:
    with zipfile.ZipFile(root / DEFAULT_ZIP_NAME) as archive:
        return archive.namelist()


def _stager(root: Path) -> dict[str, object]:
    manifest = read_json(root / ".pickkit" / "project.json")
    return manifest["metrics"]["stager"]


# --- dry-run ----------------------------------------------------------------


def test_dry_run_writes_nothing_and_reports_exclusions(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    arrange_content(root)
    hook = RecordingHook()
    source_snapshot = snapshot(root)

    result = finish_package(root, hook=hook)

    assert isinstance(result, FinishResult)
    assert result.commit is False
    assert result.zip_path is None
    assert result.finished_at is None
    assert result.eligible_count == 5
    assert result.by_ext_included == {"png": 2, "txt": 1, "yaml": 2}
    assert set(result.excluded_counts) == set(EXCLUDED_BUCKETS)
    assert result.excluded_counts == {
        "hidden": 1,
        "banned_ext": 3,
        "banned_pattern": 1,
        "not_allowed": 1,
        "no_extension": 1,
    }
    assert result.incoming_by_ext == {
        "json": 1,
        "md": 2,
        "png": 2,
        "txt": 1,
        "xyz": 1,
        "yaml": 2,
        "yml": 1,
    }

    # Nothing written: no ZIP, no finish.jsonl, no manifest/audit changes.
    assert not (root / DEFAULT_ZIP_NAME).exists()
    assert not (root / ".pickkit" / FINISH_LOG_NAME).exists()
    manifest = read_json(root / ".pickkit" / "project.json")
    assert manifest["finished_at"] is None
    assert manifest["metrics"]["stager"] == {
        "zip": "",
        "eligible_count": 0,
        "by_ext_included": {},
        "excluded_counts": {},
        "incoming_by_ext": {},
    }
    step = _finish_step(root)
    assert step["started_at"] is None
    assert step["finished_at"] is None
    assert step["images_processed"] is None
    assert [e["operation"] for e in jsonl_lines(root / ".pickkit" / "audit.jsonl")] == [
        "intake_init"
    ]

    # Dry-run audits only the caller hook, and sources are byte-unchanged.
    assert [e.operation for e in hook.events] == ["finish_package"]
    assert hook.events[0].ok is True
    assert "dry_run" in (hook.events[0].reason or "")
    assert snapshot(root) == source_snapshot


# --- commit -----------------------------------------------------------------


def test_commit_writes_zip_members_manifest_and_audit(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    arrange_content(root)
    hook = RecordingHook()

    result = finish_package(root, commit=True, hook=hook)

    assert result.commit is True
    assert result.zip_path == root / DEFAULT_ZIP_NAME
    assert result.finished_at is not None and result.finished_at.endswith("Z")
    assert result.eligible_count == 5

    # ZIP members: allowlisted non-banned files only, content-root prefixes
    # preserved; no .pickkit / __crop / __reject members; STORED (copy-only).
    names = _zip_names(root)
    assert names == [
        f"{CROPPED_DIR_NAME}/img_002.png",
        f"{CROPPED_DIR_NAME}/img_002.txt",
        f"{CROPPED_DIR_NAME}/img_002.yaml",
        f"{SELECTED_DIR_NAME}/img_001.png",
        f"{SELECTED_DIR_NAME}/img_001.yaml",
    ]
    assert not any(name.startswith(".pickkit/") for name in names)
    assert not any(name.startswith("__crop/") for name in names)
    assert not any(name.startswith("__reject/") for name in names)
    with zipfile.ZipFile(root / DEFAULT_ZIP_NAME) as archive:
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
        # Copy-only: each member's bytes equal its source file bytes.
        for name in names:
            assert archive.read(name) == (root / name).read_bytes()

    # Manifest closed: finished_at, finish_package step, metrics.stager.
    manifest = read_json(root / ".pickkit" / "project.json")
    assert manifest["finished_at"] == result.finished_at
    step = _finish_step(root)
    assert step["started_at"] == result.finished_at
    assert step["finished_at"] == result.finished_at
    assert step["images_processed"] == 2  # eligible PNGs, via DEFAULT_IMAGE_SUFFIXES
    stager = _stager(root)
    assert stager["zip"] == DEFAULT_ZIP_NAME
    assert stager["eligible_count"] == 5
    assert stager["by_ext_included"] == {"png": 2, "txt": 1, "yaml": 2}
    assert stager["excluded_counts"] == {
        "hidden": 1,
        "banned_ext": 3,
        "banned_pattern": 1,
        "not_allowed": 1,
        "no_extension": 1,
    }
    assert stager["incoming_by_ext"]["png"] == 2
    assert stager["incoming_by_ext"]["md"] == 2

    # Audit + finish log.
    audit_ops = [
        e["operation"] for e in jsonl_lines(root / ".pickkit" / "audit.jsonl")
    ]
    assert audit_ops == ["intake_init", "finish_package"]
    assert [e.operation for e in hook.events] == ["finish_package"]
    finish_lines = jsonl_lines(root / ".pickkit" / FINISH_LOG_NAME)
    assert len(finish_lines) == 1
    assert finish_lines[0]["eligible_count"] == 5
    assert finish_lines[0]["zip"] == DEFAULT_ZIP_NAME
    assert finish_lines[0]["committed"] is True


def test_commit_sources_byte_unchanged(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    paths = arrange_content(root)
    before = {
        key: value
        for key, value in snapshot(root).items()
        if not key.startswith(".pickkit/")
    }

    finish_package(root, commit=True)

    # Source files and content trees must be byte-identical after commit; only
    # the additive delivery ZIP and the .pickkit state change.
    after = {
        key: value
        for key, value in snapshot(root).items()
        if not key.startswith(".pickkit/")
    }
    for key, value in before.items():
        assert after[key] == value
    assert (root / DEFAULT_ZIP_NAME).is_file()
    assert paths["selected_png"].read_bytes() == (BATCH_A / "img_001.png").read_bytes()
    assert paths["cropped_png"].read_bytes() == (BATCH_A / "img_002.png").read_bytes()


# --- ZIP collision / force --------------------------------------------------


def test_existing_zip_refuses_without_force(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    arrange_content(root)
    zip_path = root / DEFAULT_ZIP_NAME
    zip_path.write_bytes(b"occupied delivery.zip")

    with pytest.raises(RefusedWriteError, match="already exists"):
        finish_package(root, commit=True)

    assert zip_path.read_bytes() == b"occupied delivery.zip"
    assert read_json(root / ".pickkit" / "project.json")["finished_at"] is None
    assert _finish_step(root)["finished_at"] is None
    assert not (root / ".pickkit" / FINISH_LOG_NAME).exists()
    # The refusal is audited through the batch audit JSONL.
    audit_ops = [
        e["operation"] for e in jsonl_lines(root / ".pickkit" / "audit.jsonl")
    ]
    assert audit_ops == ["intake_init", "refuse_write"]


def test_force_overwrites_zip_only(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    paths = arrange_content(root)
    zip_path = root / DEFAULT_ZIP_NAME
    zip_path.write_bytes(b"old zip bytes")
    sources_before = {
        key: path.read_bytes() for key, path in paths.items()
    }

    result = finish_package(root, commit=True, force=True)

    assert result.zip_path == zip_path
    assert zip_path.read_bytes() != b"old zip bytes"
    assert _zip_names(root)[0].startswith(f"{CROPPED_DIR_NAME}/")
    assert all(path.read_bytes() == sources_before[key] for key, path in paths.items())
    assert read_json(root / ".pickkit" / "project.json")["finished_at"] is not None


def test_force_refuses_to_overwrite_a_source_file(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    paths = arrange_content(root)
    source = paths["selected_png"]
    before = source.read_bytes()

    with pytest.raises(RefusedWriteError, match="source file"):
        finish_package(
            root,
            commit=True,
            force=True,
            output_zip=f"{SELECTED_DIR_NAME}/img_001.png",
        )

    assert source.read_bytes() == before


# --- refuses -----------------------------------------------------------------


def test_refuse_when_not_intaked(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    with pytest.raises(FileNotFoundError, match="intake"):
        finish_package(root)

    assert not (root / ".pickkit").exists()


def test_refuse_when_inventory_missing(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    (root / ".pickkit" / "allowed_ext.json").unlink()

    with pytest.raises(FileNotFoundError, match="inventory"):
        finish_package(root)


def test_content_outside_batch_refused(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    outside = tmp_path / "outside_content"
    outside.mkdir()

    with pytest.raises(ValueError, match="outside batch root"):
        finish_package(root, content=outside)


def test_content_override_missing_dir_refused(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)

    with pytest.raises(FileNotFoundError, match="content"):
        finish_package(root, content="__selected")


# --- content roots ----------------------------------------------------------


def test_content_override_scans_single_dir_only(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    arrange_content(root)

    result = finish_package(root, content=SELECTED_DIR_NAME, commit=True)

    assert result.eligible_count == 2
    assert _zip_names(root) == [
        f"{SELECTED_DIR_NAME}/img_001.png",
        f"{SELECTED_DIR_NAME}/img_001.yaml",
    ]


def test_default_content_roots_skips_missing(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    cropped = root / CROPPED_DIR_NAME
    cropped.mkdir()
    shutil.copy(BATCH_A / "img_002.png", cropped / "img_002.png")

    assert default_content_roots(root) == [cropped]

    result = finish_package(root, commit=True)

    assert result.eligible_count == 1
    assert _zip_names(root) == [f"{CROPPED_DIR_NAME}/img_002.png"]


# --- companions / bans ------------------------------------------------------


def test_banned_and_not_allowed_companions_are_excluded(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    arrange_content(root)

    result = finish_package(root)

    # img_001.md and img_002.md are banned-ext companions; yaml/txt companions
    # pass the allowlist and are eligible via the normal walk.
    assert result.excluded_counts["banned_ext"] == 3
    assert result.by_ext_included == {"png": 2, "txt": 1, "yaml": 2}


def test_classify_file_evaluation_order(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    allowed = {"png", "yml", "json", "xyz"}
    # Hidden wins over every later rule.
    assert classify_file(root / ".hidden.png", root, allowed=allowed) == "hidden"
    # Extensionless comes before the banned/allowlist checks.
    assert classify_file(root / "README", root, allowed=allowed) == "no_extension"
    # Bans win over the allowlist.
    assert classify_file(root / "a.json", root, allowed={"json"}) == "banned_ext"
    assert (
        classify_file(root / "img.project.yml", root, allowed={"yml"})
        == "banned_pattern"
    )
    # Not in the allowlist, not banned.
    assert classify_file(root / "a.xyz", root, allowed={"png"}) == "not_allowed"
    assert classify_file(root / "a.png", root, allowed={"png"}) == "eligible"


def test_load_allowlist_normalizes_and_refuses(tmp_path: Path) -> None:
    inventory = tmp_path / "allowed_ext.json"
    inventory.write_text(
        json.dumps({"allowedExtensions": ["png", ".yaml", "TXT"]}),
        encoding="utf-8",
    )
    assert load_allowlist(inventory) == {"png", "yaml", "txt"}

    with pytest.raises(FileNotFoundError, match="inventory"):
        load_allowlist(tmp_path / "missing.json")

    bad = tmp_path / "bad_inventory.json"
    bad.write_text(json.dumps({"allowedExtensions": "png"}), encoding="utf-8")
    with pytest.raises(ValueError, match="allowedExtensions"):
        load_allowlist(bad)


# --- CLI --------------------------------------------------------------------


def test_cli_dry_run_and_commit_summaries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    intake_init(root)
    arrange_content(root)

    code = main([str(root)])
    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run complete (nothing written)" in out
    assert "eligible_count: 5" in out
    assert not (root / DEFAULT_ZIP_NAME).exists()

    code = main([str(root), "--commit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "wrote zip" in out
    assert str(root / DEFAULT_ZIP_NAME) in out
    assert (root / DEFAULT_ZIP_NAME).is_file()
    assert read_json(root / ".pickkit" / "project.json")["finished_at"] is not None


def test_cli_refuse_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main([str(root), "--commit"])
    assert exc_info.value.code == 1
    assert "pickkit-finish: error:" in capsys.readouterr().err
