"""Small helpers shared by the pickkit batch engines.

The review, crop, finish, character and duplicate engines each used to carry
their own copy of these; this module is the one copy they import. Every error
message is part of the engines' contracts and must stay byte-identical.

Public API
----------
``rel_path(root, path)``
    Return *path* relative to *root* in POSIX form, or ``str(path)`` when
    it is not under *root*.
``append_jsonl(path, record)``
    Append *record* as one JSON line (keys unsorted), creating parent
    directories first.
``find_step(manifest, name, manifest_path)``
    Return the ``steps`` entry called *name* from a loaded ``project.json``.
    Raises :class:`ValueError` naming *manifest_path* when ``steps`` is not a
    list or has no such entry.
``write_manifest(manifest_path, manifest)``
    Write *manifest* as two-space-indented JSON with a trailing newline.
``load_json_records(path, label, convert)``
    Read a JSON array file, or a ``.jsonl`` file with one object per line
    (blank lines skipped), and return ``convert(record, path, index)`` for
    each record. Errors name *label*, e.g. ``"decisions file not found: ..."``.
``normalise_suffix_set(suffixes, default)``
    Return *suffixes* (or *default* when ``None``) as a set of lowercase,
    dot-prefixed suffixes; a bare string counts as one suffix.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def rel_path(root: Path, path: Path) -> str:
    """Return *path* relative to *root* (POSIX style) when it is under it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    """Append *record* to *path* as one JSON line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def find_step(
    manifest: dict[str, object], name: str, manifest_path: Path
) -> dict[str, object]:
    """Return the ``steps`` entry called *name* from *manifest*."""
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"manifest has no 'steps' list: {manifest_path}")
    for step in steps:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    raise ValueError(f"manifest has no '{name}' step: {manifest_path}")


def write_manifest(manifest_path: Path, manifest: dict[str, object]) -> None:
    """Write *manifest* to *manifest_path* as indented JSON."""
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def load_json_records(
    path: str | Path,
    label: str,
    convert: Callable[[object, Path, int], T],
) -> list[T]:
    """Load records from a JSON array file or a JSONL file.

    A ``.jsonl`` file is read one JSON value per line (blank lines skipped,
    *index* is the line number); any other file must hold a JSON array
    (*index* counts from 1). *convert* turns each record into the result.
    """
    records_file = Path(path).expanduser()
    if not records_file.is_file():
        raise FileNotFoundError(f"{label} not found: {records_file}")

    if records_file.suffix.lower() == ".jsonl":
        records: list[T] = []
        for line_no, raw in enumerate(
            records_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL in {records_file} at line {line_no}: {exc}"
                ) from exc
            records.append(convert(record, records_file, line_no))
        return records

    try:
        data = json.loads(records_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {records_file}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{label} must contain a JSON array: {records_file}")
    return [
        convert(record, records_file, index)
        for index, record in enumerate(data, start=1)
    ]


def normalise_suffix_set(suffixes: object, default: Iterable[str]) -> set[str]:
    """Return *suffixes* (or *default*) as lowercase, dot-prefixed suffixes."""
    if suffixes is None:
        raw: Iterable[str] = default
    elif isinstance(suffixes, str):
        raw = (suffixes,)
    else:
        raw = tuple(suffixes)  # type: ignore[arg-type]
    allowed: set[str] = set()
    for suffix in raw:
        lowered = suffix.lower()
        if not lowered.startswith("."):
            lowered = f".{lowered}"
        if lowered != ".":
            allowed.add(lowered)
    return allowed
