r"""Close a pickkit batch: finish the manifest and stage a copy-only delivery ZIP.

This module is the single source of truth for finish-package behaviour: how a
batch is validated as intake'd, how the allowlist is loaded from the intake
inventory, which content roots are scanned, how every scanned file is
classified against the allowlist and the default bans, how the copy-only
delivery ZIP is written (never modifying source bytes), and how the manifest
is closed on commit. The private precursor had an interactive wizard UI,
client project IDs, pre-made delivery paths, rclone upload tips, and SQLite
wiring; pickkit's finish-package is a library + thin CLI + local web wizard
that only reads source files and writes its own ZIP plus manifest/audit
updates.

Principles
----------
Library first
    :func:`finish_package` is the whole behaviour; the CLI in this module is a
    thin wrapper around it.
Interactive UI
    ``pickkit-finish <batch_root> --ui`` starts the local Flask wizard in
    ``finish_package.ui`` (``--host`` / ``--port`` override the 127.0.0.1:8767
    defaults, and are only valid together with ``--ui``). The page opens on
    a dry-run eligible/excluded preview and writes nothing until **Commit
    ZIP** (the same write as ``--commit``). The Force checkbox matches
    ``--force``: it may overwrite an existing ZIP only, never source bytes.
Batch must be intake'd
    ``<batch_root>/.pickkit/project.json`` must already exist (created by
    intake-init). Anything else is refused with :class:`FileNotFoundError`
    before any ZIP is written.
Allowlist from inventory
    The allowlist is ``allowedExtensions`` from
    ``<batch_root>/.pickkit/allowed_ext.json`` (lowercase, no dots). A missing
    inventory is refused with :class:`FileNotFoundError` before any ZIP is
    written. :func:`load_allowlist` is the single loader.
Content roots
    By default the scan is the union of :data:`SELECTED_DIR_NAME`
    (``__selected``) and :data:`CROPPED_DIR_NAME` (``__cropped``) under the
    batch root when they exist; missing roots are skipped. ``__crop`` (the
    review-select crop queue), ``__reject``, and ``.pickkit/`` are never
    scanned by default. The library ``content=`` / CLI ``--content`` override
    selects a single explicit directory that must resolve under the batch
    root, and is still subject to the allowlist, ban, and hidden rules.
Allowlist + bans
    A file is eligible when its lowercase, dot-free extension is in the
    allowlist and no ban applies. Evaluation order is
    ``hidden`` -> ``no_extension`` -> ``banned_ext`` -> ``banned_pattern`` ->
    ``not_allowed`` -> else ``eligible``. Bans win over the allowlist: a
    banned extension is never included even when it appears in
    ``allowedExtensions``.
Default bans (public kit; hardcoded module constants documented here)
    * ``hidden`` — any path with a hidden path part (a segment starting with
      ``.``). This keeps ``.pickkit`` out even if it were somehow scanned.
    * ``no_extension`` — extensionless files.
    * ``banned_ext`` — :data:`DEFAULT_BANNED_EXTENSIONS` (lowercase, no dots):
      ``json``, ``md``, ``log``, ``csv``, ``sqlite``, ``db``, ``lock``.
    * ``banned_pattern`` — basenames matching any regex in
      :data:`DEFAULT_BANNED_PATTERNS` (``.*\.project\.(json|yml)$``).
    v1 hardcodes these defaults; a future override hook/arg for custom bans is
    out of scope (see Out of scope).
Dry-run vs commit
    Default is dry-run (``commit=False``): the eligible/excluded report is
    computed and **nothing** is written — no ZIP, no ``finished_at``, no
    metrics write, no finish.jsonl, no audit.jsonl. The inventory and manifest
    may still be read. ``--commit`` / ``commit=True`` writes the ZIP and then
    updates the manifest.
ZIP destination
    Default: ``<batch_root>/delivery.zip`` — :data:`DEFAULT_ZIP_NAME`. The
    library ``output_zip=`` / CLI ``--output`` override accepts an explicit
    path; relative paths resolve under the batch root and absolute paths are
    allowed. ``lib_safety.require_new_file`` refuses an existing ZIP unless
    ``force=True`` / ``--force``. ``force`` may overwrite the ZIP only, never
    a source image: the existing ZIP is unlinked only after confirming the
    resolved ZIP path is not one of the scanned source files.
ZIP member names
    Arcnames are paths relative to the batch root, preserving content-root
    prefixes (``__selected/img_001.png``, ``__cropped/img_002.png``).
    ``.pickkit/...`` never appears in the archive.
Copy-only
    Compression is ``zipfile.ZIP_STORED`` (documented default). Eligible files
    are streamed with ``ZipFile.write``; source file bytes are never modified.
Companions
    Same-stem sidecars under the scanned content trees are included when they
    pass the allowlist and bans (a normal walk is enough). A companion with a
    banned or not-allowed extension is excluded under the matching bucket; v1
    has no strict-fail companion-integrity mode.
Manifest close (commit only)
    On successful commit the manifest is updated: top-level ``finished_at`` is
    set to ``utc_now()`` (ISO-8601 UTC ``Z``); the ``steps`` entry named
    :data:`FINISH_PACKAGE_STEP_NAME` gets ``started_at`` set when null,
    ``finished_at`` set, and ``images_processed`` set to the count of eligible
    files whose suffix is an image suffix per intake's
    ``DEFAULT_IMAGE_SUFFIXES``; and ``metrics.stager`` is filled with the
    snake_case shape reserved by intake-init.
Audit and finish log (commit only)
    One ``finish_package`` audit event is appended to
    ``<batch_root>/.pickkit/audit.jsonl`` via ``lib_safety.JsonlAuditHook``
    and to the optional caller hook. A best-effort append-only summary record
    is also written to ``<batch_root>/.pickkit/finish.jsonl``. Dry-run records
    an event on the caller hook only and writes no audit.jsonl / finish.jsonl.

Public API
----------
``finish_package(batch_root, *, commit=False, force=False, content=None, output_zip=None, hook=None)``
    Validate *batch_root* is intake'd, load the allowlist, scan the content
    roots, classify files, and either return a dry-run report (default) or
    write the delivery ZIP and close the manifest (``commit=True``). Raises
    :class:`FileNotFoundError` when the batch is missing/not intake'd or the
    inventory is missing, :class:`ValueError` when ``content`` resolves outside
    the batch root, and :class:`RefusedWriteError` when the ZIP exists without
    ``force``. Returns a :class:`FinishResult`.
``FinishResult``
    Frozen dataclass describing one run: ``batch_root``, ``commit``,
    ``zip_path`` (``Path | None``; None on dry-run), ``eligible_count``,
    ``by_ext_included``, ``excluded_counts``, ``incoming_by_ext``,
    ``finished_at`` (``str | None``; None on dry-run), ``manifest_path``,
    ``audit_path``, and ``finish_log_path``.
``load_manifest(path)``
    Read ``.pickkit/project.json`` and return it as a ``dict``. Raises
    :class:`ManifestError` (a :class:`ValueError` whose message names *path*)
    when the path is missing, a directory, unreadable, not valid UTF-8, not
    valid JSON, or JSON that is not an object (array, number, string, bool,
    or null).
``load_allowlist(path)``
    Read an intake inventory JSON and return its ``allowedExtensions`` as a
    ``set[str]`` of lowercase, dot-free extensions. Raises
    :class:`FileNotFoundError` when the file is missing and
    :class:`ValueError` when ``allowedExtensions`` is not a list.
``classify_file(path, batch_root, *, allowed)``
    Classify one file against the default bans and *allowed* extension set and
    return one of :data:`EXCLUDED_BUCKETS` or ``"eligible"``, applying the
    documented evaluation order.
``default_content_roots(batch_root)``
    Return the default content roots as a list of :class:`Path`: the existing
    ``__selected`` / ``__cropped`` directories under *batch_root*, in that
    order. Missing roots are skipped.
``build_parser()``
    Return the argparse parser for the ``pickkit-finish`` CLI. The parser
    description is this module docstring. ``--commit`` writes the ZIP and
    closes the manifest; ``--force`` allows overwriting an existing ZIP;
    ``--content`` overrides the content directory; ``--output`` overrides the
    ZIP path; ``--ui`` starts the interactive web wizard from
    ``finish_package.ui`` (``--host`` / ``--port`` override its bind and are
    only valid together with ``--ui``).
``main(argv=None)``
    CLI entry point; parses args and calls :func:`finish_package`.
``EXCLUDED_BUCKETS``
    Tuple of the excluded-count bucket names, in documented order:
    ``("hidden", "banned_ext", "banned_pattern", "not_allowed",
    "no_extension")``.
``PICKKIT_DIR_NAME``
    Shared pickkit state directory name: ``.pickkit`` (matching intake-init).
``MANIFEST_NAME``
    Shared manifest filename under ``.pickkit``: ``project.json``.
``INVENTORY_NAME``
    Shared intake inventory filename under ``.pickkit``: ``allowed_ext.json``.
``AUDIT_NAME``
    Shared audit filename under ``.pickkit``: ``audit.jsonl``.
``FINISH_LOG_NAME``
    Optional append-only finish summary filename under ``.pickkit``:
    ``finish.jsonl``.
``FINISH_PACKAGE_STEP_NAME``
    Name of the public spine step this plugin owns in ``project.json``:
    ``finish_package``.
``DEFAULT_ZIP_NAME``
    Default delivery ZIP filename under the batch root: ``delivery.zip``.
``SELECTED_DIR_NAME``
    Locked public keep directory name: ``__selected`` (matching review-select).
``CROPPED_DIR_NAME``
    Locked public crop-output directory name: ``__cropped`` (matching
    multi-crop).
``CROP_QUEUE_DIR_NAME``
    Locked public crop-queue directory name: ``__crop`` (never scanned by
    default; matching multi-crop).
``REJECT_DIR_NAME``
    Locked public reject directory name: ``__reject`` (never scanned by
    default; matching review-select).
``DEFAULT_BANNED_EXTENSIONS``
    Tuple of banned extensions (lowercase, no dots): ``json``, ``md``,
    ``log``, ``csv``, ``sqlite``, ``db``, ``lock``.
``DEFAULT_BANNED_PATTERNS``
    Tuple of banned basename regex strings: ``.*\.project\.(json|yml)$``.
``OPERATION``
    Audit operation recorded for a successful finish-package run:
    ``finish_package``.

Examples
--------
Dry-run a batch (default; writes nothing) from the library::

    from finish_package import finish_package

    result = finish_package("tmp/batch_a")
    result.commit            # False
    result.zip_path          # None
    result.eligible_count    # 2

Commit the delivery ZIP and close the manifest::

    from finish_package import finish_package

    result = finish_package("tmp/batch_a", commit=True)
    result.zip_path           # tmp/batch_a/delivery.zip
    result.finished_at        # '2026-09-26T12:34:56Z'

Finish a batch from the CLI (dry-run, then commit)::

    pickkit-finish tmp/batch_a
    pickkit-finish tmp/batch_a --commit --force

Finish a batch interactively::

    pickkit-finish tmp/batch_a --ui

Interactive wizard
------------------
``pickkit-finish <batch_root> --ui`` starts the local Flask finish wizard from
``finish_package.ui``. It binds ``127.0.0.1:8767`` by default (``--host`` /
``--port`` override it and are only valid together with ``--ui``), always
opens with a dry-run preview of the eligible/excluded report, and confirms
before writing the delivery ZIP. The wizard is documented in the module
docstring of ``finish_package.ui``; every refresh and commit still calls
:func:`finish_package` in this module.

Out of scope
------------
Custom bans JSON files / allowlist override files (v1 hardcodes
``DEFAULT_BANNED_EXTENSIONS`` + ``DEFAULT_BANNED_PATTERNS``), uploading the
ZIP (rclone etc.), strict companion-integrity failure mode, and scanning
``__crop`` / ``__reject`` / batch-root loose files by default are **not**
this module's job. Desktop/Tk wizard variants and middle-spine tools are out
of scope too.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from intake_init import DEFAULT_IMAGE_SUFFIXES
from lib_safety import (
    NULL_HOOK,
    AuditEvent,
    AuditHook,
    JsonlAuditHook,
    RefusedWriteError,
    require_new_file,
)
from lib_safety.audit import utc_now

#: Shared pickkit state directory and file names (matching intake-init).
PICKKIT_DIR_NAME = ".pickkit"
MANIFEST_NAME = "project.json"
INVENTORY_NAME = "allowed_ext.json"
AUDIT_NAME = "audit.jsonl"

#: Optional append-only finish summary written under ``<batch_root>/.pickkit/``.
FINISH_LOG_NAME = "finish.jsonl"

#: Name of the public spine step this plugin owns in ``project.json``.
FINISH_PACKAGE_STEP_NAME = "finish_package"

#: Default delivery ZIP filename under the batch root.
DEFAULT_ZIP_NAME = "delivery.zip"

#: Locked public content directory names under the batch root (matching
#: review-select / multi-crop). ``__crop`` and ``__reject`` are documented as
#: never-scanned-by-default conventions.
SELECTED_DIR_NAME = "__selected"
CROPPED_DIR_NAME = "__cropped"
CROP_QUEUE_DIR_NAME = "__crop"
REJECT_DIR_NAME = "__reject"

#: Default banned extensions (lowercase, no dots). Bans win over the allowlist.
DEFAULT_BANNED_EXTENSIONS: tuple[str, ...] = (
    "json",
    "md",
    "log",
    "csv",
    "sqlite",
    "db",
    "lock",
)

#: Default banned basename regex patterns. Any match excludes the file as
#: ``banned_pattern``.
DEFAULT_BANNED_PATTERNS: tuple[str, ...] = (r".*\.project\.(json|yml)$",)

#: Audit operation recorded for a successful finish-package run.
OPERATION = "finish_package"

#: Excluded-count bucket names, in documented report order.
EXCLUDED_BUCKETS: tuple[str, ...] = (
    "hidden",
    "banned_ext",
    "banned_pattern",
    "not_allowed",
    "no_extension",
)

_COMPILED_BANNED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern) for pattern in DEFAULT_BANNED_PATTERNS
)


@dataclass(frozen=True)
class FinishResult:
    """What :func:`finish_package` computed (dry-run) or wrote (commit).

    ``zip_path`` is the written ZIP on commit and ``None`` on dry-run.
    ``finished_at`` is the ISO-8601 UTC ``Z`` manifest close time on commit
    and ``None`` on dry-run. ``by_ext_included`` counts eligible files per
    lowercase, dot-free extension; ``excluded_counts`` always carries all
    :data:`EXCLUDED_BUCKETS` keys; ``incoming_by_ext`` counts every non-hidden
    scanned file with an extension before the allow/ban filter.
    """

    batch_root: Path
    commit: bool
    zip_path: Path | None
    eligible_count: int
    by_ext_included: dict[str, int]
    excluded_counts: dict[str, int]
    incoming_by_ext: dict[str, int]
    finished_at: str | None
    manifest_path: Path
    audit_path: Path
    finish_log_path: Path


class _FanoutHook:
    """Record one event to every wrapped hook (audit JSONL + caller hook)."""

    def __init__(self, *hooks: AuditHook) -> None:
        self._hooks = hooks

    def record(self, event: AuditEvent) -> None:
        for hook in self._hooks:
            hook.record(event)


def _as_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def _rel(root: Path, path: Path) -> str:
    """Return *path* relative to *root* (POSIX style) when it is under it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _matches_banned_pattern(basename: str) -> bool:
    return any(regex.search(basename) for regex in _COMPILED_BANNED_PATTERNS)


def _excluded_template() -> dict[str, int]:
    return {bucket: 0 for bucket in EXCLUDED_BUCKETS}


class ManifestError(ValueError):
    """``project.json`` could not be read as a JSON object.

    The message always names the manifest path. Callers (the CLI and the
    finish wizard) map this to an error response instead of a traceback.
    """


def load_manifest(path: str | Path) -> dict[str, object]:
    """Read *path* and return the manifest as a JSON object.

    Raises :class:`ManifestError` naming *path* when the path is missing, not
    a regular file, unreadable, not valid UTF-8, not valid JSON, or JSON that
    is not an object (``[]``, a number, a string, a bool, or ``null``).
    """
    manifest_path = _as_path(path)
    try:
        if manifest_path.is_dir():
            raise ManifestError(
                f"cannot read manifest {manifest_path}: path is a directory"
            )
        text = manifest_path.read_text(encoding="utf-8")
    except ManifestError:
        raise
    except UnicodeDecodeError as exc:
        raise ManifestError(
            f"manifest is not valid UTF-8: {manifest_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise ManifestError(
            f"cannot read manifest {manifest_path}: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(
            f"manifest is not valid JSON: {manifest_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ManifestError(
            f"manifest is not a JSON object: {manifest_path}"
        )
    return data


def load_allowlist(path: str | Path) -> set[str]:
    """Read an intake inventory JSON and return its ``allowedExtensions`` set.

    Extensions are normalized to lowercase without leading dots. Refuses with
    :class:`FileNotFoundError` when *path* is missing and with
    :class:`ValueError` when ``allowedExtensions`` is not a list.
    """
    inventory_path = _as_path(path)
    if not inventory_path.is_file():
        raise FileNotFoundError(
            f"allowlist inventory not found: {inventory_path}; "
            f"run pickkit-intake first"
        )
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    raw = data.get("allowedExtensions")
    if not isinstance(raw, list):
        raise ValueError(
            f"inventory has no 'allowedExtensions' list: {inventory_path}"
        )
    allowed: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(
                f"inventory 'allowedExtensions' entries must be strings: {entry!r}"
            )
        ext = entry.lower().lstrip(".")
        if ext:
            allowed.add(ext)
    return allowed


def classify_file(
    path: str | Path,
    batch_root: str | Path,
    *,
    allowed: set[str],
) -> str:
    """Classify one file against the default bans and the *allowed* set.

    Returns one of :data:`EXCLUDED_BUCKETS` (``hidden``, ``no_extension``,
    ``banned_ext``, ``banned_pattern``, ``not_allowed``) or ``"eligible"``,
    applying the documented order: hidden -> no_extension -> banned_ext ->
    banned_pattern -> not_allowed -> eligible.
    """
    file_path = _as_path(path)
    root = _as_path(batch_root)
    try:
        parts = file_path.relative_to(root).parts
    except ValueError:
        parts = file_path.parts
    if any(part.startswith(".") for part in parts):
        return "hidden"
    ext = file_path.suffix.lower().lstrip(".")
    if not ext:
        return "no_extension"
    if ext in DEFAULT_BANNED_EXTENSIONS:
        return "banned_ext"
    if _matches_banned_pattern(file_path.name):
        return "banned_pattern"
    if ext not in allowed:
        return "not_allowed"
    return "eligible"


def default_content_roots(batch_root: str | Path) -> list[Path]:
    """Return the existing default content roots under *batch_root*.

    The default scan is the union of :data:`SELECTED_DIR_NAME` and
    :data:`CROPPED_DIR_NAME`; missing roots are skipped. The returned list is
    ordered ``__selected`` then ``__cropped`` for deterministic scans.
    """
    root = _as_path(batch_root).resolve()
    candidates = (root / SELECTED_DIR_NAME, root / CROPPED_DIR_NAME)
    return [path for path in candidates if path.is_dir()]


def _resolve_content_override(root: Path, content: str | Path) -> Path:
    candidate = _as_path(content)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"content directory is outside batch root: {content}")
    if not resolved.exists():
        raise FileNotFoundError(f"content directory not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"content is not a directory: {resolved}")
    return resolved


def _resolve_zip_path(root: Path, output_zip: str | Path | None) -> Path:
    if output_zip is None:
        return root / DEFAULT_ZIP_NAME
    candidate = _as_path(output_zip)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _scan(
    batch_root: Path,
    content_roots: list[Path],
    allowed: set[str],
) -> tuple[
    list[Path], dict[str, int], dict[str, int], dict[str, int], list[Path]
]:
    """Walk *content_roots* and classify every file.

    Returns ``(eligible, by_ext_included, excluded_counts, incoming_by_ext,
    all_seen)``. ``all_seen`` is every file encountered (including hidden and
    excluded ones) and is used to guarantee ``--force`` never unlinks a source.
    """
    eligible: list[Path] = []
    by_ext_included: dict[str, int] = {}
    excluded_counts = _excluded_template()
    incoming_by_ext: dict[str, int] = {}
    all_seen: list[Path] = []

    for content_root in content_roots:
        for path in sorted(content_root.rglob("*")):
            if not path.is_file():
                continue
            all_seen.append(path)
            category = classify_file(path, batch_root, allowed=allowed)
            if category == "eligible":
                eligible.append(path)
                ext = path.suffix.lower().lstrip(".")
                by_ext_included[ext] = by_ext_included.get(ext, 0) + 1
            else:
                excluded_counts[category] += 1

            # incoming_by_ext counts non-hidden files with an extension before
            # the allow/ban filter; hidden and extensionless files are not
            # counted there (they have no usable extension).
            if category == "hidden" or category == "no_extension":
                continue
            ext = path.suffix.lower().lstrip(".")
            incoming_by_ext[ext] = incoming_by_ext.get(ext, 0) + 1

    eligible.sort(key=lambda p: _rel(batch_root, p))
    return (
        eligible,
        dict(sorted(by_ext_included.items())),
        excluded_counts,
        dict(sorted(incoming_by_ext.items())),
        all_seen,
    )


def _find_finish_package_step(
    steps: list[object], manifest_path: Path
) -> dict[str, object]:
    for step in steps:
        if isinstance(step, dict) and step.get("name") == FINISH_PACKAGE_STEP_NAME:
            return step
    raise ValueError(
        f"manifest has no '{FINISH_PACKAGE_STEP_NAME}' step: {manifest_path}"
    )


def _count_eligible_images(eligible: list[Path]) -> int:
    return sum(
        1 for path in eligible if path.suffix.lower() in DEFAULT_IMAGE_SUFFIXES
    )


def _write_zip(zip_path: Path, batch_root: Path, eligible: list[Path]) -> None:
    """Stream *eligible* files into a copy-only ``ZIP_STORED`` archive."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in eligible:
            archive.write(path, arcname=_rel(batch_root, path))


def _update_manifest(
    manifest_path: Path,
    root: Path,
    zip_path: Path,
    finished_at: str,
    eligible: list[Path],
    by_ext_included: dict[str, int],
    excluded_counts: dict[str, int],
    incoming_by_ext: dict[str, int],
) -> None:
    manifest = load_manifest(manifest_path)
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"manifest has no 'steps' list: {manifest_path}")
    step = _find_finish_package_step(steps, manifest_path)

    manifest["finished_at"] = finished_at
    if step.get("started_at") is None:
        step["started_at"] = finished_at
    step["finished_at"] = finished_at
    step["images_processed"] = _count_eligible_images(eligible)

    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    stager = metrics.get("stager")
    if not isinstance(stager, dict):
        stager = {}
    stager["zip"] = _rel(root, zip_path)
    stager["eligible_count"] = len(eligible)
    stager["by_ext_included"] = by_ext_included
    stager["excluded_counts"] = excluded_counts
    stager["incoming_by_ext"] = incoming_by_ext
    metrics["stager"] = stager
    manifest["metrics"] = metrics

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def finish_package(
    batch_root: str | Path,
    *,
    commit: bool = False,
    force: bool = False,
    content: str | Path | None = None,
    output_zip: str | Path | None = None,
    hook: AuditHook | None = None,
) -> FinishResult:
    """Finish *batch_root*: stage a copy-only delivery ZIP and close the manifest.

    Default is dry-run: the content roots are scanned and the eligible /
    excluded report is returned with **no** filesystem writes (no ZIP, no
    manifest changes, no audit.jsonl / finish.jsonl). The caller *hook*, when
    given, still receives one ``finish_package`` dry-run event.

    With ``commit=True`` the delivery ZIP is written first (default
    ``<batch_root>/delivery.zip``, or ``output_zip``), then the manifest is
    closed: top-level ``finished_at``, the ``finish_package`` step, and
    ``metrics.stager`` are updated, one audit event is appended to
    ``<batch_root>/.pickkit/audit.jsonl`` plus the caller *hook*, and a summary
    record is appended to ``<batch_root>/.pickkit/finish.jsonl``.

    Refuses with :class:`FileNotFoundError` when the batch root is missing, not
    a directory, not intake'd, or has no inventory; with :class:`ManifestError`
    when ``project.json`` cannot be read as a JSON object; with
    :class:`ValueError` when ``content`` resolves outside the batch root; and
    with :class:`RefusedWriteError` when the ZIP already exists without
    ``force``.
    ``force=True`` overwrites an existing ZIP only (never a scanned source).
    """
    root = _as_path(batch_root)
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()

    pickkit_dir = root / PICKKIT_DIR_NAME
    manifest_path = pickkit_dir / MANIFEST_NAME
    inventory_path = pickkit_dir / INVENTORY_NAME
    audit_path = pickkit_dir / AUDIT_NAME
    finish_log_path = pickkit_dir / FINISH_LOG_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"batch is not intake'd: missing manifest {manifest_path}; "
            f"run pickkit-intake first"
        )
    # Validate before any scan or ZIP write so a bad manifest cannot leave
    # a delivery ZIP behind. ManifestError names the path.
    load_manifest(manifest_path)

    allowed = load_allowlist(inventory_path)

    if content is None:
        content_roots = default_content_roots(root)
    else:
        content_roots = [_resolve_content_override(root, content)]

    hook = hook or NULL_HOOK
    eligible, by_ext_included, excluded_counts, incoming_by_ext, all_seen = _scan(
        root, content_roots, allowed
    )
    eligible_count = len(eligible)

    if not commit:
        # Dry-run: report only. Record on the caller hook (no audit.jsonl).
        hook.record(
            AuditEvent(
                operation=OPERATION,
                source=str(root),
                ok=True,
                reason=f"dry_run; eligible_count={eligible_count}",
            )
        )
        return FinishResult(
            batch_root=root,
            commit=False,
            zip_path=None,
            eligible_count=eligible_count,
            by_ext_included=by_ext_included,
            excluded_counts=excluded_counts,
            incoming_by_ext=incoming_by_ext,
            finished_at=None,
            manifest_path=manifest_path,
            audit_path=audit_path,
            finish_log_path=finish_log_path,
        )

    zip_path = _resolve_zip_path(root, output_zip)
    fanout = _FanoutHook(JsonlAuditHook(audit_path), hook)

    if zip_path.exists():
        if not force:
            require_new_file(zip_path, hook=fanout)
        # force: overwrite the ZIP only, never a scanned source file.
        resolved_zip = zip_path.resolve()
        if any(resolved_zip == path.resolve() for path in all_seen):
            raise RefusedWriteError(
                f"refusing to overwrite source file with delivery ZIP: {zip_path}"
            )
        zip_path.unlink()

    _write_zip(zip_path, root, eligible)

    finished_at = utc_now()
    _update_manifest(
        manifest_path,
        root,
        zip_path,
        finished_at,
        eligible,
        by_ext_included,
        excluded_counts,
        incoming_by_ext,
    )

    fanout.record(
        AuditEvent(
            operation=OPERATION,
            source=str(root),
            destination=str(zip_path),
            ok=True,
            reason=f"commit=True; eligible_count={eligible_count}",
        )
    )
    _append_jsonl(
        finish_log_path,
        {
            "timestamp": finished_at,
            "zip": _rel(root, zip_path),
            "eligible_count": eligible_count,
            "committed": True,
        },
    )

    return FinishResult(
        batch_root=root,
        commit=True,
        zip_path=zip_path,
        eligible_count=eligible_count,
        by_ext_included=by_ext_included,
        excluded_counts=excluded_counts,
        incoming_by_ext=incoming_by_ext,
        finished_at=finished_at,
        manifest_path=manifest_path,
        audit_path=audit_path,
        finish_log_path=finish_log_path,
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-finish`` CLI."""
    from .ui import DEFAULT_HOST, DEFAULT_PORT

    parser = argparse.ArgumentParser(
        prog="pickkit-finish",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "batch_root",
        help="Path to an already intake'd batch directory",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write the delivery ZIP and close the manifest (default is dry-run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing delivery ZIP (never overwrites source images)",
    )
    parser.add_argument(
        "--content",
        metavar="DIR",
        help=(
            "Scan a single explicit content directory instead of the default "
            "__selected/ + __cropped/ roots; must resolve under batch_root"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Write the ZIP to PATH instead of <batch_root>/delivery.zip; "
            "relative paths resolve under batch_root"
        ),
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Start the local interactive finish web wizard (Flask) instead of finishing",
    )
    parser.add_argument(
        "--host",
        metavar="HOST",
        default=DEFAULT_HOST,
        help=(
            "Host interface for the --ui web server "
            f"(default: {DEFAULT_HOST})"
        ),
    )
    parser.add_argument(
        "--port",
        metavar="PORT",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port for the --ui web server (default: {DEFAULT_PORT})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; parses args and calls :func:`finish_package`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from .ui import DEFAULT_HOST, DEFAULT_PORT

    if not args.ui and (args.host != DEFAULT_HOST or args.port != DEFAULT_PORT):
        parser.error("--host and --port may only be used together with --ui")

    if args.ui:
        from .ui import run_ui

        if args.commit or args.force or args.content or args.output:
            parser.error(
                "--ui cannot be combined with "
                "--commit/--force/--content/--output"
            )
        run_ui(args.batch_root, host=args.host, port=args.port)
        return 0

    try:
        result = finish_package(
            args.batch_root,
            commit=args.commit,
            force=args.force,
            content=args.content,
            output_zip=args.output,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError) as exc:
        parser.exit(1, f"pickkit-finish: error: {exc}\n")

    excluded = " ".join(
        f"{bucket}={result.excluded_counts[bucket]}" for bucket in EXCLUDED_BUCKETS
    )
    if result.commit:
        print(f"pickkit-finish: wrote zip {result.zip_path}")
        print(f"  finished_at: {result.finished_at}")
        print(f"  eligible_count: {result.eligible_count}")
        print(f"  excluded: {excluded}")
    else:
        print("pickkit-finish: dry-run complete (nothing written)")
        print(f"  batch_root: {result.batch_root}")
        print(f"  eligible_count: {result.eligible_count}")
        print(f"  excluded: {excluded}")
    return 0
