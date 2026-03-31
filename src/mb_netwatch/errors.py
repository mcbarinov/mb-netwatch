"""Application-level errors."""

from mm_clikit import CliError


class AppError(CliError):
    """Application error with machine-readable code.

    Caught automatically by TyperPlus — formats as JSON or plain text and exits.
    """

    def __init__(self, code: str, message: str) -> None:
        """Initialize with machine-readable code and human-readable message."""
        super().__init__(message, error_code=code)
