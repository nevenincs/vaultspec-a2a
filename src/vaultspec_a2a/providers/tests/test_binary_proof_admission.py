"""The served catalog and model factory share one version-bound lane verdict."""

from __future__ import annotations

import os
import shlex
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ...graph.enums import Provider
from ...testing import LaneInventoryFactory, armed_environment, settings_override
from .._catalog_discovery import ProviderCatalogDiscovery
from .._factory_commands import ProviderCommand
from ..acp_chat_model import AcpChatModel
from ..binary_version import probe_binary_version
from ..cli_resolution import (
    ProviderRuntimeUnavailableError,
    ProviderRuntimeUnavailableReason,
)
from ..codex_chat_model import CodexChatModel
from ..factory import (
    ProviderCatalogRegistration,
    ProviderFactory,
    binary_proof_reason,
)
from ..lane_admission import PROVEN_TURN_LANES
from ..provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    HealthState,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
)
from ..provider_catalog_service import ProviderCatalogService

if TYPE_CHECKING:
    from pathlib import Path

_CODEX = ProviderCatalogKey("codex", "codex-app-server")


def _write_launcher(path: Path, version: str, *, marker: Path | None = None) -> None:
    """Write a REAL CLI launcher that reports *version* to ``--version``.

    An optional *marker* lets a test prove whether the launcher's main command
    path (anything other than ``--version``) ever ran.
    """
    if os.name == "nt":
        body = (
            "@echo off\r\n"
            f'if "%1"=="--version" (echo codex-cli {version}& exit /b 0)\r\n'
        )
        if marker is not None:
            body += f'echo spawned>"{marker}"\r\n'
        path.write_text(body, encoding="utf-8")
    else:
        body = (
            "#!/bin/sh\n"
            f'if [ "$1" = "--version" ]; then echo codex-cli {version}; exit 0; fi\n'
        )
        if marker is not None:
            body += f"echo spawned > {shlex.quote(str(marker))}\n"
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)


@pytest.mark.asyncio
async def test_catalog_rechecks_version_beside_cached_models(tmp_path: Path) -> None:
    """A binary update revokes selectability without waiting for catalog TTL."""
    proof = PROVEN_TURN_LANES[Provider.CODEX]
    binary = tmp_path / ("codex.cmd" if os.name == "nt" else "codex")
    _write_launcher(binary, proof.ceiling_exclusive)
    discoveries = 0

    async def discover() -> ProviderCatalogDiscovery:
        nonlocal discoveries
        discoveries += 1
        return ProviderCatalogDiscovery(
            catalog=ProviderCatalog(
                _CODEX,
                CatalogState(CatalogStatus.AVAILABLE, datetime.now(UTC), "rev"),
                (ModelCatalogEntry("entry", "model", "Model"),),
            ),
            authentication=AuthenticationState.AUTHENTICATED,
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
        )

    codex = ProviderCatalogRegistration(
        _CODEX,
        discover,
        lambda: binary_proof_reason(Provider.CODEX, str(binary), "service_path"),
    )
    service = ProviderCatalogService(
        factory=LaneInventoryFactory(lambda _served: (codex,))
    )

    rejected = (await service.records(str(tmp_path)))[0]
    assert rejected.health.admission is AdmissionState.NOT_ADMITTED
    assert rejected.health.selectable is False
    assert ProviderRuntimeUnavailableReason.BINARY_OUT_OF_PROOF_RANGE.value in (
        rejected.health.reasons
    )

    previous = binary.stat()
    _write_launcher(binary, proof.proved_version)
    os.utime(binary, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    admitted = (await service.records(str(tmp_path)))[0]
    assert discoveries == 1
    assert admitted.health.admission is AdmissionState.ADMITTED
    assert admitted.health.selectable is True


def test_factory_refuses_out_of_range_codex_before_model_construction(
    tmp_path: Path,
) -> None:
    """A caller bypassing catalog selection still cannot construct that binary."""
    proof = PROVEN_TURN_LANES[Provider.CODEX]
    binary = tmp_path / ("codex.cmd" if os.name == "nt" else "codex")
    _write_launcher(binary, proof.ceiling_exclusive)

    with (
        armed_environment(PATH=str(tmp_path) + os.pathsep + os.environ["PATH"]),
        pytest.raises(ProviderRuntimeUnavailableError) as caught,
    ):
        ProviderFactory().create(Provider.CODEX, "catalog-model")

    assert (
        caught.value.reason
        is ProviderRuntimeUnavailableReason.BINARY_OUT_OF_PROOF_RANGE
    )


def test_pinned_launcher_requires_exact_proved_version(tmp_path: Path) -> None:
    """A capsule patch change cannot ride a proof earned on another binary."""
    proof = PROVEN_TURN_LANES[Provider.CODEX]
    major, minor, patch = map(int, proof.proved_version.split("."))
    version = f"{major}.{minor}.{patch + 1}"
    launcher = tmp_path / ("codex.cmd" if os.name == "nt" else "codex")
    _write_launcher(launcher, version)

    assert binary_proof_reason(Provider.CODEX, str(launcher), "capsule") is (
        ProviderRuntimeUnavailableReason.BINARY_OUT_OF_PROOF_RANGE
    )


def test_unreadable_version_has_a_typed_blocker(tmp_path: Path) -> None:
    """Probe failure cannot silently admit the lane as unknown."""
    missing = tmp_path / ("codex.cmd" if os.name == "nt" else "codex")
    assert binary_proof_reason(Provider.CODEX, str(missing), "service_path") is (
        ProviderRuntimeUnavailableReason.BINARY_VERSION_UNAVAILABLE
    )


@pytest.mark.parametrize("provider", (Provider.CLAUDE, Provider.ZAI))
def test_withdrawn_turn_proof_refuses_before_any_binary_probe(
    provider: Provider,
) -> None:
    """An absent proof cannot authorize a frozen lane by default."""
    assert binary_proof_reason(provider, "/missing/claude", "service_path") is (
        ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    )


@pytest.mark.asyncio
async def test_claude_model_rechecks_withdrawn_proof_before_child_spawn(
    tmp_path: Path,
) -> None:
    """A model retained in memory cannot spawn after its lane is withdrawn."""
    cli = tmp_path / "claude-cli"
    cli.write_text("selected binary\n", encoding="utf-8")
    marker = tmp_path / "spawned.txt"
    model = AcpChatModel(
        command=[
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
            str(marker),
        ],
        workspace_root=str(tmp_path),
        provider=Provider.CLAUDE.value,
        version_proof_required=True,
    )

    with (
        settings_override(claude_cli_executable=cli, capsule_assets_root=None),
        pytest.raises(ProviderRuntimeUnavailableError) as refusal,
    ):
        await model.ainvoke([HumanMessage(content="hello")])

    assert refusal.value.reason is ProviderRuntimeUnavailableReason.BINARY_PROOF_MISSING
    assert not marker.exists()


@pytest.mark.asyncio
async def test_model_rechecks_changed_launcher_before_child_spawn(
    tmp_path: Path,
) -> None:
    """A constructed model cannot spawn a binary replaced before its turn."""
    launcher = tmp_path / ("codex.cmd" if os.name == "nt" else "codex")
    marker = tmp_path / "spawned.txt"

    proof = PROVEN_TURN_LANES[Provider.CODEX]
    _write_launcher(launcher, proof.proved_version, marker=marker)
    assert probe_binary_version(launcher) == proof.proved_version
    model = CodexChatModel(
        command=[str(launcher), "app-server"],
        provider_command=ProviderCommand(
            argv=(str(launcher), "app-server"),
            runtime_authority="system_cli",
            command_origin="system_path_executable",
            command_kind="codex_cli",
            command_executable=launcher.name,
            command_target=str(launcher),
        ),
        workspace_root=str(tmp_path),
        version_proof_required=True,
    )
    previous = launcher.stat()
    _write_launcher(launcher, proof.ceiling_exclusive, marker=marker)
    os.utime(launcher, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    with pytest.raises(ProviderRuntimeUnavailableError) as caught:
        await model.ainvoke([HumanMessage(content="hello")])
    assert (
        caught.value.reason
        is ProviderRuntimeUnavailableReason.BINARY_OUT_OF_PROOF_RANGE
    )
    assert not marker.exists()
