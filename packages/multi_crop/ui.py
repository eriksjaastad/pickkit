"""Local Flask crop UI for pickkit multi-crop.

Started by ``pickkit-crop <batch_root> --ui``. The batch must be intake'd.
The page shows one pending image at a time; drag an axis-aligned rectangle
and Apply. Every Apply calls ``multi_crop.crop.crop_batch`` with one integer
box, so the UI never writes pixels or logs itself, and it never suggests
boxes.

The pending queue is re-read from disk on every request: images under
``__crop/`` (:data:`CROP_QUEUE_DIR_NAME`), not hidden, whose default
destination ``__cropped/<same name>`` (:data:`CROPPED_DIR_NAME`) does not
exist yet. The source stays in ``__crop/``; once cropped it drops out of the
queue. The skip set and cropped-this-session count reset when the server
restarts. Finish is CLI-only, and ``--finish`` sets ``finished_at`` only when
the same call applies at least one crop (e.g. pass it with the last image's
crop); a bare ``pickkit-crop <batch_root> --finish`` leaves the step
unfinished.

Keyboard shortcuts
------------------
``Enter`` apply the crop (the ``Apply`` button)
``S`` skip: leave it in the queue and show the next (the ``Skip`` button)
``R`` reset: clear the drawn box (the ``Reset`` button)

Box mapping
-----------
The image may be shown scaled. Display pixels map back to full-image pixels
as::

    full_x = round(display_x * (naturalWidth / clientWidth))
    full_y = round(display_y * (naturalHeight / clientHeight))

clamped to ``[0, naturalWidth]`` / ``[0, naturalHeight]``, with at least a
1x1 box before Apply is enabled. The readout shows ``(left, top, right,
bottom)`` in full-image pixels (right and bottom exclusive), and those ints
are posted. ``multi_crop.crop.clamp_box`` is the final safety net.

Host / port
-----------
Binds ``127.0.0.1:8766`` by default, local only (``DEFAULT_HOST`` /
``DEFAULT_PORT``); ``pickkit-crop --host`` / ``--port`` override it.

Routes
------
``GET /``
    The crop page.
``GET /api/status``
    JSON ``remaining`` (excluding skipped), ``cropped_this_session``,
    ``current`` (relative path of the pending head, or null) and
    ``natural_size`` (``{width, height}``, or null when unreadable).
``POST /api/crop``
    Body ``{"source": "<relative path>", "box": [L, T, R, B]}``; applies one
    crop and returns the next status. 400 for a bad body, box or path, 404 for
    a missing source, 409 when the destination exists.
``POST /api/skip``
    Body ``{"source": "<relative path>"}``; skips it for this server session
    and returns the next status.
``GET /image/<path:rel>``
    The image bytes; 404 for paths outside the batch root or missing files.

Public API
----------
``DEFAULT_HOST``
``DEFAULT_PORT``
``CROP_QUEUE_DIR_NAME``
    Re-exported from ``multi_crop.crop``.
``CROPPED_DIR_NAME``
    Re-exported from ``multi_crop.crop``.
``list_pending_images(batch_root)``
``safe_image_path(batch_root, rel_or_name)``
    Re-exported from :mod:`lib_safety.webui`.
``create_app(batch_root, *, session_cropped=None)``
``run_ui(batch_root, *, host=DEFAULT_HOST, port=DEFAULT_PORT)``
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request
from PIL import Image

from intake_init import DEFAULT_IMAGE_SUFFIXES
from lib_safety import rel_path
from lib_safety.webui import (
    require_intaked_root,
    run_app,
    safe_image_path,
    send_batch_image,
)

from .crop import (
    CROPPED_DIR_NAME,
    CROP_QUEUE_DIR_NAME,
    CropSpec,
    crop_batch,
)

#: Default bind host for the local crop UI (loopback only).
DEFAULT_HOST = "127.0.0.1"

#: Default bind port for the local crop UI (review-select uses 8765).
DEFAULT_PORT = 8766


def list_pending_images(batch_root: str | Path) -> list[Path]:
    """Return the pending crop queue for an intake'd *batch_root*.

    Absolute paths of the non-hidden images under ``__crop/`` that have no
    ``__cropped/<same name>`` yet, sorted by relative POSIX path.
    """
    root = require_intaked_root(batch_root)
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

    *session_cropped* seeds the in-memory cropped counter (default ``0``).
    """
    root = require_intaked_root(batch_root)
    app = Flask(__name__)
    app.config["BATCH_ROOT"] = root
    app.config["CROPPED_THIS_SESSION"] = int(session_cropped or 0)
    app.config["SKIPPED"] = set()

    def status_payload() -> dict[str, object]:
        pending = list_pending_images(root)
        skipped = app.config["SKIPPED"]
        queue = [path for path in pending if rel_path(root, path) not in skipped]
        current = queue[0] if queue else None
        return {
            "remaining": len(queue),
            "cropped_this_session": app.config["CROPPED_THIS_SESSION"],
            "current": rel_path(root, current) if current else None,
            "natural_size": _natural_size(current),
        }

    @app.get("/")
    def index() -> str:
        pending = list_pending_images(root)
        skipped = app.config["SKIPPED"]
        queue = [path for path in pending if rel_path(root, path) not in skipped]
        current_path = queue[0] if queue else None
        return render_template(
            "crop.html",
            batch_root=root,
            batch_name=root.name,
            remaining=len(queue),
            cropped=app.config["CROPPED_THIS_SESSION"],
            current=rel_path(root, current_path) if current_path else None,
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

        rel = rel_path(root, image_path)
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

        app.config["SKIPPED"].add(rel_path(root, image_path))
        return jsonify(status_payload())

    @app.get("/image/<path:rel>")
    def serve_image(rel: str):
        return send_batch_image(root, rel)

    return app


def run_ui(
    batch_root: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Validate *batch_root* and start the Flask crop server on ``host:port``."""
    run_app(
        create_app,
        batch_root,
        title="crop",
        hint="Drag a box on the image. Enter=Apply, S=Skip, R=Reset. Ctrl+C stops the server.",
        host=host,
        port=port,
    )
