"""Shared test helpers for staging the sandbox batch and reading its records.

Test modules import these directly (``from conftest import stage_batch_a``):
the ``tests/`` directory has no ``__init__.py``, so pytest puts it on
``sys.path`` and this file is importable as ``conftest``.

Fixtures are staged (copied) from ``sandbox/batch_a/`` into a per-test
``tmp_path``; the committed sandbox is never mutated.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_A = REPO_ROOT / "sandbox" / "batch_a"


def stage_batch_a(tmp_path: Path) -> Path:
    """Copy sandbox/batch_a into tmp_path and return the staged root."""
    root = tmp_path / "batch_a"
    shutil.copytree(BATCH_A, root)
    return root


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl_lines(path: Path) -> list[dict[str, object]]:
    """Every non-blank line of a JSONL file, or ``[]`` when it does not exist."""
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def snapshot(directory: Path) -> dict[str, bytes]:
    """Relative path -> bytes for every file under *directory*."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
