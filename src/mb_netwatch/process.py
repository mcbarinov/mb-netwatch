"""Process lifecycle management: PID files, liveness checks, spawning."""

import enum
import os
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path


class Component(enum.StrEnum):
    """Process component that can be started or stopped."""

    PROBED = "probed"
    TRAY = "tray"


def pid_path(component: Component, data_dir: Path) -> Path:
    """Return the PID file path for a component."""
    return data_dir / f"{component.value}.pid"


def read_pid(pid_path: Path) -> int | None:
    """Read PID from file. Returns None if missing, unreadable, or invalid."""
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError, OSError:
        return None
    return pid if pid > 0 else None


def is_alive(pid_path: Path) -> bool:
    """Check if the process in pid_path is alive. Removes stale PID file if dead.

    Skips pid == os.getpid() to avoid false positives during startup.
    """
    pid = read_pid(pid_path)
    if pid is None:
        return False

    # Current process wrote this file before re-exec — not a real duplicate
    if pid == os.getpid():
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return False
    except PermissionError:
        # Process exists but we can't signal it — treat as alive
        pass
    return True


def write_pid_file(pid_path: Path) -> None:
    """Atomically write current PID to file via tempfile + rename."""
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pid_path.parent)
    os.write(fd, f"{os.getpid()}\n".encode())
    os.close(fd)
    Path(tmp).replace(pid_path)


def spawn_component(component: Component) -> int:
    """Launch component as a detached background process. Returns PID.

    Raises:
        FileNotFoundError: If mb-netwatch is not found in PATH.

    """
    exe = shutil.which("mb-netwatch")
    if not exe:
        msg = "'mb-netwatch' not found in PATH. Install with: uv tool install ."
        raise FileNotFoundError(msg)

    proc = subprocess.Popen(  # noqa: S603 — exe resolved via shutil.which, subcommand is a fixed literal  # nosec B603
        [exe, component.value],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid
