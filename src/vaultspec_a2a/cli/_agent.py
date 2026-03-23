"""Agent CLI group: list, show.

Agents are preset definitions. To run an agent, use
``team start --preset <agent-name>``.
"""

from __future__ import annotations

__all__ = ["agent"]

from pathlib import Path

import click


@click.group()
def agent() -> None:
    """Inspect agent preset definitions."""


@agent.command("list")
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def list_cmd(emit_json: bool) -> None:
    """List available agent presets."""
    import json as json_mod

    presets_dir = Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"
    if not presets_dir.exists():
        click.echo("No agent presets directory found.", err=True)
        return

    tomls = sorted(presets_dir.glob("*.toml"))
    if not tomls:
        click.echo("No agent presets found.")
        return

    if emit_json:
        click.echo(json_mod.dumps([t.stem for t in tomls], indent=2))
        return

    for t in tomls:
        click.echo(f"  {t.stem}")

    click.echo('\n  Use: vaultspec team start --preset <name> --message "..."')


@agent.command()
@click.argument("name")
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def show(name: str, emit_json: bool) -> None:
    """Show the configuration of an agent preset."""
    import json as json_mod

    presets_dir = Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"
    preset_path = presets_dir / f"{name}.toml"

    if not preset_path.exists():
        # Also check team presets
        team_presets_dir = presets_dir.parent / "teams"
        preset_path = team_presets_dir / f"{name}.toml"
        if not preset_path.exists():
            click.echo(f"Preset not found: {name}", err=True)
            click.echo("  Available: vaultspec agent list", err=True)
            raise SystemExit(1)

    content = preset_path.read_text(encoding="utf-8")

    if emit_json:
        try:
            import tomllib

            data = tomllib.loads(content)
            click.echo(json_mod.dumps(data, indent=2, default=str))
        except Exception:
            click.echo(content)
        return

    click.echo(f"# {preset_path.name}\n")
    click.echo(content)
