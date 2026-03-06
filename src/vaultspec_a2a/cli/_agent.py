"""agent group: list, ask."""

from __future__ import annotations

__all__ = ["agent"]

from pathlib import Path

import click


@click.group()
def agent() -> None:
    """Single-agent operations."""


@agent.command("list")
def list_cmd() -> None:
    """List available agent presets."""
    presets_dir = (
        Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"
    )
    if not presets_dir.exists():
        click.echo("No agent presets directory found.", err=True)
        return

    tomls = sorted(presets_dir.glob("*.toml"))
    if not tomls:
        click.echo("No agent presets found.")
        return
    for t in tomls:
        click.echo(f"  {t.stem}")


@agent.command()
@click.option("--message", required=True, help="Message to send.")
def ask(message: str) -> None:
    """Send a question to the solo-coder agent preset."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.post(
            "/threads",
            json={
                "team_preset": "vaultspec-solo-coder",
                "initial_message": message,
            },
        )
        _handle_response(resp)
        data = resp.json()
        click.echo(f"Thread {data['thread_id']} created.")
