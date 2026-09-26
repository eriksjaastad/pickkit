"""intake_init: initialize a pickkit batch (manifest, inventory, audit baseline).

The authoritative behaviour reference is the module docstring of
``intake_init.intake``; ``tests/test_intake_init_docs.py`` guards it against
drift. This package re-exports the public names listed in :data:`__all__` so
callers can import them from ``intake_init`` directly.
"""

from .intake import (
    DEFAULT_IMAGE_SUFFIXES,
    IntakeResult,
    ManifestExistsError,
    build_parser,
    intake_init,
    main,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_IMAGE_SUFFIXES",
    "IntakeResult",
    "ManifestExistsError",
    "build_parser",
    "intake_init",
    "main",
]
