"""Durable-column adapter over the canonical ACP option-id rule."""

from __future__ import annotations

import json

from ..graph.acp_options import valid_option_ids

__all__ = ["extract_allowed_option_ids"]


def extract_allowed_option_ids(raw_options_json: str | None) -> set[str]:
    """Return the set of usable option ids from a durable permission row.

    The control layer stores the offered options as a JSON string in the
    ``allowed_options_json`` column, so this adapter owns only the decode; the
    question of *which ids are valid* is answered by the canonical Layer 1
    predicate. A column that is absent, empty, malformed JSON, or not a JSON
    list carries no offered options, so validation against it fails closed.
    """
    if not isinstance(raw_options_json, str) or not raw_options_json:
        return set()
    try:
        parsed = json.loads(raw_options_json)
    except (TypeError, json.JSONDecodeError):
        return set()
    return valid_option_ids(parsed)
