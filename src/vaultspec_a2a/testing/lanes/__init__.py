"""The in-process fixture lanes a source checkout contributes to a test gateway.

The product knows only the lane-plugin protocol; this package is a plugin. A
process that names it in its lane plugins, with the in-process lanes armed
outside the desktop profile, imports it and calls :func:`register_lanes`, which
registers the deterministic lane. The lane keeps its wire identity - provider
``deterministic``, execution mode ``in-process-deterministic``, model
``deterministic`` - so a run frozen against it replays under the same identity.

Two seats arm it, one per kind of process. A gateway or worker child is given
:func:`armed_lane_environment` by the test boot environment builders whenever
they serve the in-process lanes; a gateway hands its worker that environment,
so one declaration reaches both processes. A test process holds
:func:`seated_lanes` for its whole session, through the repository's root
conftest, so a test that builds models in its own process resolves the lane
without seating it.

A child armed with a hold gate also serves the hold-then-complete scenario: its
turn stays in flight while the gate file exists and completes once it is gone.
The test closes and opens the gate with :func:`held_turns`, so a run is held
mid-turn by a signal the test controls rather than by a timer.

This module stays light on purpose: a gateway imports it at startup, and the
model it registers, with its chat-model stack, loads only when a lane builds
one. The model names below resolve lazily for the same reason.
"""

from __future__ import annotations

import contextlib
import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ...graph.enums import Provider

if TYPE_CHECKING:
    from collections.abc import Generator

    from langchain_core.language_models import BaseChatModel

    from ...providers import LaneRegistration, LaneRegistry
    from ...team.team_config import AgentConfig
    from .deterministic import UNATTENDED_REPLY as UNATTENDED_REPLY
    from .deterministic import (
        DeterministicResearchAdrChatModel as DeterministicResearchAdrChatModel,
    )

__all__ = [
    "DETERMINISTIC_LANE",
    "LANES",
    "UNATTENDED_REPLY",
    "DeterministicResearchAdrChatModel",
    "armed_lane_environment",
    "held_turns",
    "register_lanes",
    "seated_lanes",
]

_LAZY_IMPORTS = {
    "DeterministicResearchAdrChatModel": ".deterministic",
    "UNATTENDED_REPLY": ".deterministic",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


# The environment variable naming the file a hold-then-complete turn waits on.
# It is read where the lane builds its model, so it reaches a worker the same way
# the lane arming does: through the environment the child is spawned with.
_HOLD_GATE_ENVIRON: Final = "VAULTSPEC_A2A_TEST_HOLD_GATE"


@dataclass(frozen=True, slots=True)
class _DeterministicLane:
    """The deterministic lane's identity, selectors and model."""

    provider: Provider = Provider.DETERMINISTIC
    execution_mode: str = "in-process-deterministic"
    display_name: str = "Deterministic (in-process)"
    description: str = (
        "In-process deterministic provider; returns fixed role-keyed content "
        "with no external service and no spend."
    )
    model_values: tuple[str, ...] = ("deterministic",)

    def create_model(self, agent_config: AgentConfig | None) -> BaseChatModel:
        from .deterministic import DeterministicResearchAdrChatModel

        gate = os.environ.get(_HOLD_GATE_ENVIRON)
        return DeterministicResearchAdrChatModel(
            agent_config=agent_config, hold_gate=Path(gate) if gate else None
        )


DETERMINISTIC_LANE: Final = _DeterministicLane()

#: Every lane this plugin registers, in registration order.
LANES: Final[tuple[LaneRegistration, ...]] = (DETERMINISTIC_LANE,)


def register_lanes(registry: LaneRegistry) -> None:
    """Register this package's lanes; the lane-plugin entry point."""
    for lane in LANES:
        registry.register(lane)


def armed_lane_environment(*, hold_gate: Path | None = None) -> dict[str, str]:
    """Return the environment that serves these lanes from a child process.

    Both settings are named through the settings schema, so the spelling a
    child reads is the one the service declares. *hold_gate* is the file the
    child's hold-then-complete turns wait on; without it that scenario refuses
    its turn rather than complete one its test meant to hold.
    """
    from ...control.config import setting_env

    environment = {
        setting_env("serve_in_process_lanes"): "true",
        setting_env("lane_plugins"): __name__,
    }
    if hold_gate is not None:
        environment[_HOLD_GATE_ENVIRON] = str(hold_gate)
    return environment


@contextlib.contextmanager
def held_turns(gate: Path) -> Generator[None]:
    """Hold every hold-then-complete turn waiting on *gate* until the block ends.

    The gate is closed before the block runs, so a run started inside it holds
    from its first turn, and opened when the block ends, however it ends, so no
    turn stays held past the test that held it. A gate that is already closed
    is refused: two holders would each believe they own the release.
    """
    gate.touch(exist_ok=False)
    try:
        yield
    finally:
        gate.unlink(missing_ok=True)


@contextlib.contextmanager
def seated_lanes() -> Generator[None]:
    """Hold these lanes in this process for the duration of the block."""
    from ..environment import settings_override

    with settings_override(serve_in_process_lanes=True, lane_plugins=(__name__,)):
        yield
