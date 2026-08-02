"""Middleware test configuration and real ACP context fixture for providers/tests/."""

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from .._acp_types import AcpSessionContext

_PACKAGE_DIR = str(Path(__file__).resolve().parent)

# Files that spawn a real ACP subprocess / network I/O declare their own
# ``service`` marker and must NOT receive the pure ``unit``/``middleware`` marks.
_LIVE_FILES = frozenset(
    {
        "test_acp_authoring_bridge.py",
        "test_acp_project_mcp_service.py",
        "test_codex_config_home_service.py",
        "test_authoring_stdio_bridge.py",
        "test_acp_migration_surface.py",
        "test_acp_catalog_live.py",
        "test_kimi_handshake_live.py",
        "test_provider_containment.py",
        "test_terminal_containment.py",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure provider tests as ``middleware`` + ``unit``.

    These tests exercise pure provider logic — command classification, auth-env
    construction, exception mapping, path-security validation — with no real
    subprocess spawn or network I/O, so they carry the orthogonal ``unit`` marker.
    Live subprocess files are left to their own ``service`` marker.
    """
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _LIVE_FILES:
            continue
        item.add_marker(pytest.mark.middleware)
        item.add_marker(pytest.mark.unit)


@pytest_asyncio.fixture
async def acp_session_context() -> AsyncIterator[AcpSessionContext]:
    """Yield a production context wrapped around genuine subprocess streams.

    Permission, filesystem, and terminal handler tests intentionally call the
    production handlers directly.  This fixture makes their otherwise-idle
    context equally real: an actual Python child owns the exact asyncio stream
    reader/writer pair production receives from an ACP child process.
    """
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
    context = AcpSessionContext(
        process=process,
        stdin=process.stdin,
        stdout=process.stdout,
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )
    try:
        yield context
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()
