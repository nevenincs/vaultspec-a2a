"""team group: start, status, resume, stop, delete, archive, list."""

from __future__ import annotations

__all__ = ["team"]

import click


@click.group()
def team() -> None:
    """Manage agent teams (threads)."""


@team.command()
@click.option("--preset", required=True, help="Team preset name.")
@click.option("--message", required=True, help="Initial task instruction.")
def start(preset: str, message: str) -> None:
    """Start a new team from a preset."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        body: dict[str, str] = {
            "team_preset": preset,
            "initial_message": message,
        }
        resp = client.post("/threads", json=body)
        _handle_response(resp)
        data = resp.json()
        nick = data.get("nickname") or data["thread_id"][:8]
        click.echo(f"Thread {data['thread_id']} ({nick}) started.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID or nickname.")
def status(thread_id: str) -> None:
    """Get team status for a thread."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.get(f"/threads/{thread_id}/state")
        _handle_response(resp)
        data = resp.json()
        click.echo(f"Status: {data.get('status', 'unknown')}")
        agents = data.get("agents", [])
        if agents:
            click.echo("Agents:")
            for a in agents:
                click.echo(f"  {a['agent_id']:20s}  {a.get('state', 'unknown')}")
        perms = data.get("pending_permissions", [])
        if perms:
            click.echo(f"Pending permissions: {len(perms)}")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
@click.option("--message", default=None, help="New input message (omit for contentless resume).")
def resume(thread_id: str, message: str | None) -> None:
    """Send a message into a thread to resume work."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.post(
            f"/threads/{thread_id}/messages",
            json={"content": message or ""},
        )
        _handle_response(resp)
        click.echo(f"Thread {thread_id} resumed.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def stop(thread_id: str) -> None:
    """Cancel a running team."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.post(f"/threads/{thread_id}/cancel")
        _handle_response(resp)
        data = resp.json()
        if data.get("cancelled"):
            click.echo(f"Thread {thread_id} cancelled.")
        else:
            click.echo(f"Thread {thread_id} already in terminal state: {data.get('status')}")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def delete(thread_id: str) -> None:
    """Delete a thread and all its data."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.delete(f"/threads/{thread_id}")
        _handle_response(resp)
        click.echo(f"Thread {thread_id} deleted.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def archive(thread_id: str) -> None:
    """Archive a completed/failed/cancelled thread."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.post(f"/threads/{thread_id}/archive")
        _handle_response(resp)
        click.echo(f"Thread {thread_id} archived.")


@team.command("list")
@click.argument(
    "status_filter",
    required=False,
    default=None,
    type=click.Choice(
        ["submitted", "created", "running", "completed", "failed", "cancelled", "archived"],
        case_sensitive=False,
    ),
)
def list_cmd(status_filter: str | None) -> None:
    """List teams. Optional filter: running | completed | archived | ..."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        params: dict[str, str] = {}
        if status_filter:
            params["status"] = status_filter
        resp = client.get("/threads", params=params)
        _handle_response(resp)
        data = resp.json()
        threads = data.get("threads", [])
        if not threads:
            click.echo("No threads found.")
            return
        for t in threads:
            nick = t.get("nickname") or t["thread_id"][:8]
            click.echo(f"  {t['thread_id']}  {t['status']:12s}  {nick}")
