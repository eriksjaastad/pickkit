"""Drift-guards for the ``finish_package.finish`` module docstring.

The module docstring is the single source of truth for finish-package
behaviour and is reused as the CLI ``--help`` description, so these tests pin
it to the module and the parser: the first line must be non-empty, every name
in its "Public API" section must be a real attribute, the locked constants and
the metrics.stager snake_case keys must be documented by name, every parser
option must be documented, every ``--flag`` token in the docstring must be a
real parser option, and ``--help`` must open with the docstring's first line.
The shared ``.pickkit`` path/file names must also match intake-init's.
"""

from __future__ import annotations

import re

import finish_package.finish as finish
import intake_init.intake as intake

#: A documented public name opens a double-backtick span, e.g.
#: ``finish_package(batch_root, *, commit=False, ...)`` -> ``finish_package``.
_NAME_RE = re.compile(r"``([A-Za-z_][A-Za-z0-9_]*)")


def _doc_lines() -> list[str]:
    doc = finish.__doc__
    assert doc is not None, "finish_package.finish docstring must exist"
    return doc.splitlines()


def _is_underline(line: str) -> bool:
    """True for a reST-style section underline (at least three same chars)."""
    stripped = line.strip()
    return (
        len(stripped) >= 3
        and stripped[0] in "-=~^"
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


def _parser_option_strings() -> set[str]:
    return {
        option
        for action in finish.build_parser()._actions
        for option in action.option_strings
    }


def test_module_docstring_first_line_is_non_empty() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "finish_package.finish docstring must have a non-empty first line"


def test_every_public_api_name_is_a_real_module_attribute() -> None:
    names = _public_api_names()
    assert names, "expected a non-empty 'Public API' section in the docstring"
    for name in sorted(names):
        assert hasattr(finish, name), (
            f"{name} is listed under Public API but is not an attribute of "
            f"{finish.__name__}"
        )


def test_required_public_names_are_documented() -> None:
    doc = "\n".join(_doc_lines())
    for name in (
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
    ):
        assert name in doc, (
            f"{name} must be documented by name instead of duplicating the "
            f"paths/layout in prose"
        )


def test_stager_metric_keys_documented() -> None:
    doc = "\n".join(_doc_lines())
    for key in (
        "zip",
        "eligible_count",
        "by_ext_included",
        "excluded_counts",
        "incoming_by_ext",
    ):
        assert key in doc, (
            f"metrics.stager key {key!r} must be documented in the module docstring"
        )


def test_excluded_buckets_documented() -> None:
    doc = "\n".join(_doc_lines())
    for bucket in ("hidden", "banned_ext", "banned_pattern", "not_allowed", "no_extension"):
        assert bucket in doc, (
            f"excluded bucket {bucket!r} must be documented in the module docstring"
        )


def test_every_parser_option_appears_in_module_docstring() -> None:
    options = {
        option
        for action in finish.build_parser()._actions
        for option in action.option_strings
        if option not in ("-h", "--help")
    }
    assert options, "expected CLI options beyond --help"
    doc = "\n".join(_doc_lines())
    for option in sorted(options):
        assert option in doc, (
            f"{option} is defined by build_parser() but missing from the "
            f"finish_package.finish docstring"
        )


def test_every_documented_flag_is_a_real_parser_option() -> None:
    real = _parser_option_strings()
    doc = "\n".join(_doc_lines())
    tokens = re.findall(r"--[a-z][a-z0-9-]*", doc)
    assert tokens, "expected --flag tokens in the finish_package.finish docstring"
    for token in tokens:
        assert token in real, (
            f"{token} appears in the docstring but is not a build_parser() option"
        )


def test_help_contains_docstring_first_line() -> None:
    first_line = _doc_lines()[0].strip()
    assert first_line, "module docstring must have a non-empty first line"
    assert first_line in finish.build_parser().format_help()


def test_shared_pickkit_paths_match_intake_init() -> None:
    assert finish.PICKKIT_DIR_NAME == intake.PICKKIT_DIR_NAME
    assert finish.MANIFEST_NAME == intake.MANIFEST_NAME
    assert finish.INVENTORY_NAME == intake.INVENTORY_NAME
    assert finish.AUDIT_NAME == intake.AUDIT_NAME
