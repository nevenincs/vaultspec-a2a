"""run group: mock, probe."""

from __future__ import annotations

__all__ = ["run"]

import subprocess
import sys

import click


@click.group()
def run() -> None:
    """Run scenarios and probes."""


@run.command()
@click.argument("scenario", required=False, default=None)
def mock(scenario: str | None) -> None:
    """Run a mock scenario (or list available scenarios)."""
    import re

    if scenario is None:
        cmd = [sys.executable, "-m", "vaultspec_a2a.tests.preps"]
    else:
        if not re.fullmatch(r"[a-zA-Z0-9_]+", scenario):
            click.echo(f"Invalid scenario name: {scenario!r}", err=True)
            raise SystemExit(1)
        cmd = [
            sys.executable,
            "-m",
            f"vaultspec_a2a.tests.preps.{scenario}",
        ]
    sys.exit(subprocess.run(cmd, check=False).returncode)


@run.command()
@click.argument(
    "provider",
    required=False,
    default=None,
    type=click.Choice(
        ["claude", "gemini", "openai", "zhipu"], case_sensitive=False,
    ),
)
def probe(provider: str | None) -> None:
    """Run a provider connectivity probe. Bare = list available."""
    if provider is None:
        click.echo("Available probes: claude, gemini, openai, zhipu")
        return
    cmd = [
        sys.executable,
        "-m",
        f"vaultspec_a2a.providers.probes.{provider}",
    ]
    sys.exit(subprocess.run(cmd, check=False).returncode)
