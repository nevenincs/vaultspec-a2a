"""Team CLI group for thread lifecycle and team preset operations."""

from __future__ import annotations

__all__ = ["team"]

from typing import Any, cast

import click


def _format_elapsed(created_at_str: str | None) -> str:
    """Compute human-readable elapsed time from an ISO datetime string."""
    if not created_at_str:
        return ""
    try:
        from datetime import UTC, datetime

        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - created
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        if total_seconds < 3600:
            return f"{total_seconds // 60}m"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    except Exception:
        return ""


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

    from ._util import _api_client, _handle_response

    with _api_client() as client:
        resp = client.get(f"/threads/{thread_id}/state")
        _handle_response(resp)
        data = resp.json()

        if emit_json:
            click.echo(json.dumps(data, indent=2))
            return

        # Fetch identity fields not on ThreadStateSnapshot
        meta = _fetch_thread_metadata(client, thread_id)

        # Thread header
        nick = meta["nickname"] or thread_id[:8]
        click.echo(f"  Thread:     {thread_id} ({nick})")
        if meta["team_preset"]:
            click.echo(f"  Preset:     {meta['team_preset']}")
        click.echo(f"  Status:     {data.get('status', 'unknown')}")
        elapsed = _format_elapsed(meta["created_at"])
        if elapsed:
            click.echo(f"  Elapsed:    {elapsed}")
        if data.get("pause_cause"):
            click.echo(f"  Paused:     {data['pause_cause']}")

        # Next nodes (what the graph will execute next)
        next_nodes = data.get("next_nodes", [])
        if next_nodes:
            click.echo(f"  Next:       {', '.join(next_nodes)}")

        # Agents
        agents = data.get("agents", [])
        if agents:
            click.echo("  Agents:")
            for a in agents:
                agent_id = a.get("agent_id", "?")
                state = a.get("state", "unknown")
                display = a.get("display_name", "")
                label = f"{agent_id:20s}  {state:16s}"
                if display:
                    label += f"  {display}"
                click.echo(f"    {label}")

        # Plan progress — API field is "plan", entries have "content" and "status"
        plan = data.get("plan", [])
        if plan:
            click.echo("  Plan:")
            for entry in plan:
                entry_status = entry.get("status", "pending")
                if entry_status == "completed":
                    icon = "[x]"
                elif entry_status == "in_progress":
                    icon = "[>]"
                else:
                    icon = "[ ]"
                content = entry.get("content", "")
                click.echo(f"    {icon} {content}")

        # Pending permissions
        perms = data.get("pending_permissions", [])
        if perms:
            click.echo(f"  Pending permissions: {len(perms)}")
            for p in perms:
                description = p.get("description", "")
                click.echo(f"    {p.get('request_id', '?')}  {description}")
                if p.get("tool_call"):
                    click.echo(f"    Tool: {p['tool_call']}")
                opts = p.get("options", [])
                if opts:
                    opt_names = " | ".join(o.get("option_id", "?") for o in opts)
                    click.echo(f"    Options: {opt_names}")
                    click.echo(
                        f"    Respond: vaultspec team respond {thread_id} "
                        f"--request-id {p.get('request_id', '?')} --option <OPTION>"
                    )

        # Pending interrupts count
        interrupt_count = data.get("pending_interrupt_count", 0)
        if interrupt_count and not perms:
            click.echo(f"  Pending interrupts: {interrupt_count}")

        # Tool calls — API field is "title" for tool name
        tool_calls = data.get("tool_calls", [])
        active_tools = [
            t for t in tool_calls if t.get("status") in ("pending", "in_progress")
        ]
        if active_tools:
            click.echo(f"  Active tool calls: {len(active_tools)}")
            for t in active_tools:
                name = t.get("title") or "(unknown)"
                kind = t.get("kind", "")
                kind_str = f" [{kind}]" if kind else ""
                click.echo(f"    {name}{kind_str}: {t.get('status', 'unknown')}")


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

        if not threads:
            click.echo("No threads found.")
            return

        # Summary counts
        counts: dict[str, int] = {}
        for t in threads:
            s = t.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        active = counts.get("running", 0) + counts.get("input_required", 0)
        total = len(threads)
        click.echo(f"  {total} threads ({active} active)\n")

        # Thread table — created_at IS on ThreadSummary
        click.echo(
            f"  {'THREAD_ID':34s}  {'STATUS':16s}  {'ELAPSED':8s}  "
            f"{'PRESET / NICKNAME'}"
        )
        click.echo(f"  {'─' * 34}  {'─' * 16}  {'─' * 8}  {'─' * 30}")
        for t in threads:
            tid = t["thread_id"]
            tst = t.get("status", "unknown")
            elapsed = _format_elapsed(t.get("created_at"))
            nick = t.get("nickname") or t.get("team_preset", "")
            click.echo(f"  {tid:34s}  {tst:16s}  {elapsed:8s}  {nick}")

        # Pending permissions summary from /team/status
        try:
            perm_resp = client.get("/team/status")
            if perm_resp.is_success:
                perm_data = perm_resp.json()
                perms = perm_data.get("pending_permissions", [])
                if perms:
                    click.echo(f"\n  Pending permissions: {len(perms)}")
                    for p in perms:
                        tid = p.get("thread_id", "?")[:8]
                        description = p.get("description", "")
                        click.echo(
                            f"    [{tid}] {p.get('request_id', '?')}  {description}"
                        )
        except Exception:
            pass


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
    import asyncio
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
            "  uv add websockets\n",
            err=True,
        )
        raise SystemExit(1) from None

    import httpx

    from ..core.config import settings

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

    # --- Event rendering helpers ---

    def _render_agent_status(evt: dict[str, object]) -> str | None:
        agent = evt.get("agent_id") or "agent"
        state = evt.get("state", "")
        detail = evt.get("detail", "")
        parts = [f"{_elapsed()} {agent}: {state}"]
        if detail:
            parts[0] += f" -- {detail}"
        return parts[0]

    def _render_message_chunk(evt: dict[str, object]) -> str | None:
        content = evt.get("content", "")
        if not content:
            return None
        agent = evt.get("agent_id") or "agent"
        finish = evt.get("finish_reason")
        if finish:
            return f"{_elapsed()} {agent}: {content} [{finish}]"
        return f"{_elapsed()} {agent}: {content}"

    def _render_thought_chunk(evt: dict[str, object]) -> str | None:
        content = evt.get("content", "")
        if not content:
            return None
        agent = evt.get("agent_id") or "agent"
        return f"{_elapsed()} {agent} (thinking): {content}"

    def _render_tool_call_start(evt: dict[str, object]) -> str | None:
        title = evt.get("title") or "(unknown tool)"
        kind = evt.get("kind", "")
        agent = evt.get("agent_id") or "agent"
        kind_str = f" [{kind}]" if kind else ""
        return f"{_elapsed()} {agent}: tool_call_start {title}{kind_str}"

    def _render_tool_call_update(evt: dict[str, object]) -> str | None:
        title = evt.get("title") or ""
        status = evt.get("status") or ""
        agent = evt.get("agent_id") or "agent"
        label = title or evt.get("tool_call_id", "")
        return f"{_elapsed()} {agent}: tool_call_update {label} ({status})"

    def _render_plan_update(evt: dict[str, object]) -> str | None:
        entries = cast("list[dict[str, Any]]", evt.get("entries", []))
        if not entries:
            return f"{_elapsed()} plan: (empty)"
        lines = [f"{_elapsed()} plan:"]
        for entry in entries:
            entry_status = entry.get("status", "pending")
            if entry_status == "completed":
                icon = "[x]"
            elif entry_status == "in_progress":
                icon = "[>]"
            else:
                icon = "[ ]"
            content = entry.get("content", "")
            lines.append(f"        {icon} {content}")
        return "\n".join(lines)

    def _render_artifact_update(evt: dict[str, object]) -> str | None:
        filename = evt.get("filename", "")
        last_chunk = evt.get("last_chunk", False)
        suffix = " (complete)" if last_chunk else ""
        return f"{_elapsed()} artifact: {filename}{suffix}"

    def _render_error(evt: dict[str, object]) -> str | None:
        code = evt.get("code", "")
        message = evt.get("message", "")
        return f"{_elapsed()} ERROR [{code}]: {message}"

    def _render_team_status(evt: dict[str, object]) -> str | None:
        agents = cast("list[dict[str, Any]]", evt.get("agents", []))
        if not agents:
            return None
        lines = [f"{_elapsed()} team_status:"]
        for a in agents:
            agent_id = a.get("agent_id", "?")
            state = a.get("state", "unknown")
            lines.append(f"        {agent_id}: {state}")
        return "\n".join(lines)

    def _render_event(evt: dict[str, object]) -> str | None:
        """Dispatch to the appropriate renderer based on event type."""
        event_type = evt.get("type", "")
        match event_type:
            case "agent_status":
                return _render_agent_status(evt)
            case "message_chunk":
                return _render_message_chunk(evt)
            case "thought_chunk":
                return _render_thought_chunk(evt)
            case "tool_call_start":
                return _render_tool_call_start(evt)
            case "tool_call_update":
                return _render_tool_call_update(evt)
            case "plan_update":
                return _render_plan_update(evt)
            case "artifact_update":
                return _render_artifact_update(evt)
            case "error":
                return _render_error(evt)
            case "team_status":
                return _render_team_status(evt)
            case "heartbeat":
                return None  # Suppress heartbeats in output.
            case "connected":
                return None  # Handled separately during handshake.
            case _:
                return f"{_elapsed()} {event_type}: {evt}"

    # --- Permission prompt ---

    async def _handle_permission(
        evt: dict[str, object],
    ) -> None:
        """Prompt the user inline for a permission decision and POST it."""
        request_id = evt.get("request_id", "")
        description = evt.get("description", "")
        tool_call = evt.get("tool_call", "")
        options: list[dict[str, str]] = evt.get("options", [])  # type: ignore[assignment]

        click.echo(f"{_elapsed()} PERMISSION REQUIRED: {description}")
        if tool_call:
            click.echo(f"        Tool: {tool_call}")

        # Build shortcut map from options.
        shortcut_map: dict[str, str] = {}
        labels: list[str] = []
        for opt in options:
            oid = opt.get("option_id", "")
            name = opt.get("name", oid)
            kind = opt.get("kind", "")
            if kind == "allow_once":
                shortcut_map["a"] = oid
                labels.append("[a]llow")
            elif kind == "allow_always":
                shortcut_map["A"] = oid
                labels.append("[A]llow always")
            elif kind == "reject_once":
                shortcut_map["r"] = oid
                labels.append("[r]eject")
            elif kind == "reject_always":
                shortcut_map["R"] = oid
                labels.append("[R]eject always")
            else:
                # Fallback: use first char of option_id.
                key = oid[0] if oid else name[0] if name else "?"
                shortcut_map[key] = oid
                labels.append(f"[{key}]{name[1:] if len(name) > 1 else ''}")

        prompt_line = "  ".join(labels)
        click.echo(f"        {prompt_line}")

        # Run the blocking input() in a thread so the event loop stays alive.
        loop = asyncio.get_running_loop()
        chosen_option_id: str | None = None
        while chosen_option_id is None:
            try:
                answer = await loop.run_in_executor(
                    None, lambda: click.prompt("        >", prompt_suffix=" ")
                )
            except (EOFError, KeyboardInterrupt):
                click.echo("\n        Skipped (no response sent).")
                return
            answer = answer.strip()
            if answer in shortcut_map:
                chosen_option_id = shortcut_map[answer]
            else:
                # Try matching as a raw option_id.
                valid_ids = {o.get("option_id") for o in options}
                if answer in valid_ids:
                    chosen_option_id = answer
                else:
                    click.echo(
                        f"        Invalid choice '{answer}'. "
                        f"Options: {', '.join(shortcut_map.keys())}"
                    )

        # POST the permission response via REST.
        try:
            async with httpx.AsyncClient(base_url=api_url, timeout=10.0) as http:
                resp = await http.post(
                    f"/permissions/{request_id}/respond",
                    json={"option_id": chosen_option_id},
                )
                if resp.is_success:
                    data = resp.json()
                    status = data.get("action_status", "unknown")
                    click.echo(f"        Permission {request_id}: {status}")
                else:
                    click.echo(
                        f"        Permission response failed: {resp.status_code}",
                        err=True,
                    )
        except Exception as exc:
            click.echo(f"        Permission response error: {exc}", err=True)

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
                        await _handle_permission(evt)
                    else:
                        rendered = _render_event(evt)
                        if rendered is not None:
                            click.echo(rendered)

                # Check for terminal agent states.
                if event_type == "agent_status":
                    state = evt.get("state", "")
                    if state in terminal_states:
                        # Check if ALL agents are terminal by fetching status.
                        # For now, treat the thread-level terminal signal as
                        # definitive when the supervisor reaches a terminal state.
                        node = evt.get("node_name", "")
                        if node in ("supervisor", "vaultspec-supervisor"):
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
