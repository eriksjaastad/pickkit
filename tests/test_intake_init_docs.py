"""Drift-guards for the ``intake_init.intake`` module docstring.

The module docstring is the single source of truth for intake behaviour and
is reused as the CLI ``--help`` description, so these tests pin it to the
module and the parser: the first line must be non-empty, every name in its
"Public API" section must be a real attribute, ``DEFAULT_IMAGE_SUFFIXES``
must be referenced by name, every parser option must be documented, every
``--flag`` token in the docstring must be a real parser option, and
``--help`` must open with the docstring's first line.
"""

from __future__ import annotations

import re

import intake_init.intake as intake

#: A documented public name opens a double-backtick span, e.g.
#: ``intake_init(batch_root, *, force=False, hook=None)`` -> ``intake_init``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")

_DOC_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")

_UNDERLINE_CHARS = frozenset("-=~^")


def _doc_lines() -> list[str]:
    doc = intake.__doc__
    assert doc is not None, "intake_init.intake docstring must exist"
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
    assert first_line, "intake_init.intake docstring must have a non-empty first line"


def test_every_public_api_name_is_a_real_module_attribute() -> None:
    names = _public_api_names()
    assert names, "expected a non-empty 'Public API' section in the docstring"
    for name in sorted(names):
        assert hasattr(intake, name), (
            f"{name} is listed under Public API but is not an attribute of "
            f"{intake.__name__}"
        )


def test_default_image_suffixes_documented_by_name() -> None:
    doc = "\n".join(_doc_lines())
    assert "DEFAULT_IMAGE_SUFFIXES" in doc, (
        "the image-count rule must reference DEFAULT_IMAGE_SUFFIXES by name "
        "instead of duplicating the tuple in prose"
    )


def _parser_option_strings() -> set[str]:
    return {
        option
        for action in intake.build_parser()._actions
        for option in action.option_strings
    }


def test_every_parser_option_appears_in_module_docstring() -> None:
    options = {
        option
        for action in intake.build_parser()._actions
        for option in action.option_strings
        if option not in ("-h", "--help")
    }
    assert options, "expected CLI options beyond --help"
    doc = "\n".join(_doc_lines())
    for option in sorted(options):
        assert option in doc, (
            f"{option} is defined by build_parser() but missing from the "
            f"intake_init.intake docstring"
        )


def test_every_documented_flag_is_a_real_parser_option() -> None:
    real = _parser_option_strings()
    doc = "\n".join(_doc_lines())
    tokens = _DOC_FLAG_RE.findall(doc)
    assert tokens, "expected --flag tokens in the intake_init.intake docstring"
    for token in tokens:
        assert token in real, (
            f"{token} appears in the docstring but is not a build_parser() option"
        )


def test_help_contains_docstring_first_line() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "module docstring must have a non-empty first line"
    assert first_line in intake.build_parser().format_help()
