<!-- version: 2026-04-08 | source: https://github.com/mcbarinov/mm-clikit -->

# CLI Application Architecture Guide

Architecture reference for building CLI apps with mm-clikit.

## Project Layout

```
src/mb_<name>/
├── __init__.py
├── config.py              # Frozen Pydantic Config
│
├── core/
│   ├── __init__.py
│   ├── core.py            # Composition root (db + config + service)
│   ├── service.py         # Business logic (validation, orchestration)
│   └── db.py              # SQLite layer (optional)
│
├── cli/
│   ├── __init__.py
│   ├── main.py            # TyperPlus app, callback, command registration
│   ├── context.py         # Typed use_context()
│   ├── output.py          # Output(DualModeOutput)
│   └── commands/          # One file per command
│       ├── __init__.py
│       ├── add.py
│       └── list.py
│
├── tui/                   # TUI adapter (optional, uses Core)
│   ├── __init__.py
│   ├── app.py             # Textual App subclass
│   └── screens/           # App-specific screens
│       └── ...
├── daemon.py              # Background daemon (optional, uses Core)
└── tray.py                # Menu bar / system tray UI (optional, uses Core)
```

Core business logic lives in the `core/` package.
CLI adapter code lives in the `cli/` subfolder.
Config is at the package root — shared by both core and CLI.
Other adapters (`daemon.py`, `tray.py`) sit at the package root alongside `cli/` — they use `Core` directly.
Core has zero imports from `cli/` or other adapters — the dependency is strictly one-way.

## Data Classes Convention

Use Pydantic `BaseModel` for all data classes — config, row models, value objects, result types.
Since Pydantic is already a dependency (Config, SqliteRow), standardizing on it avoids mixing
two data-class systems and gives validation + `.model_dump()` for free.
Use `ConfigDict(frozen=True)` where immutability matters (Config, row models), but mutable models are fine when needed.

## Layer Diagram

```
CLI (cli/commands/)  →  Core  →  Service  →  Db
                         ↕         ↕
                      Output    Config
                         ↓
                         Db  (direct access for simple reads)
```

Commands use `core.service` for operations with business logic (validation, orchestration, multi-step).
Commands use `core.db` directly for simple reads — no need for pass-through service wrappers.

## Dependency Flow

```
cli/main.py  →  cli/commands/*  →  cli/context.py  →  core/  →  core/service.py
                     ↓                   ↓                ↓
                cli/output.py        config.py        core/db.py (direct reads)
```

---

## File-by-File Reference

### Errors

Use `CliError` from mm-clikit directly — no wrapper needed:

```python
from mm_clikit import CliError

raise CliError("Stash is locked.", "LOCKED")
raise CliError("Name cannot be empty.", "EMPTY_NAME")
```

Use UPPER_SNAKE_CASE for error codes (e.g. `NOT_FOUND`, `ALREADY_EXISTS`, `EMPTY_NAME`).

**To exit with a formatted error message, raise `CliError`.** TyperPlus catches it and outputs
the error in the correct format (JSON envelope with `--json`, plain text otherwise) and exits
with code 1. Never call `sys.exit()` or `typer.Exit()` for error reporting — always raise `CliError`.

If you genuinely need a project-specific error class (e.g. to catch only your errors in middleware),
subclass `CliError`. But default to using `CliError` directly — don't create a subclass just for the sake of it.

### config.py

```python
"""Centralized application configuration."""

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

DEFAULT_DATA_DIR = Path.home() / ".local" / "mb-<name>"


class Config(BaseModel):
    """Application-wide configuration."""

    model_config = ConfigDict(frozen=True)  # Immutable after creation

    data_dir: Path = Field(description="Base directory for all application data")

    @computed_field(description="SQLite database file")
    @property
    def db_path(self) -> Path:
        """SQLite database file."""
        return self.data_dir / "<name>.db"

    @computed_field(description="Rotating log file")
    @property
    def log_path(self) -> Path:
        """Rotating log file."""
        return self.data_dir / "<name>.log"

    @computed_field(description="Optional TOML configuration file")
    @property
    def config_path(self) -> Path:
        """Optional TOML configuration file."""
        return self.data_dir / "config.toml"

    def cli_base_args(self) -> list[str]:
        """Build CLI base args, including --data-dir only when non-default.

        Useful for spawning subprocesses (daemons, workers) that need
        to inherit the data directory setting.
        """
        args: list[str] = ["mb-<name>"]
        if self.data_dir != DEFAULT_DATA_DIR:
            args.extend(["--data-dir", str(self.data_dir)])
        return args

    @staticmethod
    def build(data_dir: Path | None = None) -> Config:
        """Build a Config from CLI arg / env var / default, with optional TOML overlay."""
        if data_dir is not None:
            resolved = data_dir.resolve()
        elif env := os.environ.get("MB_<NAME>_DATA_DIR"):
            resolved = Path(env).resolve()
        else:
            resolved = DEFAULT_DATA_DIR

        kwargs: dict[str, Any] = {"data_dir": resolved}
        config_path = resolved / "config.toml"
        if config_path.is_file():
            with config_path.open("rb") as f:
                toml_data = tomllib.load(f)
            # Read app-specific settings from TOML here
            # e.g.: kwargs["timeout"] = toml_data.get("timeout", 30)

        resolved.mkdir(parents=True, exist_ok=True)
        return Config(**kwargs)
```

Data directory resolution order:
1. `--data-dir` CLI flag (highest priority)
2. `MB_<NAME>_DATA_DIR` environment variable
3. `~/.local/mb-<name>/` default

The `cli_base_args()` method is optional — only needed if the app spawns background processes
(daemons, workers) that must inherit the data directory.

---

## Core Package

All business logic lives in `core/`.

### core/\_\_init\_\_.py

```python
"""Core business logic."""
```

Empty — import from specific modules directly (e.g. `from mb_<name>.core.core import Core`).

### core/core.py

```python
"""Composition root — holds config, database, and service layer."""

from mb_<name>.config import Config
from mb_<name>.core.db import Db
from mb_<name>.core.service import Service


class Core:
    """Application composition root.

    Creates and owns all shared resources (database, services).
    Passed to CLI commands via ``CoreContext``.
    """

    def __init__(self, config: Config) -> None:
        self.config = config  # Application configuration
        self.db = Db(config.db_path)  # SQLite database — used directly for simple reads
        self.service = Service(self.db, config)  # Business logic (validation, orchestration)

    def close(self) -> None:
        """Release resources."""
        self.db.close()
```

`Core` owns the lifecycle of all resources. The CLI callback creates it and registers
cleanup via `ctx.call_on_close(core.close)`.

Commands use `core.db` directly for simple reads (listing, fetching by ID).
Commands use `core.service` for operations with real business logic — validation,
multi-step orchestration, state checks. Don't create service methods that just
forward to a single db method with no added logic.

### core/service.py

The service layer. Validation, orchestration, and business rules live here.
Only create service methods when there is logic beyond a simple db call.

```python
"""Core business logic — validation and orchestration."""

from mm_clikit import CliError

from mb_<name>.config import Config
from mb_<name>.core.db import Db


class Service:
    """Business logic that goes beyond simple data access."""

    def __init__(self, db: Db, config: Config) -> None:
        self._db = db  # Database access layer
        self._config = config  # Application configuration

    def add_item(self, name: str) -> int:
        """Create an item. Returns the new ID."""
        if not name.strip():
            raise CliError("Name cannot be empty.", "EMPTY_NAME")
        return self._db.insert_item(name.strip())
```

Raise `CliError` for any validation or business rule violation.
Commands don't catch these — TyperPlus handles formatting and exit automatically.

**When to use Service vs direct Db access:**
- **Service:** validation, multi-step operations, state transitions, business rules, error checking
- **Direct Db:** simple reads (list all, fetch by ID), straightforward inserts with no validation

### core/db.py (optional)

For apps that need local persistence. Subclass `SqliteDb` from mm-clikit — it handles
connection setup (WAL mode, busy timeout, foreign keys) and `PRAGMA user_version` migrations.

Use `SqliteRow` as a base for typed row models — each row type implements `from_row()`
to convert `sqlite3.Row` into a validated Pydantic model.

```python
"""SQLite data access layer."""

import sqlite3
from pathlib import Path
from typing import Self

from mm_clikit import SqliteDb, SqliteRow


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Create initial schema."""
    conn.execute("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT (unixepoch())
        ) STRICT
    """)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Add tags column."""
    conn.execute("ALTER TABLE items ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")


class ItemRow(SqliteRow):
    """A single item from the database."""

    id: int  # Primary key
    name: str  # Item name

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Create from a database row."""
        return cls(id=row["id"], name=row["name"])


class Db(SqliteDb):
    """SQLite database access."""

    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path, migrations=(_migrate_v1, _migrate_v2))

    def insert_item(self, name: str) -> int:
        """Insert an item and return its ID."""
        cur = self.conn.execute("INSERT INTO items (name) VALUES (?)", (name,))
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def fetch_all_items(self) -> list[ItemRow]:
        """Fetch all items."""
        rows = self.conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()
        return [ItemRow.from_row(row) for row in rows]
```

Migration rules:
- Do **not** call `commit()` — `SqliteDb` commits each migration together with its `user_version` bump atomically.
- Use `conn.execute()` for each statement, **not** `conn.executescript()` (which does implicit commits and breaks atomicity).
- Add new migrations as `_migrate_v2`, `_migrate_v3`, etc. and append to the `migrations` tuple.

---

## CLI Layer

### cli/\_\_init\_\_.py

```python
"""CLI adapter."""
```

Empty — the entry point in pyproject.toml points directly to `mb_<name>.cli.main:app`.

### cli/context.py

```python
"""Typed CLI context."""

import typer
from mm_clikit import CoreContext, use_context as _use_context

from mb_<name>.cli.output import Output
from mb_<name>.core.core import Core


def use_context(ctx: typer.Context) -> CoreContext[Core, Output]:
    """Extract typed core context from Typer context."""
    return _use_context(ctx, CoreContext[Core, Output])
```

Pre-typed wrapper over `mm_clikit.use_context`. Commands import only this function — one import
instead of two. Separate file to avoid circular imports (main.py imports commands, commands import use_context).

### cli/output.py

```python
"""Structured output for CLI and JSON modes."""

from mm_clikit import DualModeOutput
from rich.table import Table

from mb_<name>.core.db import ItemRow


class Output(DualModeOutput):
    """Handles all CLI output in JSON or human-readable format."""

    def print_item_added(self, item_id: int, name: str) -> None:
        """Print item creation confirmation."""
        self.output(
            json_data={"id": item_id, "name": name},
            display_data=f"Item #{item_id} created: {name}",
        )

    def print_items(self, items: list[ItemRow]) -> None:
        """Print item list."""
        if not items:
            self.output(json_data={"items": []}, display_data="No items.")
            return
        table = Table("ID", "Name")
        for item in items:
            table.add_row(str(item.id), item.name)
        self.output(json_data={"items": [item.model_dump() for item in items]}, display_data=table)
```

Every user-visible output goes through a dedicated `Output` method. Each method provides:
- `json_data` — dict for `--json` mode (envelope: `{"ok": true, "data": {...}}`)
- `display_data` — string or Rich renderable for normal mode

### cli/main.py

```python
"""CLI app definition and initialization."""

from pathlib import Path
from typing import Annotated

import typer
from mm_clikit import CoreContext, TyperPlus, setup_logging

from mb_<name>.cli.commands.add import add
from mb_<name>.cli.commands.list import list_
from mb_<name>.cli.output import Output
from mb_<name>.config import Config
from mb_<name>.core.core import Core

app = TyperPlus(package_name="mb-<name>")


@app.callback()
def main(
    ctx: typer.Context,
    *,
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", help="Data directory. Env: MB_<NAME>_DATA_DIR."),
    ] = None,
) -> None:
    """Short app description."""
    config = Config.build(data_dir)
    setup_logging("mb_<name>", config.log_path)
    core = Core(config)
    ctx.call_on_close(core.close)
    ctx.obj = CoreContext(core=core, out=Output())


app.command(aliases=["a"])(add)
app.command(name="list", aliases=["l", "ls"])(list_)
```

The callback handles all initialization: config, logging, core, context.
Resources that need cleanup use `ctx.call_on_close()`.

TyperPlus provides automatically:
- `--version` / `-V` flag
- `--json` flag (`DualModeOutput` reads it automatically — never add a manual `--json` parameter)
- `--help` / `--help-all`
- `CliError` catch and formatting

### cli/commands/add.py

```python
"""Add a new item."""

from typing import Annotated

import typer

from mb_<name>.cli.context import use_context


def add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Item name.")],
) -> None:
    """Create a new item."""
    app = use_context(ctx)
    item_id = app.core.service.add_item(name)
    app.out.print_item_added(item_id, name)
```

Uses `core.service` because `add_item` has validation logic (non-empty name check).

### cli/commands/list.py

```python
"""List all items."""

import typer

from mb_<name>.cli.context import use_context


def list_(ctx: typer.Context) -> None:
    """Show all items."""
    app = use_context(ctx)
    items = app.core.db.fetch_all_items()
    app.out.print_items(items)
```

Uses `core.db` directly — fetching all items is a simple read with no business logic.

---

## Scaling Up

As the project grows, organize core logic into domain sub-packages:

```
src/mb_<name>/
├── config.py
├── core/
│   ├── __init__.py
│   ├── core.py
│   ├── db/                # Multiple DB access classes
│   │   ├── __init__.py
│   │   ├── user_db.py
│   │   └── order_db.py
│   ├── services/          # Multiple service classes
│   │   ├── __init__.py
│   │   ├── user.py
│   │   └── order.py
│   └── probes/            # Domain-specific modules
│       ├── __init__.py
│       └── ...
├── cli/
│   └── ...
```

With multiple services, `Core` exposes them individually:

```python
class Core:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.db = Db(config.db_path)
        self.users = UserService(self.db, config)
        self.orders = OrderService(self.db, config)
```

Commands access them as `app.core.users.create(...)` for business logic,
or `app.core.db.fetch_users()` for simple reads.

The `cli/` structure stays the same. Only the core grows.

## Testability

Core modules can be imported and tested directly — no CLI involved:

```python
from mb_<name>.config import Config
from mb_<name>.core.core import Core

config = Config(data_dir=tmp_path)
core = Core(config)

# Service for operations with business logic
item_id = core.service.add_item("test")

# Direct db for simple reads
assert core.db.fetch_all_items()[0].name == "test"

core.close()
```

The CLI is just one adapter over the core. Future adapters (web API, telegram bot) would sit alongside `cli/` as separate sub-packages, all using the same core.

---

## Rules Summary

1. **Structure:** Core logic in `core/` package. CLI adapter in `cli/` subfolder. Config at package root.
2. **Dependencies:** `cli/` → `core/` → `config.py` (one-way for logic). Core never imports from `cli/`. Config may import shared type aliases (e.g. `Literal` types) from `core/` — these are domain vocabulary, not logic coupling.
3. **Data access:** Commands use `core.service` for business logic (validation, orchestration). Commands use `core.db` directly for simple reads. Don't create service methods that just forward to db.
4. **Core class:** Composition root — creates and owns Db, Service, Config. Single `Core(config)` constructor, `close()` for cleanup.
5. **Errors:** `CliError(message, code)` from mm-clikit. Raise from service. TyperPlus catches automatically.
6. **Output:** All user output via `Output(DualModeOutput)` in `cli/output.py`. One method per operation, both `json_data` and `display_data`.
7. **Config:** Frozen Pydantic. Resolution: `--data-dir` → env var → default. Optional TOML overlay.
8. **Context:** Pre-typed `use_context()` in `cli/context.py`. Returns `CoreContext[Core, Output]`. Commands call `use_context(ctx)` — one import, fully typed.
9. **JSON mode:** Via TyperPlus `--json` flag. `DualModeOutput` reads it automatically. Never add a manual `--json` parameter.
10. **Logging:** `setup_logging(logger_name, log_path)` from mm-clikit, called in the callback.
11. **Entry point:** `mb_<name>.cli.main:app` in pyproject.toml.
12. **Row models:** Subclass `SqliteRow` for typed database rows with `from_row()` conversion.
13. **`__init__.py`:** Keep empty in application packages — just a module docstring. No re-exports.
