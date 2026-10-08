"""Create NEW cropped image files from axis-aligned pixel boxes.

``pickkit-crop <batch_root>`` writes each crop as a new file under
``__cropped/`` in the batch. It never overwrites an existing file and never
moves, deletes or rewrites a source; same-stem companions are left alone. It
prints a JSON summary.

Usage::

    pickkit-crop tmp/batch_a --ui                          # local web UI
    pickkit-crop tmp/batch_a --crops crops.jsonl --finish
    pickkit-crop tmp/batch_a --source __crop/img_002.png --box 10,10,50,40

Options
-------
``--crops PATH``
    A JSON array, or a ``.jsonl`` file with one object per line, of
    ``{"source": ..., "box": [left, top, right, bottom], "destination": ...,
    "note": ...}`` (``destination`` and ``note`` optional).
``--source PATH`` / ``--box L,T,R,B``
    One crop per pair; both repeatable and paired in order. Use these or
    ``--crops``, not both.
``--finish``
    Set the step's ``finished_at`` after at least one crop is applied.
``--ui``
    Start the local crop page (``multi_crop.ui``). ``--host`` / ``--port``
    override its 127.0.0.1:8766 bind and are only valid with ``--ui``, which
    cannot be combined with the flags above.

Boxes and destinations
----------------------
A box is ``(left, top, right, bottom)`` in whole pixels with Pillow semantics
(right and bottom exclusive). It is clamped to the image and kept at least
1x1 px. Sources can be anywhere under the batch root; the usual input is the
review crop queue ``__crop/`` (:data:`CROP_QUEUE_DIR_NAME`). The default
destination is ``__cropped/<source name>`` (:data:`CROPPED_DIR_NAME`); a
relative ``destination`` is placed under ``__cropped/`` and an absolute one
must be under the batch root. If a destination exists the crop is refused,
never renamed. Every crop is checked before any is written.

Files
-----
The batch must be intake'd: ``project.json`` (:data:`MANIFEST_NAME`) must
exist under ``.pickkit/`` (:data:`PICKKIT_DIR_NAME`). Each applied crop
appends one record to ``.pickkit/crops.jsonl`` (:data:`CROPS_LOG_NAME`) with
``timestamp``, ``source``, ``destination`` and ``box``, plus ``note`` when
given; one ``multi_crop`` event to ``.pickkit/audit.jsonl``
(:data:`AUDIT_NAME`); and updates the :data:`MULTI_CROP_STEP_NAME` step
(``started_at`` on the first crop, ``images_processed`` per crop).

Public API
----------
``CROPPED_DIR_NAME = "__cropped"``
``CROP_QUEUE_DIR_NAME = "__crop"``
``PICKKIT_DIR_NAME = ".pickkit"``
``MANIFEST_NAME = "project.json"``
``AUDIT_NAME = "audit.jsonl"``
``CROPS_LOG_NAME = "crops.jsonl"``
``MULTI_CROP_STEP_NAME = "multi_crop"``
``CropSpec``
``ApplyResult``
``clamp_box(box, width, height)``
``apply_crop(source, box, destination, *, hook=None)``
    Crop one file to a new path; needs no intake.
``crop_batch(batch_root, specs, *, finish=False, hook=None)``
    Validate, then apply every :class:`CropSpec`; returns an
    :class:`ApplyResult`.
``load_crop_specs(path)``
    Read a ``--crops`` file into a list of :class:`CropSpec`.
``build_parser()``
``main(argv=None)``
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
    FanoutHook,
    JsonlAuditHook,
    RefusedWriteError,
    append_jsonl,
    find_step,
    load_json_records,
    rel_path,
    require_new_file,
    write_manifest,
)
from lib_safety.audit import utc_now

#: Names the ``multi_crop`` package re-exports.
__all__ = [
    "AUDIT_NAME",
    "CROPPED_DIR_NAME",
    "CROP_QUEUE_DIR_NAME",
    "CROPS_LOG_NAME",
    "MANIFEST_NAME",
    "MULTI_CROP_STEP_NAME",
    "PICKKIT_DIR_NAME",
    "ApplyResult",
    "CropSpec",
    "apply_crop",
    "build_parser",
    "clamp_box",
    "crop_batch",
    "load_crop_specs",
    "main",
]

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

    ``right``/``bottom`` are exclusive, as in Pillow ``Image.crop``. A box
    that clamps to empty is nudged to the nearest 1px box inside the image.
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

    ``source`` is relative to the batch root or an absolute path under it.
    ``destination`` defaults to ``__cropped/<source name>``; a relative one
    goes under ``__cropped``. ``timestamp`` defaults to creation time (UTC
    ``Z``). Invalid boxes are refused at construction.
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


def _resolve_source(root: Path, source: str | Path) -> Path:
    """Resolve a crop source under *root*, refusing paths outside it."""
    candidate = Path(source).expanduser()
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
    candidate = Path(destination).expanduser()
    if not candidate.is_absolute():
        candidate = root / CROPPED_DIR_NAME / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"crop destination is outside batch root: {destination}")
    return resolved


def apply_crop(
    source: str | Path,
    box: object,
    destination: str | Path,
    *,
    hook: AuditHook | None = None,
) -> Path:
    """Crop *source* with *box* and save a NEW raster at *destination*.

    The box is clamped with :func:`clamp_box`; an existing *destination*
    (the source included) raises :class:`RefusedWriteError`. Creates the
    destination's parent directory if needed and returns the destination.
    Needs no intake. Records one ``multi_crop`` event on *hook* on success.
    """
    source_path = Path(source).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"crop source not found: {source_path}")
    dest_path = Path(destination).expanduser()
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

    Writes each crop and the log, audit and manifest records described in
    the module docstring; events also go to *hook* when given.
    ``finish=True`` sets the step's ``finished_at``. All specs are validated
    first, so a refusal writes no crop and no log record. Raises
    :class:`FileNotFoundError` for a missing or un-intake'd batch root.
    """
    root = Path(batch_root).expanduser()
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
    step = find_step(manifest, MULTI_CROP_STEP_NAME, manifest_path)

    specs = list(specs)
    hook = hook or NULL_HOOK
    audit_path = pickkit_dir / AUDIT_NAME
    crops_log_path = pickkit_dir / CROPS_LOG_NAME
    fanout = FanoutHook(JsonlAuditHook(audit_path), hook)

    # Pre-flight: validate everything before any file or directory changes.
    planned = _plan_crops(root, specs, hook=fanout)

    applied = 0
    destinations: list[str] = []
    for spec, source, dest, clamped in planned:
        # Writes the NEW raster (guard re-checked at the moment of save).
        apply_crop(source, clamped, dest, hook=fanout)

        record: dict[str, object] = {
            "timestamp": spec.timestamp,
            "source": rel_path(root, source),
            "destination": rel_path(root, dest),
            "box": list(clamped),
        }
        if spec.note is not None:
            record["note"] = spec.note
        append_jsonl(crops_log_path, record)

        if step.get("started_at") is None:
            step["started_at"] = utc_now()
        step["images_processed"] = int(step.get("images_processed") or 0) + 1
        applied += 1
        destinations.append(rel_path(root, dest))

    finished = False
    if finish and applied:
        step["finished_at"] = utc_now()
        finished = True

    if applied:
        write_manifest(manifest_path, manifest)

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
    """Load crop specs from a JSON array file or a ``.jsonl`` file.

    Each object needs ``source`` and a 4-int ``box`` and may have
    ``destination`` and ``note``. Extra keys are ignored.
    """
    return load_json_records(path, "crop specs file", _record_to_crop_spec)


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

    from lib_safety.webui import check_ui_args

    from .ui import DEFAULT_HOST, DEFAULT_PORT, run_ui

    check_ui_args(
        parser,
        args,
        default_host=DEFAULT_HOST,
        default_port=DEFAULT_PORT,
        conflicts="--crops/--source/--box/--finish",
        conflicting=bool(args.crops or args.source or args.box or args.finish),
    )
    if args.ui:
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
