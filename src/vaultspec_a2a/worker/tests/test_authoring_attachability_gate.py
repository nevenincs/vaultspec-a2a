"""The armed authoring preset, and the two provider surfaces its attach accepts.

This module was written against ``assert_armed_authoring_attachable``, a
COMPILE-TIME gate in ``worker.graph_lifecycle``. That symbol never existed in any
committed version of the tree -- the file was committed against uncommitted work
that never landed -- so every test here failed at IMPORT, and because pytest
aborts a whole run on a collection error, no ``pytest src/vaultspec_a2a`` run
could complete at all. Every suite-wide green reported against this tree was in
fact a scoped subset that stepped around this module.

The behaviour those tests wanted does exist; it is ATTACH-TIME rather than
compile-time. ``_acp_authoring.attach_authoring_tools`` refuses a model with no
mount surface instead of returning it unchanged, which is the same refusal one
seam later -- before any turn runs, though not before the subprocess spawns.

Repointed rather than deleted, intent by intent:

* the armed-shape assertion never touched the missing symbol and stands as it was;
* the two surface-acceptance cases are repointed at the real attach seam, keeping
  the model fixtures that made them worth having -- they distinguish the ACP lane's
  ``with_mcp_servers`` from the Codex lane's ``with_authoring_mcp_server``, which
  the binding-shaped tests in ``providers/tests/test_acp_authoring.py`` do not;
* the no-surface refusal is already covered there by
  ``test_model_without_acp_surface_is_refused_rather_than_passed_through``;
* the two no-op cases asked when the compile-time GATE applied. No such gate
  exists, and the attach-time analogue -- an unarmed run attaching nothing even
  to a surfaceless model -- is covered there by
  ``test_absent_binding_returns_the_model_unchanged`` and
  ``test_unarmed_run_is_a_noop_even_on_a_model_with_no_surface``.

Real config loading throughout: the shipped ``vaultspec-solo-coder`` preset and
its agent TOML, no mocks.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeChatModel
from pydantic import Field

from ...providers._acp_authoring import attach_authoring_tools
from ...providers.tests.test_acp_authoring import _binding, _stdio_binding
from ...team.team_config import load_agent_config, load_team_config


class _AcpSurfaceModel(FakeChatModel):
    """A model exposing the ACP lane's ``with_mcp_servers`` surface."""

    responses: list[str] = Field(default_factory=list)

    def with_mcp_servers(
        self, mcp_servers: Any, allowed_tools: Any = None
    ) -> _AcpSurfaceModel:
        return self


class _CodexSurfaceModel(FakeChatModel):
    """A model exposing the Codex lane's ``with_authoring_mcp_server`` surface."""

    responses: list[str] = Field(default_factory=list)

    def with_authoring_mcp_server(self, spec: Any) -> _CodexSurfaceModel:
        return self


def _solo_coder() -> tuple[Any, dict[str, Any]]:
    team = load_team_config("vaultspec-solo-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    return team, agent_configs


def test_solo_coder_is_armed_via_authoring_bridge() -> None:
    """The armed shape is authoring_bridge=true with NO declared harness servers.

    A predicate keyed on ``mcp_servers`` alone would read this preset as unarmed
    and skip every attachment check, which is the class of gap this file exists
    to hold shut.
    """
    team, _ = _solo_coder()
    harness = team.effective_harness()
    assert harness is not None
    assert harness.authoring_bridge is True
    assert not harness.mcp_servers


def test_acp_lane_surface_is_accepted_by_the_attach_seam() -> None:
    """A model exposing ``with_mcp_servers`` mounts rather than being refused."""
    model = _AcpSurfaceModel(responses=["stub"])
    assert attach_authoring_tools(model, _binding(), autonomous=True) is model


def test_codex_lane_surface_is_accepted_by_the_attach_seam() -> None:
    """The Codex lane mounts through its OWN surface, and only over stdio.

    Held separately from the ACP case for two reasons the seam actually
    enforces. The lanes reach the same capability by different method names, so
    a seam knowing only ``with_mcp_servers`` would refuse a perfectly attachable
    Codex run. And the transport is not interchangeable: handed the HTTP binding
    this path raises, because the Codex bridge rides the per-run config home and
    needs ``engine_base_url`` + ``run_id``. Passing the HTTP binding here is what
    the first draft of this test did, and the refusal is what corrected it.
    """
    model = _CodexSurfaceModel(responses=["stub"])
    assert attach_authoring_tools(model, _stdio_binding(), autonomous=True) is model
