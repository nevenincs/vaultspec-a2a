"""Read a running service stack's durable thread state, and its options.

Two helpers the service suites share: reading one thread's durable state, and
resolving a permission option's id from the human label a scenario names
("approve", "deny", "reject") rather than the opaque id the service minted for
it. Waiting on that state is :func:`vaultspec_a2a.testing.wait_for_run_status`
with ``thread_state`` as the reader.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..testing import json_object, json_object_list

if TYPE_CHECKING:
    from ..providers import JsonObject
    from .harness import ServiceStack

__all__ = ["select_option_id", "thread_state"]


def thread_state(stack: ServiceStack, thread_id: str) -> JsonObject:
    """Read the real durable thread state before inspecting it."""
    return json_object(stack.get_thread_state(thread_id), at="thread state")


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
