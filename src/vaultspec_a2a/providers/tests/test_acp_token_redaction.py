"""Provider auth tokens must never surface via repr/str/model_dump.

Pins the multi-provider-execution env_vars redaction audit: env_vars carries
CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_AUTH_TOKEN, and neither the Pydantic model's
repr/str/serialization nor the frozen _AcpModelConfig snapshot's dataclass repr
may render the token value. Real objects, a token-shaped (synthetic) value.
"""

from .._acp_types import _AcpModelConfig
from ..acp_chat_model import AcpChatModel

# Token-shaped probe; clearly synthetic, never a real credential.
_TOKEN = "sk-ant-oat01-REDACTIONPROBE0000deadbeefcafe0123"


def _model() -> AcpChatModel:
    return AcpChatModel(
        command=["node", "acp.js"],
        env_vars={"ANTHROPIC_AUTH_TOKEN": _TOKEN, "CLAUDE_CODE_OAUTH_TOKEN": _TOKEN},
    )


def _config() -> _AcpModelConfig:
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=None,
        cwd=None,
        command=["node", "acp.js"],
        env_vars={"ANTHROPIC_AUTH_TOKEN": _TOKEN},
        session_id=None,
        mcp_servers=[],
        use_exec=False,
        provider="zai",
        runtime_authority=None,
        acp_backend=None,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode="zai_auth_token",
    )


def test_token_absent_from_model_repr_and_str() -> None:
    """AcpChatModel repr/str must not render the injected token."""
    model = _model()
    assert _TOKEN not in repr(model)
    assert _TOKEN not in str(model)


def test_token_absent_from_model_dump_json() -> None:
    """The token must not survive Pydantic serialization of the model."""
    model = _model()
    assert _TOKEN not in model.model_dump_json()


def test_token_absent_from_config_repr() -> None:
    """The frozen _AcpModelConfig snapshot's dataclass repr must redact the token."""
    assert _TOKEN not in repr(_config())


def test_env_vars_still_accessible_despite_redacted_repr() -> None:
    """Redaction is repr/serialization-only; the value stays usable at runtime."""
    model = _model()
    assert model.env_vars["ANTHROPIC_AUTH_TOKEN"] == _TOKEN
