"""Middleware test configuration — auto-applies ``middleware`` marker to pure tests.

Tests marked ``live``, ``requires_acp``, ``requires_vidaimock``, or other infra
markers are excluded so they remain gated by their infrastructure requirements.

The ``requires_acp`` fail-fast hook hard-fails (not skips) when the ACP node
module is absent. Run ``npm install`` to install @zed-industries/claude-agent-acp.
"""

from pathlib import Path

import pytest

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
_INFRA_MARKERS = frozenset(
    {
        "live",
        "requires_acp",
        "requires_postgres",
        "requires_jaeger",
        "requires_vidaimock",
    }
)

# Resolved once at collection time — the ACP node entry point.
_ACP_ENTRY = (
    Path(__file__).resolve().parents[3]
    / "node_modules"
    / "@zed-industries"
    / "claude-agent-acp"
    / "dist"
    / "index.js"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure provider tests as ``middleware``, excluding infra-marked tests."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if any(item.get_closest_marker(m) for m in _INFRA_MARKERS):
            continue
        item.add_marker(pytest.mark.middleware)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Fail (not skip) any ``requires_acp`` test when the ACP module is absent."""
    if item.get_closest_marker("requires_acp") and not _ACP_ENTRY.exists():
        pytest.fail(
            f"ACP node module not found at {_ACP_ENTRY}. "
            "Run 'npm install' to install @zed-industries/claude-agent-acp.",
            pytrace=False,
        )
