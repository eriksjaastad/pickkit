"""Drift-guards for the ``duplicate_finder.dupes`` module docstring.

The module docstring is the single source of truth for duplicate-finder
behaviour and is reused as the CLI ``--help`` description, so these tests pin
it to the module and the parser: the first line must be non-empty, every name
in its "Public API" section must be a real attribute, the locked constants and
result dataclasses must be documented by name, every parser option must be
documented, every ``--flag`` token in the docstring must be a real parser
option, and ``--help`` must open with the docstring's first line. The public
spine stays intake / review_select / multi_crop / finish_package — this
optional middle tool must not extend it — and duplicate_finder must not have a
cross-plugin hard dependency on character_tools.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import duplicate_finder.dupes as dupes
import intake_init.intake as intake

#: A documented public name opens a double-backtick span, e.g.
#: ``content_hash(path) -> str`` -> ``content_hash``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")


def _doc_lines() -> list[str]:
    doc = dupes.__doc__
    assert doc is not None, "duplicate_finder.dupes docstring must exist"
    return doc.splitlines()


def _section_lines(heading: str) -> list[str]:
    doc = _doc_lines()
    underline_chars = frozenset("-=~^")
    for i, line in enumerate(doc):
        stripped_next = doc[i + 1].strip() if i + 1 < len(doc) else ""
        if (
            line.strip() == heading
            and len(stripped_next) >= 3
            and stripped_next[0] in underline_chars
            and all(ch == stripped_next[0] for ch in stripped_next)
        ):
            start = i + 2
            break
    else:
        return []
    lines: list[str] = []
    j = start
    while j < len(doc):
        stripped_next = doc[j + 1].strip() if j + 1 < len(doc) else ""
        if (
            j + 1 < len(doc)
            and doc[j].strip()
            and len(stripped_next) >= 3
            and stripped_next[0] in underline_chars
            and all(ch == stripped_next[0] for ch in stripped_next)
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


def _iter_parser_actions(parser: argparse.ArgumentParser):
    for action in parser._actions:
        yield action
        if isinstance(action, argparse._SubParsersAction):
            for sub_parser in action.choices.values():
                yield from _iter_parser_actions(sub_parser)


def _parser_option_strings() -> set[str]:
    return {
        option
        for action in _iter_parser_actions(dupes.build_parser())
        for option in action.option_strings
    }


def test_module_docstring_first_line_is_non_empty() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "duplicate_finder.dupes docstring must have a non-empty first line"


def test_every_public_api_name_is_a_real_module_attribute() -> None:
    names = _public_api_names()
    assert names, "expected a non-empty 'Public API' section in the docstring"
    for name in sorted(names):
        assert hasattr(dupes, name), (
            f"{name} is listed under Public API but is not an attribute of "
            f"{dupes.__name__}"
        )


def test_required_public_names_are_documented() -> None:
    doc = "\n".join(_doc_lines())
    for name in (
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
    ):
        assert name in doc, (
            f"{name} must be documented by name instead of duplicating the "
            f"behaviour in prose"
        )


def test_locked_product_defaults_are_documented_and_real() -> None:
    assert dupes.DEFAULT_IMAGE_SUFFIXES == (
        ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    )
    assert dupes.HASH_SIZE == 8
    assert dupes.DEFAULT_NEAR_THRESHOLD == 5
    assert dupes.KEEP_POLICIES == ("keep_first", "keep_largest", "keep_oldest")
    assert dupes.DEFAULT_KEEP_POLICY == "keep_first"
    assert dupes.OPERATION == "duplicate_finder"

    doc = "\n".join(_doc_lines())
    assert "non-recursive" in doc
    assert "sha256" in doc
    assert "average hash" in doc
    assert "seed-neighbour" in doc
    assert "companions=True" in doc


def test_every_parser_option_appears_in_module_docstring() -> None:
    options = {
        option
        for action in _iter_parser_actions(dupes.build_parser())
        for option in action.option_strings
        if option not in ("-h", "--help")
    }
    assert options, "expected CLI options beyond --help"
    doc = "\n".join(_doc_lines())
    for option in sorted(options):
        assert option in doc, (
            f"{option} is defined by build_parser() but missing from the "
            f"duplicate_finder.dupes docstring"
        )


def test_every_documented_flag_is_a_real_parser_option() -> None:
    real = _parser_option_strings()
    doc = "\n".join(_doc_lines())
    tokens = re.findall(r"--[a-z][a-z0-9-]*", doc)
    assert tokens, "expected --flag tokens in the duplicate_finder.dupes docstring"
    for token in tokens:
        assert token in real, (
            f"{token} appears in the docstring but is not a build_parser() option"
        )


def test_help_contains_docstring_first_line() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "module docstring must have a non-empty first line"
    assert first_line in dupes.build_parser().format_help()


def test_public_spine_steps_are_not_extended() -> None:
    assert intake.PUBLIC_SPINE_STEPS == (
        "intake",
        "review_select",
        "multi_crop",
        "finish_package",
    )
    assert not hasattr(dupes, "PUBLIC_SPINE_STEPS"), (
        "duplicate-finder is an optional middle tool and must not define its "
        "own spine steps"
    )


def test_no_cross_plugin_hard_dependency_on_character_tools() -> None:
    source = Path(dupes.__file__).read_text(encoding="utf-8")
    assert "import character_tools" not in source
    assert "from character_tools" not in source


def test_console_script_is_wired_in_pyproject() -> None:
    pyproject = (
        Path(dupes.__file__).resolve().parents[2] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert 'pickkit-dupes = "duplicate_finder.dupes:main"' in pyproject
