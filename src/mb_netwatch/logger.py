"""Application-wide logging configuration."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup_logging(*, debug: bool = False, log_file: Path | None = None) -> None:
    """Configure logging for the mb_netwatch package.

    Sets the level on the ``mb_netwatch`` namespace logger so that
    third-party libraries (aiohttp, etc.) stay at WARNING.

    When *log_file* is given, logs go to a rotating file (2 MB, 1 backup).
    Otherwise logs go to stderr.
    """
    level = logging.DEBUG if debug else logging.INFO
    app_logger = logging.getLogger("mb_netwatch")
    app_logger.setLevel(level)
    app_logger.propagate = False

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=1)
    else:
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    # Remove old handlers to avoid duplicates on re-init
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
