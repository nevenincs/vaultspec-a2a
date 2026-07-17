"""Real-subprocess proof that the stdio bridge serves from the handed catalog.

No mocks, no engine: the bridge is spawned with a handed catalog snapshot (env)
and an UNREACHABLE engine base URL. If it writes its "serving tools=N" startup
marker, it served ``list_tools`` from the handoff without an engine fetch at spawn
- the cold-start fix that let the bridge's tools reach the model in time
(a2a-edge-conformance S18). A fetch would have had to reach the unreachable engine
and could never serve.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from ....authoring import AgentTool, CatalogSnapshot
from ....authoring.catalog import snapshot_to_catalog_payload
from ..authoring_stdio import (
    ENV_ACTOR_TOKEN,
    ENV_BASE_URL,
    ENV_BEARER,
    ENV_CATALOG_JSON,
    ENV_RUN_ID,
    ENV_SERVER_NAME,
)
from ..authoring_stdio import (
    ENV_DEBUG_MARKER as _ENV_DEBUG_MARKER,
)

if TYPE_CHECKING:
    from pathlib import Path

# An unreachable loopback engine: a spawn-time fetch could never serve against it.
_UNREACHABLE = "http://127.0.0.1:1"
_MODULE = "vaultspec_a2a.protocols.mcp.authoring_stdio"


def _snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=tuple(
            AgentTool(
                name=name,
                description=name,
                input_schema={"type": "object"},
                risk_tier="read_only",
                permission_requirement="auto_permitted",
                idempotency_required=False,
                commands=(name,),
            )
            for name in ("read_context", "search_graph", "propose_changeset")
        ),
    )


def test_bridge_serves_from_handed_catalog_without_engine(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    snapshot = _snapshot()
    # Inherit the real environment so the child interpreter starts, then pin the
    # bridge's own vars (unreachable engine + handed catalog).
    env = {
        **os.environ,
        ENV_BASE_URL: _UNREACHABLE,
        ENV_BEARER: "bogus-bearer",
        ENV_ACTOR_TOKEN: "bogus-actor",
        ENV_RUN_ID: "handoff-run",
        ENV_SERVER_NAME: "vaultspec-authoring",
        ENV_CATALOG_JSON: json.dumps(snapshot_to_catalog_payload(snapshot)),
        _ENV_DEBUG_MARKER: str(marker),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", _MODULE],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30.0
        served = False
        while time.monotonic() < deadline:
            if marker.exists() and "serving tools=" in marker.read_text(
                encoding="utf-8"
            ):
                served = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    text = marker.read_text(encoding="utf-8") if marker.exists() else ""
    assert served, (
        "bridge did not serve from the handed catalog against an unreachable "
        f"engine; marker was {text!r}"
    )
    # It served exactly the handed tool count, proving no engine fetch occurred.
    assert "serving tools=3" in text
