"""Drift-guards for the ``character_tools.character`` module docstring.

The module docstring is the single source of truth for character-tools
behaviour and is reused as the CLI ``--help`` description, so these tests pin
it to the module and the parser: the first line must be non-empty, every name
in its "Public API" section must be a real attribute, the locked constants and
result dataclasses must be documented by name, every parser option must be
documented, every ``--flag`` token in the docstring must be a real parser
option, and ``--help`` must open with the docstring's first line. The public
spine stays intake / review_select / multi_crop / finish_package — this
optional middle tool must not extend it.
"""

from __future__ import annotations

import argparse
import re

import character_tools.character as character
import intake_init.intake as intake

#: A documented public name opens a double-backtick span, e.g.
#: ``move_to_bin(image, bin_name, *, ...)`` -> ``move_to_bin``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")

_DOC_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")

_UNDERLINE_CHARS = frozenset("-=~^")


def _doc_lines() -> list[str]:
    doc = character.__doc__
    assert doc is not None, "character_tools.character docstring must exist"
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


def _iter_parser_actions(parser: argparse.ArgumentParser):
    """Yield every action in *parser*, descending into subparsers."""
    for action in parser._actions:
        yield action
        if isinstance(action, argparse._SubParsersAction):
            for sub_parser in action.choices.values():
                yield from _iter_parser_actions(sub_parser)


def _parser_option_strings() -> set[str]:
    return {
        option
        for action in _iter_parser_actions(character.build_parser())
        for option in action.option_strings
    }


def test_module_docstring_first_line_is_non_empty() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "character_tools.character docstring must have a non-empty first line"


def test_every_public_api_name_is_a_real_module_attribute() -> None:
    names = _public_api_names()
    assert names, "expected a non-empty 'Public API' section in the docstring"
    for name in sorted(names):
        assert hasattr(character, name), (
            f"{name} is listed under Public API but is not an attribute of "
            f"{character.__name__}"
        )


def test_required_public_names_are_documented() -> None:
    doc = "\n".join(_doc_lines())
    for name in (
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
    ):
        assert name in doc, (
            f"{name} must be documented by name instead of duplicating the "
            f"behaviour in prose"
        )


def test_every_parser_option_appears_in_module_docstring() -> None:
    options = {
        option
        for action in _iter_parser_actions(character.build_parser())
        for option in action.option_strings
        if option not in ("-h", "--help")
    }
    assert options, "expected CLI options beyond --help"
    doc = "\n".join(_doc_lines())
    for option in sorted(options):
        assert option in doc, (
            f"{option} is defined by build_parser() but missing from the "
            f"character_tools.character docstring"
        )


def test_every_documented_flag_is_a_real_parser_option() -> None:
    real = _parser_option_strings()
    doc = "\n".join(_doc_lines())
    tokens = _DOC_FLAG_RE.findall(doc)
    assert tokens, "expected --flag tokens in the character_tools.character docstring"
    for token in tokens:
        assert token in real, (
            f"{token} appears in the docstring but is not a build_parser() option"
        )


def test_help_contains_docstring_first_line() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "module docstring must have a non-empty first line"
    assert first_line in character.build_parser().format_help()


def test_public_spine_steps_are_not_extended() -> None:
    assert intake.PUBLIC_SPINE_STEPS == (
        "intake",
        "review_select",
        "multi_crop",
        "finish_package",
    )
    assert not hasattr(character, "PUBLIC_SPINE_STEPS"), (
        "character-tools is an optional middle tool and must not define its "
        "own spine steps"
    )
