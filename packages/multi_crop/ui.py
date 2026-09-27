"""Local Flask crop UI for pickkit multi-crop.

This module is the single source of truth for the interactive crop UI: how the
pending image queue is listed from an already intake'd batch's ``__crop``
directory, how drag-drawn axis-aligned rectangles are mapped from display
pixels back to full-image pixels, how Apply / Skip / Reset actions map onto
``multi_crop.crop``, how image bytes are served safely under the batch root,
and how the small Flask app is assembled and run. The batch engine itself
(pixel writes, crops log, manifest step, audit) is
``multi_crop.crop.crop_batch``; the UI never reimplements pixel writes.

Principles
----------
Engine only
    Every Apply action calls ``crop_batch(batch_root,
    [CropSpec(source, box)])`` immediately with an integer pixel box; the UI
    never opens images, writes cropped rasters, writes logs, or updates the
    manifest itself.
Batch must be intake'd
    ``<batch_root>/.pickkit/project.json`` must already exist (created by
    intake-init). :func:`list_pending_images` and :func:`create_app` refuse
    anything else with :class:`FileNotFoundError` before a server starts or a
    queue is returned — the same refusal path as ``crop_batch``.
Pending queue from disk
    The queue is re-listed from disk on every request; the UI never trusts a
    stale in-memory queue. A file is pending when it lives under
    :data:`CROP_QUEUE_DIR_NAME` (``__crop``), has a lowercase suffix in
    :data:`intake_init.intake.DEFAULT_IMAGE_SUFFIXES`, has no hidden path
    part, and its engine-default destination ``__cropped/<same name>`` does
    not exist yet. A missing or empty ``__crop`` queue yields a friendly
    empty state.
Sources stay put
    The v1 engine writes the crop to ``__cropped`` and leaves the source in
    ``__crop``. That is fine: the pending filter excludes names that already
    have a crop, so a cropped source falls out of the queue naturally.
Session state is in-memory only
    ``cropped_this_session`` (apply count) and the skip set are Flask app
    config values, reset on each server start. The pending list itself is
    always re-read from disk.
No AI
    The UI never recommends boxes, preloads suggestions, trains, or reads
    SQLite. Boxes come only from Erik's drag.

Public API
----------
``DEFAULT_HOST``
    Default bind host for :func:`run_ui`: ``127.0.0.1`` (local only).
``DEFAULT_PORT``
    Default bind port for :func:`run_ui`: ``8766`` (review-select uses
    ``8765`` so both UIs can run at once).
``CROP_QUEUE_DIR_NAME``
    Reused from ``multi_crop.crop``: ``__crop``, the queue directory the UI
    lists.
``CROPPED_DIR_NAME``
    Reused from ``multi_crop.crop``: ``__cropped``, the default destination
    directory used by the pending filter.
``list_pending_images(batch_root)``
    Return the pending crop queue as a sorted list of absolute
    :class:`pathlib.Path` objects under ``<batch_root>/__crop/`` (sorted by
    relative POSIX path, stable), excluding images whose default destination
    ``__cropped/<same name>`` already exists.
``safe_image_path(batch_root, rel_or_name)``
    Resolve *rel_or_name* under *batch_root* and return the absolute
    :class:`pathlib.Path`. Refuses ``..`` escapes and absolute paths outside
    the root with :class:`ValueError`.
``create_app(batch_root, *, session_cropped=None)``
    Build the Flask app for *batch_root*. ``session_cropped`` seeds the
    in-memory cropped counter (default ``0``).
``run_ui(batch_root, *, host=DEFAULT_HOST, port=DEFAULT_PORT)``
    Validate *batch_root* and start the Flask server on ``host:port``.

Keyboard shortcuts
------------------
``Enter`` — apply crop (same as the ``Apply`` button)
``S`` — skip (``Skip`` button): leave in queue, advance to next pending
``R`` — reset rect (``Reset`` button): clear the drawn box

The page buttons post those actions; the keyboard shortcuts are conveniences.

Box mapping
-----------
Display pixels map back to full-image pixels like this:

    full_x = round(display_x * (naturalWidth / clientWidth))
    full_y = round(display_y * (naturalHeight / clientHeight))

The image may be CSS-scaled (``max-width`` / ``max-height``). On
mousedown/mousemove/mouseup the template records coordinates relative to the
rendered image box and maps them with the formula above, clamps to
``[0, naturalWidth]`` / ``[0, naturalHeight]``, and enforces at least a 1×1
box (``right > left`` and ``bottom > top``) before Apply is enabled. The live
readout shows ``(left, top, right, bottom)`` in full-image pixels; those ints
are posted to ``POST /api/crop``. Pillow semantics: ``right``/``bottom`` are
exclusive. ``multi_crop.crop.clamp_box`` is the final safety net.

Host / port
-----------
The UI binds ``127.0.0.1:8766`` by default (see ``DEFAULT_HOST`` /
``DEFAULT_PORT``). The ``pickkit-crop`` CLI overrides these with ``--host``
and ``--port``, which are only valid together with ``--ui``. The server is
local-only by default; binding a non-loopback interface is an explicit
operator choice.

Routes
------
``GET /``
    Crop page: current pending head with a drag overlay, or a "queue empty"
    state, plus the remaining and cropped-this-session counts.
``GET /api/status``
    JSON: ``remaining`` (int, session queue excluding skipped),
    ``cropped_this_session`` (int), ``current`` (relative POSIX path of the
    pending head under the batch root, or null), and ``natural_size``
    (``{width, height}`` for the current image, or null when it cannot be
    read cheaply).
``POST /api/crop``
    JSON body ``{"source": "<relative path>", "box": [L, T, R, B]}`` (ints,
    Pillow exclusive right/bottom). Resolves the source safely, applies one
    :class:`CropSpec` via :func:`multi_crop.crop.crop_batch` immediately, and
    returns the next status JSON in the same shape as ``GET /api/status``.
    Errors map to 400 (bad body / bad box / escape / outside root), 404
    (source missing), or 409 (destination already exists —
    ``RefusedWriteError`` / ``FileExistsError``) so the page never crashes.
``POST /api/skip``
    JSON body ``{"source": "<relative path>"}``. Adds the source to the
    in-memory session skip set (it stays in ``__crop`` on disk) and returns
    the next status JSON. The client can also advance by simply applying or
    skipping; the skip set only affects the current server session.
``GET /image/<path:rel>``
    Serve the original image bytes for a file under the batch root with Flask
    ``send_file``; escape attempts and missing files return 404.

Out of scope / Notes
--------------------
- Finish: ``--finish`` stays CLI-only for now. The UI never shows a finish
  wizard or a finish button.
- AI crop suggestions, non-axis-aligned / rotated crops, moving sources out
  of ``__crop`` after apply, and SQLite training are out of scope.
- Template: ``templates/crop.html`` is shipped as package data (see
  ``pyproject.toml`` ``[tool.setuptools.package-data]``).
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image

from intake_init import DEFAULT_IMAGE_SUFFIXES

from .crop import (
    CROPPED_DIR_NAME,
    CROP_QUEUE_DIR_NAME,
    MANIFEST_NAME,
    PICKKIT_DIR_NAME,
    CropSpec,
    crop_batch,
)

#: Default bind host for the local crop UI (loopback only).
DEFAULT_HOST = "127.0.0.1"

#: Default bind port for the local crop UI (review-select uses 8765).
DEFAULT_PORT = 8766


def _rel(root: Path, path: Path) -> str:
    """Return *path* relative to *root* (POSIX style) when it is under it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _require_intaked_root(batch_root: str | Path) -> Path:
    """Resolve *batch_root* and refuse anything that is not intake'd.

    Mirrors the refusal path of :func:`multi_crop.crop.crop_batch`: the root
    must exist, be a directory, and contain ``.pickkit/project.json``.
    """
    root = Path(batch_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()
    manifest_path = root / PICKKIT_DIR_NAME / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"batch is not intake'd: missing manifest {manifest_path}; "
            f"run pickkit-intake first"
        )
    return root


def list_pending_images(batch_root: str | Path) -> list[Path]:
    """Return the pending crop queue for an intake'd *batch_root*.

    The queue is every visible file under ``<batch_root>/__crop/`` whose
    lowercase suffix is in
    :data:`intake_init.intake.DEFAULT_IMAGE_SUFFIXES`, skipping hidden path
    parts, and excluding any file whose engine-default destination
    ``__cropped/<same name>`` already exists. Returns absolute
    :class:`pathlib.Path` objects sorted by relative POSIX path (stable).
    """
    root = _require_intaked_root(batch_root)
    crop_dir = root / CROP_QUEUE_DIR_NAME
    if not crop_dir.is_dir():
        return []

    pending: list[Path] = []
    for path in crop_dir.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        if path.suffix.lower() not in DEFAULT_IMAGE_SUFFIXES:
            continue
        default_destination = root / CROPPED_DIR_NAME / path.name
        if default_destination.exists():
            continue
        pending.append(path)
    return sorted(pending, key=lambda p: p.relative_to(root).as_posix())


def safe_image_path(batch_root: str | Path, rel_or_name: str | Path) -> Path:
    """Resolve *rel_or_name* under *batch_root*, refusing escapes.

    Relative names resolve under the batch root; absolute paths must already
    resolve under it. Symlinks are resolved, so a link pointing outside the
    root is refused too. Raises :class:`ValueError` for anything outside the
    root. This helper only resolves paths; it does not require the file to
    exist or the batch to be intake'd.
    """
    root = Path(batch_root).expanduser()
    if not root.is_dir():
        raise ValueError(f"batch root is not a directory: {root}")
    root = root.resolve()
    candidate = Path(rel_or_name)
    if candidate.is_absolute():
        candidate = candidate.expanduser()
    else:
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes batch root: {rel_or_name}")
    return resolved


def _natural_size(path: Path | None) -> dict[str, int] | None:
    """Return ``{width, height}`` for *path*, or ``None`` if not readable."""
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            return {"width": image.size[0], "height": image.size[1]}
    except OSError:
        return None


def create_app(
    batch_root: str | Path,
    *,
    session_cropped: int | None = None,
) -> Flask:
    """Build the Flask crop app for an intake'd *batch_root*.

    The pending queue is re-listed from disk on every request.
    ``cropped_this_session`` and the skip set are kept in-memory on the app
    config (the counter is seeded by *session_cropped*, default ``0``).
    """
    root = _require_intaked_root(batch_root)
    app = Flask(__name__)
    app.config["BATCH_ROOT"] = root
    app.config["CROPPED_THIS_SESSION"] = int(session_cropped or 0)
    app.config["SKIPPED"] = set()

    def status_payload() -> dict[str, object]:
        pending = list_pending_images(root)
        skipped = app.config["SKIPPED"]
        queue = [path for path in pending if _rel(root, path) not in skipped]
        current = queue[0] if queue else None
        return {
            "remaining": len(queue),
            "cropped_this_session": app.config["CROPPED_THIS_SESSION"],
            "current": _rel(root, current) if current else None,
            "natural_size": _natural_size(current),
        }

    @app.get("/")
    def index() -> str:
        pending = list_pending_images(root)
        skipped = app.config["SKIPPED"]
        queue = [path for path in pending if _rel(root, path) not in skipped]
        current_path = queue[0] if queue else None
        return render_template(
            "crop.html",
            batch_root=root,
            batch_name=root.name,
            remaining=len(queue),
            cropped=app.config["CROPPED_THIS_SESSION"],
            current=_rel(root, current_path) if current_path else None,
            current_name=current_path.name if current_path else None,
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(status_payload())

    @app.post("/api/crop")
    def api_crop():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(
                {"error": "JSON body must be an object with 'source' and 'box'"}
            ), 400
        source = payload.get("source")
        box = payload.get("box")
        if not isinstance(source, str) or not source:
            return jsonify({"error": "'source' must be a non-empty string"}), 400
        if not isinstance(box, list) or len(box) != 4:
            return jsonify(
                {"error": "'box' must be a list of 4 integers [left, top, right, bottom]"}
            ), 400
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in box):
            return jsonify({"error": "'box' coordinates must be integers"}), 400

        try:
            image_path = safe_image_path(root, source)
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        if not image_path.is_file():
            return jsonify({"error": f"source not found: {source}"}), 404

        rel = _rel(root, image_path)
        try:
            crop_batch(
                root,
                [CropSpec(source=rel, box=(box[0], box[1], box[2], box[3]))],
            )
        except FileExistsError as exc:  # includes RefusedWriteError
            return jsonify({"error": str(exc)}), 409
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except (NotADirectoryError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

        app.config["CROPPED_THIS_SESSION"] = (
            int(app.config["CROPPED_THIS_SESSION"]) + 1
        )
        return jsonify(status_payload())

    @app.post("/api/skip")
    def api_skip():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body must be an object with 'source'"}), 400
        source = payload.get("source")
        if not isinstance(source, str) or not source:
            return jsonify({"error": "'source' must be a non-empty string"}), 400

        try:
            image_path = safe_image_path(root, source)
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        if not image_path.is_file():
            return jsonify({"error": f"source not found: {source}"}), 404

        app.config["SKIPPED"].add(_rel(root, image_path))
        return jsonify(status_payload())

    @app.get("/image/<path:rel>")
    def serve_image(rel: str):
        try:
            image_path = safe_image_path(root, rel)
        except (ValueError, OSError):
            abort(404)
        if not image_path.is_file():
            abort(404)
        return send_file(image_path)

    return app


def run_ui(
    batch_root: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Validate *batch_root* and start the Flask crop server on ``host:port``."""
    root = _require_intaked_root(batch_root)
    app = create_app(root)
    print(f"pickkit crop UI: http://{host}:{port}  (batch: {root})")
    print("Drag a box on the image. Enter=Apply, S=Skip, R=Reset. Ctrl+C stops the server.")
    app.run(host=host, port=port, debug=False)
