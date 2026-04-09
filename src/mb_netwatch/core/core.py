"""Composition root — holds config, database, and service layer."""

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
        self.db = Db(config.db_path)  # SQLite database — used directly for simple reads
        self.service = Service(self.db, config)  # Business logic (validation, orchestration)

    def close(self) -> None:
        """Release resources."""
        self.db.close()
