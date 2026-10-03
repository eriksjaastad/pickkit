"""Local Flask finish wizard for pickkit finish-package.

This module is the single source of truth for the interactive finish wizard:
how the eligible/excluded dry-run report is previewed for an already intake'd
batch, how the Force checkbox and optional content/output overrides map onto
``finish_package.finish``, how the copy-only delivery ZIP is committed only
after confirmation, and how the small Flask app is assembled and run. The
batch engine itself (scanning, classification, ZIP writing, manifest close,
audit) is ``finish_package.finish.finish_package``; the UI never reimplements
ZIP logic, scanning rules, or manifest close.

Principles
----------
Engine only
    Every dry-run and commit goes through
    ``finish_package.finish.finish_package``. The UI never opens a
    ``ZipFile``, unlinks a delivery ZIP, or writes ``finished_at`` / metrics
    itself.
Batch must be intake'd
    ``<batch_root>/.pickkit/project.json`` must already exist (created by
    intake-init). :func:`create_app` and :func:`run_ui` refuse anything else
    with :class:`FileNotFoundError` before a server starts, mirroring the
    refusal path of ``finish_package``.
Dry-run first
    The initial page load and every Refresh dry-run call
    ``finish_package(..., commit=False)`` with the current form overrides and
    write nothing. Commit is the only write path.
Preview eligible vs excluded
    The page shows ``eligible_count``, ``by_ext_included``,
    ``excluded_counts`` (all ``EXCLUDED_BUCKETS`` keys), the planned ZIP path,
    the content roots used, and short sample lists of eligible / excluded
    relative paths (capped at ~20 each). Samples are built with the public
    ``classify_file`` helper plus ``default_content_roots`` / the content
    override; the UI never reimplements allow/ban rules.
Report re-read from disk
    Every status / refresh / commit response re-runs the engine and re-reads
    the manifest, so the page never trusts a stale in-memory report.
No auto-upload
    The wizard only calls the engine; it never uploads the delivery ZIP or
    writes outside the engine's chosen paths.

Public API
----------
``DEFAULT_HOST``
    Default bind host for :func:`run_ui`: ``127.0.0.1`` (local only).
``DEFAULT_PORT``
    Default bind port for :func:`run_ui`: ``8767`` (review-select uses
    ``8765`` and multi-crop uses ``8766``, so all three UIs can run at once).
``planned_zip_path(batch_root, output_zip=None)``
    Return the ZIP path a commit would write for *batch_root*: the default
    ``<batch_root>/delivery.zip`` (:data:`DEFAULT_ZIP_NAME`) or the
    *output_zip* override resolved the same way the engine resolves it
    (relative paths under the batch root, absolute paths allowed). A dry-run
    ``FinishResult.zip_path`` is ``None``, so the wizard uses this helper to
    display the planned path before committing.
``content_roots_for_ui(batch_root, content=None)``
    Return the content roots the engine will scan for *batch_root*: the
    public ``default_content_roots`` list when *content* is ``None``, or a
    single explicit directory resolved under the batch root (refusing
    outside / missing / non-directory paths like the engine does).
``sample_paths(batch_root, content=None, *, limit=20)``
    Return ``{"eligible": [...], "excluded": [...]}`` short sample lists of
    relative POSIX paths (capped at *limit* each) by walking the same content
    roots and classifying each file with the public ``classify_file``.
``create_app(batch_root)``
    Build the Flask finish wizard app for *batch_root*.
``run_ui(batch_root, *, host=DEFAULT_HOST, port=DEFAULT_PORT)``
    Validate *batch_root* and start the Flask server on ``host:port``.

Buttons
-------
- **Refresh dry-run** — re-runs ``finish_package(..., commit=False)`` with
  the current form overrides and refreshes the report. No writes.
- **Commit ZIP** — calls ``finish_package(..., commit=True,
  force=<checkbox>, content=<override or None>, output_zip=<override or
  None>)``; after success the page shows the ZIP path and ``finished_at``.
  The button is disabled once the manifest has ``finished_at`` or the planned
  ZIP already exists, unless Force is checked.
- **Force** checkbox — allows overwriting an existing delivery ZIP (never a
  source image); required to re-commit after the batch is finished or the ZIP
  already exists.

Host / port
-----------
The wizard binds ``127.0.0.1:8767`` by default (see ``DEFAULT_HOST`` /
``DEFAULT_PORT``). The ``pickkit-finish`` CLI overrides these with ``--host``
and ``--port``, which are only valid together with ``--ui``. The server is
local-only by default; binding a non-loopback interface is an explicit
operator choice.

Routes
------
``GET /``
    Finish wizard page; initial load runs a dry-run and renders the report
    plus the Force / content / output form.
``GET /api/status``
    JSON dry-run report for the current (or ``?content=`` / ``?output=``
    query) overrides: ``eligible_count``, ``by_ext_included``,
    ``excluded_counts``, ``incoming_by_ext``, ``planned_zip``,
    ``content_roots``, ``samples`` (eligible/excluded short lists),
    ``committed`` / ``finished_at`` when already finished, and ``zip_exists``.
``POST /api/refresh``
    JSON body ``{"content": "...", "output": "..."}`` (both optional). Runs
    ``finish_package(..., commit=False)`` again with those overrides and
    returns the same shape as ``GET /api/status``. No writes.
``POST /api/commit``
    JSON body ``{"force": false, "content": "...", "output": "..."}`` (all
    optional). Calls ``finish_package(..., commit=True, ...)``; on success
    returns the report plus ``zip_path`` and ``finished_at``. Collisions
    without Force return 409 with a clear error (``RefusedWriteError`` /
    ``FileExistsError``); missing batches/inventories return 404 and bad
    overrides return 400. The body includes ``committed``: false when the
    commit did not finish, and a JSON 500 with ``committed`` true when the
    ZIP and manifest close succeeded but the follow-up summary could not be
    re-read.
Manifest read failures
    Every route, including ``GET /``, answers JSON (never an HTML error page)
    when ``project.json`` cannot be read. :func:`finish_package.finish.load_manifest`
    raises :class:`~finish_package.finish.ManifestError` for a missing file,
    a directory, an unreadable file, bad UTF-8, invalid JSON, or JSON that is
    not an object. Flask error handlers map that error, and other expected engine errors (``ValueError``, ``NotADirectoryError``, ``FileNotFoundError``), to JSON. The app
    is created only after intake, so these failures are ones that show up on
    a later request.

Out of scope / Notes
--------------------
- Uploading the delivery ZIP to remote storage is not part of this wizard.
- Custom bans JSON files / allowlist override files, scanning ``__crop`` /
  ``__reject`` / loose batch-root files by default (the engine decides; the
  UI just displays), client project IDs, training databases, a Tk precursor
  wizard, and middle-spine tools / card #7651 are out of scope.
- Template: ``templates/finish.html`` is shipped as package data (see
  ``pyproject.toml`` ``[tool.setuptools.package-data]``).
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from .finish import (
    DEFAULT_ZIP_NAME,
    EXCLUDED_BUCKETS,
    INVENTORY_NAME,
    MANIFEST_NAME,
    PICKKIT_DIR_NAME,
    FinishLogError,
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


def _rel(root: Path, path: Path) -> str:
    """Return *path* relative to *root* (POSIX style) when it is under it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _require_intaked_root(batch_root: str | Path) -> Path:
    """Resolve *batch_root* and refuse anything that is not intake'd.

    Mirrors the refusal path of :func:`finish_package.finish.finish_package`:
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


def planned_zip_path(
    batch_root: str | Path, output_zip: str | Path | None = None
) -> Path:
    """Return the ZIP path a commit would write for *batch_root*.

    The default is ``<batch_root>/delivery.zip`` (:data:`DEFAULT_ZIP_NAME`);
    *output_zip* overrides it with the same resolution the engine uses
    (relative paths under the batch root, absolute paths allowed).
    """
    root = _require_intaked_root(batch_root)
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

    With *content* ``None`` this is the public ``default_content_roots`` list;
    otherwise it is a single explicit directory resolved under the batch root.
    Outside / missing / non-directory overrides are refused the same way the
    engine refuses them.
    """
    root = _require_intaked_root(batch_root)
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

    Walks the same content roots the engine would scan and classifies every
    file with the public :func:`finish_package.finish.classify_file` (and the
    intake allowlist via :func:`load_allowlist`), so the UI never reimplements
    allow/ban rules. Each list is capped at *limit* entries.
    """
    root = _require_intaked_root(batch_root)
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
                    eligible.append(_rel(root, path))
            elif len(excluded) < limit:
                excluded.append(_rel(root, path))
            if len(eligible) >= limit and len(excluded) >= limit:
                return {"eligible": eligible, "excluded": excluded}
    return {"eligible": eligible, "excluded": excluded}


def _read_finished_at(root: Path) -> str | None:
    """Return the manifest's top-level ``finished_at`` string, or ``None``.

    Uses :func:`finish_package.finish.load_manifest`. A missing file, a
    directory, an unreadable file, bad UTF-8, invalid JSON, or a non-object
    raises :class:`~finish_package.finish.ManifestError` naming the path
    instead of looking like "not committed".
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
    root = _require_intaked_root(batch_root)
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

        ``ManifestError`` is a ``ValueError`` and keeps its own handler.
        A malformed allowlist used to be caught on ``GET /`` and shown in
        the page; without this handler that request is an HTML 500 while
        ``/api/status`` still returns the diagnostic.
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
            "planned_zip": _rel(root, planned),
            "content_roots": [_rel(root, path) for path in roots],
            "samples": sample_paths(root, content),
            "committed": finished_at is not None,
            "finished_at": finished_at,
            "zip_exists": planned.is_file(),
        }

    def _optional_json_body() -> dict[str, object] | None:
        """Return the JSON object body, ``{}`` for an empty body, else ``None``.

        An empty body is allowed (the form always sends ``{}`` or overrides);
        a non-empty, non-object body is rejected by the caller with 400.
        """
        if request.get_data() == b"":
            return {}
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return None
        return payload

    def dry_run_response(
        content: str | None, output: str | None
    ):
        """Run the dry-run payload and map engine errors to status codes."""
        try:
            return jsonify(report_payload(content, output))
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except (NotADirectoryError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

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
        return dry_run_response(
            request.args.get("content"), request.args.get("output")
        )

    @app.post("/api/refresh")
    def api_refresh():
        body = _optional_json_body()
        if body is None:
            return jsonify(
                {"error": "JSON body must be an object with optional 'content' and 'output'"}
            ), 400
        content = body.get("content")
        output = body.get("output")
        if content is not None and not isinstance(content, str):
            return jsonify({"error": "'content' must be a string or null"}), 400
        if output is not None and not isinstance(output, str):
            return jsonify({"error": "'output' must be a string or null"}), 400
        return dry_run_response(content or None, output or None)

    @app.post("/api/commit")
    def api_commit():
        body = _optional_json_body()
        if body is None:
            return jsonify(
                {"error": "JSON body must be an object with optional 'force', 'content', and 'output'"}
            ), 400
        force = body.get("force", False)
        if not isinstance(force, bool):
            return jsonify({"error": "'force' must be a boolean"}), 400
        content = body.get("content")
        output = body.get("output")
        if content is not None and not isinstance(content, str):
            return jsonify({"error": "'content' must be a string or null"}), 400
        if output is not None and not isinstance(output, str):
            return jsonify({"error": "'output' must be a string or null"}), 400
        content = content or None
        output = output or None

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
            result = exc.result
            return jsonify({
                "error": str(exc),
                "committed": result.finished_at is not None,
                "finished_at": result.finished_at,
                "zip_path": (
                    _rel(root, result.zip_path) if result.zip_path is not None else None
                ),
            }), 500
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
            return jsonify({
                "error": (
                    "committed, but the batch summary could not be re-read: "
                    f"{exc}"
                ),
                "committed": result.finished_at is not None,
                "finished_at": result.finished_at,
                "zip_path": (
                    _rel(root, result.zip_path) if result.zip_path is not None else None
                ),
            }), 500

        payload = dict(payload)
        payload["zip_path"] = (
            _rel(root, result.zip_path) if result.zip_path is not None else None
        )
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
    root = _require_intaked_root(batch_root)
    app = create_app(root)
    print(f"pickkit finish UI: http://{host}:{port}  (batch: {root})")
    print("Preview the eligible/excluded report, then Commit ZIP. Ctrl+C stops the server.")
    app.run(host=host, port=port, debug=False)
