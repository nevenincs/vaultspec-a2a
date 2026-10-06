"""Credential-denial contract for provider child environments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..environment import resolve_env_vars, scrub_agent_environment

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_service_and_database_credentials_never_reach_provider_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        "VAULTSPEC_A2A_GATEWAY_TOKEN": "gateway-secret",
        "VAULTSPEC_A2A_INTERNAL_TOKEN": "internal-secret",
        "VAULTSPEC_A2A_DATABASE_URL": "postgresql://service:secret@db/runtime",
        "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL": "postgresql://checkpoint:secret@db/cp",
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


def test_claude_oauth_is_removed_before_lane_selection() -> None:
    resolved = scrub_agent_environment(
        {
            "CLAUDE_CODE_OAUTH_TOKEN": "claude-lane-token",
            "claude_code_oauth_token": "lowercase-token",
            "PATH": "runtime-path",
        }
    )
    assert resolved == {"PATH": "runtime-path"}
