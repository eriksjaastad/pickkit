"""finish_package: close the batch manifest and stage a copy-only delivery ZIP.

The authoritative behaviour reference is the module docstring of
``finish_package.finish``; ``tests/test_finish_package_docs.py`` guards it
against drift. This package re-exports the public names listed in
:data:`__all__` so callers can import them from ``finish_package`` directly.
"""

from .finish import (
    AUDIT_NAME,
    CROPPED_DIR_NAME,
    CROP_QUEUE_DIR_NAME,
    DEFAULT_BANNED_EXTENSIONS,
    DEFAULT_BANNED_PATTERNS,
    DEFAULT_ZIP_NAME,
    EXCLUDED_BUCKETS,
    FINISH_LOG_NAME,
    FINISH_PACKAGE_STEP_NAME,
    INVENTORY_NAME,
    MANIFEST_NAME,
    OPERATION,
    PICKKIT_DIR_NAME,
    REJECT_DIR_NAME,
    SELECTED_DIR_NAME,
    FinishResult,
    build_parser,
    classify_file,
    default_content_roots,
    finish_package,
    load_allowlist,
    main,
)

__version__ = "0.1.0"

__all__ = [
    "AUDIT_NAME",
    "CROPPED_DIR_NAME",
    "CROP_QUEUE_DIR_NAME",
    "DEFAULT_BANNED_EXTENSIONS",
    "DEFAULT_BANNED_PATTERNS",
    "DEFAULT_ZIP_NAME",
    "EXCLUDED_BUCKETS",
    "FINISH_LOG_NAME",
    "FINISH_PACKAGE_STEP_NAME",
    "INVENTORY_NAME",
    "MANIFEST_NAME",
    "OPERATION",
    "PICKKIT_DIR_NAME",
    "REJECT_DIR_NAME",
    "SELECTED_DIR_NAME",
    "FinishResult",
    "build_parser",
    "classify_file",
    "default_content_roots",
    "finish_package",
    "load_allowlist",
    "main",
]
