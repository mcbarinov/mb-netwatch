"""Composition root — holds config, database, and service layer."""

import logging

from mm_clikit import setup_logging

from mb_netwatch.config import Config
from mb_netwatch.core.db import Db
from mb_netwatch.core.service import Service


class Core:
    """Application composition root. Creates and owns all shared resources (database, services)."""

    def __init__(self, config: Config) -> None:
        """Initialize core with configuration.

        Args:
            config: Application configuration.

        """
        self.config = config
        # console_level=None is required for TUI (Textual owns the terminal) and harmless elsewhere:
        # typer/CliError handle user-facing errors via stderr independently of stdlib logging.
        # quiet_loggers suppresses aiohttp internals — under --debug our log would otherwise drown in per-request noise.
        setup_logging(
            "mb_netwatch",
            file_path=config.log_path,
            file_level=logging.DEBUG if config.debug else logging.INFO,
            console_level=None,
            quiet_loggers=("aiohttp.client", "aiohttp.internal"),
        )

        self.db = Db(config.db_path)  # SQLite database — used directly for simple reads
        self.service = Service(self.db, config)  # Business logic (validation, orchestration)

    def close(self) -> None:
        """Release resources."""
        self.db.close()
