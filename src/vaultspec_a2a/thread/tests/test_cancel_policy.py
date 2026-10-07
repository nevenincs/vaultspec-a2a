"""Cancel eligibility is pinned for every status the lifecycle can be in.

A cancel is admitted exactly where a run can still enter ``CANCELLING``, plus on
a run already there (a repeat cancel replays the one in flight). The table below
states that rule as literal, independently-judged expectations for every member
of :class:`ThreadStatus`, so a change to the derivation - or to the transition
table it reads - that silently admits or refuses the wrong status is caught here
rather than only where a refusal is user-visible.
"""

from __future__ import annotations

import pytest

from ..cancel_policy import can_cancel
from ..enums import ThreadStatus

#: Every ``ThreadStatus`` paired with whether a cancel is admitted there and
#: whether that status is itself the "already cancelled" terminal.
_EXPECTED: dict[ThreadStatus, tuple[bool, bool]] = {
    ThreadStatus.SUBMITTED: (True, False),
    ThreadStatus.RUNNING: (True, False),
    ThreadStatus.INPUT_REQUIRED: (True, False),
    ThreadStatus.RECONCILING: (True, False),
    ThreadStatus.REPAIR_NEEDED: (True, False),
    ThreadStatus.CANCELLING: (True, False),
    ThreadStatus.CANCELLED: (False, True),
    ThreadStatus.COMPLETED: (False, False),
    ThreadStatus.FAILED: (False, False),
    ThreadStatus.ARCHIVED: (False, False),
    ThreadStatus.DELETING: (False, False),
}


def test_every_known_status_is_covered() -> None:
    """Guard the table itself: a new status must be added here on purpose."""
    assert set(_EXPECTED) == set(ThreadStatus)


@pytest.mark.parametrize("status", list(ThreadStatus))
def test_cancel_eligibility_is_pinned_per_status(status: ThreadStatus) -> None:
    allowed, already_cancelled = _EXPECTED[status]
    eligibility = can_cancel(status.value)
    assert eligibility.allowed is allowed
    assert eligibility.already_cancelled is already_cancelled
    if allowed:
        assert eligibility.reason is None
    else:
        assert eligibility.reason == f"Cannot cancel thread in {status.value!r} state"
