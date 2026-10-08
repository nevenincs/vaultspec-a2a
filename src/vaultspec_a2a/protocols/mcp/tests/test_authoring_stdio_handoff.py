"""Real-subprocess proof that the stdio bridge serves from the handed catalog.

No mocks, no engine: the bridge is spawned with a handed catalog snapshot (env)
and an UNREACHABLE engine base URL. If it writes its "serving tools=N" startup
marker, it served ``list_tools`` from the handoff without an engine fetch at spawn
- the cold-start fix that let the bridge's tools reach the model in time.
A fetch would have had to reach the unreachable engine
and could never serve.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

from ....authoring import AgentTool, CatalogSnapshot
from ....authoring.catalog import snapshot_to_catalog_payload
from ....testing import (
    LivenessWatch,
    ProgressDeadline,
    inherited_environment,
    wait_until,
)
from ....utils import ProcessContainment, reap_contained, spawn_contained
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
    env = inherited_environment(
        {
            ENV_BASE_URL: _UNREACHABLE,
            ENV_BEARER: "bogus-bearer",
            ENV_ACTOR_TOKEN: "bogus-actor",
            ENV_RUN_ID: "handoff-run",
            ENV_SERVER_NAME: "vaultspec-authoring",
            ENV_CATALOG_JSON: json.dumps(snapshot_to_catalog_payload(snapshot)),
            _ENV_DEBUG_MARKER: str(marker),
        }
    )
    containment = ProcessContainment.create()
    proc = spawn_contained(
        [sys.executable, "-m", _MODULE],
        containment,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def _marker_text() -> str:
        return marker.read_text(encoding="utf-8") if marker.exists() else ""

    def _bridge_exited() -> str | None:
        if proc.poll() is None:
            return None
        return (
            f"exited with code {proc.returncode} before serving; "
            f"marker was {_marker_text()!r}"
        )

    try:
        wait_until(
            lambda: "serving tools=" in _marker_text(),
            deadline=ProgressDeadline(
                idle_window_s=30.0,
                watches=(LivenessWatch(label="stdio bridge", verdict=_bridge_exited),),
            ),
            interval_s=0.05,
            stalled=lambda: (
                "bridge did not serve from the handed catalog against an "
                f"unreachable engine; marker was {_marker_text()!r}"
            ),
        )
    finally:
        reap_contained(proc, containment)

    # It served exactly the handed tool count, proving no engine fetch occurred.
    assert "serving tools=3" in _marker_text()


def test_the_bridge_is_spawned_through_the_contained_lifecycle() -> None:
    """The stdio bridge is a contained spawn, not a raw, hand-reaped one (PV42).

    A raw ``Popen`` only kills the direct child it names; a descendant the
    bridge spawned would survive its teardown. ``spawn_contained`` seats it
    under the project's one process-tree containment, which
    ``reap_contained`` then fells whole. This reads the test's own compiled
    code for both names rather than asserting on behaviour the unfixed test
    already exhibited identically (the bridge here spawns no descendant of
    its own, so a behavioural probe would pass on either implementation).
    """
    names = test_bridge_serves_from_handed_catalog_without_engine.__code__.co_names
    assert "spawn_contained" in names
    assert "reap_contained" in names
