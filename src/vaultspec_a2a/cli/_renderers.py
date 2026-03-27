"""Domain rendering functions for the CLI team commands.

Extracts terminal rendering from command definitions so that `_team.py`
contains only Click command wiring while all Rich/Click output formatting
lives here.
"""

from __future__ import annotations

__all__ = [
    "format_elapsed",
    "handle_permission_prompt",
    "render_event",
    "render_status_display",
    "render_thread_list",
]

import asyncio
from typing import Any, cast

import click

# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------


def format_elapsed(created_at_str: str | None) -> str:
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


# ---------------------------------------------------------------------------
# WebSocket event rendering
# ---------------------------------------------------------------------------


def _render_agent_status(elapsed: str, evt: dict[str, object]) -> str | None:
    agent = evt.get("agent_id") or "agent"
    state = evt.get("state", "")
    detail = evt.get("detail", "")
    line = f"{elapsed} {agent}: {state}"
    if detail:
        line += f" -- {detail}"
    return line


def _render_message_chunk(elapsed: str, evt: dict[str, object]) -> str | None:
    content = evt.get("content", "")
    if not content:
        return None
    agent = evt.get("agent_id") or "agent"
    finish = evt.get("finish_reason")
    if finish:
        return f"{elapsed} {agent}: {content} [{finish}]"
    return f"{elapsed} {agent}: {content}"


def _render_thought_chunk(elapsed: str, evt: dict[str, object]) -> str | None:
    content = evt.get("content", "")
    if not content:
        return None
    agent = evt.get("agent_id") or "agent"
    return f"{elapsed} {agent} (thinking): {content}"


def _render_tool_call_start(elapsed: str, evt: dict[str, object]) -> str | None:
    title = evt.get("title") or "(unknown tool)"
    kind = evt.get("kind", "")
    agent = evt.get("agent_id") or "agent"
    kind_str = f" [{kind}]" if kind else ""
    return f"{elapsed} {agent}: tool_call_start {title}{kind_str}"


def _render_tool_call_update(elapsed: str, evt: dict[str, object]) -> str | None:
    title = evt.get("title") or ""
    status = evt.get("status") or ""
    agent = evt.get("agent_id") or "agent"
    label = title or evt.get("tool_call_id", "")
    return f"{elapsed} {agent}: tool_call_update {label} ({status})"


def _render_plan_update(elapsed: str, evt: dict[str, object]) -> str | None:
    entries = cast("list[dict[str, Any]]", evt.get("entries", []))
    if not entries:
        return f"{elapsed} plan: (empty)"
    lines = [f"{elapsed} plan:"]
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


def _render_artifact_update(elapsed: str, evt: dict[str, object]) -> str | None:
    filename = evt.get("filename", "")
    last_chunk = evt.get("last_chunk", False)
    suffix = " (complete)" if last_chunk else ""
    return f"{elapsed} artifact: {filename}{suffix}"


def _render_error(elapsed: str, evt: dict[str, object]) -> str | None:
    code = evt.get("code", "")
    message = evt.get("message", "")
    return f"{elapsed} ERROR [{code}]: {message}"


def _render_team_status(elapsed: str, evt: dict[str, object]) -> str | None:
    agents = cast("list[dict[str, Any]]", evt.get("agents", []))
    if not agents:
        return None
    lines = [f"{elapsed} team_status:"]
    for a in agents:
        agent_id = a.get("agent_id", "?")
        state = a.get("state", "unknown")
        lines.append(f"        {agent_id}: {state}")
    return "\n".join(lines)


def render_event(elapsed: str, evt: dict[str, object]) -> str | None:
    """Dispatch to the appropriate renderer based on event type.

    Parameters
    ----------
    elapsed:
        Pre-formatted elapsed timestamp string (e.g. ``"[01:23]"``).
    evt:
        Parsed JSON event dict from the WebSocket stream.
    """
    event_type = evt.get("type", "")
    match event_type:
        case "agent_status":
            return _render_agent_status(elapsed, evt)
        case "message_chunk":
            return _render_message_chunk(elapsed, evt)
        case "thought_chunk":
            return _render_thought_chunk(elapsed, evt)
        case "tool_call_start":
            return _render_tool_call_start(elapsed, evt)
        case "tool_call_update":
            return _render_tool_call_update(elapsed, evt)
        case "plan_update":
            return _render_plan_update(elapsed, evt)
        case "artifact_update":
            return _render_artifact_update(elapsed, evt)
        case "error":
            return _render_error(elapsed, evt)
        case "team_status":
            return _render_team_status(elapsed, evt)
        case "heartbeat":
            return None  # Suppress heartbeats in output.
        case "connected":
            return None  # Handled separately during handshake.
        case _:
            return f"{elapsed} {event_type}: {evt}"


# ---------------------------------------------------------------------------
# Permission prompt
# ---------------------------------------------------------------------------


async def handle_permission_prompt(
    evt: dict[str, object],
    elapsed: str,
    api_url: str,
) -> None:
    """Prompt the user inline for a permission decision and POST the response.

    Parameters
    ----------
    evt:
        The ``permission_request`` event dict.
    elapsed:
        Pre-formatted elapsed timestamp string.
    api_url:
        Base REST API URL for posting the permission response.
    """
    import httpx

    request_id = evt.get("request_id", "")
    description = evt.get("description", "")
    tool_call = evt.get("tool_call", "")
    options: list[dict[str, str]] = cast("list[dict[str, str]]", evt.get("options", []))

    click.echo(f"{elapsed} PERMISSION REQUIRED: {description}")
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


# ---------------------------------------------------------------------------
# Status display (single thread)
# ---------------------------------------------------------------------------


def _plan_status_icon(entry_status: str) -> str:
    """Return a checkbox icon for the given plan entry status."""
    if entry_status == "completed":
        return "[x]"
    if entry_status == "in_progress":
        return "[>]"
    return "[ ]"


def render_status_display(
    thread_id: str,
    data: dict[str, Any],
    meta: dict[str, str | None],
) -> None:
    """Render the detailed status view for a single thread.

    Parameters
    ----------
    thread_id:
        The thread identifier.
    data:
        Parsed JSON from ``GET /threads/{id}/state``.
    meta:
        Thread metadata dict with ``nickname``, ``team_preset``, ``created_at``.
    """
    # Thread header
    nick = meta["nickname"] or thread_id[:8]
    click.echo(f"  Thread:     {thread_id} ({nick})")
    if meta["team_preset"]:
        click.echo(f"  Preset:     {meta['team_preset']}")
    click.echo(f"  Status:     {data.get('status', 'unknown')}")
    elapsed = format_elapsed(meta["created_at"])
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

    # Plan progress
    plan = data.get("plan", [])
    if plan:
        click.echo("  Plan:")
        for entry in plan:
            icon = _plan_status_icon(entry.get("status", "pending"))
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

    # Tool calls
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


# ---------------------------------------------------------------------------
# Thread list display
# ---------------------------------------------------------------------------


def render_thread_list(
    threads: list[dict[str, Any]],
    pending_permissions: list[dict[str, Any]] | None = None,
) -> None:
    """Render the summary dashboard for the thread list.

    Parameters
    ----------
    threads:
        List of thread summary dicts from ``GET /threads``.
    pending_permissions:
        Optional list of pending permissions from ``GET /team/status``.
    """
    if not threads:
        click.echo("No threads found.")
        return

    # Summary counts
    counts: dict[str, int] = {}
    for t in threads:
        s = t.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    _active_states = ("submitted", "running", "input_required", "cancelling")
    active = sum(counts.get(s, 0) for s in _active_states)
    total = len(threads)
    click.echo(f"  {total} threads ({active} active)\n")

    # Thread table
    click.echo(
        f"  {'THREAD_ID':34s}  {'STATUS':16s}  {'ELAPSED':8s}  {'PRESET / NICKNAME'}"
    )
    click.echo(f"  {'-' * 34}  {'-' * 16}  {'-' * 8}  {'-' * 30}")
    for t in threads:
        tid = t["thread_id"]
        tst = t.get("status", "unknown")
        elapsed = format_elapsed(t.get("created_at"))
        nick = t.get("nickname") or t.get("team_preset", "")
        click.echo(f"  {tid:34s}  {tst:16s}  {elapsed:8s}  {nick}")

    # Pending permissions summary
    if pending_permissions:
        click.echo(f"\n  Pending permissions: {len(pending_permissions)}")
        for p in pending_permissions:
            tid = p.get("thread_id", "?")[:8]
            description = p.get("description", "")
            click.echo(f"    [{tid}] {p.get('request_id', '?')}  {description}")
