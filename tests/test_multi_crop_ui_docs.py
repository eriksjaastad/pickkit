"""Drift-guards for the ``multi_crop.ui`` module docstring.

The module docstring is the single source of truth for the crop UI behaviour,
so these tests pin it to the module: the first line must be non-empty, every
name in its "Public API" section must be a real attribute, the host/port
defaults must be documented and locked to 127.0.0.1:8766, the keyboard
shortcuts (Enter/Apply/Skip/Reset) must be documented, the routes and the
queue/output directory names must be documented, and the display-to-full-image
box-mapping formula must be documented.
"""

from __future__ import annotations

import re

import multi_crop.ui as ui

#: A documented public name opens a double-backtick span, e.g.
#: ``list_pending_images(batch_root)`` -> ``list_pending_images``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")


def _doc_lines() -> list[str]:
    doc = ui.__doc__
    assert doc is not None, "multi_crop.ui docstring must exist"
    return doc.splitlines()


def _section_lines(heading: str) -> list[str]:
    """Return the body lines of one reST section, excluding its header."""
    doc = _doc_lines()
    for i, line in enumerate(doc):
        if (
            line.strip() == heading
            and i + 1 < len(doc)
            and len(doc[i + 1].strip()) >= 3
            and all(ch == doc[i + 1].strip()[0] for ch in doc[i + 1].strip())
            and doc[i + 1].strip()[0] in "-=~^"
        ):
            start = i + 2
            break
    else:
        return []

    lines: list[str] = []
    j = start
    while j < len(doc):
        if (
            j + 1 < len(doc)
            and doc[j].strip()
            and len(doc[j + 1].strip()) >= 3
            and all(ch == doc[j + 1].strip()[0] for ch in doc[j + 1].strip())
            and doc[j + 1].strip()[0] in "-=~^"
        ):
            break
        lines.append(doc[j])
        j += 1
    return lines


def _public_api_names() -> set[str]:
    names: set[str] = set()
    for line in _section_lines("Public API"):
        # Only entry lines (flush-left `` ``name`` ``) are API names; the
        # indented description lines may mention other identifiers.
        if line.startswith("``"):
            match = _NAME_RE.search(line)
            if match:
                names.add(match.group(1))
    return names


def test_module_docstring_first_line_is_non_empty() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "multi_crop.ui docstring must have a non-empty first line"


def test_every_public_api_name_is_a_real_module_attribute() -> None:
    names = _public_api_names()
    assert names, "expected a non-empty 'Public API' section in the docstring"
    for name in sorted(names):
        assert hasattr(ui, name), (
            f"{name} is listed under Public API but is not an attribute of "
            f"{ui.__name__}"
        )


def test_host_and_port_defaults_documented_and_locked() -> None:
    doc = "\n".join(_doc_lines())
    assert "DEFAULT_HOST" in doc
    assert "DEFAULT_PORT" in doc
    assert ui.DEFAULT_HOST == "127.0.0.1"
    assert ui.DEFAULT_PORT == 8766


def test_keyboard_shortcuts_section_documents_actions() -> None:
    section = "\n".join(_section_lines("Keyboard shortcuts"))
    assert section, "expected a 'Keyboard shortcuts' section in the docstring"
    for token in ("``Enter``", "``Apply``", "``Skip``", "``Reset``"):
        assert token in section, (
            f"{token} must be documented in the Keyboard shortcuts section"
        )


def test_routes_documented() -> None:
    doc = "\n".join(_doc_lines())
    for route in (
        "GET /",
        "GET /api/status",
        "POST /api/crop",
        "POST /api/skip",
        "GET /image/<path:rel>",
    ):
        assert route in doc, f"{route} must be documented in the Routes section"


def test_queue_and_output_dir_names_documented_and_locked() -> None:
    doc = "\n".join(_doc_lines())
    assert "CROP_QUEUE_DIR_NAME" in doc
    assert "CROPPED_DIR_NAME" in doc
    assert ui.CROP_QUEUE_DIR_NAME == "__crop"
    assert ui.CROPPED_DIR_NAME == "__cropped"


def test_box_mapping_formula_documented() -> None:
    doc = "\n".join(_doc_lines())
    for token in ("naturalWidth", "naturalHeight", "clientWidth", "clientHeight", "round"):
        assert token in doc, (
            f"{token} must be documented in the Box mapping section"
        )
