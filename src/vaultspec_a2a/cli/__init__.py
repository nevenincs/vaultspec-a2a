"""Click CLI for vaultspec-a2a."""

__all__ = ["cli", "main"]

import click

from ._util import _show_config_callback


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--show-config",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_config_callback,
    help="Print resolved settings and exit.",
)
def cli() -> None:
    """Vaultspec A2A -- agent orchestration server and tooling."""


from ._agent import agent  # noqa: E402
from ._database import database  # noqa: E402
from ._run import run  # noqa: E402
from ._service import service  # noqa: E402
from ._team import team  # noqa: E402
from ._test import test  # noqa: E402

cli.add_command(agent)
cli.add_command(database)
cli.add_command(run)
cli.add_command(service)
cli.add_command(team)
cli.add_command(test)

main = cli
