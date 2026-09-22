"""Credential-denial contract for provider child environments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..environment import resolve_env_vars

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_service_and_database_credentials_never_reach_provider_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        "VAULTSPEC_A2A_GATEWAY_TOKEN": "gateway-secret",
        "VAULTSPEC_INTERNAL_TOKEN": "internal-secret",
        "VAULTSPEC_DATABASE_URL": "postgresql://service:secret@db/runtime",
        "VAULTSPEC_CHECKPOINT_DATABASE_URL": "postgresql://checkpoint:secret@db/cp",
        "VAULTSPEC_A2A_HOME": "/service/discovery",
        "DATABASE_URL": "postgresql://generic:secret@db/runtime",
        "CHECKPOINT_DATABASE_URL": "postgresql://generic:secret@db/checkpoint",
        "SQLALCHEMY_DATABASE_URI": "postgresql://generic:secret@db/sqlalchemy",
        "PGPASSWORD": "postgres-secret",
        "POSTGRES_PASSWORD": "postgres-secret-2",
        "SERVICE_TOKEN": "service-secret",
        "GATEWAY_TOKEN": "gateway-secret-2",
        "INTERNAL_TOKEN": "internal-secret-2",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    resolved = resolve_env_vars(tmp_path)

    assert not values.keys() & resolved.keys()
    assert not any(secret in resolved.values() for secret in values.values())


def test_intended_lane_auth_survives_base_environment_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "zai-lane-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "claude-lane-token")

    resolved = resolve_env_vars(tmp_path)

    assert resolved["ANTHROPIC_AUTH_TOKEN"] == "zai-lane-token"
    assert resolved["CLAUDE_CODE_OAUTH_TOKEN"] == "claude-lane-token"
