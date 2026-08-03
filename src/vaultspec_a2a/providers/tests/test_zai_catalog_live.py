"""Live Z.ai catalog and selected-model proof through the production ACP lane.

This service test first performs the prompt-free catalog handshake, then sends
one deliberately tiny real turn only after the operator identifies an
advertised, low-cost provider value in ``VAULTSPEC_ZAI_PROOF_MODEL``.  The
catalog is the authority for that value: no static Z.ai tier or Claude alias is
accepted here.  The assertion after the turn reads the ACP adapter's confirmed
``currentValue`` from the production model instance, proving that the selected
value reached the gateway before the prompt was sent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from ...control.config import settings
from ...graph.enums import Provider
from ..acp_chat_model import AcpChatModel
from ..factory import ProviderFactory
from ..provider_catalog import AuthenticationState, CatalogStatus, ProviderCatalogKey

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .._json_contract import JsonObject


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
async def test_zai_catalog_selection_is_confirmed_by_one_minimal_turn(
    tmp_path: Path,
) -> None:
    """Prove catalog admission plus exact configured-model selection end to end."""
    key = ProviderCatalogKey(
        Provider.ZAI.value, f"zai-claude-agent-acp:{settings.acp_backend}"
    )
    assert settings.zai_auth_token and settings.zai_auth_token.strip(), (
        "Settings did not resolve a Z.ai auth token for the production catalog path"
    )
    discovery = await ProviderFactory().catalog_registration(key, Path.cwd()).discover()

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

    requested = os.environ.get("VAULTSPEC_ZAI_PROOF_MODEL", "").strip()
    assert requested, (
        "set VAULTSPEC_ZAI_PROOF_MODEL to one low-cost value from the current "
        "Z.ai catalog before authorizing this billable proof"
    )
    assert requested in advertised, (
        "VAULTSPEC_ZAI_PROOF_MODEL is not advertised by the current Z.ai catalog"
    )

    model = ProviderFactory().create(
        Provider.ZAI, model=requested, workspace_root=tmp_path
    )
    assert isinstance(model, AcpChatModel)
    assert model.desired_model == requested
    assert model._config.desired_model == requested

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
    assert selected == requested or selected.startswith(f"{requested}["), (
        "Z.ai ACP confirmed a different model than the catalog-selected value: "
        f"requested={requested!r}, selected={selected!r}"
    )
