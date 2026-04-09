"""Application settings and user-facing configuration."""

import os
import tomllib
from functools import cached_property
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

DEFAULT_DATA_DIR = Path.home() / ".local" / "mb-netwatch"
"""Fallback data directory when neither --data-dir nor env var is set."""


class _ProbedConfig(BaseModel):
    """Settings for the background measurement daemon.

    Args:
        latency_interval: seconds between latency probes.
        vpn_interval: seconds between VPN status checks.
        ip_interval: seconds between public IP lookups.
        purge_interval: seconds between old-data purge runs.
        latency_timeout: HTTP timeout for latency probes (seconds).
        ip_timeout: HTTP timeout for IP/country lookups (seconds).
        retention_days: days to keep raw measurement rows before purging.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    latency_interval: float = Field(default=2.0, gt=0)
    vpn_interval: float = Field(default=10.0, gt=0)
    ip_interval: float = Field(default=60.0, gt=0)
    purge_interval: float = Field(default=3600.0, gt=0)
    latency_timeout: float = Field(default=5.0, gt=0)
    ip_timeout: float = Field(default=5.0, gt=0)
    retention_days: int = Field(default=30, gt=0)


class _TrayConfig(BaseModel):
    """Settings for the menu bar UI process.

    Args:
        poll_interval: seconds between tray DB polls for fresh data.
        ok_threshold_ms: latency below this is OK (milliseconds).
        slow_threshold_ms: latency below this is SLOW, at or above is BAD (milliseconds).
        stale_threshold: seconds since last latency row before data is considered stale.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_interval: float = Field(default=2.0, gt=0)
    ok_threshold_ms: int = Field(default=300, gt=0)
    slow_threshold_ms: int = Field(default=800, gt=0)
    stale_threshold: float = Field(default=10.0, gt=0)

    @model_validator(mode="after")
    def _check_threshold_ordering(self) -> Self:
        if self.ok_threshold_ms >= self.slow_threshold_ms:
            ok, slow = self.ok_threshold_ms, self.slow_threshold_ms
            raise ValueError(f"tray.ok_threshold_ms ({ok}) must be less than tray.slow_threshold_ms ({slow})")
        return self


class _WatchConfig(BaseModel):
    """Settings for the live terminal view.

    Args:
        poll_interval: seconds between terminal view DB polls.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_interval: float = Field(default=0.5, gt=0)


class Config(BaseModel):
    """Top-level application configuration.

    Args:
        data_dir: base directory for all application data (DB, config, PID files, logs).
        probed: background measurement daemon settings.
        tray: menu bar UI settings.
        watch: live terminal view settings.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: Path = Field(default=DEFAULT_DATA_DIR, description="Base directory for all application data")
    probed: _ProbedConfig = Field(default_factory=_ProbedConfig)
    tray: _TrayConfig = Field(default_factory=_TrayConfig)
    watch: _WatchConfig = Field(default_factory=_WatchConfig)

    @computed_field
    @cached_property
    def db_path(self) -> Path:
        """SQLite database file path."""
        return self.data_dir / "netwatch.db"

    @computed_field
    @cached_property
    def config_path(self) -> Path:
        """Optional TOML configuration file path."""
        return self.data_dir / "config.toml"

    @computed_field
    @cached_property
    def probed_pid_path(self) -> Path:
        """PID file for the probed process."""
        return self.data_dir / "probed.pid"

    @computed_field
    @cached_property
    def tray_pid_path(self) -> Path:
        """PID file for the tray process."""
        return self.data_dir / "tray.pid"

    @computed_field
    @cached_property
    def probed_log_path(self) -> Path:
        """Log file for the probed process."""
        return self.data_dir / "probed.log"

    @computed_field
    @cached_property
    def tray_log_path(self) -> Path:
        """Log file for the tray process."""
        return self.data_dir / "tray.log"

    def cli_base_args(self) -> list[str]:
        """Build CLI base args, including --data-dir only when non-default.

        Useful for spawning subprocesses (daemons, workers) that need
        to inherit the data directory setting.
        """
        args: list[str] = ["mb-netwatch"]
        if self.data_dir != DEFAULT_DATA_DIR:
            args.extend(["--data-dir", str(self.data_dir)])
        return args

    @staticmethod
    def build(data_dir: Path | None = None) -> Config:
        """Build a Config from CLI arg / env var / default, with optional TOML overlay.

        Raises ValueError on invalid values or unknown TOML keys.
        """
        if data_dir is not None:
            resolved = data_dir.resolve()
        elif env := os.environ.get("MB_NETWATCH_DATA_DIR"):
            resolved = Path(env).resolve()
        else:
            resolved = DEFAULT_DATA_DIR

        config_path = resolved / "config.toml"
        kwargs: dict[str, Any] = {"data_dir": resolved}

        if config_path.exists():
            with config_path.open("rb") as f:
                data = tomllib.load(f)

            known_sections = frozenset({"probed", "tray", "watch"})
            unknown = set(data.keys()) - known_sections
            if unknown:
                raise ValueError(f"Unknown config sections: {', '.join(sorted(unknown))}")

            kwargs["probed"] = _ProbedConfig(**data.get("probed", {}))
            kwargs["tray"] = _TrayConfig(**data.get("tray", {}))
            kwargs["watch"] = _WatchConfig(**data.get("watch", {}))

        cfg = Config(**kwargs)
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        return cfg
