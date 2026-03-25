"""Team CLI group for thread lifecycle and team preset operations."""

from __future__ import annotations

__all__ = ["team"]

import click


def _fetch_thread_metadata(client: object, thread_id: str) -> dict[str, str | None]:
    """Fetch nickname, team_preset, created_at from the thread list endpoint.

    ThreadStateSnapshot does not include these identity fields.
    """
    try:
        resp = client.get("/threads")  # type: ignore[union-attr]
        if not resp.is_success:
            return {"nickname": None, "team_preset": None, "created_at": None}
        data = resp.json()
        for t in data.get("threads", []):
            if t.get("thread_id") == thread_id:
                return {
                    "nickname": t.get("nickname"),
                    "team_preset": t.get("team_preset"),
                    "created_at": t.get("created_at"),
                }
    except Exception:
        pass
    return {"nickname": None, "team_preset": None, "created_at": None}


@click.group()
def team() -> None:
    """Manage agent teams and threads."""


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
    from ._util import _api_client, _handle_response

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
        thread_id = data["thread_id"]
        click.echo(f"Thread {thread_id} ({nick}) started.")
        click.echo(f"\n  vaultspec team status {thread_id}")


@team.command("message")
@click.argument("thread_id")
@click.option("--content", required=True, help="Message text to send.")
@click.option(
    "--agent",
    "agent_id",
    default=None,
    help="Target agent (optional -- supervisor routes by default).",
)
def message_cmd(thread_id: str, content: str, agent_id: str | None) -> None:
    """Send a message into a running thread."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        body: dict[str, object] = {"content": content}
        if agent_id:
            body["agent_id"] = agent_id
        resp = client.post(f"/threads/{thread_id}/messages", json=body)
        _handle_response(resp)
        target = f" (directed to {agent_id})" if agent_id else " (routed by supervisor)"
        click.echo(f"Message sent to thread {thread_id}{target}.")
        click.echo(f"\n  vaultspec team status {thread_id}")


@team.command()
@click.argument("thread_id")
@click.option("--request-id", required=True, help="Permission request ID.")
@click.option("--option", "option_id", required=True, help="Option ID to select.")
def respond(thread_id: str, request_id: str, option_id: str) -> None:
    """Respond to a pending permission request."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        # Fetch permission context before responding so we can show what was approved
        perm_description = ""
        try:
            state_resp = client.get(f"/threads/{thread_id}/state")
            if state_resp.is_success:
                state_data = state_resp.json()
                for p in state_data.get("pending_permissions", []):
                    if p.get("request_id") == request_id:
                        perm_description = p.get("description", "")
                        break
        except Exception:
            pass

        resp = client.post(
            f"/permissions/{request_id}/respond",
            json={"option_id": option_id},
        )
        _handle_response(resp)
        data = resp.json()
        action_status = data.get("action_status", "unknown")

        if data.get("accepted"):
            click.echo(f"Permission {request_id}: approved ({action_status}).")
            if perm_description:
                click.echo(f"  {perm_description}")
            if data.get("applied"):
                click.echo(f"  Already applied to thread {thread_id}.")
            else:
                click.echo(f"  Thread {thread_id} resuming.")
        else:
            click.echo(
                f"Permission {request_id}: not accepted ({action_status}).",
                err=True,
            )
            if action_status == "rejected_invalid_state":
                click.echo(
                    (
                        "  The request may have expired or the thread "
                        "state is inconsistent."
                    ),
                    err=True,
                )
            elif action_status == "duplicate":
                click.echo(
                    "  This permission was already responded to.",
                    err=True,
                )
            click.echo(f"\n  vaultspec team status {thread_id}", err=True)


@team.command()
@click.argument("thread_id")
@click.option(
    "--message", default=None, help="New input message (omit for contentless resume)."
)
def resume(thread_id: str, message: str | None) -> None:
    """Resume a thread that is waiting for input."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.post(
            f"/threads/{thread_id}/messages",
            json={"content": message or "Continue."},
        )
        _handle_response(resp)
        click.echo(f"Thread {thread_id} resumed.")


@team.command()
@click.argument("thread_id")
def cancel(thread_id: str) -> None:
    """Cancel a running thread (permanent)."""
    from ._util import _api_client, _handle_response

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
@click.argument("thread_id")
def delete(thread_id: str) -> None:
    """Delete a thread and all its data."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.delete(f"/threads/{thread_id}")
        _handle_response(resp)
        click.echo(f"Thread {thread_id} deleted.")


@team.command()
@click.argument("thread_id")
def archive(thread_id: str) -> None:
    """Archive a completed/failed/cancelled thread."""
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.post(f"/threads/{thread_id}/archive")
        _handle_response(resp)
        click.echo(f"Thread {thread_id} archived.")


@team.command()
@click.argument("thread_id")
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def status(thread_id: str, emit_json: bool) -> None:
    """Show detailed status for a single thread."""
    import json

    from ._renderers import render_status_display
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.get(f"/threads/{thread_id}/state")
        _handle_response(resp)
        data = resp.json()

        if emit_json:
            meta = _fetch_thread_metadata(client, thread_id)
            data["_nickname"] = meta["nickname"]
            data["_team_preset"] = meta["team_preset"]
            data["_created_at"] = meta["created_at"]
            click.echo(json.dumps(data, indent=2))
            return

        meta = _fetch_thread_metadata(client, thread_id)
        render_status_display(thread_id, data, meta)


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
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def list_cmd(status_filter: str | None, emit_json: bool) -> None:
    """List threads with summary dashboard.

    Optional filter: running | completed | archived | ...
    """
    import json

    from ._renderers import render_thread_list
    from ._util import _api_client, _handle_response

    with _api_client() as client:
        params: dict[str, str] = {}
        if status_filter:
            params["status"] = status_filter
        resp = client.get("/threads", params=params)
        _handle_response(resp)
        data = resp.json()

        if emit_json:
            click.echo(json.dumps(data, indent=2))
            return

        threads = data.get("threads", [])

        # Fetch pending permissions for the dashboard summary.
        pending_permissions = None
        try:
            perm_resp = client.get("/team/status")
            if perm_resp.is_success:
                perm_data = perm_resp.json()
                perms = perm_data.get("pending_permissions", [])
                if perms:
                    pending_permissions = perms
        except Exception:
            pass

        render_thread_list(threads, pending_permissions)


@team.command()
@click.argument("thread_id")
@click.option("--json", "emit_json", is_flag=True, help="Output raw JSON events.")
def watch(thread_id: str, emit_json: bool) -> None:
    """Stream live events for a thread via WebSocket."""
    import asyncio

    asyncio.run(_watch_async(thread_id, emit_json=emit_json))


async def _watch_async(thread_id: str, *, emit_json: bool = False) -> None:
    """Connect to the gateway WebSocket and stream events for a thread.

    The multiplexed WS protocol requires:
    1. Connect to ``ws://host:port/ws``
    2. Receive ``ConnectedEvent`` with assigned ``client_id``
    3. Send ``SUBSCRIBE`` command with the target thread ID
    4. Read events, render each one, handle permission prompts inline
    5. On terminal thread events or Ctrl+C, disconnect cleanly
    """
    import json
    import time

    try:
        import websockets
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:
        click.echo(
            "Error: 'websockets' package is required for the watch command.\n"
            "\n"
            "Install it with:\n"
            "  uv sync\n",
            err=True,
        )
        raise SystemExit(1) from None

    import httpx

    from ..control.config import settings
    from ._renderers import handle_permission_prompt, render_event

    base_url = f"http://127.0.0.1:{settings.port}"
    api_url = f"{base_url}/api"
    ws_url = f"ws://127.0.0.1:{settings.port}/ws"

    # Fail-fast: probe health before opening the WebSocket.
    try:
        resp = httpx.get(f"{api_url}/health", timeout=5.0)
        if resp.status_code != 200:
            click.echo(
                f"Error: Gateway health check returned {resp.status_code}.",
                err=True,
            )
            raise SystemExit(1)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        click.echo(
            f"Error: Gateway not running at {api_url}\n"
            "\n"
            "Start the backend first:\n"
            "  just dev service start gateway    (gateway only)\n"
            "  just dev service start            (all services)\n",
            err=True,
        )
        raise SystemExit(1) from None

    # Track elapsed time from connection start for timestamp display.
    t0 = time.monotonic()

    def _elapsed() -> str:
        """Format elapsed seconds as [MM:SS]."""
        seconds = int(time.monotonic() - t0)
        minutes, secs = divmod(seconds, 60)
        return f"[{minutes:02d}:{secs:02d}]"

    # Terminal agent states that signal the thread is done.
    terminal_states = frozenset({"completed", "failed", "cancelled"})

    # --- Main WebSocket loop ---

    disconnected_cleanly = False
    try:
        async with ws_connect(ws_url) as ws:
            # Step 1: receive ConnectedEvent.
            raw = await ws.recv()
            connected_evt = json.loads(raw)
            if connected_evt.get("type") != "connected":
                click.echo(
                    f"Unexpected initial event: {connected_evt.get('type')}",
                    err=True,
                )
                raise SystemExit(1)

            # Step 2: subscribe to the target thread.
            subscribe_cmd = json.dumps(
                {
                    "type": "subscribe",
                    "thread_ids": [thread_id],
                }
            )
            await ws.send(subscribe_cmd)

            click.echo(f"Watching thread {thread_id}...")
            click.echo("(Press Ctrl+C to detach)\n")

            # Step 3: read events.
            async for raw_msg in ws:
                evt = json.loads(raw_msg)
                event_type = evt.get("type", "")

                # Skip events for other threads (multiplexed connection).
                evt_thread = evt.get("thread_id")
                if evt_thread and evt_thread != thread_id:
                    continue

                if emit_json:
                    click.echo(json.dumps(evt, indent=2))
                else:
                    # Handle permission requests interactively.
                    if event_type == "permission_request":
                        await handle_permission_prompt(evt, _elapsed(), api_url)
                    else:
                        rendered = render_event(_elapsed(), evt)
                        if rendered is not None:
                            click.echo(rendered)

                # Thread-level terminal signal
                if event_type == "thread_terminal":
                    thread_status = evt.get("status", "unknown")
                    click.echo(f"\nThread {thread_id} {thread_status}.")
                    disconnected_cleanly = True
                    break

                # Fallback: supervisor agent_status for star topologies.
                if event_type == "agent_status":
                    state = evt.get("state", "")
                    if state in terminal_states:
                        node = evt.get("node_name", "")
                        agent = evt.get("agent_id", "")
                        is_supervisor = (
                            node == "supervisor" or agent == "vaultspec-supervisor"
                        )
                        if is_supervisor:
                            click.echo(
                                f"\nThread {thread_id} reached terminal state: {state}"
                            )
                            disconnected_cleanly = True
                            break

    except KeyboardInterrupt:
        disconnected_cleanly = True
        click.echo("\nDisconnected. Thread continues running.")
    except websockets.exceptions.ConnectionClosed:
        click.echo("\nWebSocket connection closed by server.")
    except Exception as exc:
        click.echo(f"\nWebSocket error: {exc}", err=True)
        raise SystemExit(1) from None

    if not disconnected_cleanly:
        click.echo("\nDisconnected. Thread continues running.")


@team.command()
@click.option("--json", "emit_json", is_flag=True, help="Output as JSON.")
def presets(emit_json: bool) -> None:
    """List available team presets."""
    import json

    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.get("/teams")
        _handle_response(resp)
        data = resp.json()

        if emit_json:
            click.echo(json.dumps(data, indent=2))
            return

        items = data.get("presets", [])
        if not items:
            click.echo("No team presets found.")
            return
        for p in items:
            click.echo(
                f"  {p['id']:30s}  "
                f"{p.get('display_name', '')}  "
                f"({p.get('worker_count', '?')} agents, {p.get('topology', '?')})"
            )
