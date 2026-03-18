"""Team CLI group: start, status, resume, stop, delete, archive, etc."""

from __future__ import annotations


__all__ = ["team"]

import click


@click.group()
def team() -> None:
    """Manage agent teams (threads)."""


@team.command()
@click.option("--preset", required=True, help="Team preset name.")
@click.option("--message", required=True, help="Initial task instruction.")
@click.option("--name", default=None, help="Optional thread nickname.")
@click.option("--title", default=None, help="Thread title (max 200 chars).")
@click.option(
    "--autonomous/--supervised", default=None, help="Override auto-approve mode."
)
def start(
    preset: str,
    message: str,
    name: str | None,
    title: str | None,
    autonomous: bool | None,
) -> None:
    """Start a new team from a preset."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        body: dict[str, object] = {
            "team_preset": preset,
            "initial_message": message,
        }
        if name:
            body["nickname"] = name
        if title:
            body["title"] = title
        if autonomous is not None:
            body["autonomous"] = autonomous
        resp = client.post("/threads", json=body)
        _handle_response(resp)
        data = resp.json()
        nick = data.get("nickname") or data["thread_id"][:8]
        click.echo(f"Thread {data['thread_id']} ({nick}) started.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID or nickname.")
def status(thread_id: str) -> None:
    """Get team status for a thread."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

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
@click.option(
    "--message", default=None, help="New input message (omit for contentless resume)."
)
def resume(thread_id: str, message: str | None) -> None:
    """Send a message into a thread to resume work."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.post(
            f"/threads/{thread_id}/messages",
            json={"content": message or "Continue."},
        )
        _handle_response(resp)
        click.echo(f"Thread {thread_id} resumed.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def stop(thread_id: str) -> None:
    """Cancel a running team."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.post(f"/threads/{thread_id}/cancel")
        _handle_response(resp)
        data = resp.json()
        if data.get("cancelled"):
            click.echo(f"Thread {thread_id} cancelled.")
        else:
            click.echo(
                f"Thread {thread_id} already in terminal state: {data.get('status')}"
            )


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def delete(thread_id: str) -> None:
    """Delete a thread and all its data."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.delete(f"/threads/{thread_id}")
        _handle_response(resp)
        click.echo(f"Thread {thread_id} deleted.")


@team.command()
@click.option("--id", "thread_id", required=True, help="Thread ID.")
def archive(thread_id: str) -> None:
    """Archive a completed/failed/cancelled thread."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

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
        [
            "submitted",
            "running",
            "input_required",
            "cancelling",
            "cancelled",
            "completed",
            "failed",
            "archived",
            "repair_needed",
            "reconciling",
        ],
        case_sensitive=False,
    ),
)
def list_cmd(status_filter: str | None) -> None:
    """List teams. Optional filter: running | completed | archived | ..."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

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


@team.command()
def presets() -> None:
    """List available team presets."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.get("/teams")
        _handle_response(resp)
        data = resp.json()
        items = data.get("presets", [])
        if not items:
            click.echo("No team presets found.")
            return
        for p in items:
            click.echo(
                f"  {p['id']:20s}  "
                f"{p.get('display_name', '')}  "
                f"({p.get('worker_count', '?')} agents)"
            )


@team.command()
@click.option("--request-id", required=True, help="Permission request ID.")
@click.option("--option", "option_id", required=True, help="Option ID to select.")
def respond(request_id: str, option_id: str) -> None:
    """Respond to a pending permission request."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.post(
            f"/permissions/{request_id}/respond",
            json={"option_id": option_id},
        )
        _handle_response(resp)
        data = resp.json()
        status = "accepted" if data.get("accepted") else "rejected"
        click.echo(f"Permission {request_id}: {status}.")


@team.command()
def overview() -> None:
    """Show team-wide status: agents, active threads, pending permissions."""
    from ._util import _api_client, _handle_response  # noqa: PLC0415

    with _api_client() as client:
        resp = client.get("/team/status")
        _handle_response(resp)
        data = resp.json()

        agents = data.get("agents", [])
        if agents:
            click.echo("Agents:")
            for a in agents:
                click.echo(
                    f"  {a['agent_id']:20s}  "
                    f"{a.get('state', 'unknown'):12s}  "
                    f"{a.get('display_name', '')}"
                )
        else:
            click.echo("No agents registered.")

        threads = data.get("active_threads", [])
        click.echo(f"Active threads: {len(threads)}")

        perms = data.get("pending_permissions", [])
        if perms:
            click.echo(f"Pending permissions: {len(perms)}")
            for p in perms:
                click.echo(f"  {p['request_id']}  {p.get('description', '')}")
