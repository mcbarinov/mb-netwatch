"""Shared process-control helpers for stopping components by pid file."""

from pathlib import Path
from typing import Literal

from mm_clikit import is_process_running, read_pid_file, stop_process
from pydantic import BaseModel, ConfigDict

StopOutcome = Literal["not_running", "stopped", "timeout"]


class StopResult(BaseModel):
    """Result of attempting to stop a component by its PID file."""

    model_config = ConfigDict(frozen=True)

    outcome: StopOutcome  # not_running | stopped | timeout
    pid: int | None  # Target PID, or None if nothing was running


def stop_by_pid_file(pid_path: Path, *, timeout: float, force_kill: bool) -> StopResult:
    """Send SIGTERM to the process named in ``pid_path`` and wait for exit.

    With ``force_kill=True``, SIGKILL follows if the process doesn't exit within
    ``timeout``, so the returned outcome is never ``"timeout"``.
    """
    if not is_process_running(pid_path, remove_stale=True, skip_self=True):
        return StopResult(outcome="not_running", pid=None)

    pid = read_pid_file(pid_path)
    if pid is None:
        return StopResult(outcome="not_running", pid=None)

    if stop_process(pid, timeout=timeout, force_kill=force_kill):
        pid_path.unlink(missing_ok=True)
        return StopResult(outcome="stopped", pid=pid)

    return StopResult(outcome="timeout", pid=pid)
