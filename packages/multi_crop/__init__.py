"""multi_crop: create NEW cropped image files (never overwrite originals).

The authoritative behaviour reference is the module docstring of
``multi_crop.crop``; ``tests/test_multi_crop_docs.py`` guards it against
drift. This package re-exports the public names listed in :data:`__all__` so
callers can import them from ``multi_crop`` directly.
"""

from .crop import (
    AUDIT_NAME,
    CROPPED_DIR_NAME,
    CROP_QUEUE_DIR_NAME,
    CROPS_LOG_NAME,
    MANIFEST_NAME,
    MULTI_CROP_STEP_NAME,
    PICKKIT_DIR_NAME,
    ApplyResult,
    CropSpec,
    apply_crop,
    build_parser,
    clamp_box,
    crop_batch,
    load_crop_specs,
    main,
)

__version__ = "0.1.0"

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
