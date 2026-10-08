"""Control-layer policy over a durable permission row's offered options.

The repository decodes the options a permission request offered from its
``allowed_options_json`` column; whether an answer denies the request is answered
by the canonical Layer 1 option rules over a decoded list, whichever source the
list came from, and this module holds what the control layer decides from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import decode_allowed_options
from ..graph.acp_options import is_rejection, offered_option, valid_option_ids

if TYPE_CHECKING:
    from ..database import PendingPermission

__all__ = [
    "answer_is_rejection",
    "pending_is_actionable",
    "pending_option_ids",
    "response_is_rejection",
]


def pending_option_ids(pending: PendingPermission) -> set[str]:
    """The option ids a response to *pending* could name."""
    return valid_option_ids(pending.offered)


def pending_is_actionable(pending: PendingPermission) -> bool:
    """Whether a response could still be addressed to *pending*.

    It must offer a usable option, and its run must still have checkpoint truth
    to resume from.
    """
    return bool(pending_option_ids(pending)) and not pending.checkpoint_unavailable


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
