"""Application settings and user-facing configuration."""

import tomllib
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Self

from mm_clikit import BaseDataDirConfig
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class ProbedConfig(BaseModel):
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


class LatencyThresholdConfig(BaseModel):
    """Latency classification thresholds shared by all display consumers (tray, TUI).

    Args:
        ok_ms: latency below this is OK (milliseconds).
        slow_ms: latency below this is SLOW, at or above is BAD (milliseconds).
        stale_seconds: seconds since last latency row before data is considered stale.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok_ms: int = Field(default=300, gt=0)
    slow_ms: int = Field(default=800, gt=0)
    stale_seconds: float = Field(default=10.0, gt=0)

    @model_validator(mode="after")
    def _check_threshold_ordering(self) -> Self:
        if self.ok_ms >= self.slow_ms:
            raise ValueError(
                f"latency_threshold.ok_ms ({self.ok_ms}) must be less than latency_threshold.slow_ms ({self.slow_ms})"
            )
        return self


class TrayConfig(BaseModel):
    """Settings for the menu bar UI process.

    Args:
        poll_interval: seconds between tray DB polls for fresh data.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_interval: float = Field(default=2.0, gt=0)


class TuiConfig(BaseModel):
    """Settings for the TUI dashboard.

    Args:
        poll_interval: seconds between TUI DB polls.
        latency_history_max: max number of latency readings in sparkline.

    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_interval: float = Field(default=0.5, gt=0)
    latency_history_max: int = Field(default=300, gt=0)


class Config(BaseDataDirConfig):
    """Top-level application configuration.

    Args:
        probed: background measurement daemon settings.
        latency_threshold: latency classification thresholds for display.
        tray: menu bar UI settings.
        tui: TUI dashboard settings.

    """

    app_name: ClassVar[str] = "mb-netwatch"

    model_config = ConfigDict(frozen=True, extra="forbid")

    debug: bool = Field(default=False, description="Enable DEBUG level in the log file")
    probed: ProbedConfig = Field(default_factory=ProbedConfig)
    latency_threshold: LatencyThresholdConfig = Field(default_factory=LatencyThresholdConfig)
    tray: TrayConfig = Field(default_factory=TrayConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)

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
    def log_path(self) -> Path:
        """Unified log file shared by probed, tray, and TUI."""
        return self.data_dir / "netwatch.log"

    def base_argv(self) -> list[str]:
        """Extend inherited argv with --debug when set."""
        args = super().base_argv()
        if self.debug:
            args.append("--debug")
        return args

    @staticmethod
    def build(data_dir: Path | None = None, *, debug: bool = False) -> Config:
        """Build a Config from CLI arg / env var / default, with optional TOML overlay.

        Raises ValueError on invalid values or unknown TOML keys.
        """
        resolved = Config.resolve_data_dir(data_dir)

        config_path = resolved / "config.toml"
        kwargs: dict[str, Any] = {"data_dir": resolved, "debug": debug}

        if config_path.exists():
            with config_path.open("rb") as f:
                data = tomllib.load(f)

            known_sections = frozenset({"probed", "latency_threshold", "tray", "tui"})
            unknown = set(data.keys()) - known_sections
            if unknown:
                raise ValueError(f"Unknown config sections: {', '.join(sorted(unknown))}")

            kwargs["probed"] = ProbedConfig(**data.get("probed", {}))
            kwargs["latency_threshold"] = LatencyThresholdConfig(**data.get("latency_threshold", {}))
            kwargs["tray"] = TrayConfig(**data.get("tray", {}))
            kwargs["tui"] = TuiConfig(**data.get("tui", {}))

        return Config(**kwargs)
