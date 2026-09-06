"""Prove retired provider/model policy has no executable authority."""

from pathlib import Path

import pytest

from ...api.app import create_app
from ...control.config import settings
from ...graph import enums
from ...graph.enums import Provider
from ...ipc.schemas import DispatchRequest
from ...team import team_config
from ..factory import ProviderFactory
from ..in_process_catalog import served_in_process_lanes
from ..provider_catalog import ProviderCatalogKey


def test_retired_authority_symbols_are_absent() -> None:
    for owner, names in (
        (enums, ("Model", "MODEL_MAP", "PROVIDER_DEFAULT_MODELS")),
        (
            team_config,
            (
                "AgentModelConfig",
                "WorkerOverrideConfig",
                "TeamProfileConfig",
                "TeamProfileRoleConfig",
                "TeamDefaultsConfig",
                "SupervisorConfig",
                "DEFAULT_PROFILE_ID",
            ),
        ),
    ):
        assert not [name for name in names if hasattr(owner, name)]


def test_dispatch_and_public_openapi_expose_no_retired_fields() -> None:
    assert "profile_id" not in DispatchRequest.model_fields
    schema = create_app().openapi()
    serialized = str(schema)
    for retired in (
        "profile_id",
        "default_profile_id",
        "model_profile",
        "ProfileSummary",
    ):
        assert retired not in serialized


def test_bundled_presets_declare_no_provider_or_model_policy() -> None:
    root = Path(team_config.__file__).parent / "presets"
    retired = (
        "[agent.model]",
        "[team.defaults]",
        "[team.supervisor]",
        "[team.profiles",
        "provider_fallback",
    )
    for path in root.rglob("*.toml"):
        text = path.read_text(encoding="utf-8")
        assert not [token for token in retired if token in text], path
        assert not any(
            line.strip().startswith("model") for line in text.splitlines()
        ), path


def test_retired_stored_key_is_only_a_fail_closed_detection_sentinel() -> None:
    source_root = Path(team_config.__file__).parents[1]
    hits = []
    for path in source_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if "model_profile" in path.read_text(encoding="utf-8"):
            hits.append(path.relative_to(source_root).as_posix())
    assert hits == ["control/dispatch.py"]


def test_retired_provider_and_discovery_authorities_are_absent() -> None:
    with pytest.raises(ValueError):
        Provider("gemini")

    source_root = Path(team_config.__file__).parents[1]
    forbidden = (
        "availableModels",
        "additionalSpeedTiers",
        "GEMINI_SESSION_STORE_DECLARATION",
        "_build_gemini_env",
        "_classify_gemini_command",
        "gemini_auth",
        "kimi_legacy",
    )
    hits: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        present = [token for token in forbidden if token in text]
        if present:
            hits[path.relative_to(source_root).as_posix()] = present
    assert hits == {}


def test_supported_provider_and_exact_mode_inventories_are_current_only() -> None:
    """Every constructible provider is owned by one exact current lane."""
    assert tuple(provider.value for provider in Provider) == (
        "antigravity",
        "claude",
        "codex",
        "deterministic",
        "kimi",
        "mock",
        "openai",
        "zai",
        "zhipu",
    )
    factory = ProviderFactory()
    external = tuple(
        registration.key for registration in factory.catalog_registrations(Path.cwd())
    )
    assert external == (
        ProviderCatalogKey("antigravity", "antigravity-cli"),
        ProviderCatalogKey("claude", f"claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("codex", "codex-app-server"),
        ProviderCatalogKey("kimi", "kimi-code-acp"),
        ProviderCatalogKey("openai", "openai-api"),
        ProviderCatalogKey("zai", f"zai-claude-agent-acp:{settings.acp_backend}"),
        ProviderCatalogKey("zhipu", "zhipu-openai-compatible-api"),
    )
    armed = tuple(
        registration.key
        for registration in factory.catalog_registrations(
            Path.cwd(), serve_in_process_lanes=True
        )
    )
    assert armed == external + served_in_process_lanes(
        armed=True, mock_api_base=settings.mock_api_base
    )
    assert all(
        "gemini" not in f"{key.provider_id}/{key.execution_mode}" for key in armed
    )
