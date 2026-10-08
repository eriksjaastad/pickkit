"""Local Flask finish wizard for pickkit finish-package.

Started by ``pickkit-finish <batch_root> --ui``. The batch must be intake'd.
Every dry-run and commit calls ``finish_package.finish.finish_package``; the
wizard has no ZIP, scanning or manifest logic of its own, re-reads the report
from disk on every request, and never uploads the ZIP.

The page opens on a dry-run preview: ``eligible_count``, ``by_ext_included``,
``excluded_counts``, the planned ZIP path, the content roots, and up to 20
sample eligible and excluded paths. Nothing is written until Commit ZIP.

Buttons
-------
- **Refresh dry-run**: re-run the dry-run with the form's content / output
  overrides. Writes nothing.
- **Commit ZIP**: commit with the Force checkbox and the overrides, then show
  the ZIP path and ``finished_at``. Disabled once the manifest has
  ``finished_at`` or the planned ZIP exists, unless Force is checked.
- **Force**: allow overwriting an existing delivery ZIP, never a source image.

Host / port
-----------
Binds ``127.0.0.1:8767`` by default, local only (``DEFAULT_HOST`` /
``DEFAULT_PORT``); ``pickkit-finish --host`` / ``--port`` override it.

Routes
------
``GET /``
    The wizard page with a dry-run report.
``GET /api/status``
    JSON dry-run report for optional ``?content=`` / ``?output=`` overrides:
    ``eligible_count``, ``by_ext_included``, ``excluded_counts``,
    ``incoming_by_ext``, ``planned_zip``, ``content_roots``, ``samples``,
    ``committed``, ``finished_at`` and ``zip_exists``.
``POST /api/refresh``
    Body ``{"content": ..., "output": ...}`` (both optional). Same shape as
    ``GET /api/status``; writes nothing.
``POST /api/commit``
    Body ``{"force": false, "content": ..., "output": ...}`` (all optional).
    Commits and returns the report plus ``zip_path`` and ``finished_at``.
    Errors: 409 when the ZIP exists without force, 404 for a missing batch or
    inventory, 400 for bad overrides (each with ``committed: false``), and 500
    with ``committed: true`` when the commit succeeded but its log or the
    follow-up report failed.

Every route, ``GET /`` included, answers a bad ``project.json`` or inventory
with a JSON error rather than an HTML error page.

Public API
----------
``DEFAULT_HOST``
``DEFAULT_PORT``
``planned_zip_path(batch_root, output_zip=None)``
``content_roots_for_ui(batch_root, content=None)``
``sample_paths(batch_root, content=None, *, limit=20)``
``create_app(batch_root)``
``run_ui(batch_root, *, host=DEFAULT_HOST, port=DEFAULT_PORT)``
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from lib_safety import rel_path
from lib_safety.webui import require_intaked_root, run_app

from .finish import (
    DEFAULT_ZIP_NAME,
    EXCLUDED_BUCKETS,
    INVENTORY_NAME,
    MANIFEST_NAME,
    PICKKIT_DIR_NAME,
    FinishLogError,
    FinishResult,
    ManifestError,
    classify_file,
    default_content_roots,
    finish_package,
    load_allowlist,
    load_manifest,
)

#: Default bind host for the local finish wizard (loopback only).
DEFAULT_HOST = "127.0.0.1"

#: Default bind port for the local finish wizard (review uses 8765, crop 8766).
DEFAULT_PORT = 8767

#: Sample-list cap for eligible / excluded previews (each list).
SAMPLE_LIMIT = 20


def planned_zip_path(
    batch_root: str | Path, output_zip: str | Path | None = None
) -> Path:
    """Return the ZIP path a commit would write for *batch_root*.

    The default is ``<batch_root>/delivery.zip`` (:data:`DEFAULT_ZIP_NAME`);
    *output_zip* overrides it with the same resolution the engine uses
    (relative paths under the batch root, absolute paths allowed).
    """
    root = require_intaked_root(batch_root)
    if output_zip is None:
        return root / DEFAULT_ZIP_NAME
    candidate = Path(output_zip).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def content_roots_for_ui(
    batch_root: str | Path, content: str | Path | None = None
) -> list[Path]:
    """Return the content roots the engine will scan for *batch_root*.

    ``default_content_roots`` when *content* is ``None``, else the one
    override directory, refused the same way the engine refuses it.
    """
    root = require_intaked_root(batch_root)
    if content is None:
        return default_content_roots(root)
    candidate = Path(content).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"content directory is outside batch root: {content}")
    if not resolved.exists():
        raise FileNotFoundError(f"content directory not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"content is not a directory: {resolved}")
    return [resolved]


def sample_paths(
    batch_root: str | Path,
    content: str | Path | None = None,
    *,
    limit: int = SAMPLE_LIMIT,
) -> dict[str, list[str]]:
    """Return short sample lists of eligible / excluded relative POSIX paths.

    Walks the same content roots the engine scans and classifies each file
    with the engine's :func:`classify_file`. Each list is capped at *limit*.
    """
    root = require_intaked_root(batch_root)
    allowed = load_allowlist(root / PICKKIT_DIR_NAME / INVENTORY_NAME)
    eligible: list[str] = []
    excluded: list[str] = []
    for content_root in content_roots_for_ui(root, content):
        for path in sorted(content_root.rglob("*")):
            if not path.is_file():
                continue
            category = classify_file(path, root, allowed=allowed)
            if category == "eligible":
                if len(eligible) < limit:
                    eligible.append(rel_path(root, path))
            elif len(excluded) < limit:
                excluded.append(rel_path(root, path))
            if len(eligible) >= limit and len(excluded) >= limit:
                return {"eligible": eligible, "excluded": excluded}
    return {"eligible": eligible, "excluded": excluded}


def _read_finished_at(root: Path) -> str | None:
    """Return the manifest's top-level ``finished_at`` string, or ``None``.

    An unreadable manifest raises :class:`ManifestError` rather than looking
    like "not committed".
    """
    data = load_manifest(root / PICKKIT_DIR_NAME / MANIFEST_NAME)
    finished_at = data.get("finished_at")
    return finished_at if isinstance(finished_at, str) else None


def _status_text(payload: dict[str, object]) -> str:
    """Human-readable commit status for the page."""
    if payload.get("committed"):
        return f"Committed at {payload.get('finished_at')}"
    if payload.get("zip_exists"):
        return "Not committed — planned ZIP already exists (use Force to overwrite)"
    return "Not committed — dry-run only"


def create_app(batch_root: str | Path) -> Flask:
    """Build the Flask finish wizard app for an intake'd *batch_root*.

    Every report is re-derived from disk on each request; the engine runs
    behind every dry-run and commit.
    """
    root = require_intaked_root(batch_root)
    app = Flask(__name__)
    app.config["BATCH_ROOT"] = root

    @app.errorhandler(ManifestError)
    def manifest_read_failed(exc: ManifestError):
        """JSON for every manifest-read failure that escapes a view."""
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(FileNotFoundError)
    def missing_file(exc: FileNotFoundError):
        """JSON for a manifest or inventory that disappeared after startup."""
        return jsonify({"error": str(exc)}), 404

    @app.errorhandler(NotADirectoryError)
    def not_a_directory(exc: NotADirectoryError):
        """JSON for an expected engine path that is not a directory."""
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(ValueError)
    def bad_value(exc: ValueError):
        """JSON for other expected engine errors, including a bad inventory.

        The request-body checks below raise ``ValueError`` to reach it too.
        ``ManifestError`` is a ``ValueError`` and keeps its own handler.
        """
        return jsonify({"error": str(exc)}), 400

    def report_payload(
        content: str | None = None, output: str | None = None
    ) -> dict[str, object]:
        """Run a dry-run and build the JSON report shape."""
        result = finish_package(
            root, commit=False, content=content, output_zip=output
        )
        planned = planned_zip_path(root, output)
        roots = content_roots_for_ui(root, content)
        finished_at = _read_finished_at(root)
        return {
            "batch_root": str(root),
            "batch_name": root.name,
            "eligible_count": result.eligible_count,
            "by_ext_included": result.by_ext_included,
            "excluded_counts": result.excluded_counts,
            "incoming_by_ext": result.incoming_by_ext,
            "planned_zip": rel_path(root, planned),
            "content_roots": [rel_path(root, path) for path in roots],
            "samples": sample_paths(root, content),
            "committed": finished_at is not None,
            "finished_at": finished_at,
            "zip_exists": planned.is_file(),
        }

    def _json_body(error: str) -> dict[str, object]:
        """Return the JSON object body, or ``{}`` for an empty body.

        An empty body is allowed (the form always sends ``{}`` or overrides).
        Any other non-object body raises :class:`ValueError` with *error*,
        which the ``ValueError`` handler above answers with a 400.
        """
        if request.get_data() == b"":
            return {}
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError(error)
        return payload

    def _overrides(body: dict[str, object]) -> tuple[str | None, str | None]:
        """Return the ``content`` / ``output`` overrides, ``None`` when blank.

        A value that is neither a string nor null raises :class:`ValueError`
        (a 400 through the handler above).
        """
        content = body.get("content")
        output = body.get("output")
        if content is not None and not isinstance(content, str):
            raise ValueError("'content' must be a string or null")
        if output is not None and not isinstance(output, str):
            raise ValueError("'output' must be a string or null")
        return content or None, output or None

    def _zip_rel(result: FinishResult) -> str | None:
        """The committed ZIP path relative to the batch root, or ``None``."""
        if result.zip_path is None:
            return None
        return rel_path(root, result.zip_path)

    def _committed_error(error: str, result: FinishResult):
        """JSON 500 for a commit whose ZIP and manifest close already succeeded."""
        return jsonify({
            "error": error,
            "committed": result.finished_at is not None,
            "finished_at": result.finished_at,
            "zip_path": _zip_rel(result),
        }), 500

    @app.get("/")
    def index() -> str:
        # Manifest and other engine failures propagate to the JSON error
        # handlers above. This view only renders a successful dry-run.
        payload = report_payload()
        by_ext_included_text = (
            " ".join(
                f"{ext}={count}"
                for ext, count in payload["by_ext_included"].items()
            )
            or "—"
        )
        excluded_counts_text = " ".join(
            f"{bucket}={payload['excluded_counts'][bucket]}"
            for bucket in EXCLUDED_BUCKETS
        )
        return render_template(
            "finish.html",
            batch_root=root,
            batch_name=root.name,
            report=payload,
            error=None,
            by_ext_included_text=by_ext_included_text,
            excluded_counts_text=excluded_counts_text,
            status_text=_status_text(payload),
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(
            report_payload(request.args.get("content"), request.args.get("output"))
        )

    @app.post("/api/refresh")
    def api_refresh():
        body = _json_body(
            "JSON body must be an object with optional 'content' and 'output'"
        )
        content, output = _overrides(body)
        return jsonify(report_payload(content, output))

    @app.post("/api/commit")
    def api_commit():
        body = _json_body(
            "JSON body must be an object with optional 'force', 'content', and 'output'"
        )
        force = body.get("force", False)
        if not isinstance(force, bool):
            raise ValueError("'force' must be a boolean")
        content, output = _overrides(body)

        try:
            result = finish_package(
                root,
                commit=True,
                force=force,
                content=content,
                output_zip=output,
            )
        except FinishLogError as exc:
            # ZIP and manifest close already finished. The log write failed.
            return _committed_error(str(exc), exc.result)
        except FileExistsError as exc:  # includes RefusedWriteError
            return jsonify({"error": str(exc), "committed": False}), 409
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc), "committed": False}), 404
        except (NotADirectoryError, ValueError) as exc:
            # ManifestError is a ValueError. The commit did not finish.
            return jsonify({"error": str(exc), "committed": False}), 400

        try:
            payload = report_payload(content, output)
        except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
            # ZIP and manifest close already succeeded. Say so in JSON
            # instead of an HTML 500 that looks like nothing was committed.
            return _committed_error(
                f"committed, but the batch summary could not be re-read: {exc}",
                result,
            )

        payload["zip_path"] = _zip_rel(result)
        payload["finished_at"] = result.finished_at
        payload["committed"] = result.finished_at is not None
        payload["zip_exists"] = (
            result.zip_path is not None and result.zip_path.is_file()
        )
        return jsonify(payload)

    return app


def run_ui(
    batch_root: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Validate *batch_root* and start the Flask finish wizard on ``host:port``."""
    run_app(
        create_app,
        batch_root,
        title="finish",
        hint="Preview the eligible/excluded report, then Commit ZIP. Ctrl+C stops the server.",
        host=host,
        port=port,
    )
