"""duplicate_finder: find exact/near-duplicate images and thin the extras.

The authoritative behaviour reference is the module docstring of
``duplicate_finder.dupes``; ``tests/test_duplicate_finder_docs.py`` guards it
against drift. This package re-exports the public names listed in
:data:`__all__` so callers can import them from ``duplicate_finder`` directly.
"""

from .dupes import (
    DEFAULT_IMAGE_SUFFIXES,
    DEFAULT_KEEP_POLICY,
    DEFAULT_NEAR_THRESHOLD,
    HASH_SIZE,
    KEEP_POLICIES,
    OPERATION,
    DuplicateGroup,
    ThinPlan,
    ThinResult,
    average_hash,
    build_parser,
    content_hash,
    find_exact_duplicates,
    find_near_duplicates,
    hamming_distance,
    list_images,
    main,
    plan_thin,
    thin_groups,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "DEFAULT_KEEP_POLICY",
    "DEFAULT_NEAR_THRESHOLD",
    "HASH_SIZE",
    "KEEP_POLICIES",
    "OPERATION",
    "DuplicateGroup",
    "ThinPlan",
    "ThinResult",
    "average_hash",
    "build_parser",
    "content_hash",
    "find_exact_duplicates",
    "find_near_duplicates",
    "hamming_distance",
    "list_images",
    "main",
    "plan_thin",
    "thin_groups",
]
