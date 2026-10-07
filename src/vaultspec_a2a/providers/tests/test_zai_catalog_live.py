"""Live Z.ai catalog and selected-model proofs through the production ACP lane.

Two proofs, separately authorized. The first is prompt-free: the production
catalog registration opens a real authenticated session through the adapter the
lane runs and enumerates the models Z.ai advertises. The second is billable: one
deliberately tiny real turn that proves the catalog-selected value reached the
gateway before the prompt was sent, read back from the ACP adapter's own
confirmed ``currentValue``.

The catalog is the authority for the model value - no static Z.ai tier and no
Claude alias is accepted here - and the operator names the entry through the
shared live-selection declaration, so neither proof can pick a paid model
nobody chose.

The billable proof builds the model directly rather than through
``ProviderFactory.create``, because the factory refuses this lane until a
completed turn is recorded against it and this test is what earns that record.
The same shape as the Claude candidate proof in ``test_claude_live_turn.py``.

Re-arm (one command):

    uv run --no-sync pytest -m service \\
        src/vaultspec_a2a/providers/tests/test_zai_catalog_live.py \\
        --require-prerequisite=zai-credential

Service-marked, so deselected from the default suite. An absent credential or an
undeclared catalog selection is reported as missing, never as a pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from ...control.config import settings
from ...graph.enums import Provider
from ...testing import declared_lane_model_value
from .._factory_commands import _classify_acp_command, acp_launch_options
from ..acp_chat_model import AcpChatModel
from ..execution_modes import external_execution_mode
from ..factory import ProviderFactory, _zai_auth_env
from ..provider_catalog import AuthenticationState, CatalogStatus, ProviderCatalogKey

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule
    from .._json_contract import JsonObject


def _zai_catalog_key() -> ProviderCatalogKey:
    return ProviderCatalogKey(
        Provider.ZAI.value, f"zai-claude-agent-acp:{settings.acp_backend}"
    )


def _selected_model_value(config_options: Sequence[JsonObject]) -> str:
    matching = [
        option
        for option in config_options
        if option.get("category") == "model" and isinstance(option.get("id"), str)
    ]
    assert len(matching) == 1, "ACP did not confirm exactly one model selector"
    selected = matching[0].get("currentValue")
    assert isinstance(selected, str) and selected, (
        "ACP did not confirm the selected Z.ai model value"
    )
    return selected


@pytest.mark.service
@pytest.mark.asyncio
async def test_zai_catalog_enumerates_through_the_production_lane(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Prove the lane's own prompt-free enumeration, spending nothing.

    An ABSENT credential is not a failing lane, it is an unsupplied one, so the
    rule owns that decision: a skip naming the missing token, or a failure when
    the caller guaranteed it with ``--require-prerequisite=zai-credential``.
    """
    external_prerequisite("zai-credential")
    registration = ProviderFactory().catalog_registration(_zai_catalog_key(), tmp_path)
    discovery = await registration.discover()

    assert discovery.authentication is AuthenticationState.AUTHENTICATED, (
        "Z.ai catalog authentication was not confirmed: "
        f"{discovery.authentication.value}; "
        f"reason={discovery.catalog.state.reason!r}"
    )
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE, (
        "Z.ai ACP did not enumerate a catalog: "
        f"reason={discovery.catalog.state.reason!r}"
    )
    advertised = {entry.provider_value for entry in discovery.catalog.models}
    assert advertised, "Z.ai ACP session advertised no model choices"


@pytest.mark.service
@pytest.mark.asyncio
async def test_zai_catalog_selection_is_confirmed_by_one_minimal_turn(
    tmp_path: Path,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """Earn a first completed-turn proof, on the exact value the catalog serves."""
    external_prerequisite("zai-credential")
    served, reason = await declared_lane_model_value(Provider.ZAI.value, tmp_path)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)

    command = _classify_acp_command(settings.acp_backend)
    env_vars, auth_mode = _zai_auth_env()
    use_exec, launch_env = acp_launch_options(settings.acp_backend)
    model = AcpChatModel(
        command=list(command.argv),
        env_vars={**env_vars, **launch_env},
        desired_model=served,
        workspace_root=str(tmp_path),
        use_exec=use_exec,
        provider=Provider.ZAI.value,
        execution_mode=external_execution_mode(Provider.ZAI, settings.acp_backend),
        provider_command=command,
        auth_mode=auth_mode,
    )
    assert model.desired_model == served
    assert model._config.desired_model == served

    messages = [
        SystemMessage(content="You are terse."),
        HumanMessage(content="Reply with exactly the single word: pong"),
    ]
    response_parts: list[str] = []
    async for chunk in model.astream(messages):
        if isinstance(chunk.content, str):
            response_parts.append(chunk.content)
    response = "".join(response_parts).strip()
    assert response, "Z.ai returned no assistant content for the proof turn"

    selected = _selected_model_value(model._session_config_options)
    assert selected == served or selected.startswith(f"{served}["), (
        "Z.ai ACP confirmed a different model than the catalog-selected value: "
        f"requested={served!r}, selected={selected!r}"
    )
