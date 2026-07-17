"""Kimi harness composition rides the existing with_mcp_servers ACP branch (P03.S13).

Masking-gap lesson (Codex wiring defect): the wiring claim is proven THROUGH the
real ``compose_harness_mcp_servers`` seam - the exact production call the worker
makes - not by setting ``mcp_servers``/``allowed_tools`` directly on the model.
Because Kimi is an ``AcpChatModel`` variant (it exposes ``with_mcp_servers``), it
must ride the same session-inject branch Claude/Z.ai use, with NO new dispatch and
NO Codex-style config path.
"""

from __future__ import annotations

from .._acp_mcp import compose_harness_mcp_servers, harness_allowed_tool_names
from ..acp_chat_model import AcpChatModel
from ..factory import _build_kimi_env, _classify_kimi_command


def _kimi_model() -> AcpChatModel:
    """A Kimi AcpChatModel as the factory builds it (kimi family, kimi acp)."""
    command, _ = _classify_kimi_command()
    return AcpChatModel(
        command=command,
        env_vars=_build_kimi_env(kimi_api_key="sk-test"),
        acp_family="kimi",
        provider="kimi",
    )


def test_kimi_rides_with_mcp_servers_branch_through_real_compose_seam() -> None:
    model = _kimi_model()
    assert model.mcp_servers == []  # not wired yet
    assert model.allowed_tools == []

    composed = compose_harness_mcp_servers(
        model,
        ["vaultspec-rag"],
        allowed_tools=harness_allowed_tool_names(["vaultspec-rag"]),
    )

    # Rode the ACP with_mcp_servers branch: a same-type copy carrying the declared
    # server in the session surface AND the composed read tools in the allowlist.
    assert isinstance(composed, AcpChatModel)
    assert [s["name"] for s in composed.mcp_servers] == ["vaultspec-rag"]
    assert composed.allowed_tools == [
        "mcp__vaultspec-rag__search_vault",
        "mcp__vaultspec-rag__search_codebase",
        "mcp__vaultspec-rag__get_code_file",
    ]
    # The backend family discriminator survives the model_copy the compose does,
    # so _acp_session still omits the Claude allowedTools _meta for this model.
    assert composed.acp_family == "kimi"


def test_kimi_is_not_dispatched_to_the_codex_config_home_path() -> None:
    # Kimi exposes with_mcp_servers (ACP), NOT with_harness_mcp_servers (Codex),
    # so compose takes the ACP branch. Guards against a future refactor that would
    # mis-route Kimi to the Codex config.toml delivery.
    model = _kimi_model()
    assert hasattr(model, "with_mcp_servers")
    assert not hasattr(model, "with_harness_mcp_servers")
