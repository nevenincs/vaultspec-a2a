"""The seam through which an in-process provider lane is contributed to this build.

The product declares what an in-process lane is - :class:`LaneRegistration` - and
never which ones exist beyond those it compiles in. Any other lane arrives through
the ``lane_plugins`` setting: a list of module paths, each exposing
``register_lanes(registry)``, which receives a :class:`LaneRegistry` and registers
its lanes into it. The dependency points one way: a plugin knows this protocol,
and nothing here knows a plugin.

**Honoured only under a double arm.** The plugins are imported only while
``serve_in_process_lanes`` is armed and the desktop profile is not. A plugin lane
returns scripted content, and a product install has no business serving one: a
non-empty ``lane_plugins`` outside that double arm is not quietly ignored, it is
refused, and so is a plugin that fails to import or exposes no
``register_lanes``. Each refusal is a :class:`LanePluginError`, raised when the
lane set is first resolved, which the provider factory does at construction so a
misconfigured process stops at startup rather than at its first run.

The setting reaches a worker only through the environment its gateway hands it,
so one declaration arms both processes. Control of that environment already
implies control of the process, so naming a module in it grants no authority the
environment did not already carry.
"""

from __future__ import annotations

import importlib
from functools import cache
from typing import TYPE_CHECKING, Protocol

from ..control.config import setting_env, settings
from ..thread.errors import ConfigError
from .execution_modes import EXTERNAL_EXECUTION_MODES

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from ..graph.enums import Provider
    from ..team.team_config import AgentConfig

__all__ = [
    "LanePluginError",
    "LaneRegistration",
    "LaneRegistry",
    "registered_lanes",
]


class LanePluginError(ConfigError):
    """A configured lane plugin cannot be honoured, so the process refuses to run."""

    __slots__ = ()


class LaneRegistration(Protocol):
    """One in-process lane: its catalog identity, its selectors, and its model.

    ``provider`` and ``execution_mode`` are the lane's wire identity, and the pair
    is its catalog key. ``model_values`` are the exact selectors the lane's model
    answers to, served as its catalog entries. ``display_name`` must name the lane
    as in-process: a lane that returns fixed or replayed content is served beside
    real providers and must not be presentable as one. ``description`` is the
    text each served entry carries.
    """

    @property
    def provider(self) -> Provider: ...

    @property
    def execution_mode(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def model_values(self) -> tuple[str, ...]: ...

    def create_model(self, agent_config: AgentConfig | None) -> BaseChatModel:
        """Construct the lane's model for one role of a run."""
        ...


class LaneRegistry:
    """The collector a lane plugin's ``register_lanes`` receives.

    A registration may not claim a provider an external lane already executes,
    nor one this build already holds, and it must advertise at least one
    selector; each violation refuses the plugin rather than letting one lane
    shadow another.
    """

    def __init__(self, *, reserved: frozenset[Provider]) -> None:
        self._reserved = reserved
        self._lanes: dict[Provider, LaneRegistration] = {}

    def register(self, lane: LaneRegistration) -> None:
        """Add *lane* to this process's in-process lanes.

        Raises:
            LanePluginError: If the lane claims a provider another lane holds, or
                advertises no selector.
        """
        provider = lane.provider
        if (
            provider in EXTERNAL_EXECUTION_MODES
            or provider in self._reserved
            or provider in self._lanes
        ):
            raise LanePluginError(
                f"lane plugin registration claims provider {provider.value!r}, "
                "which another lane in this build already holds"
            )
        if not lane.model_values:
            raise LanePluginError(
                f"lane plugin registration for {provider.value!r} advertises no "
                "model selector"
            )
        self._lanes[provider] = lane

    @property
    def lanes(self) -> tuple[LaneRegistration, ...]:
        """The registered lanes, in registration order."""
        return tuple(self._lanes.values())


def registered_lanes(
    *, reserved: frozenset[Provider] = frozenset()
) -> tuple[LaneRegistration, ...]:
    """Return the lanes the configured plugins register, loading them once.

    The result is cached per configuration, so a process imports its plugins a
    single time and a changed configuration is resolved afresh. *reserved* names
    the in-process providers the build itself holds, which no plugin may claim.

    Raises:
        LanePluginError: If plugins are configured outside the double arm, or a
            plugin cannot be imported, exposes no ``register_lanes``, or
            registers a lane the registry refuses.
    """
    return _load(
        settings.lane_plugins,
        settings.serve_in_process_lanes,
        settings.desktop_profile_armed,
        reserved,
    )


@cache
def _load(
    plugins: tuple[str, ...],
    serve_in_process_lanes: bool,
    desktop_profile_armed: bool,
    reserved: frozenset[Provider],
) -> tuple[LaneRegistration, ...]:
    if not plugins:
        return ()
    if not serve_in_process_lanes or desktop_profile_armed:
        raise LanePluginError(
            f"{setting_env('lane_plugins')} names lane plugins, which are honoured "
            f"only while {setting_env('serve_in_process_lanes')} is armed and the "
            "desktop profile is not; unset it or arm the in-process lanes"
        )
    registry = LaneRegistry(reserved=reserved)
    for module_path in plugins:
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            raise LanePluginError(
                f"lane plugin {module_path!r} cannot be imported"
            ) from exc
        register = getattr(module, "register_lanes", None)
        if not callable(register):
            raise LanePluginError(
                f"lane plugin {module_path!r} exposes no register_lanes(registry)"
            )
        register(registry)
    return registry.lanes
