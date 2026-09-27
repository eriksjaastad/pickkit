"""directory_viewer: read-only multi-directory image inventory.

The authoritative behaviour reference is the module docstring of
``directory_viewer.viewer``; ``tests/test_directory_viewer_docs.py`` guards it
against drift. This package re-exports the public names listed in
:data:`__all__` so callers can import them from ``directory_viewer`` directly.
"""

from .viewer import (
    DEFAULT_IMAGE_SUFFIXES,
    DEFAULT_SAMPLE_LIMIT,
    OPERATION,
    DirInventory,
    RootReport,
    build_parser,
    compare_roots,
    inventory,
    list_images_in,
    main,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "DEFAULT_SAMPLE_LIMIT",
    "OPERATION",
    "DirInventory",
    "RootReport",
    "build_parser",
    "compare_roots",
    "inventory",
    "list_images_in",
    "main",
]
