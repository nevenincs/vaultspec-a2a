"""Worker HTTP admission rechecks the desktop workspace before scheduling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest
from fastapi.testclient import TestClient

from ...control.state_layout import state_layout
from ...ipc.schemas import DispatchRequest
from ...testing import settings_override
from ...utils import bearer_header
from ..app import create_worker_app

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("action", ["ingest", "resume"])
def test_worker_refuses_desktop_state_before_receipt_or_scheduling(
    tmp_path: Path, action: Literal["ingest", "resume"]
) -> None:
    home = tmp_path / "desktop"
    project = state_layout(home).workspaces_root / "project"
    project.mkdir(parents=True)
    with settings_override(desktop_app_home=home, internal_token="worker-test-token"):
        client = TestClient(create_worker_app())
        for root, expected in ((home, 422), (project, 409)):
            request = DispatchRequest(
                action=action,
                thread_id="saved-run",
                workspace_root=str(root),
                recursion_limit=25,
            )
            response = client.post(
                "/dispatch",
                json=request.model_dump(),
                headers=bearer_header("worker-test-token"),
            )
            assert response.status_code == expected, response.text
            if root == home:
                assert "configured workspace root" in response.json()["detail"]
            else:
                assert response.json()["detail"] == {"condition": "incompatible_state"}
