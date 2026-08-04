"""Poll a running service stack's durable thread state, and read its options.

Three service suites had each grown their own byte-identical copies of these:
reading one thread's durable state, polling it until a caller-supplied
predicate holds, and resolving a permission option's id from the human label a
scenario names ("approve", "deny", "reject") rather than the opaque id the
service minted for it.

The 120-second poll budget is shared by all three source declarations - no
divergence to preserve - and stays a caller-supplied default rather than a
hardcoded constant, since a scenario asserting on a slower path (dispatch under
load, a multi-step permission chain) may still need to widen it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..testing.payloads import json_object, json_object_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..providers._json_contract import JsonObject
    from .harness import ServiceStack

__all__ = ["select_option_id", "thread_state", "wait_for_state"]


def thread_state(stack: ServiceStack, thread_id: str) -> JsonObject:
    """Read the real durable thread state before inspecting it."""
    return json_object(stack.get_thread_state(thread_id), at="thread state")


def wait_for_state(
    stack: ServiceStack,
    thread_id: str,
    predicate: Callable[[JsonObject], bool],
    *,
    timeout: float = 120.0,
) -> JsonObject:
    """Poll *thread_id*'s durable state until *predicate* holds or time runs out."""
    deadline = time.monotonic() + timeout
    last_state: JsonObject | None = None
    while time.monotonic() < deadline:
        state = thread_state(stack, thread_id)
        last_state = state
        if predicate(state):
            return state
        time.sleep(1.0)
    raise AssertionError(f"timed out waiting for thread {thread_id}: {last_state}")


def select_option_id(request: JsonObject, *, label: str) -> str:
    """Resolve a permission option's id from the human label a scenario names.

    A scenario names the option it wants by its human-readable label
    ("approve", "deny", "reject") rather than the opaque id the service
    minted for it, so this matches the label against each option's id, name,
    and label fields case-insensitively and returns the real id.
    """
    target = label.casefold()
    for option in json_object_list(request.get("options"), at="permission options"):
        option_id = option.get("option_id")
        option_name = option.get("name")
        option_label = option.get("label")
        for candidate in (option_id, option_name, option_label):
            if (
                isinstance(candidate, str)
                and candidate.casefold() == target
                and isinstance(option_id, str)
                and option_id
            ):
                return option_id
    raise AssertionError(f"permission option {label!r} not found: {request}")
