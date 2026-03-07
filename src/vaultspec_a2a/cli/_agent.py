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
    presets_dir = Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"
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
@click.option(
    "--agent", "agent_name", default="vaultspec-solo-coder", help="Agent preset name."
)
@click.option("--message", required=True, help="Message to send.")
def ask(agent_name: str, message: str) -> None:
    """Send a question to an agent preset (solo-coder by default)."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.post(
            "/threads",
            json={
                "team_preset": agent_name,
                "initial_message": message,
                "nickname": agent_name,
            },
        )
        _handle_response(resp)
        data = resp.json()
        click.echo(f"Thread {data['thread_id']} created (agent: {agent_name}).")
