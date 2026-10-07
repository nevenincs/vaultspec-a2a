"""Durable-column adapter over the canonical ACP option rules.

The control layer stores the options a permission request offered as a JSON
string in the ``allowed_options_json`` column. This module owns that column's one
decode; which ids are valid and whether an answer denies the request are answered
by the canonical Layer 1 option rules over the decoded list.
"""

from __future__ import annotations

import json
from typing import cast

from ..graph.acp_options import is_rejection, offered_option, valid_option_ids

__all__ = [
    "decode_allowed_options",
    "extract_allowed_option_ids",
    "response_is_rejection",
]


def decode_allowed_options(raw_options_json: str | None) -> list[object] | None:
    """Decode the offered options of a durable permission row.

    An absent column offered nothing, so it decodes to an empty list. A column
    that is present but empty, malformed JSON, or not a JSON list is unreadable
    and decodes to ``None``, so a caller that must fail closed on a broken row
    can tell it apart from a row that offered nothing.
    """
    if raw_options_json is None:
        return []
    try:
        decoded: object = json.loads(raw_options_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return cast("list[object]", decoded) if isinstance(decoded, list) else None


def extract_allowed_option_ids(raw_options_json: str | None) -> set[str]:
    """Return the set of usable option ids from a durable permission row.

    A column that is absent or unreadable carries no offered options, so
    validation against it fails closed.
    """
    return valid_option_ids(decode_allowed_options(raw_options_json))


def response_is_rejection(
    raw_options_json: str | None,
    response_option_id: str | None,
) -> bool:
    """Return the one rejection verdict for an answer to a durable permission row.

    The submission stamp and the resolution settlement both ask this one
    question, so a denial cannot be recorded as an approval by one path and a
    rejection by another.

    The chosen option's declared kind decides. An answer naming an option the
    row does not carry, or a row that cannot be read, is judged by the chosen
    id's own spelling, so a legacy or malformed row still gets the best verdict
    available rather than silently reading as approved. Nothing chosen is not a
    rejection.
    """
    if not response_option_id:
        return False
    chosen = offered_option(
        decode_allowed_options(raw_options_json), response_option_id
    )
    return is_rejection(
        chosen if chosen is not None else {"optionId": response_option_id}
    )
