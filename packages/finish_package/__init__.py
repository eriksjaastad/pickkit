"""finish_package: close the batch manifest and stage a copy-only delivery ZIP.

Re-exports ``finish_package.finish.__all__``; that module's docstring
(``pickkit-finish --help``) documents them.
"""

from .finish import *
from .finish import __all__

__version__ = "0.1.0"
