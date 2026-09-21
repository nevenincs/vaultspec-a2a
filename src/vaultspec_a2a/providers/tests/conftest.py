"""Middleware test configuration and real ACP context fixture for providers/tests/."""

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from ...testing import forfeits_purity
from .._acp_types import AcpSessionContext

_PACKAGE_DIR = str(Path(__file__).resolve().parent)

# Files that spawn a real ACP subprocess / network I/O declare their own
# ``service`` marker and must NOT receive the pure ``unit``/``middleware`` marks.
_LIVE_FILES = frozenset(
    {
        "test_acp_authoring_bridge.py",
        "test_acp_strict_mcp_surface.py",
        "test_codex_config_home_service.py",
        "test_authoring_stdio_bridge.py",
        "test_acp_migration_surface.py",
        "test_acp_catalog_live.py",
        "test_kimi_handshake_live.py",
        "test_provider_containment.py",
        "test_terminal_containment.py",
    }
)


# Files that stay on the middleware layer but really do spawn a child or open a
# real database, so the orthogonal purity claim is withheld. Distinct from
# ``_LIVE_FILES``, which declare their own ``service`` marker and take no layer
# mark at all: these are ordinary middleware tests that are simply not pure.
#
# ``unit`` is a machine-readable claim, so a wrong one is worse than none - a
# selection that excludes impure tests silently includes anything missing here.
_IMPURE_FILES = frozenset(
    {
        # Real child processes.
        "test_acp_mcp.py",
        "test_acp_model_selection.py",
        "test_acp_turn_deadline.py",
        "test_acp_vault_deny.py",
        "test_capsule_acp_resolution.py",
        "test_catalog_registration_live.py",
        "test_codex_config_home.py",
        "test_codex_stderr_drain.py",
        "test_codex_turn_idle_timeout.py",
        "test_model_stack_warmup.py",
        "test_resource_lifetimes.py",
        # Real async engine and session maker.
        "test_deterministic_scripts.py",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark provider tests ``middleware``, and ``unit`` only where actually pure.

    Most tests here exercise pure provider logic — command classification,
    auth-env construction, exception mapping, path-security validation — with no
    real subprocess spawn or network I/O, so they carry the orthogonal ``unit``
    marker. Live subprocess files are left to their own ``service`` marker, and
    files that spawn or open a database keep the layer mark without the purity
    claim.
    """
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _LIVE_FILES:
            continue
        item.add_marker(pytest.mark.middleware)
        if item.path.name not in _IMPURE_FILES and not forfeits_purity(item):
            item.add_marker(pytest.mark.unit)


@dataclass(frozen=True, slots=True)
class _AcpChildStreams:
    """The immutable, module-owned process fields shared by handler tests."""

    process: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader


def _fresh_acp_session_context(child: _AcpChildStreams) -> AcpSessionContext:
    """Seat new mutable ACP state around one otherwise-idle real child."""

    return AcpSessionContext(
        process=child.process,
        stdin=child.stdin,
        stdout=child.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def _acp_child_streams() -> AsyncIterator[_AcpChildStreams]:
    """Own one idle ACP-shaped child on the module fixture event loop."""

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdin.read()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        yield _AcpChildStreams(
            process=process,
            stdin=process.stdin,
            stdout=process.stdout,
        )
    finally:
        process.stdin.close()
        await process.stdin.wait_closed()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()


@pytest_asyncio.fixture
async def acp_session_context(
    _acp_child_streams: _AcpChildStreams,
) -> AsyncIterator[AcpSessionContext]:
    """Yield fresh per-test state over module-owned subprocess streams.

    Permission, filesystem, and terminal handler tests intentionally call the
    production handlers directly. Their otherwise-idle process fields remain
    real, but those fields are never read or written by these consumers, so one
    child can safely serve the module while every mutable session field remains
    function-scoped and loop-local.
    """
    yield _fresh_acp_session_context(_acp_child_streams)
