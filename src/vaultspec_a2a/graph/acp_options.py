"""Canonical identity rules for ACP permission options (Layer 1 leaf).

An ACP ``PermissionOption`` reaches this process through several transports —
the provider's ``session/request_permission`` RPC params, a LangGraph interrupt
resume payload, an SSE frame, and a durable ``allowed_options_json`` column — and
those transports do not agree on the spelling of the identity field. The ACP wire
schema uses camelCase ``optionId``; our own snake_case surfaces (the versioned
API edge and the dashboard) use ``option_id``. Both spellings are accepted, and
``optionId`` wins when a single dict somehow carries both.

This module is the one place that rule lives. It imports nothing from the package
(stdlib only), so every layer that speaks ACP — ``providers``, ``graph.nodes``,
``streaming``, ``control`` — depends on it downward with no new package edge:
all four already import :mod:`vaultspec_a2a.graph.enums`, the sibling Layer 1
leaf that owns the ACP option *vocabulary* (``PermissionOptionKind``,
``REJECT_OPTION_IDS``). It is a separate module from ``enums`` because a
dict-shape predicate is not an enum.

Both helpers are total over untrusted input: an option that is not a dict, or
whose id is missing, non-string, or empty, simply has no id. Callers therefore
never see ``None`` leak into a set of "valid" ids, and never need a bare
``option["optionId"]`` subscript that could raise ``KeyError`` on a malformed
payload from a subprocess.
"""

__all__ = ["OPTION_ID_KEYS", "option_id_of", "valid_option_ids"]

# Accepted spellings of the option identity field, in precedence order.
OPTION_ID_KEYS: tuple[str, ...] = ("optionId", "option_id")


def option_id_of(option: object) -> str | None:
    """Return the id of one ACP permission option, or None if it has none.

    ``None`` means "this option carries no usable identity" — a non-dict entry,
    a missing key under either spelling, or a value that is not a non-empty
    string. Callers that need a concrete id substitute their own fallback.
    """
    if not isinstance(option, dict):
        return None
    for key in OPTION_ID_KEYS:
        value = option.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def valid_option_ids(options: object) -> set[str]:
    """Return every usable option id offered by a parsed ACP option list.

    Accepts both spellings on every entry, so a list mixing camelCase and
    snake_case options validates as one set. An entry carrying both spellings
    contributes both ids, keeping a client that echoes the other spelling
    valid. A non-list, or a list of malformed entries, yields an empty set —
    which callers read as "nothing to validate against", never as a set
    containing ``None``.
    """
    if not isinstance(options, list):
        return set()
    option_ids: set[str] = set()
    for option in options:
        if not isinstance(option, dict):
            continue
        for key in OPTION_ID_KEYS:
            value = option.get(key)
            if isinstance(value, str) and value:
                option_ids.add(value)
    return option_ids
