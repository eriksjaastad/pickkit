"""Exception types for lib_safety."""


class SafetyError(Exception):
    """Base class for all lib_safety failures."""


class DestinationExistsError(SafetyError, FileExistsError):
    """Raised when a move would clobber an existing destination file."""


class RefusedWriteError(SafetyError, FileExistsError):
    """Raised when a write would overwrite an existing file (no in-place writes)."""
