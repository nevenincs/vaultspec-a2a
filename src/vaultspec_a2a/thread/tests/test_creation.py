"""The autonomous flag resolves the caller's explicit choice over the team default."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ...team.team_config import TeamPermissionsConfig
from ..creation import resolve_autonomous


def _team_config(*, auto_approve: bool) -> SimpleNamespace:
    """The minimal shape ``resolve_autonomous`` reads: ``.permissions.auto_approve``."""
    return SimpleNamespace(permissions=TeamPermissionsConfig(auto_approve=auto_approve))


@pytest.mark.parametrize("auto_approve", [True, False])
@pytest.mark.parametrize("explicit", [True, False])
def test_an_explicit_flag_always_wins_over_the_team_default(
    explicit: bool, auto_approve: bool
) -> None:
    assert resolve_autonomous(explicit, _team_config(auto_approve=auto_approve)) is (
        explicit
    )


@pytest.mark.parametrize("auto_approve", [True, False])
def test_an_unset_flag_falls_back_to_the_team_default(auto_approve: bool) -> None:
    assert (
        resolve_autonomous(None, _team_config(auto_approve=auto_approve))
        is auto_approve
    )
