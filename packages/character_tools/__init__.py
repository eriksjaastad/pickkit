"""character_tools: assign images to user-supplied named bins with companions.

The authoritative behaviour reference is the module docstring of
``character_tools.character``; ``tests/test_character_tools_docs.py`` guards it
against drift. This package re-exports the public names listed in
:data:`__all__` so callers can import them from ``character_tools`` directly.
"""

from .character import (
    DEFAULT_IMAGE_SUFFIXES,
    OPERATION,
    Assignment,
    AssignResult,
    BinSummary,
    MoveToBinResult,
    RejectResult,
    assign_batch,
    build_parser,
    check_bins,
    list_images,
    load_assignments,
    main,
    move_to_bin,
    normalise_bin_name,
    reject_image,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "OPERATION",
    "Assignment",
    "AssignResult",
    "BinSummary",
    "MoveToBinResult",
    "RejectResult",
    "assign_batch",
    "build_parser",
    "check_bins",
    "list_images",
    "load_assignments",
    "main",
    "move_to_bin",
    "normalise_bin_name",
    "reject_image",
]
