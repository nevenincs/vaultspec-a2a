"""Click-based CLI for vaultspec-a2a."""

from __future__ import annotations

import subprocess
import sys

from pathlib import Path

import click


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"

_SENSITIVE_SUBSTRINGS = ("key", "token", "secret", "password")
_MASK_MIN_LEN = 4


def _mask(name: str, value: object) -> str:
    """Mask sensitive settings values, showing only last 4 chars."""
    text = str(value)
    if (
        any(s in name.lower() for s in _SENSITIVE_SUBSTRINGS)
        and len(text) > _MASK_MIN_LEN
    ):
        return f"****{text[-4:]}"
    return text


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Vaultspec A2A -- agent orchestration server and tooling."""


@cli.command()
@click.option(
    "--host",
    default=None,
    help="Bind host (default: from settings).",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Bind port (default: from settings).",
)
@click.option(
    "--log-level",
    default=None,
    help="Uvicorn log level (default: from settings).",
)
def serve(
    host: str | None,
    port: int | None,
    log_level: str | None,
) -> None:
    """Launch the API server."""
    import uvicorn

    from .core.config import settings

    uvicorn.run(
        "vaultspec_a2a.api.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        log_level=(log_level or settings.log_level.value).lower(),
    )


@cli.command()
@click.option(
    "--port",
    default=None,
    type=int,
    help="Worker port (default: from settings).",
)
@click.option(
    "--log-level",
    default=None,
    help="Uvicorn log level (default: from settings).",
)
def worker(port: int | None, log_level: str | None) -> None:
    """Launch the worker process."""
    import uvicorn

    from .core.config import settings

    uvicorn.run(
        "vaultspec_a2a.worker.app:create_worker_app",
        factory=True,
        host="127.0.0.1",
        port=port or settings.worker_port,
        log_level=(log_level or settings.log_level.value).lower(),
    )


@cli.command("test")
@click.argument("target", default="all")
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def test_cmd(target: str, extra: tuple[str, ...]) -> None:
    """Run pytest. TARGET: all | marker name | file path.

    Extra arguments after -- are forwarded to pytest.
    """
    cmd: list[str] = ["uv", "run", "pytest"]

    if target == "all":
        pass
    elif "/" in target or "\\" in target or target.endswith(".py"):
        cmd.append(target)
    else:
        cmd += [
            "--override-ini=addopts=--durations=10 --showlocals -ra --capture=sys",
            "-m",
            target,
        ]

    cmd.extend(extra)
    sys.exit(subprocess.run(cmd, check=False).returncode)


# -- migrate group -----------------------------------------------------------


@cli.group()
def migrate() -> None:
    """Database migration commands (Alembic)."""


def _alembic_cfg() -> tuple:
    """Build an Alembic Config with the project database URL."""
    from alembic.config import Config as AlembicConfig

    from .core.config import settings

    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg, settings


@migrate.command()
@click.option(
    "--target",
    default="head",
    help="Migration target (default: head).",
)
def upgrade(target: str) -> None:
    """Run pending migrations (alembic upgrade)."""
    from alembic import command

    cfg, _ = _alembic_cfg()
    command.upgrade(cfg, target)
    print(f"Migrated to {target}.")


@migrate.command()
@click.option(
    "--target",
    default="head",
    help="Stamp target (default: head).",
)
def stamp(target: str) -> None:
    """Stamp the database at a revision without running migrations."""
    from alembic import command

    cfg, _ = _alembic_cfg()
    command.stamp(cfg, target)
    print(f"Stamped at {target}.")


# -- config command -----------------------------------------------------------


@cli.command()
def config() -> None:
    """Print resolved settings (sensitive values masked)."""
    from .core.config import settings

    for name in settings.model_fields:
        value = getattr(settings, name)
        print(f"{name}={_mask(name, value)}")


# -- preps command ------------------------------------------------------------


@cli.command()
@click.argument("scenario", required=False, default=None)
def preps(scenario: str | None) -> None:
    """Run a preps scenario (or list available scenarios)."""
    if scenario is None:
        cmd = [sys.executable, "-m", "vaultspec_a2a.tests.preps"]
    else:
        cmd = [
            sys.executable,
            "-m",
            f"vaultspec_a2a.tests.preps.{scenario}",
        ]
    sys.exit(subprocess.run(cmd, check=False).returncode)


# -- eval group ---------------------------------------------------------------


@cli.group("eval")
def eval_group() -> None:
    """Evaluation suite commands."""


@eval_group.command()
def smoke() -> None:
    """Run the smoke evaluation suite."""
    cmd = [
        sys.executable,
        "-m",
        "vaultspec_a2a.tests.evals.suites.smoke",
    ]
    sys.exit(subprocess.run(cmd, check=False).returncode)


@eval_group.command()
def nightly() -> None:
    """Run the nightly evaluation suite."""
    cmd = [
        sys.executable,
        "-m",
        "vaultspec_a2a.tests.evals.suites.nightly",
    ]
    sys.exit(subprocess.run(cmd, check=False).returncode)


# Backward-compat alias for any code that calls main().
main = cli
