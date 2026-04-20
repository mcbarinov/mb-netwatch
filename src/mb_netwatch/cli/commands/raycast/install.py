"""Install Raycast script commands into a user-chosen directory."""

import re
import shlex
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
from mm_clikit import CliError

from mb_netwatch.cli.context import use_context
from mb_netwatch.cli.output import RaycastInstallResult

_PATH_LINE = re.compile(r"^export PATH=.*$\n?", re.MULTILINE)
_CMD_LINE = re.compile(r"^mb-netwatch\b(.*)$", re.MULTILINE)


def install(
    ctx: typer.Context,
    target_dir: Annotated[
        Path | None,
        typer.Argument(help="Target directory. Defaults to <data_dir>/raycast."),
    ] = None,
    *,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Install Raycast script commands into a directory."""
    app = use_context(ctx)
    config = app.core.config

    dest = target_dir.resolve() if target_dir is not None else config.data_dir / "raycast"

    cmd_prefix = " ".join(shlex.quote(p) for p in config.base_argv())

    refreshed = dest.exists() and any(dest.glob("*.sh"))

    templates = resources.files("mb_netwatch.raycast")
    sources = sorted((p for p in templates.iterdir() if p.name.endswith(".sh")), key=lambda p: p.name)
    if not sources:
        raise CliError("No Raycast script templates found in package.", "NO_TEMPLATES")

    dest.mkdir(parents=True, exist_ok=True)

    if not force:
        conflicts = [src.name for src in sources if (dest / src.name).exists()]
        if conflicts:
            raise CliError(f"Existing files: {', '.join(conflicts)}. Use --force to overwrite.", "EXISTS")

    installed: list[str] = []
    for src in sources:
        name = src.name
        out_path = dest / name
        text = src.read_text(encoding="utf-8")
        text = _PATH_LINE.sub("", text)
        text = _CMD_LINE.sub(lambda m: f"{cmd_prefix}{m.group(1)}", text)

        out_path.write_text(text, encoding="utf-8")
        out_path.chmod(0o755)
        installed.append(name)

    app.out.print_raycast_installed(
        RaycastInstallResult(
            target_dir=str(dest),
            installed=installed,
            refreshed=refreshed,
            command=cmd_prefix,
        )
    )
