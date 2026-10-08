"""Small Flask helpers shared by the pickkit web UIs.

The review, crop and finish UIs each used to carry their own copy of these;
this module is the one copy they import. It imports Flask, so
``lib_safety/__init__`` deliberately does not import it: ``import lib_safety``
stays Flask-free. Every error message is part of the UIs' contracts and must
stay byte-identical.

Public API
----------
``require_intaked_root(batch_root)``
    Resolve *batch_root* and return it. Raises :class:`FileNotFoundError`
    when it does not exist or has no ``.pickkit/project.json``, and
    :class:`NotADirectoryError` when it is not a directory.
``safe_image_path(batch_root, rel_or_name)``
    Resolve *rel_or_name* under *batch_root* and return the absolute
    :class:`pathlib.Path`. Refuses ``..`` escapes and absolute paths outside
    the root with :class:`ValueError`.
``send_batch_image(root, rel)``
    Flask response with the bytes of *rel* under *root*; aborts with 404 for
    escapes and missing files.
``run_app(create_app, batch_root, *, title, hint, host, port)``
    Validate *batch_root*, build the app with *create_app*, print the two
    start-up lines (``pickkit <title> UI: ...`` and *hint*) and serve it.
``check_ui_args(parser, args, *, default_host, default_port, conflicts, conflicting)``
    The shared ``--ui`` / ``--host`` / ``--port`` CLI checks. Exits through
    ``parser.error`` when ``--host`` / ``--port`` differ from their defaults
    without ``--ui``, or when ``--ui`` is given and *conflicting* is true
    (*conflicts* names the CLI's other flags, e.g. ``"--commit/--force"``).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from flask import Flask, abort, send_file


def require_intaked_root(batch_root: str | Path) -> Path:
    """Resolve *batch_root* and refuse anything that is not intake'd.

    Mirrors the refusal path of the batch engines: the root must exist, be a
    directory, and contain intake-init's ``.pickkit/project.json``.
    """
    root = Path(batch_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"batch root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"batch root is not a directory: {root}")
    root = root.resolve()
    manifest_path = root / ".pickkit" / "project.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"batch is not intake'd: missing manifest {manifest_path}; "
            f"run pickkit-intake first"
        )
    return root


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


def send_batch_image(root: Path, rel: str):
    """Serve the bytes of *rel* under *root*; 404 for escapes or missing files."""
    try:
        image_path = safe_image_path(root, rel)
    except (ValueError, OSError):
        abort(404)
    if not image_path.is_file():
        abort(404)
    return send_file(image_path)


def run_app(
    create_app: Callable[[Path], Flask],
    batch_root: str | Path,
    *,
    title: str,
    hint: str,
    host: str,
    port: int,
) -> None:
    """Validate *batch_root*, build the app and serve it on ``host:port``."""
    root = require_intaked_root(batch_root)
    app = create_app(root)
    print(f"pickkit {title} UI: http://{host}:{port}  (batch: {root})")
    print(hint)
    app.run(host=host, port=port, debug=False)


def check_ui_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    default_host: str,
    default_port: int,
    conflicts: str,
    conflicting: bool,
) -> None:
    """Refuse ``--host`` / ``--port`` without ``--ui`` and ``--ui`` with *conflicts*."""
    if not args.ui and (args.host != default_host or args.port != default_port):
        parser.error("--host and --port may only be used together with --ui")
    if args.ui and conflicting:
        parser.error(f"--ui cannot be combined with {conflicts}")
