"""review_select: apply review triage decisions (keep/crop/reject) and log them.

The authoritative behaviour reference is the module docstring of
``review_select.review``; ``tests/test_review_select_docs.py`` guards it against
drift. This package re-exports the public names listed in :data:`__all__` so
callers can import them from ``review_select`` directly.
"""

from .review import (
    ACTIONS,
    CROP,
    CROP_DIR_NAME,
    KEEP,
    KEEP_DIR_NAME,
    REJECT,
    REJECT_DIR_NAME,
    ApplyResult,
    Decision,
    apply_decisions,
    build_parser,
    load_decisions,
    main,
)

__version__ = "0.1.0"

__all__ = [
    "ACTIONS",
    "CROP",
    "CROP_DIR_NAME",
    "KEEP",
    "KEEP_DIR_NAME",
    "REJECT",
    "REJECT_DIR_NAME",
    "ApplyResult",
    "Decision",
    "apply_decisions",
    "build_parser",
    "load_decisions",
    "main",
]
