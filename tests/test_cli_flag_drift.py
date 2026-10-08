"""Fail if a pickkit CLI flag and its --help text drift apart.

Each console script builds its parser with description=<module>.__doc__, so
the module docstring is the manual. Every flag the parser accepts (except
-h/--help) must appear in that docstring, and every --flag token in the
docstring must be a real parser option, including subcommands.
"""

from __future__ import annotations

import argparse
import re

import character_tools.character as character
import directory_viewer.viewer as viewer
import duplicate_finder.dupes as dupes
import finish_package.finish as finish
import intake_init.intake as intake
import multi_crop.crop as crop
import review_select.review as review

_DOC_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")

_CLIS = (
    intake,
    review,
    crop,
    finish,
    character,
    dupes,
    viewer,
)


def _iter_actions(parser: argparse.ArgumentParser):
    for action in parser._actions:
        yield action
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _iter_actions(sub)


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in _iter_actions(parser)
        for option in action.option_strings
    }


def test_cli_flags_match_module_docstrings() -> None:
    for module in _CLIS:
        doc = module.__doc__ or ""
        parser = module.build_parser()
        real = _option_strings(parser)
        assert real - {"-h", "--help"}, f"{parser.prog}: expected CLI options beyond --help"
        assert _DOC_FLAG_RE.findall(doc), (
            f"{parser.prog}: expected --flag tokens in the module docstring"
        )
        missing = sorted(
            option
            for option in real
            if option not in ("-h", "--help") and option not in doc
        )
        assert not missing, (
            f"{parser.prog}: flag(s) missing from the module docstring: {missing}"
        )
        invented = sorted(
            token for token in _DOC_FLAG_RE.findall(doc) if token not in real
        )
        assert not invented, (
            f"{parser.prog}: docstring mentions flag(s) the parser does not have: {invented}"
        )
        first = doc.strip().splitlines()[0].strip()
        assert first in parser.format_help()
