"""Local Flask review UI for pickkit review-select triage.

Started by ``pickkit-review <batch_root> --ui``. The batch must be intake'd.
The page shows one pending image at a time; every Keep / Crop / Reject calls
``review_select.review.apply_decisions`` for that one image, so the UI never
moves files or writes logs itself, and it never recommends anything.

The pending queue is re-read from disk on every request: every image under the
batch root (suffix in ``intake_init.DEFAULT_IMAGE_SUFFIXES``) except hidden
paths and anything inside a stage directory (:data:`STAGE_DIR_NAMES`:
``__selected``, ``__crop``, ``__reject``, ``__cropped``). The
decided-this-session count resets when the server restarts. To finish the
step, run ``pickkit-review <batch_root> --finish`` from the CLI.

Keyboard shortcuts
------------------
``K`` / ``1`` keep (moves to ``__selected``)
``C`` / ``2`` crop (queues to ``__crop``)
``R`` / ``3`` reject (moves to ``__reject``)

Host / port
-----------
Binds ``127.0.0.1:8765`` by default (``DEFAULT_HOST`` / ``DEFAULT_PORT``);
``pickkit-review --host`` / ``--port`` override it.

Routes
------
``GET /``
    The review page.
``GET /api/status``
    JSON ``remaining``, ``decided_this_session`` and ``current`` (the pending
    head's relative path, or null).
``POST /api/decide``
    Body ``{"source": "<relative path>", "action": "<token>"}``; applies one
    decision and returns the next status. 400 for a bad body, token or path,
    404 for a missing source, 409 when the destination exists.
``GET /image/<path:rel>``
    The image bytes; 404 for paths outside the batch root or missing files.

Public API
----------
``DEFAULT_HOST``
``DEFAULT_PORT``
``STAGE_DIR_NAMES``
``list_pending_images(batch_root)``
``map_ui_action(token)``
    K/C/R, 1/2/3 or keep/crop/reject (any case) -> a review action.
``safe_image_path(batch_root, rel_or_name)``
    Re-exported from :mod:`lib_safety.webui`.
``create_app(batch_root, *, session_decided=None)``
``run_ui(batch_root, *, host=DEFAULT_HOST, port=DEFAULT_PORT)``
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from intake_init import DEFAULT_IMAGE_SUFFIXES
from lib_safety import rel_path
from lib_safety.webui import (
    require_intaked_root,
    run_app,
    safe_image_path,
    send_batch_image,
)
from multi_crop.crop import CROPPED_DIR_NAME

from .review import (
    CROP,
    CROP_DIR_NAME,
    KEEP,
    KEEP_DIR_NAME,
    REJECT,
    REJECT_DIR_NAME,
    Decision,
    apply_decisions,
)

#: Default bind host for the local review UI (loopback only).
DEFAULT_HOST = "127.0.0.1"

#: Default bind port for the local review UI.
DEFAULT_PORT = 8765

#: Known stage directory names skipped as path parts when listing pending
#: images. ``__cropped`` is multi-crop output, not a pending triage input.
STAGE_DIR_NAMES: frozenset[str] = frozenset(
    {KEEP_DIR_NAME, CROP_DIR_NAME, REJECT_DIR_NAME, CROPPED_DIR_NAME}
)

#: UI action tokens -> snake_case review actions. Unknown tokens are refused.
_UI_ACTION_TOKENS: dict[str, str] = {
    "k": KEEP,
    "keep": KEEP,
    "1": KEEP,
    "c": CROP,
    "crop": CROP,
    "2": CROP,
    "r": REJECT,
    "reject": REJECT,
    "3": REJECT,
}


def list_pending_images(batch_root: str | Path) -> list[Path]:
    """Return the pending image queue for an intake'd *batch_root*.

    Absolute paths of every image outside hidden paths and
    :data:`STAGE_DIR_NAMES`, sorted by relative POSIX path.
    """
    root = require_intaked_root(batch_root)
    pending: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        if any(part in STAGE_DIR_NAMES for part in parts):
            continue
        if path.suffix.lower() not in DEFAULT_IMAGE_SUFFIXES:
            continue
        pending.append(path)
    return sorted(pending, key=lambda p: p.relative_to(root).as_posix())


def map_ui_action(token: str) -> str:
    """Map K/C/R, 1/2/3 or keep/crop/reject (any case) to a review action.

    Unknown tokens raise :class:`ValueError`.
    """
    if not isinstance(token, str):
        raise ValueError(
            f"UI action must be a string; got {type(token).__name__}"
        )
    action = _UI_ACTION_TOKENS.get(token.strip().lower())
    if action is None:
        raise ValueError(
            f"unknown UI action {token!r}; expected K/C/R, 1/2/3, "
            f"or keep/crop/reject"
        )
    return action


def create_app(
    batch_root: str | Path,
    *,
    session_decided: int | None = None,
) -> Flask:
    """Build the Flask review app for an intake'd *batch_root*.

    *session_decided* seeds the in-memory decided counter (default ``0``).
    """
    root = require_intaked_root(batch_root)
    app = Flask(__name__)
    app.config["BATCH_ROOT"] = root
    app.config["DECIDED_THIS_SESSION"] = int(session_decided or 0)

    def status_payload() -> dict[str, object]:
        pending = list_pending_images(root)
        return {
            "remaining": len(pending),
            "decided_this_session": app.config["DECIDED_THIS_SESSION"],
            "current": rel_path(root, pending[0]) if pending else None,
        }

    @app.get("/")
    def index() -> str:
        pending = list_pending_images(root)
        current_path = pending[0] if pending else None
        return render_template(
            "review.html",
            batch_root=root,
            batch_name=root.name,
            remaining=len(pending),
            decided=app.config["DECIDED_THIS_SESSION"],
            current=rel_path(root, current_path) if current_path else None,
            current_name=current_path.name if current_path else None,
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(status_payload())

    @app.post("/api/decide")
    def api_decide():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(
                {"error": "JSON body must be an object with 'source' and 'action'"}
            ), 400
        source = payload.get("source")
        token = payload.get("action")
        if not isinstance(source, str) or not source:
            return jsonify({"error": "'source' must be a non-empty string"}), 400
        if not isinstance(token, str) or not token:
            return jsonify({"error": "'action' must be a non-empty string"}), 400

        try:
            action = map_ui_action(token)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            image_path = safe_image_path(root, source)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not image_path.is_file():
            return jsonify({"error": f"source not found: {source}"}), 404

        try:
            apply_decisions(root, [Decision(rel_path(root, image_path), action)])
        except FileExistsError as exc:
            return jsonify({"error": str(exc)}), 409
        except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

        app.config["DECIDED_THIS_SESSION"] = (
            int(app.config["DECIDED_THIS_SESSION"]) + 1
        )
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
    """Validate *batch_root* and start the Flask review server on ``host:port``."""
    run_app(
        create_app,
        batch_root,
        title="review",
        hint="Keyboard: K/C/R or 1/2/3. Ctrl+C stops the server.",
        host=host,
        port=port,
    )
