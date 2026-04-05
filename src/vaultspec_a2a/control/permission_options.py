"""Shared helpers for validating durable permission option payloads."""

from __future__ import annotations

import json


def extract_allowed_option_ids(raw_options_json: str | None) -> set[str]:
    """Return the set of usable option ids from a durable permission row."""
    if not isinstance(raw_options_json, str) or not raw_options_json:
        return set()
    try:
        parsed = json.loads(raw_options_json)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(parsed, list):
        return set()

    option_ids: set[str] = set()
    for option in parsed:
        if not isinstance(option, dict):
            continue
        for key in ("option_id", "optionId"):
            value = option.get(key)
            if isinstance(value, str) and value:
                option_ids.add(value)
    return option_ids
