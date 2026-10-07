"""Durable-column adapter over the canonical ACP option rules.

The control layer stores the options a permission request offered as a JSON
string in the ``allowed_options_json`` column. This module owns that column's one
decode; whether an answer denies the request is answered by the canonical Layer 1
option rules over a decoded list, whichever source the list came from.
"""

from __future__ import annotations

import json
from typing import cast

from ..graph.acp_options import is_rejection, offered_option

__all__ = [
    "answer_is_rejection",
    "decode_allowed_options",
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


def answer_is_rejection(
    offered: object,
    response_option_id: str | None,
) -> bool:
    """Return the one rejection verdict for an answer to an offered option list.

    The submission stamp and the resolution settlement both ask this one
    question, so a denial cannot be recorded as an approval by one path and a
    rejection by another.

    The chosen option's declared kind decides. An answer naming an option the
    offer does not carry, or an offer that cannot be read, is judged by the
    chosen id's own spelling, so a legacy or malformed offer still gets the best
    verdict available rather than silently reading as approved. Nothing chosen is
    not a rejection.
    """
    if not response_option_id:
        return False
    chosen = offered_option(offered, response_option_id)
    return is_rejection(
        chosen if chosen is not None else {"optionId": response_option_id}
    )


def response_is_rejection(
    raw_options_json: str | None,
    response_option_id: str | None,
) -> bool:
    """Return the rejection verdict for an answer to a durable permission row."""
    return answer_is_rejection(
        decode_allowed_options(raw_options_json), response_option_id
    )
