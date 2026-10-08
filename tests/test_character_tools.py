"""Tests for character_tools against the synthetic sandbox fixtures.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated. Core invariants under
test: list/check agree with :data:`DEFAULT_IMAGE_SUFFIXES`, dry-run moves and
rejects write nothing, commit moves image + same-stem companions into the
named bin via ``lib_safety.move_with_companions``, collisions refuse without
overwriting, bad bin names raise ``ValueError``, assignment maps load and
apply in order, rejects trash image + companions, and the spine manifest is
never mutated even when a fake ``.pickkit/project.json`` exists.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from character_tools import (
    DEFAULT_IMAGE_SUFFIXES,
    OPERATION,
    Assignment,
    AssignResult,
    BinSummary,
    MoveToBinResult,
    RejectResult,
    assign_batch,
    check_bins,
    list_images,
    load_assignments,
    main,
    move_to_bin,
    normalise_bin_name,
    reject_image,
)
from lib_safety import AuditEvent, DestinationExistsError

from conftest import BATCH_A, read_json, stage_batch_a


class RecordingHook:
    """Collects AuditEvents for assertions."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


# --- list_images -------------------------------------------------------------


def test_list_images_finds_pngs_in_directory(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    images = list_images(root)

    assert images == [
        root / "img_001.png",
        root / "img_002.png",
        root / "img_003.png",
        root / "img_004.png",
    ]
    assert set(DEFAULT_IMAGE_SUFFIXES) == {
        ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    }


def test_list_images_accepts_file_and_non_image(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)

    assert list_images(root / "img_001.png") == [root / "img_001.png"]
    assert list_images(root / "img_001.yaml") == []
    assert list_images(root, suffixes=".yaml") == [
        root / "img_001.yaml",
        root / "img_002.yaml",
        root / "img_004.yaml",
    ]


def test_list_images_skips_hidden_names(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    (root / ".hidden.png").write_bytes((root / "img_003.png").read_bytes())

    assert ".hidden.png" not in [path.name for path in list_images(root)]


def test_list_images_refuses_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="source not found"):
        list_images(tmp_path / "missing.png")


# --- normalise_bin_name -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["../x", "a/b", "a\\b", "", "   ", ".", "a..b", "bad!name", "a:b", "a\nb"],
)
def test_bad_bin_names_raise_value_error(name: str) -> None:
    with pytest.raises(ValueError):
        normalise_bin_name(name)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  alice  ", "alice"),
        ("group a", "group a"),
        ("img_set-1.2", "img_set-1.2"),
        ("_private", "_private"),
        ("__character_group_1", "__character_group_1"),
    ],
)
def test_normalise_bin_name_keeps_allowed_names(raw: str, expected: str) -> None:
    assert normalise_bin_name(raw) == expected


# --- move_to_bin ---------------------------------------------------------------


def test_dry_run_move_writes_nothing(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()
    hook = RecordingHook()
    source = root / "img_004.png"

    result = move_to_bin(source, "alice", bins_root=bins_root, hook=hook)

    assert isinstance(result, MoveToBinResult)
    assert result.committed is False
    assert result.image == source.resolve()
    assert result.bin_name == "alice"
    assert result.bins_root == bins_root.resolve()
    assert result.destination_image == bins_root / "alice" / "img_004.png"
    assert [path.name for path in result.companions] == [
        "img_004.txt",
        "img_004.yaml",
    ]
    # Nothing moved or created.
    assert source.is_file()
    assert (root / "img_004.txt").is_file()
    assert (root / "img_004.yaml").is_file()
    assert not (bins_root / "alice").exists()
    # One character_tools dry-run event on the caller hook.
    assert [event.operation for event in hook.events] == [OPERATION]
    assert hook.events[0].ok is True
    assert hook.events[0].reason == "move; dry_run"


def test_commit_move_moves_image_and_companions_into_bin(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()
    hook = RecordingHook()
    source = root / "img_004.png"

    result = move_to_bin(
        source, "alice", bins_root=bins_root, commit=True, hook=hook
    )

    assert result.committed is True
    assert result.destination_image == bins_root / "alice" / "img_004.png"
    assert (bins_root / "alice" / "img_004.png").is_file()
    assert (bins_root / "alice" / "img_004.yaml").is_file()
    assert (bins_root / "alice" / "img_004.txt").is_file()
    assert not source.exists()
    assert not (root / "img_004.yaml").exists()
    assert not (root / "img_004.txt").exists()
    # lib_safety records its move event plus our character_tools event.
    assert [event.operation for event in hook.events] == ["move", OPERATION]
    assert hook.events[-1].reason == "move; committed=True"


def test_commit_move_collision_refuses_and_keeps_originals(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bin_dir = bins_root / "alice"
    bin_dir.mkdir(parents=True)
    occupied = bin_dir / "img_004.png"
    occupied.write_bytes(b"occupied destination bytes")
    source = root / "img_004.png"
    source_before = source.read_bytes()

    with pytest.raises(DestinationExistsError, match="already exists"):
        move_to_bin(source, "alice", bins_root=bins_root, commit=True)

    # Originals stay put; the occupied destination is not overwritten.
    assert source.read_bytes() == source_before
    assert (root / "img_004.yaml").is_file()
    assert (root / "img_004.txt").is_file()
    assert occupied.read_bytes() == b"occupied destination bytes"


def test_move_refuses_missing_image_and_bins_root(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()

    with pytest.raises(FileNotFoundError, match="image not found"):
        move_to_bin(root / "nope.png", "alice", bins_root=bins_root)

    with pytest.raises(FileNotFoundError, match="bins root not found"):
        move_to_bin(root / "img_001.png", "alice", bins_root=tmp_path / "nope")


# --- check_bins -----------------------------------------------------------------


def test_check_bins_reports_counts_including_empty_bins(tmp_path: Path) -> None:
    bins_root = tmp_path / "bins"
    alice = bins_root / "alice"
    bob = bins_root / "bob"
    alice.mkdir(parents=True)
    bob.mkdir()
    shutil.copy(BATCH_A / "img_001.png", alice / "img_001.png")
    shutil.copy(BATCH_A / "img_002.png", alice / "img_002.png")
    (alice / "img_002.yaml").write_text("sidecar\n", encoding="utf-8")
    (bins_root / ".hidden_bin").mkdir()
    (bins_root / "loose.txt").write_text("not a bin\n", encoding="utf-8")

    bins = check_bins(bins_root)

    assert isinstance(bins, list)
    assert [summary.name for summary in bins] == ["alice", "bob"]
    alice_summary, bob_summary = bins
    assert isinstance(alice_summary, BinSummary)
    assert alice_summary.path == alice
    assert alice_summary.image_count == 2
    assert alice_summary.images == ("img_001.png", "img_002.png")
    assert bob_summary.image_count == 0
    assert bob_summary.images == ()


# --- Assignment / assign_batch --------------------------------------------------


def test_assignment_holds_source_and_bin_name() -> None:
    assignment = Assignment("img_001.png", "alice")

    assert assignment.source == "img_001.png"
    assert assignment.bin_name == "alice"


def test_load_assignments_json_array_and_jsonl(tmp_path: Path) -> None:
    array_path = tmp_path / "assignments.json"
    array_path.write_text(
        json.dumps([{"source": "img_001.png", "bin": "alice"}]),
        encoding="utf-8",
    )
    assert load_assignments(array_path) == [
        Assignment(Path("img_001.png"), "alice")
    ]

    jsonl_path = tmp_path / "assignments.jsonl"
    jsonl_path.write_text(
        '{"source": "img_001.png", "bin": "alice"}\n\n'
        '{"source": "img_002.png", "bin": "bob"}\n',
        encoding="utf-8",
    )
    assert load_assignments(jsonl_path) == [
        Assignment(Path("img_001.png"), "alice"),
        Assignment(Path("img_002.png"), "bob"),
    ]


def test_load_assignments_refuses_unknown_shapes(tmp_path: Path) -> None:
    missing_key = tmp_path / "missing_key.json"
    missing_key.write_text(
        json.dumps([{"source": "img_001.png"}]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="'source' and 'bin'"):
        load_assignments(missing_key)

    extra_key = tmp_path / "extra_key.json"
    extra_key.write_text(
        json.dumps([{"source": "img_001.png", "bin": "alice", "note": "x"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly 'source' and 'bin'"):
        load_assignments(extra_key)

    not_array = tmp_path / "not_array.json"
    not_array.write_text(json.dumps({"source": "img_001.png"}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_assignments(not_array)

    with pytest.raises(FileNotFoundError, match="assignments file"):
        load_assignments(tmp_path / "nope.json")


def test_assign_batch_dry_run_validates_all_without_moving(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()

    result = assign_batch(
        [
            (root / "img_001.png", "alice"),
            Assignment(root / "img_002.png", "bob"),
        ],
        bins_root=bins_root,
    )

    assert isinstance(result, AssignResult)
    assert result.planned_count == 2
    assert result.moved_count == 0
    assert result.committed is False
    assert len(result.results) == 2
    assert all(item.committed is False for item in result.results)
    assert (root / "img_001.png").is_file()
    assert (root / "img_002.png").is_file()
    assert not (bins_root / "alice").exists()
    assert not (bins_root / "bob").exists()


def test_assign_batch_commit_moves_multiple(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()
    map_path = tmp_path / "map.json"
    map_path.write_text(
        json.dumps(
            [
                {"source": str(root / "img_001.png"), "bin": "alice"},
                {"source": str(root / "img_003.png"), "bin": "bob"},
            ]
        ),
        encoding="utf-8",
    )

    assignments = load_assignments(map_path)
    result = assign_batch(assignments, bins_root=bins_root, commit=True)

    assert result.planned_count == 2
    assert result.moved_count == 2
    assert result.committed is True
    assert (bins_root / "alice" / "img_001.png").is_file()
    assert (bins_root / "alice" / "img_001.yaml").is_file()
    assert (bins_root / "bob" / "img_003.png").is_file()
    assert (bins_root / "bob" / "img_003.txt").is_file()
    assert not (root / "img_001.png").exists()
    assert not (root / "img_003.png").exists()


def test_assign_batch_stops_on_first_bad_assignment(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()

    with pytest.raises(ValueError):
        assign_batch(
            [
                (root / "img_001.png", "alice"),
                (root / "img_002.png", "bad/name"),
            ],
            bins_root=bins_root,
            commit=True,
        )

    # The failing batch moved nothing (the bad name is caught on item two,
    # but the failure is raised before item one commits in dry-run; commit
    # applies in order, so item one moved before the failure).
    assert not (root / "img_001.png").exists()
    assert (bins_root / "alice" / "img_001.png").is_file()
    assert (root / "img_002.png").is_file()


# --- reject_image ----------------------------------------------------------------


def test_reject_image_dry_run_lists_but_keeps_files(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    hook = RecordingHook()
    source = root / "img_004.png"

    result = reject_image(source, hook=hook)

    assert isinstance(result, RejectResult)
    assert result.committed is False
    assert result.trashed == ()
    assert [path.name for path in result.companions] == [
        "img_004.txt",
        "img_004.yaml",
    ]
    assert source.is_file()
    assert (root / "img_004.txt").is_file()
    assert (root / "img_004.yaml").is_file()
    assert hook.events[0].operation == OPERATION
    assert hook.events[0].reason == "reject; dry_run"


def test_reject_image_commit_trashes_image_and_companions(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
    source = root / "img_004.png"

    result = reject_image(source, commit=True)

    assert result.committed is True
    assert len(result.trashed) == 3
    assert not source.exists()
    assert not (root / "img_004.txt").exists()
    assert not (root / "img_004.yaml").exists()
    # Other images are untouched.
    assert (root / "img_001.png").is_file()
    assert (root / "img_001.yaml").is_file()


# --- spine manifest is never touched ----------------------------------------------


def test_no_spine_manifest_mutation_with_fake_project_json(tmp_path: Path) -> None:
    root = stage_batch_a(tmp_path)
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

    bins_root = root / "bins"
    bins_root.mkdir()
    move_to_bin(root / "img_001.png", "alice", bins_root=bins_root, commit=True)
    assign_batch([(root / "img_002.png", "bob")], bins_root=bins_root, commit=True)

    assert manifest_path.read_bytes() == before
    assert read_json(manifest_path)["finished_at"] is None
    assert sorted(path.name for path in pickkit_dir.iterdir()) == ["project.json"]


# --- CLI ---------------------------------------------------------------------------


def test_cli_list_and_check_print_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    (bins_root / "alice").mkdir(parents=True)
    shutil.copy(BATCH_A / "img_001.png", bins_root / "alice" / "img_001.png")

    assert main(["list", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["source"] == str(root)
    assert len(out["images"]) == 4

    assert main(["check", str(bins_root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["bins"][0]["name"] == "alice"
    assert out["bins"][0]["image_count"] == 1


def test_cli_move_commit_and_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()
    audit_path = tmp_path / "audit.jsonl"

    code = main(
        [
            "move", str(root / "img_001.png"),
            "--bin", "alice",
            "--bins-root", str(bins_root),
            "--commit",
            "--audit", str(audit_path),
        ]
    )

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["committed"] is True
    assert out["destination_image"] == str(bins_root / "alice" / "img_001.png")
    assert (bins_root / "alice" / "img_001.png").is_file()
    assert (bins_root / "alice" / "img_001.yaml").is_file()
    audit_lines = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [line["operation"] for line in audit_lines] == ["move", "character_tools"]


def test_cli_refuses_bad_bin_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = stage_batch_a(tmp_path)
    bins_root = tmp_path / "bins"
    bins_root.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "move", str(root / "img_001.png"),
                "--bin", "../escape",
                "--bins-root", str(bins_root),
            ]
        )
    assert exc_info.value.code == 1
    assert "pickkit-character: error:" in capsys.readouterr().err
