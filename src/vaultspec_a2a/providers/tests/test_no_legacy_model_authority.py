"""Prove retired provider/model policy has no executable authority."""

from pathlib import Path

import pytest

from ...api.app import create_app
from ...graph import enums
from ...graph.enums import Provider
from ...ipc.schemas import DispatchRequest
from ...team import team_config


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
