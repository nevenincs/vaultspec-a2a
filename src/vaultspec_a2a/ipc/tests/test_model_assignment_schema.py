"""Closed IPC validation for exact catalog-frozen assignments."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from ..schemas import DispatchRequest


def _assignment() -> dict[str, dict[str, Any]]:
    return {
        "coder": {
            "provider": "codex",
            "execution_mode": "codex-app-server",
            "catalog_revision": "rev",
            "entry_id": "entry",
            "model_name": "exact",
            "controls": [
                {
                    "control_id": "reasoning",
                    "option_id": "high",
                    "provider_value": "high",
                }
            ],
            "fallbacks": [
                {
                    "schema_version": 1,
                    "provider_id": "claude",
                    "execution_mode": "claude-agent-acp:node",
                    "catalog_revision": "rev-2",
                    "entry_id": "entry-2",
                    "model_name": "exact-2",
                    "controls": [],
                    "defaulted_control_ids": [],
                }
            ],
            "provenance": {"selection_source": "team_selection"},
            "schema_version": 1,
        }
    }


@pytest.mark.parametrize("location", ("lane", "control", "fallback", "provenance"))
def test_dispatch_rejects_unknown_nested_assignment_fields(location: str) -> None:
    assignment = deepcopy(_assignment())
    lane = assignment["coder"]
    target = {
        "lane": lane,
        "control": lane["controls"][0],
        "fallback": lane["fallbacks"][0],
        "provenance": lane["provenance"],
    }[location]
    target["profile_id"] = "retired"
    with pytest.raises(ValidationError, match="model_assignment"):
        DispatchRequest(
            action="ingest",
            thread_id="thread",
            workspace_root="Y:/code/project",
            recursion_limit=10,
            model_assignment=assignment,
        )


def test_dispatch_accepts_the_exact_closed_assignment() -> None:
    request = DispatchRequest(
        action="ingest",
        thread_id="thread",
        workspace_root="Y:/code/project",
        recursion_limit=10,
        model_assignment=_assignment(),
    )
    assert request.model_assignment["coder"]["model_name"] == "exact"
