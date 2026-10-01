"""The two messages a pytest child sends the runner that owns it.

Kept apart from the harness plugin on purpose: the child sends its hello
before pytest starts, and importing the plugin module to reach these would
import it before pytest can, so pytest could no longer rewrite the plugin's
assertions and would warn on every run.
"""

from __future__ import annotations

import os
import socket

__all__ = ["send_completion_message", "send_completion_receipt"]


def send_completion_message(
    endpoint: str, message_type: str, exitstatus: int | None = None
) -> None:
    """Send one bounded runner-child message with its actual process identity."""
    if message_type not in {"hello", "complete"}:
        raise ValueError("invalid pytest completion message type")
    if message_type == "complete" and exitstatus is None:
        raise ValueError("completion receipt requires an exit status")
    host, port_text, token = endpoint.split(":", maxsplit=2)
    if host != "127.0.0.1" or not port_text.isdigit() or not token:
        raise ValueError("invalid pytest completion endpoint")
    payload = f"{token}:{os.getpid()}:{message_type}"
    if exitstatus is not None:
        payload += f":{exitstatus}"
    with socket.create_connection((host, int(port_text)), timeout=1.0) as connection:
        connection.sendall(f"{payload}\n".encode("ascii"))


def send_completion_receipt(exitstatus: int, *, endpoint: str | None = None) -> None:
    """Notify the containing runner that pytest has produced its result."""
    from .session_root import TestSessionSettings

    if endpoint is None:
        harness = TestSessionSettings()
        endpoint = harness.completion_endpoint
        if not endpoint or harness.completion_owner_pid != os.getpid():
            return
    send_completion_message(endpoint, "complete", exitstatus)
