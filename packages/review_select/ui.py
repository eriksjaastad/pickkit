"""Local Flask review UI for pickkit review-select triage.

This module is the single source of truth for the interactive review UI: how
the pending image queue is listed from an already intake'd batch, how
keyboard/button actions map onto ``review_select`` decisions, how image bytes
are served safely under the batch root, and how the small Flask app is
assembled and run. The batch engine itself (moving files, companions, the
decision log, manifest updates, audit) is
``review_select.review.apply_decisions``; the UI never reimplements file
moves.

Principles
----------
Engine only
    Every Keep / Crop / Reject action calls
    ``apply_decisions(batch_root, [Decision(source, action)])`` immediately;
    the UI never moves files, writes logs, or updates the manifest itself.
Batch must be intake'd
    ``<batch_root>/.pickkit/project.json`` must already exist (created by
    intake-init). :func:`list_pending_images` and :func:`create_app` refuse
    anything else with :class:`FileNotFoundError` before a server starts or a
    queue is returned.
Pending queue from disk
    The queue is re-listed from disk on every request; the UI never trusts a
    stale in-memory queue. Visible files matching
    :data:`intake_init.intake.DEFAULT_IMAGE_SUFFIXES` under the batch root are
    pending. Anything with a hidden path part (``.pickkit`` included) or a
    known stage directory part (:data:`STAGE_DIR_NAMES`) is skipped.
Flat batches first
    Per-image triage is the v1 UX: the pending head is one image. Same-stem
    image groups are deferred.
Safe bytes
    Image bytes are served with Flask ``send_file`` from paths resolved under
    the batch root only; ``..`` and absolute escapes are refused.
Session counter
    ``decided_this_session`` is an in-memory Flask app config value, reset on
    each server start.
No AI
    The UI never recommends, ranks, crops, or writes pixels; it only shows
    originals and applies the three public decisions.

Public API
----------
``DEFAULT_HOST``
    Default bind host for :func:`run_ui`: ``127.0.0.1`` (local only).
``DEFAULT_PORT``
    Default bind port for :func:`run_ui`: ``8765``.
``STAGE_DIR_NAMES``
    Frozenset of known stage directory names skipped when they appear as a
    path part while listing pending images: ``__selected``, ``__crop``,
    ``__reject``, and ``__cropped``.
``list_pending_images(batch_root)``
    Return the pending image queue as a sorted list of absolute
    :class:`pathlib.Path` objects under *batch_root* (sorted by relative
    POSIX path, stable).
``map_ui_action(token)``
    Map a UI action token to one of ``review_select.review.ACTIONS``.
    Accepts ``K``/``C``/``R``, ``1``/``2``/``3``, and the snake_case
    synonyms ``keep``/``crop``/``reject``. Unknown tokens are refused with
    :class:`ValueError`.
``safe_image_path(batch_root, rel_or_name)``
    Resolve *rel_or_name* under *batch_root* and return the absolute
    :class:`pathlib.Path`. Refuses ``..`` escapes and absolute paths outside
    the root with :class:`ValueError`.
``create_app(batch_root, *, session_decided=None)``
    Build the Flask app for *batch_root*. ``session_decided`` seeds the
    in-memory decided counter (default ``0``).
``run_ui(batch_root, *, host=DEFAULT_HOST, port=DEFAULT_PORT)``
    Validate *batch_root* and start the Flask server on ``host:port``.

Keyboard shortcuts
------------------
``K`` / ``1`` — keep   (moves to ``__selected``)
``C`` / ``2`` — crop   (queues to ``__crop``)
``R`` / ``3`` — reject (moves to ``__reject``)

The full-word tokens ``keep`` / ``crop`` / ``reject`` are accepted by
:func:`map_ui_action` as synonyms; the page buttons post those words.

Host / port
-----------
The UI binds ``127.0.0.1:8765`` by default (see ``DEFAULT_HOST`` /
``DEFAULT_PORT``). The ``pickkit-review`` CLI overrides these with ``--host``
and ``--port``. The server is local-only by default; binding a non-loopback
interface is an explicit operator choice.

Routes
------
``GET /``
    Review page: current pending head or a "queue empty" state, with the
    remaining and decided-this-session counts.
``GET /api/status``
    JSON: ``remaining`` (int), ``decided_this_session`` (int), and
    ``current`` (relative POSIX path of the pending head, or null).
``POST /api/decide``
    JSON body ``{"source": "<relative path>", "action": "<token>"}``. Maps
    the action, resolves the source safely, applies one ``Decision`` via
    :func:`review_select.review.apply_decisions` immediately, and returns the
    next status JSON in the same shape as ``GET /api/status``.
``GET /image/<path:rel>``
    Serve the original image bytes for a file under the batch root; escape
    attempts and missing files return 404.

Out of scope / Notes
--------------------
- Finish: ``--finish`` stays CLI-only for now. An empty-queue finish call
  would be a no-op under ``apply_decisions`` finish semantics
  (``finished_at`` is only set when at least one decision is applied in the
  same call), so the UI shows ``pickkit-review <batch_root> --finish`` in the
  queue-empty state instead of shipping a misleading finish button.
- Same-stem image grouping, AI recommendations, pixel crops, and the
  multi-crop UI are out of scope.
- Template: ``templates/review.html`` is shipped as package data (see
  ``pyproject.toml`` ``[tool.setuptools.package-data]``).
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from intake_init import DEFAULT_IMAGE_SUFFIXES
from multi_crop.crop import CROPPED_DIR_NAME

from .review import (
    CROP,
    CROP_DIR_NAME,
    KEEP,
    KEEP_DIR_NAME,
    MANIFEST_NAME,
    PICKKIT_DIR_NAME,
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


def _rel(root: Path, path: Path) -> str:
    """Return *path* relative to *root* (POSIX style) when it is under it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _require_intaked_root(batch_root: str | Path) -> Path:
    """Resolve *batch_root* and refuse anything that is not intake'd.

    Mirrors the refusal path of :func:`review_select.review.apply_decisions`:
    the root must exist, be a directory, and contain
    ``.pickkit/project.json``.
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
    """Return the pending image queue for an intake'd *batch_root*.

    The queue is every visible file under the batch root whose lowercase
    suffix is in :data:`intake_init.intake.DEFAULT_IMAGE_SUFFIXES`, skipping
    hidden path parts (including ``.pickkit``) and known stage directories
    (:data:`STAGE_DIR_NAMES`). Returns absolute :class:`pathlib.Path` objects
    sorted by relative POSIX path (stable).
    """
    root = _require_intaked_root(batch_root)
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
    """Map a UI action token to one of ``review_select.review.ACTIONS``.

    Accepts ``K`` / ``C`` / ``R``, ``1`` / ``2`` / ``3``, and the synonyms
    ``keep`` / ``crop`` / ``reject`` (case-insensitive). Unknown tokens are
    refused with :class:`ValueError`.
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


def create_app(
    batch_root: str | Path,
    *,
    session_decided: int | None = None,
) -> Flask:
    """Build the Flask review app for an intake'd *batch_root*.

    The pending queue is re-listed from disk on every request, and
    ``decided_this_session`` is kept in-memory on the app config (seeded by
    *session_decided*, default ``0``).
    """
    root = _require_intaked_root(batch_root)
    app = Flask(__name__)
    app.config["BATCH_ROOT"] = root
    app.config["DECIDED_THIS_SESSION"] = int(session_decided or 0)

    def status_payload() -> dict[str, object]:
        pending = list_pending_images(root)
        return {
            "remaining": len(pending),
            "decided_this_session": app.config["DECIDED_THIS_SESSION"],
            "current": _rel(root, pending[0]) if pending else None,
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
            current=_rel(root, current_path) if current_path else None,
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
            apply_decisions(root, [Decision(_rel(root, image_path), action)])
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
    """Validate *batch_root* and start the Flask review server on ``host:port``."""
    root = _require_intaked_root(batch_root)
    app = create_app(root)
    print(f"pickkit review UI: http://{host}:{port}  (batch: {root})")
    print("Keyboard: K/C/R or 1/2/3. Ctrl+C stops the server.")
    app.run(host=host, port=port, debug=False)
