"""Drift-guard for the ``lib_safety.companions`` module docstring.

The module docstring is the single source of truth for companion-file
behaviour, so these tests pin it to the module it documents: the first
line must summarise the module, every name in its "Public API" section
must be a real attribute of ``lib_safety.companions``, and the default
suffix set must be documented by name (see ``DEFAULT_COMPANION_SUFFIXES``
instead of duplicating the tuple in prose).
"""

from __future__ import annotations

import importlib
import re

# ``lib_safety.companions`` is a submodule; import it explicitly so
# attribute checks below test the module, not the package re-exports.
companions = importlib.import_module("lib_safety.companions")

#: A documented public name opens a double-backtick span, e.g.
#: ``find_companions(image_path, *, suffixes=None)`` -> ``find_companions``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")

_UNDERLINE_CHARS = frozenset("-=~^")


def _doc_lines() -> list[str]:
    assert companions.__doc__ is not None, "module docstring must exist"
    return companions.__doc__.splitlines()


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
    assert first_line, "module docstring must have a non-empty first line"


def test_every_public_api_name_is_a_real_module_attribute() -> None:
    names = _public_api_names()
    assert names, "expected a non-empty 'Public API' section in the docstring"
    for name in sorted(names):
        assert hasattr(companions, name), (
            f"{name} is listed under Public API but is not an attribute of "
            "lib_safety.companions"
        )


def test_default_companion_suffixes_documented_by_name() -> None:
    doc = "\n".join(_doc_lines())
    assert "DEFAULT_COMPANION_SUFFIXES" in doc, (
        "the companion rule must reference DEFAULT_COMPANION_SUFFIXES by name "
        "instead of duplicating the tuple in prose"
    )
