"""Agent CLI group: list, show.

Agents are preset definitions. To run an agent, use
``team start --preset <agent-name>``.
"""

from __future__ import annotations

__all__ = ["agent"]

import click


@click.group()
def agent() -> None:
    """Inspect agent preset definitions."""


@agent.command("list")
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def list_cmd(emit_json: bool) -> None:
    """List available agent presets."""
    import json as json_mod

    from vaultspec_a2a.team.team_config import discover_agent_preset_ids

    preset_ids = sorted(discover_agent_preset_ids())
    if not preset_ids:
        click.echo("No agent presets found.")
        return

    if emit_json:
        click.echo(json_mod.dumps(preset_ids, indent=2))
        return

    for name in preset_ids:
        click.echo(f"  {name}")

    click.echo('\n  Use: vaultspec team start --preset <name> --message "..."')


@agent.command()
@click.argument("name")
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def show(name: str, emit_json: bool) -> None:
    """Show the configuration of an agent preset."""
    import json as json_mod

    from vaultspec_a2a.team.team_config import (
        AgentConfigNotFoundError,
        load_agent_config,
    )

    try:
        config = load_agent_config(name)
    except AgentConfigNotFoundError:
        click.echo(f"Preset not found: {name}", err=True)
        click.echo("  Available: vaultspec agent list", err=True)
        raise SystemExit(1) from None

    if emit_json:
        data = config.model_dump(mode="json")
        click.echo(json_mod.dumps(data, indent=2, default=str))
        return

    click.echo(f"# {name}\n")
    click.echo(f"  id:           {config.id}")
    click.echo(f"  display_name: {config.display_name}")
    click.echo(f"  role:         {config.role}")
    click.echo(f"  description:  {config.description}")
    if config.model.provider:
        click.echo(f"  provider:     {config.model.provider}")
    if config.model.capability:
        click.echo(f"  capability:   {config.model.capability}")
