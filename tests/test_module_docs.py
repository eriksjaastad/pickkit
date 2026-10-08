"""Drift-guards for the pickkit module docstrings.

Each module docstring is the single source of truth for that module's
behaviour, so these tests pin it to the code: the first line must be
non-empty, every name in its "Public API" section must be a real attribute,
locked constants must be documented by name and keep their values, and the
routes, keyboard shortcuts, log keys and other contracts each docstring
promises must be written down. The flag <-> docstring <-> ``--help`` drift
guard for the seven CLIs lives in ``test_cli_flag_drift.py``.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

import character_tools.character as character
import directory_viewer.viewer as viewer
import duplicate_finder.dupes as dupes
import finish_package.finish as finish
import finish_package.ui as finish_ui
import intake_init.intake as intake
import multi_crop.crop as crop
import multi_crop.ui as crop_ui
import review_select.review as review
import review_select.ui as review_ui

# lib_safety re-exports functions named after its submodules (``trash``), so
# ``import lib_safety.trash`` would bind the function. Load the modules.
safety_audit = importlib.import_module("lib_safety.audit")
safety_batch = importlib.import_module("lib_safety.batch")
safety_companions = importlib.import_module("lib_safety.companions")
safety_guards = importlib.import_module("lib_safety.guards")
safety_trash = importlib.import_module("lib_safety.trash")
safety_webui = importlib.import_module("lib_safety.webui")

#: Every module whose docstring carries a "Public API" section.
#: ``lib_safety.errors`` is intentionally absent: it has no Public API section.
DOCUMENTED_MODULES = (
    safety_audit,
    safety_batch,
    safety_companions,
    safety_guards,
    safety_trash,
    safety_webui,
    intake,
    review,
    review_ui,
    crop,
    crop_ui,
    finish,
    finish_ui,
    character,
    dupes,
    viewer,
)

#: The optional middle tools. None of them may extend the public spine.
MIDDLE_TOOLS = (character, dupes, viewer)

#: A documented public name opens a double-backtick span, e.g.
#: ``find_companions(image_path, *, suffixes=None)`` -> ``find_companions``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")

_UNDERLINE_CHARS = frozenset("-=~^")


def _module_id(module: object) -> str:
    return getattr(module, "__name__", str(module))


def _case_id(value: object) -> str | None:
    """Name module parameters in test ids; let pytest number the rest."""
    return value.__name__ if hasattr(value, "__name__") else None


def _doc_lines(module: object) -> list[str]:
    doc = getattr(module, "__doc__")
    assert doc is not None, f"{_module_id(module)} docstring must exist"
    return doc.splitlines()


def _doc(module: object) -> str:
    return "\n".join(_doc_lines(module))


def _is_underline(line: str) -> bool:
    """True for a reST-style section underline (at least three same chars)."""
    stripped = line.strip()
    return (
        len(stripped) >= 3
        and stripped[0] in _UNDERLINE_CHARS
        and all(ch == stripped[0] for ch in stripped)
    )


def _section_lines(module: object, heading: str) -> list[str]:
    """Return the body lines of one reST section, excluding its header."""
    doc = _doc_lines(module)
    for i, line in enumerate(doc):
        if line.strip() == heading and i + 1 < len(doc) and _is_underline(doc[i + 1]):
            start = i + 2
            break
    else:
        return []

    lines: list[str] = []
    j = start
    while j < len(doc):
        # A non-empty line followed by an underline starts the next section.
        if j + 1 < len(doc) and doc[j].strip() and _is_underline(doc[j + 1]):
            break
        lines.append(doc[j])
        j += 1
    return lines


def _public_api_names(module: object) -> set[str]:
    names: set[str] = set()
    for line in _section_lines(module, "Public API"):
        # Only entry lines (flush-left `` ``name`` ``) are API names; the
        # indented description lines may mention other identifiers.
        if line.startswith("``"):
            match = _NAME_RE.search(line)
            if match:
                names.add(match.group(1))
    return names


# --- every documented module -------------------------------------------------


@pytest.mark.parametrize("module", DOCUMENTED_MODULES, ids=_module_id)
def test_module_docstring_first_line_is_non_empty(module: object) -> None:
    first_line = _doc_lines(module)[0].strip()
    assert first_line, f"{_module_id(module)} docstring must have a non-empty first line"


@pytest.mark.parametrize("module", DOCUMENTED_MODULES, ids=_module_id)
def test_every_public_api_name_is_a_real_module_attribute(module: object) -> None:
    names = _public_api_names(module)
    assert names, (
        f"expected a non-empty 'Public API' section in the "
        f"{_module_id(module)} docstring"
    )
    for name in sorted(names):
        assert hasattr(module, name), (
            f"{name} is listed under Public API but is not an attribute of "
            f"{_module_id(module)}"
        )


# --- names documented instead of duplicated in prose -------------------------


@pytest.mark.parametrize(
    "module,names,duplicated",
    [
        (safety_companions, ("DEFAULT_COMPANION_SUFFIXES",), "the companion suffix tuple"),
        (intake, ("DEFAULT_IMAGE_SUFFIXES",), "the image-count suffix tuple"),
        (
            review,
            ("KEEP_DIR_NAME", "CROP_DIR_NAME", "REJECT_DIR_NAME"),
            "the destination directory layout",
        ),
        (review, ("ACTIONS",), "the valid action set tuple"),
        (
            crop,
            (
                "CROPPED_DIR_NAME",
                "CROP_QUEUE_DIR_NAME",
                "PICKKIT_DIR_NAME",
                "MANIFEST_NAME",
                "AUDIT_NAME",
                "CROPS_LOG_NAME",
                "MULTI_CROP_STEP_NAME",
            ),
            "the paths/layout",
        ),
        (
            finish,
            (
                "PICKKIT_DIR_NAME",
                "MANIFEST_NAME",
                "INVENTORY_NAME",
                "AUDIT_NAME",
                "FINISH_LOG_NAME",
                "FINISH_PACKAGE_STEP_NAME",
                "DEFAULT_ZIP_NAME",
                "SELECTED_DIR_NAME",
                "CROPPED_DIR_NAME",
                "DEFAULT_BANNED_EXTENSIONS",
                "DEFAULT_BANNED_PATTERNS",
                "OPERATION",
            ),
            "the paths/layout",
        ),
        (
            character,
            (
                "DEFAULT_IMAGE_SUFFIXES",
                "OPERATION",
                "Assignment",
                "BinSummary",
                "MoveToBinResult",
                "AssignResult",
                "RejectResult",
                "normalise_bin_name",
                "list_images",
                "check_bins",
                "move_to_bin",
                "assign_batch",
                "reject_image",
                "load_assignments",
                "build_parser",
                "main",
            ),
            "the behaviour",
        ),
        (
            dupes,
            (
                "DEFAULT_IMAGE_SUFFIXES",
                "HASH_SIZE",
                "DEFAULT_NEAR_THRESHOLD",
                "KEEP_POLICIES",
                "DEFAULT_KEEP_POLICY",
                "OPERATION",
                "content_hash",
                "average_hash",
                "hamming_distance",
                "list_images",
                "find_exact_duplicates",
                "find_near_duplicates",
                "plan_thin",
                "thin_groups",
                "DuplicateGroup",
                "ThinPlan",
                "ThinResult",
                "build_parser",
                "main",
            ),
            "the behaviour",
        ),
        (
            viewer,
            (
                "DEFAULT_IMAGE_SUFFIXES",
                "OPERATION",
                "DEFAULT_SAMPLE_LIMIT",
                "list_images_in",
                "inventory",
                "compare_roots",
                "DirInventory",
                "RootReport",
                "build_parser",
                "main",
            ),
            "the behaviour",
        ),
    ],
    ids=_case_id,
)
def test_names_are_documented_instead_of_duplicated(
    module: object, names: tuple[str, ...], duplicated: str
) -> None:
    doc = _doc(module)
    for name in names:
        assert name in doc, (
            f"{name} must be documented by name in {_module_id(module)} "
            f"instead of duplicating {duplicated} in prose"
        )


# --- locked constants: documented by name and pinned -------------------------


@pytest.mark.parametrize(
    "module,locked",
    [
        (review_ui, {"DEFAULT_HOST": "127.0.0.1", "DEFAULT_PORT": 8765}),
        (
            crop_ui,
            {
                "DEFAULT_HOST": "127.0.0.1",
                "DEFAULT_PORT": 8766,
                "CROP_QUEUE_DIR_NAME": "__crop",
                "CROPPED_DIR_NAME": "__cropped",
            },
        ),
        (finish_ui, {"DEFAULT_HOST": "127.0.0.1", "DEFAULT_PORT": 8767}),
        (
            dupes,
            {
                "DEFAULT_IMAGE_SUFFIXES": (
                    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
                ),
                "HASH_SIZE": 8,
                "DEFAULT_NEAR_THRESHOLD": 5,
                "KEEP_POLICIES": ("keep_first", "keep_largest", "keep_oldest"),
                "DEFAULT_KEEP_POLICY": "keep_first",
                "OPERATION": "duplicate_finder",
            },
        ),
        (
            viewer,
            {
                "DEFAULT_IMAGE_SUFFIXES": (
                    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
                ),
                "OPERATION": "directory_viewer",
                "DEFAULT_SAMPLE_LIMIT": 20,
            },
        ),
    ],
    ids=_case_id,
)
def test_locked_constants_are_documented_and_pinned(
    module: object, locked: dict[str, object]
) -> None:
    doc = _doc(module)
    for name, value in locked.items():
        assert name in doc, f"{name} must be documented in {_module_id(module)}"
        assert getattr(module, name) == value, (
            f"{_module_id(module)}.{name} is locked to {value!r}"
        )


def test_review_ui_stage_dir_names_documented_and_locked() -> None:
    doc = _doc(review_ui)
    assert "STAGE_DIR_NAMES" in doc
    for name in ("__selected", "__crop", "__reject"):
        assert name in doc
    assert {"__selected", "__crop", "__reject"} <= set(review_ui.STAGE_DIR_NAMES)


# --- behaviour the docstring must describe -----------------------------------


@pytest.mark.parametrize(
    "module,label,keys",
    [
        (review, "decision-log key", ("timestamp", "action", "source", "destination", "companions")),
        (crop, "crops-log key", ("timestamp", "source", "destination", "box")),
        (
            finish,
            "metrics.stager key",
            ("zip", "eligible_count", "by_ext_included", "excluded_counts", "incoming_by_ext"),
        ),
        (
            finish,
            "excluded bucket",
            ("hidden", "banned_ext", "banned_pattern", "not_allowed", "no_extension"),
        ),
    ],
    ids=_case_id,
)
def test_record_keys_documented(
    module: object, label: str, keys: tuple[str, ...]
) -> None:
    doc = _doc(module)
    for key in keys:
        assert key in doc, (
            f"{label} {key!r} must be documented in the {_module_id(module)} docstring"
        )


@pytest.mark.parametrize(
    "module,phrases",
    [
        (dupes, ("non-recursive", "sha256", "average hash", "seed-neighbour", "companions=True")),
        (viewer, ("flat", "subdirs", "sample_limit", "by_ext")),
    ],
    ids=_case_id,
)
def test_middle_tool_behaviour_is_described(
    module: object, phrases: tuple[str, ...]
) -> None:
    doc = _doc(module)
    for phrase in phrases:
        assert phrase in doc, (
            f"{phrase!r} must be described in the {_module_id(module)} docstring"
        )


def test_viewer_docstring_says_read_only() -> None:
    doc = _doc(viewer)
    assert "read-only" in doc or "Read-only" in doc


# --- web UIs: routes, keyboard shortcuts, buttons ----------------------------


@pytest.mark.parametrize(
    "module,routes",
    [
        (
            crop_ui,
            (
                "GET /",
                "GET /api/status",
                "POST /api/crop",
                "POST /api/skip",
                "GET /image/<path:rel>",
            ),
        ),
        (
            finish_ui,
            ("GET /", "GET /api/status", "POST /api/refresh", "POST /api/commit"),
        ),
    ],
    ids=_case_id,
)
def test_routes_documented(module: object, routes: tuple[str, ...]) -> None:
    doc = _doc(module)
    for route in routes:
        assert route in doc, (
            f"{route} must be documented in the {_module_id(module)} Routes section"
        )


@pytest.mark.parametrize(
    "module,shortcuts",
    [
        (review_ui, ("``K``", "``C``", "``R``", "``1``", "``2``", "``3``")),
        (crop_ui, ("``Enter``", "``Apply``", "``Skip``", "``Reset``")),
    ],
    ids=_case_id,
)
def test_keyboard_shortcuts_documented(
    module: object, shortcuts: tuple[str, ...]
) -> None:
    section = "\n".join(_section_lines(module, "Keyboard shortcuts"))
    assert section, (
        f"expected a 'Keyboard shortcuts' section in the {_module_id(module)} docstring"
    )
    for shortcut in shortcuts:
        assert shortcut in section, (
            f"{shortcut} must be documented in the Keyboard shortcuts section"
        )


def test_finish_ui_buttons_commit_refresh_force_mentioned() -> None:
    section = "\n".join(_section_lines(finish_ui, "Buttons"))
    assert section, "expected a 'Buttons' section in the finish_package.ui docstring"
    for token in ("Commit", "Refresh", "Force"):
        assert token in section, (
            f"{token} must be documented in the Buttons section"
        )


def test_finish_ui_has_no_upload_ids_or_databases_in_docstring() -> None:
    doc = _doc(finish_ui)
    for banned in ("rclone", "mojo", "SQLite"):
        assert banned not in doc, (
            f"{banned!r} must not appear in the finish_package.ui docstring"
        )


def test_crop_ui_box_mapping_formula_documented() -> None:
    doc = _doc(crop_ui)
    for token in ("naturalWidth", "naturalHeight", "clientWidth", "clientHeight", "round"):
        assert token in doc, (
            f"{token} must be documented in the Box mapping section"
        )


# --- spine and plugin boundaries ---------------------------------------------


@pytest.mark.parametrize(
    "module,names",
    [
        (review, ("PICKKIT_DIR_NAME", "MANIFEST_NAME", "AUDIT_NAME")),
        (crop, ("PICKKIT_DIR_NAME", "MANIFEST_NAME", "AUDIT_NAME")),
        (finish, ("PICKKIT_DIR_NAME", "MANIFEST_NAME", "INVENTORY_NAME", "AUDIT_NAME")),
    ],
    ids=_case_id,
)
def test_shared_pickkit_paths_match_intake_init(
    module: object, names: tuple[str, ...]
) -> None:
    for name in names:
        assert getattr(module, name) == getattr(intake, name), (
            f"{_module_id(module)}.{name} must match intake_init.intake.{name}"
        )


def test_public_spine_steps_are_locked() -> None:
    assert intake.PUBLIC_SPINE_STEPS == (
        "intake",
        "review_select",
        "multi_crop",
        "finish_package",
    )


@pytest.mark.parametrize("module", MIDDLE_TOOLS, ids=_module_id)
def test_middle_tools_do_not_extend_the_spine(module: object) -> None:
    assert not hasattr(module, "PUBLIC_SPINE_STEPS"), (
        f"{_module_id(module)} is an optional middle tool and must not define "
        f"its own spine steps"
    )


@pytest.mark.parametrize(
    "module,banned_imports",
    [
        (dupes, ("import character_tools", "from character_tools")),
        (
            viewer,
            (
                "import character_tools",
                "from character_tools",
                "import duplicate_finder",
                "from duplicate_finder",
                "import intake_init",
                "from intake_init",
                "import lib_safety",
                "from lib_safety",
            ),
        ),
    ],
    ids=_case_id,
)
def test_no_cross_plugin_hard_dependency(
    module: object, banned_imports: tuple[str, ...]
) -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")
    for banned in banned_imports:
        assert banned not in source, (
            f"{_module_id(module)} must not have a cross-plugin hard "
            f"dependency ({banned!r} found)"
        )


def test_directory_viewer_has_no_ui_imports() -> None:
    source = Path(viewer.__file__).read_text(encoding="utf-8")
    for banned in ("import flask", "from flask", "import tkinter", "from tkinter"):
        assert banned not in source, (
            f"directory_viewer.viewer is library + CLI only ({banned!r} found)"
        )


@pytest.mark.parametrize(
    "module,script_line",
    [
        (dupes, 'pickkit-dupes = "duplicate_finder.dupes:main"'),
        (viewer, 'pickkit-viewer = "directory_viewer.viewer:main"'),
    ],
    ids=_case_id,
)
def test_console_script_is_wired_in_pyproject(module: object, script_line: str) -> None:
    pyproject = (
        Path(module.__file__).resolve().parents[2] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert script_line in pyproject
