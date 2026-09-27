"""Drift-guards for the ``review_select.ui`` module docstring.

The module docstring is the single source of truth for UI behaviour, so these
tests pin it to the module: the first line must be non-empty, every name in
its "Public API" section must be a real attribute, the host/port defaults must
be documented and locked, the keyboard shortcuts (K/C/R and 1/2/3) must be
documented, and the stage-directory exclusion set must be documented by name.
"""

from __future__ import annotations

import re

import review_select.ui as ui

#: A documented public name opens a double-backtick span, e.g.
#: ``list_pending_images(batch_root)`` -> ``list_pending_images``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")

_UNDERLINE_CHARS = frozenset("-=~^")


def _doc_lines() -> list[str]:
    doc = ui.__doc__
    assert doc is not None, "review_select.ui docstring must exist"
    return doc.splitlines()


def _is_underline(line: str) -> bool:
    """True for a reST-style section underline (at least three same chars)."""
    stripped = line.strip()
    return (
        len(stripped) >= 3
        and stripped[0] in _UNDERLINE_CHARS
        and all(ch == stripped[0] for ch in stripped)
    )


def _section_lines(heading: str) -> list[str]:
    """Return the body lines of one reST section, excluding its header."""
    doc = _doc_lines()
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
    assert first_line, "review_select.ui docstring must have a non-empty first line"


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
    assert ui.DEFAULT_PORT == 8765


def test_keyboard_shortcuts_section_documents_both_bindings() -> None:
    section = "\n".join(_section_lines("Keyboard shortcuts"))
    assert section, "expected a 'Keyboard shortcuts' section in the docstring"
    for pair in ("``K``", "``C``", "``R``", "``1``", "``2``", "``3``"):
        assert pair in section, (
            f"{pair} must be documented in the Keyboard shortcuts section"
        )


def test_stage_dir_names_documented_and_locked() -> None:
    doc = "\n".join(_doc_lines())
    assert "STAGE_DIR_NAMES" in doc
    for name in ("__selected", "__crop", "__reject"):
        assert name in doc
    assert {"__selected", "__crop", "__reject"} <= set(ui.STAGE_DIR_NAMES)
