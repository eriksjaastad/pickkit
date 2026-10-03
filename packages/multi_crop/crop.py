"""Create NEW cropped image files from axis-aligned pixel boxes.

This module is the single source of truth for multi-crop behaviour: how a
batch is validated as intake'd, how axis-aligned ``(left, top, right,
bottom)`` pixel boxes are clamped to image bounds, how NEW raster files are
written under ``__cropped`` (never overwriting originals), how the append-only
crops log is written, how the ``multi_crop`` step in ``project.json`` is
updated, and how each applied crop is audited. The private precursor had an
interactive desktop UI with AI sidecar preload, client IDs, and training
wiring; pickkit's multi-crop is a small batch library + thin CLI that only
writes new cropped raster files and appends logs.

Principles
----------
Library first
    :func:`crop_batch` is the batch behaviour; the CLI in this module is a
    thin wrapper around it. :func:`apply_crop` is the low-level single-crop
    primitive and is usable standalone (no intake required).
Interactive UI
    ``pickkit-crop <batch_root> --ui`` starts the local Flask crop page in
    ``multi_crop.ui`` (``--host`` / ``--port`` override the 127.0.0.1:8766
    defaults). The UI calls :func:`crop_batch` for every Apply — it never
    reimplements pixel writes, crops-log records, or manifest updates. Drag
    an axis-aligned rectangle. Keyboard shortcuts are ``Enter`` apply,
    ``S`` skip, and ``R`` reset the rectangle.
Batch must be intake'd
    ``<batch_root>/.pickkit/project.json`` must already exist (created by
    intake-init). Batch mode refuses with :class:`FileNotFoundError` before
    any crop is written or any directory is created.
Inputs
    Sources may live anywhere under the batch root. The typical input is the
    review-select crop queue :data:`CROP_QUEUE_DIR_NAME` (``__crop``), but a
    spec may point at any explicit relative or absolute source path under the
    batch root.
New files only, never overwrite
    Every crop is written to a NEW path; ``lib_safety.require_new_file``
    refuses any destination that already exists (including the source itself)
    with :class:`lib_safety.errors.RefusedWriteError`. Sources are never
    moved, deleted, or rewritten.
Output directory
    New rasters land under :data:`CROPPED_DIR_NAME` (``__cropped``) under the
    batch root, created on first need only. The default destination basename
    keeps the source stem + suffix (``img_002.png`` → ``__cropped/img_002.png``).
    If that path exists the crop is refused — no silent rename. Callers who
    need multiple crops of one source pass an explicit ``destination``.
Crop geometry
    Boxes are axis-aligned pixel boxes ``(left, top, right, bottom)`` with
    Pillow ``Image.crop`` semantics: ``right``/``bottom`` are exclusive.
    :func:`clamp_box` clamps every coordinate to the image bounds and
    guarantees at least 1px width and height. Normalized [0,1] coordinates
    and AI sidecar preload are not accepted.
Companions left alone
    Only the new cropped raster is written. Same-stem sidecars (yaml/txt)
    are never copied, rewritten, or moved in v1.
Crops log
    One JSON object per applied crop is appended to
    ``<batch_root>/.pickkit/crops.jsonl`` with snake_case keys: ``timestamp``,
    ``source``, ``destination``, ``box`` (list ``[left, top, right, bottom]``),
    plus ``note`` only when a note was given. Relative paths from the batch
    root are preferred. Existing lines are never read or rewritten.
Manifest step update
    The existing ``multi_crop`` entry in ``project.json`` ``steps`` is
    updated in place: ``started_at`` is set on the first applied crop when
    null, ``images_processed`` increments per applied crop, and
    ``finished_at`` is set only when the caller passes the explicit ``finish``
    flag (CLI ``--finish``). No finish ZIP is created here.
Audit
    Each applied crop is recorded through a ``JsonlAuditHook`` on
    ``<batch_root>/.pickkit/audit.jsonl`` and on the optional caller hook
    with operation ``multi_crop``. Refused writes are audited through the
    same hooks by ``require_new_file``.

Public API
----------
``CROPPED_DIR_NAME``
    Locked public output directory name: ``__cropped`` (new crops out).
``CROP_QUEUE_DIR_NAME``
    Locked public crop-queue directory name: ``__crop`` (typical review-select
    crop queue in). Documented as a convention, not required by this module.
``PICKKIT_DIR_NAME``
    Shared pickkit state directory name: ``.pickkit`` (matching intake-init).
``MANIFEST_NAME``
    Shared manifest filename under ``.pickkit``: ``project.json``.
``AUDIT_NAME``
    Shared audit filename under ``.pickkit``: ``audit.jsonl``.
``CROPS_LOG_NAME``
    Append-only crops log filename under ``.pickkit``: ``crops.jsonl``.
``MULTI_CROP_STEP_NAME``
    Name of the public spine step this plugin owns in ``project.json``:
    ``multi_crop``.
``CropSpec``
    Frozen dataclass describing one crop: ``source`` (image path or relative
    name under the batch root), ``box`` (``(left, top, right, bottom)``
    integer pixel box), optional ``destination`` (relative name under
    ``__cropped`` or absolute path under the batch root), optional ``note``,
    and ``timestamp`` (UTC ``Z`` by default).
``ApplyResult``
    Frozen dataclass describing an applied run: ``batch_root``,
    ``crops_applied``, ``destinations`` (relative paths of written crops),
    ``finished``, ``manifest_path``, and ``crops_log_path``.
``clamp_box(box, width, height)``
    Clamp *box* to a ``width`` x ``height`` image and return
    ``(left, top, right, bottom)`` with at least 1px width and height.
``apply_crop(source, box, destination, *, hook=None)``
    Open *source* with Pillow, clamp *box* to the image bounds, guard
    *destination* with ``lib_safety.require_new_file``, and save a NEW
    cropped raster there. Returns the destination :class:`Path`. Does not
    require intake, does not touch companions, and records one ``multi_crop``
    audit event on *hook* when given.
``crop_batch(batch_root, specs, *, finish=False, hook=None)``
    Validate *batch_root* is intake'd, then apply every :class:`CropSpec`,
    writing each crop under ``__cropped`` (default) or the spec's explicit
    ``destination``, appending crops-log records, auditing, and updating the
    manifest ``multi_crop`` step. With ``finish=True`` (CLI ``--finish``) the
    step's ``finished_at`` is set after crops are applied. Returns an
    :class:`ApplyResult`.
``load_crop_specs(path)``
    Read crop specs from a JSON array file or a JSONL file (one
    ``{"source": ..., "box": [...], ...}`` object per line) and return them
    as a list of :class:`CropSpec`.
``build_parser()``
    Return the argparse parser for the ``pickkit-crop`` CLI. The parser
    description is this module docstring. ``--crops`` loads a JSON/JSONL
    specs file; ``--source`` and ``--box`` accept one source and one
    ``L,T,R,B`` box each, are repeatable, and pair positionally; ``--finish``
    marks the step finished after applying; ``--ui`` starts the interactive
    web UI from ``multi_crop.ui`` (with optional ``--host`` / ``--port``
    overrides for its 127.0.0.1:8766 defaults).
``main(argv=None)``
    CLI entry point; parses args and calls :func:`crop_batch` (or
    :func:`multi_crop.ui.run_ui` when ``--ui`` is set).

Examples
--------
Crop one image from the library (no intake required)::

    from multi_crop import apply_crop

    apply_crop("img_002.png", (10, 10, 50, 40), "__cropped/img_002.png")

Apply a batch from the crop queue::

    from multi_crop import CropSpec, crop_batch

    result = crop_batch(
        "tmp/batch_a",
        [CropSpec("__crop/img_002.png", (10, 10, 50, 40))],
    )
    result.crops_applied        # 1
    result.destinations         # ("__cropped/img_002.png",)

Crop a batch from the CLI::

    pickkit-crop tmp/batch_a --crops crops.jsonl --finish

Start the interactive crop UI::

    pickkit-crop tmp/batch_a --ui

Out of scope
------------
Interactive UI is **no longer** out of scope: ``multi_crop.ui`` implements
the local Flask crop page and ``pickkit-crop <batch_root> --ui`` starts it
(see that module's docstring for UI behaviour, host/port, shortcuts, box
mapping, and routes). AI crop preload / training / SQLite, normalized
[0,1] coordinates, moving/deleting sources after crop, finish-package ZIP
staging, and companion sidecar rewriting are **not** this module's job.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

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
AUDIT_NAME = "audit.jsonl"

#: Append-only crops log written under ``<batch_root>/.pickkit/``.
CROPS_LOG_NAME = "crops.jsonl"

#: Name of the public spine step this plugin owns in ``project.json``.
MULTI_CROP_STEP_NAME = "multi_crop"

#: Locked public output directory name for NEW cropped rasters.
CROPPED_DIR_NAME = "__cropped"

#: Typical input queue directory (review-select crop queue); a convention,
#: never created or required by this plugin.
CROP_QUEUE_DIR_NAME = "__crop"

#: Audit operation recorded for each applied crop.
OPERATION = "multi_crop"


def _validate_box(box: object) -> tuple[int, int, int, int]:
    """Return *box* as a 4-int tuple or raise :class:`ValueError`."""
    if isinstance(box, (str, bytes, bytearray)) or not hasattr(box, "__iter__"):
        raise ValueError(f"crop box must be (left, top, right, bottom), got {box!r}")
    try:
        values = tuple(box)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(
            f"crop box must be (left, top, right, bottom), got {box!r}"
        ) from exc
    if len(values) != 4:
        raise ValueError(
            "crop box must have exactly 4 integers "
            f"(left, top, right, bottom), got {box!r}"
        )
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"crop box coordinates must be integers, got {value!r} in {box!r}"
            )
    return values  # type: ignore[return-value]


def clamp_box(
    box: object, width: int, height: int
) -> tuple[int, int, int, int]:
    """Clamp *box* to a ``width`` x ``height`` image and guarantee >=1px size.

    Semantics match Pillow ``Image.crop((left, top, right, bottom))``:
    ``right``/``bottom`` are exclusive. Every coordinate is clamped into the
    image bounds; if the clamped box is empty (``right <= left`` or
    ``bottom <= top``) it is nudged to the nearest valid 1px box inside the
    image. *width* and *height* must be positive integers.
    """
    left, top, right, bottom = _validate_box(box)
    if isinstance(width, bool) or not isinstance(width, int):
        raise ValueError(f"image width must be a positive integer, got {width!r}")
    if isinstance(height, bool) or not isinstance(height, int):
        raise ValueError(f"image height must be a positive integer, got {height!r}")
    if width < 1 or height < 1:
        raise ValueError(f"image width and height must be positive, got {width}x{height}")

    left = max(0, min(left, width))
    right = max(0, min(right, width))
    top = max(0, min(top, height))
    bottom = max(0, min(bottom, height))

    if right <= left:
        if left < width:
            right = left + 1
        else:
            left = width - 1
            right = width
    if bottom <= top:
        if top < height:
            bottom = top + 1
        else:
            top = height - 1
            bottom = height
    return (left, top, right, bottom)


@dataclass(frozen=True)
class CropSpec:
    """One crop: a source image, a pixel box, and optional metadata.

    ``source`` may be a path relative to the batch root (``img_002.png``) or
    an absolute path under the batch root. ``box`` is an axis-aligned pixel
    box ``(left, top, right, bottom)`` (``right``/``bottom`` exclusive).
    ``destination``, when given, is a relative name under ``__cropped`` or an
    absolute path under the batch root; when omitted the default keeps the
    source stem + suffix under ``__cropped``. ``timestamp`` defaults to the
    UTC time the :class:`CropSpec` was created. Invalid boxes are refused at
    construction.
    """

    source: str
    box: tuple[int, int, int, int]
    destination: str | None = None
    note: str | None = None
    timestamp: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.source, Path):
            object.__setattr__(self, "source", str(self.source))
        if not self.source:
            raise ValueError("crop source must not be empty")
        object.__setattr__(self, "box", _validate_box(self.box))
        if self.destination is not None:
            if isinstance(self.destination, Path):
                object.__setattr__(self, "destination", str(self.destination))
            if not self.destination:
                raise ValueError("crop destination must not be empty when given")
        if self.note is not None and not isinstance(self.note, str):
            raise ValueError("crop note must be a string")


@dataclass(frozen=True)
class ApplyResult:
    """What :func:`crop_batch` applied.

    ``destinations`` holds the relative paths (from the batch root) of the
    written crop files, in applied order. ``finished`` is True only when
    ``finish=True`` was passed and at least one crop was applied.
    """

    batch_root: Path
    crops_applied: int
    destinations: tuple[str, ...]
    finished: bool
    manifest_path: Path
    crops_log_path: Path


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


def _resolve_source(root: Path, source: str | Path) -> Path:
    """Resolve a crop source under *root*, refusing paths outside it."""
    candidate = _as_path(source)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"crop source is outside batch root: {source}")
    return resolved


def _resolve_destination(
    root: Path, destination: str | None, source: Path
) -> Path:
    """Resolve a crop destination under *root*.

    ``None`` uses the default ``__cropped/<source name>``. A relative
    destination is under ``__cropped``; an absolute destination must still be
    under the batch root.
    """
    if destination is None:
        return root / CROPPED_DIR_NAME / source.name
    candidate = _as_path(destination)
    if not candidate.is_absolute():
        candidate = root / CROPPED_DIR_NAME / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"crop destination is outside batch root: {destination}")
    return resolved


def _find_multi_crop_step(
    steps: list[object], manifest_path: Path
) -> dict[str, object]:
    for step in steps:
        if isinstance(step, dict) and step.get("name") == MULTI_CROP_STEP_NAME:
            return step
    raise ValueError(
        f"manifest has no '{MULTI_CROP_STEP_NAME}' step: {manifest_path}"
    )


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def apply_crop(
    source: str | Path,
    box: object,
    destination: str | Path,
    *,
    hook: AuditHook | None = None,
) -> Path:
    """Crop *source* with *box* and save a NEW raster at *destination*.

    Opens *source* with Pillow, clamps *box* to the image bounds with
    :func:`clamp_box`, then refuses to write if *destination* already exists
    (``lib_safety.require_new_file``) and saves the cropped image. The
    destination's parent directory is created on first need. Returns the
    destination :class:`Path`. Does not require intake, never touches
    companions, and never modifies the source. With *hook* given, one
    ``multi_crop`` audit event is recorded on success (refusals are recorded
    by ``require_new_file``).
    """
    source_path = _as_path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"crop source not found: {source_path}")
    dest_path = _as_path(destination)
    hook = hook or NULL_HOOK

    if dest_path.resolve() == source_path.resolve():
        hook.record(
            AuditEvent(
                operation="refuse_write",
                source=str(source_path),
                ok=False,
                reason="refusing to crop: destination resolves to source image",
            )
        )
        raise RefusedWriteError(
            f"refusing to crop: destination resolves to source image: {source_path}"
        )

    with Image.open(source_path) as image:
        clamped = clamp_box(box, image.size[0], image.size[1])
        require_new_file(dest_path, hook=hook)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        image.crop(clamped).save(dest_path)

    hook.record(
        AuditEvent(
            operation=OPERATION,
            source=str(source_path),
            destination=str(dest_path),
            ok=True,
            reason=f"box={clamped[0]},{clamped[1]},{clamped[2]},{clamped[3]}",
        )
    )
    return dest_path


def _plan_crops(
    root: Path,
    specs: list[CropSpec],
    *,
    hook: AuditHook,
) -> list[tuple[CropSpec, Path, Path, tuple[int, int, int, int]]]:
    """Validate every spec before any crop is written or directory created.

    Returns ``(spec, source, dest, clamped_box)`` tuples. Refuses missing
    sources, sources outside the batch root, duplicate destinations, any
    destination that already exists (auditing the refusal), and sources that
    cannot be opened as images.
    """
    planned: list[
        tuple[CropSpec, Path, Path, tuple[int, int, int, int]]
    ] = []
    seen_destinations: set[Path] = set()
    for spec in specs:
        source = _resolve_source(root, spec.source)
        if not source.is_file():
            raise FileNotFoundError(f"crop source not found: {source}")

        dest = _resolve_destination(root, spec.destination, source)
        if dest in seen_destinations:
            raise ValueError(f"duplicate crop destination: {dest}")
        seen_destinations.add(dest)

        # Shared no-overwrite guard at plan time: any existing destination
        # aborts the whole call before anything is written, and the refusal
        # is audited through the same fanout hooks.
        require_new_file(dest, hook=hook)

        try:
            with Image.open(source) as image:
                width, height = image.size
        except OSError as exc:
            raise ValueError(
                f"cannot open crop source as an image: {source}"
            ) from exc
        clamped = clamp_box(spec.box, width, height)
        planned.append((spec, source, dest, clamped))
    return planned


def crop_batch(
    batch_root: str | Path,
    specs: Iterable[CropSpec],
    *,
    finish: bool = False,
    hook: AuditHook | None = None,
) -> ApplyResult:
    """Apply *specs* to an already intake'd batch under *batch_root*.

    For each :class:`CropSpec` the source image is opened, the box is clamped
    to the image bounds, and a NEW cropped raster is written under
    ``__cropped`` (or the spec's explicit destination under the batch root).
    One JSON record is appended to
    ``<batch_root>/.pickkit/crops.jsonl`` per applied crop, the ``multi_crop``
    step in ``<batch_root>/.pickkit/project.json`` is updated (``started_at``
    on first crop, ``images_processed`` bumped, ``finished_at`` only with
    ``finish=True``), and events are recorded on
    ``<batch_root>/.pickkit/audit.jsonl`` plus the optional caller *hook*.

    Refuses with :class:`FileNotFoundError` if *batch_root* is missing, not a
    directory, or not intake'd (no ``project.json`` manifest). All specs are
    validated before anything is written; a missing source, a source outside
    the batch root, a duplicate destination, or an existing destination
    aborts the whole call without creating crop files or log records.
    """
    root = _as_path(batch_root)
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()

    pickkit_dir = root / PICKKIT_DIR_NAME
    manifest_path = pickkit_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"batch is not intake'd: missing manifest {manifest_path}; "
            f"run pickkit-intake first"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"manifest has no 'steps' list: {manifest_path}")
    step = _find_multi_crop_step(steps, manifest_path)

    specs = list(specs)
    hook = hook or NULL_HOOK
    audit_path = pickkit_dir / AUDIT_NAME
    crops_log_path = pickkit_dir / CROPS_LOG_NAME
    fanout = _FanoutHook(JsonlAuditHook(audit_path), hook)

    # Pre-flight: validate everything before any file or directory changes.
    planned = _plan_crops(root, specs, hook=fanout)

    applied = 0
    destinations: list[str] = []
    for spec, source, dest, clamped in planned:
        # Writes the NEW raster (guard re-checked at the moment of save).
        apply_crop(source, clamped, dest, hook=fanout)

        record: dict[str, object] = {
            "timestamp": spec.timestamp,
            "source": _rel(root, source),
            "destination": _rel(root, dest),
            "box": list(clamped),
        }
        if spec.note is not None:
            record["note"] = spec.note
        _append_jsonl(crops_log_path, record)

        if step.get("started_at") is None:
            step["started_at"] = utc_now()
        step["images_processed"] = int(step.get("images_processed") or 0) + 1
        applied += 1
        destinations.append(_rel(root, dest))

    finished = False
    if finish and applied:
        step["finished_at"] = utc_now()
        finished = True

    if applied:
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    return ApplyResult(
        batch_root=root,
        crops_applied=applied,
        destinations=tuple(destinations),
        finished=finished,
        manifest_path=manifest_path,
        crops_log_path=crops_log_path,
    )


def _record_to_crop_spec(record: object, path: Path, index: int) -> CropSpec:
    if not isinstance(record, dict):
        raise ValueError(f"crop spec #{index} in {path} must be a JSON object")
    if "source" not in record or "box" not in record:
        raise ValueError(
            f"crop spec #{index} in {path} must have 'source' and 'box' keys"
        )
    source = record["source"]
    box = record["box"]
    destination = record.get("destination")
    note = record.get("note")
    if not isinstance(source, str):
        raise ValueError(
            f"crop spec #{index} in {path} must have a string 'source'"
        )
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError(
            f"crop spec #{index} in {path} 'box' must be a list of 4 integers"
        )
    if destination is not None and not isinstance(destination, str):
        raise ValueError(
            f"crop spec #{index} in {path} has a non-string 'destination'"
        )
    if note is not None and not isinstance(note, str):
        raise ValueError(f"crop spec #{index} in {path} has a non-string 'note'")
    return CropSpec(source=source, box=box, destination=destination, note=note)


def load_crop_specs(path: str | Path) -> list[CropSpec]:
    """Load crop specs from a JSON array file or a JSONL file.

    A ``.jsonl`` file is read one JSON object per line; any other file is
    read as a JSON array of
    ``{"source": ..., "box": [left, top, right, bottom], ...}`` objects.
    Blank JSONL lines are skipped. Extra keys are ignored.
    """
    specs_file = _as_path(path)
    if not specs_file.is_file():
        raise FileNotFoundError(f"crop specs file not found: {specs_file}")

    if specs_file.suffix.lower() == ".jsonl":
        specs: list[CropSpec] = []
        for line_no, raw in enumerate(
            specs_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL in {specs_file} at line {line_no}: {exc}"
                ) from exc
            specs.append(_record_to_crop_spec(record, specs_file, line_no))
        return specs

    try:
        data = json.loads(specs_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {specs_file}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(
            f"crop specs file must contain a JSON array: {specs_file}"
        )
    return [
        _record_to_crop_spec(record, specs_file, index)
        for index, record in enumerate(data, start=1)
    ]


def _parse_box(text: str) -> tuple[int, int, int, int]:
    """Parse a CLI ``L,T,R,B`` string into a validated 4-int box."""
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(
            f"--box must be 'left,top,right,bottom', got {text!r}"
        )
    try:
        values = tuple(int(part.strip()) for part in parts)
    except ValueError as exc:
        raise ValueError(f"--box values must be integers, got {text!r}") from exc
    return _validate_box(values)


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser for the ``pickkit-crop`` CLI."""
    from .ui import DEFAULT_HOST, DEFAULT_PORT

    parser = argparse.ArgumentParser(
        prog="pickkit-crop",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "batch_root",
        help="Path to an already intake'd batch directory",
    )
    parser.add_argument(
        "--crops",
        metavar="PATH",
        help="JSON or JSONL crop specs file (objects with 'source' and 'box')",
    )
    parser.add_argument(
        "--source",
        metavar="PATH",
        action="append",
        default=[],
        help=(
            "Crop one image path (relative to batch_root); repeatable and "
            "paired positionally with --box"
        ),
    )
    parser.add_argument(
        "--box",
        metavar="L,T,R,B",
        action="append",
        default=[],
        help="Axis-aligned pixel box for the paired --source; repeatable",
    )
    parser.add_argument(
        "--finish",
        action="store_true",
        help="Mark the multi_crop step finished after applying crops",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Start the local interactive crop web UI (Flask) instead of applying crops",
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
    """CLI entry point; parses args and calls :func:`crop_batch`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from .ui import DEFAULT_HOST, DEFAULT_PORT

    if not args.ui and (args.host != DEFAULT_HOST or args.port != DEFAULT_PORT):
        parser.error("--host and --port may only be used together with --ui")

    if args.ui:
        from .ui import run_ui

        if args.crops or args.source or args.box or args.finish:
            parser.error(
                "--ui cannot be combined with "
                "--crops/--source/--box/--finish"
            )
        run_ui(args.batch_root, host=args.host, port=args.port)
        return 0

    if args.crops and (args.source or args.box):
        parser.error("use either --crops or --source/--box, not both")

    try:
        if args.crops:
            specs = load_crop_specs(args.crops)
        else:
            if not args.source and not args.box:
                parser.error("no crops given: pass --crops or --source/--box")
            if len(args.source) != len(args.box):
                parser.error(
                    "--source and --box must be given the same number of times"
                )
            specs = [
                CropSpec(source=source, box=_parse_box(box))
                for source, box in zip(args.source, args.box)
            ]
        result = crop_batch(args.batch_root, specs, finish=args.finish)
    except (
        FileNotFoundError,
        NotADirectoryError,
        ValueError,
        FileExistsError,
    ) as exc:
        parser.exit(1, f"pickkit-crop: error: {exc}\n")

    print(
        json.dumps(
            {
                "batch_root": str(result.batch_root),
                "crops_applied": result.crops_applied,
                "destinations": list(result.destinations),
                "finished": result.finished,
                "manifest_path": str(result.manifest_path),
                "crops_log_path": str(result.crops_log_path),
            },
            indent=2,
        )
    )
    return 0
