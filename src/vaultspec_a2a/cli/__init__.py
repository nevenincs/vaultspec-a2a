"""Click CLI for vaultspec-a2a.

Production-only CLI surface. Operates teams and agents against a running
backend. All dev tooling (service lifecycle, testing, database management)
lives in the Justfile under the ``dev`` namespace.

See ADR-038 for the CLI/Justfile separation rationale.
"""

__all__ = ["cli", "main"]

import logging
from importlib.metadata import version as _pkg_version

import click

from ._util import _show_config_callback


def _version_callback(
    ctx: click.Context,
    _param: click.Parameter,
    value: bool,
) -> None:
    if not value or ctx.resilient_parsing:
        return
    try:
        ver = _pkg_version("vaultspec-a2a")
    except Exception:
        ver = "unknown"
    click.echo(ver)
    ctx.exit()


def _configure_logging(verbose: bool, debug: bool) -> None:
    level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", force=True)
    # Suppress noisy HTTP client logs unless verbose/debug
    if not verbose and not debug:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--show-config",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_config_callback,
    help="Print resolved settings and exit.",
)
@click.option(
    "--version",
    "-V",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_version_callback,
    help="Print version and exit.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable INFO logging."
)
@click.option(
    "--debug", "-d", is_flag=True, default=False, help="Enable DEBUG logging."
)
def cli(verbose: bool, debug: bool) -> None:
    """Vaultspec A2A -- agent orchestration CLI.

    Operates teams and agents against a running gateway+worker backend.
    Start the backend with: just dev service start
    """
    _configure_logging(verbose, debug)


def _register_commands() -> None:
    from ._agent import agent
    from ._team import team

    cli.add_command(agent)
    cli.add_command(team)


_register_commands()

main = cli
