"""Installed prompt-free proofs for the S06 catalog registration boundary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ..factory import ProviderCatalogRegistration, ProviderFactory
from ..provider_catalog import AuthenticationState, CatalogStatus


def _registration(provider_id: str) -> ProviderCatalogRegistration:
    return next(
        registration
        for registration in ProviderFactory().catalog_registrations(Path.cwd())
        if registration.key.provider_id == provider_id
    )


@pytest.mark.service
@pytest.mark.asyncio
@pytest.mark.parametrize("provider_id", ("claude", "codex", "gemini"))
async def test_installed_registered_lane_enumerates_without_a_prompt(
    provider_id: str,
) -> None:
    if shutil.which(provider_id) is None and provider_id != "claude":
        pytest.fail(f"{provider_id} CLI is not installed")

    discovery = await _registration(provider_id).discover()

    assert discovery.authentication in {
        AuthenticationState.AUTHENTICATED,
        AuthenticationState.NOT_APPLICABLE,
    }
    assert discovery.catalog.state.status is CatalogStatus.AVAILABLE
    assert discovery.catalog.models


_ISOLATED_KIMI_DRIVER = """
import asyncio
import json
from vaultspec_a2a.providers.factory import ProviderFactory

async def main():
    registration = next(
        item for item in ProviderFactory().catalog_registrations()
        if item.key.provider_id == "kimi"
    )
    discovery = await registration.discover()
    print(json.dumps({
        "provider": discovery.catalog.key.provider_id,
        "mode": discovery.catalog.key.execution_mode,
        "authentication": discovery.authentication.value,
        "status": discovery.catalog.state.status.value,
        "models": len(discovery.catalog.models),
        "reason": discovery.catalog.state.reason,
    }))

asyncio.run(main())
"""


@pytest.mark.service
def test_installed_kimi_registration_uses_isolated_persisted_config(
    tmp_path: Path,
) -> None:
    if shutil.which("kimi") is None:
        pytest.fail("Kimi Code CLI is not installed")
    kimi_home = tmp_path / "kimi-home"
    kimi_home.mkdir()
    env = dict(os.environ)
    env["KIMI_CODE_HOME"] = str(kimi_home)
    for name in (
        "KIMI_API_KEY",
        "KIMI_BASE_URL",
        "KIMI_MODEL_API_KEY",
        "KIMI_MODEL_BASE_URL",
        "KIMI_MODEL_NAME",
        "KIMI_MODEL_MAX_CONTEXT_SIZE",
        "KIMI_MODEL_CAPABILITIES",
    ):
        env.pop(name, None)
    completed = subprocess.run(
        [sys.executable, "-c", _ISOLATED_KIMI_DRIVER],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        "provider": "kimi",
        "mode": "kimi-code-acp",
        "authentication": "unknown",
        "status": "unavailable",
        "models": 0,
        "reason": "Kimi CLI has no configured model aliases",
    }
