"""Central application entry point."""

from mb_netwatch.config import Config
from mb_netwatch.core.db import Db
from mb_netwatch.core.service import Service


class Core:
    """Holds shared resources and services. All consumers access db, config, and business logic through this object."""

    def __init__(self, db: Db, cfg: Config) -> None:
        """Initialize core with database and configuration.

        Args:
            db: Database access object.
            cfg: Application configuration.

        """
        self.db = db
        self.cfg = cfg
        self.service = Service(db, cfg)
