"""The dashboard's per-role override outranks every configured default.

Capability policy is declared by the team, not by the product personas, and the
served catalog supplies the concrete model. That leaves one question this module
exists to answer: when an operator picks a different model for ONE role in the
dashboard, does that choice actually reach the run, or is it validated and then
quietly dropped in favour of the configured default?

Schema coverage cannot answer it. `overrides` is a well-typed field with its own
validation tests, and every one of them would still pass if nothing downstream
ever read it. So these drive the real run-start verb and read the FROZEN
assignment the run will actually execute with.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from .conftest import catalog_run_fields, make_app


def _catalog_entries(client: TestClient, workspace_root: str) -> tuple[str, list[Any]]:
    """Return a selectable lane's revision and its available model entries."""
    response = client.get(
        "/v1/provider-catalog", params={"workspace_root": workspace_root}
    )
    assert response.status_code == 200, response.text
    record = next(
        item
        for item in response.json()["providers"]
        if item["health"]["selectable"] and len(item["catalog"]["models"]) > 1
    )
    return record["catalog"]["state"]["revision"], record["catalog"]["models"]


def _frozen_assignment(client: TestClient, run_id: str) -> dict[str, Any]:
    """Read back the assignment the run was frozen with."""
    response = client.get(f"/v1/runs/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    frozen = body.get("frozen_assignment") or body.get("assignments") or {}
    assert frozen, f"run-status disclosed no frozen selection: {sorted(body)}"
    return frozen


class TestRoleOverrideAuthority:
    """A per-role override must beat the team's configured default."""

    def test_an_override_changes_the_entry_that_role_runs(
        self, session_factory: Any, checkpointer: Any
    ) -> None:
        """One role is redirected to a different catalog entry; the rest are not.

        The override names a DIFFERENT entry than the run-wide selection, so a
        run that ignored overrides and a run that honoured them disagree about
        this role and agree about every other. That difference is the assertion:
        it cannot pass if the override is dropped, and it cannot pass by
        accident, because the two entries are read from the same served catalog
        rather than invented here.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            fields = catalog_run_fields(client)
            metadata = dict(fields["metadata"])
            workspace_root = metadata["workspace_root"]
            revision, entries = _catalog_entries(client, workspace_root)

            baseline = dict(fields["selection"])
            baseline["catalog_revision"] = revision
            baseline["entry_id"] = entries[0]["entry_id"]

            overridden = dict(baseline)
            overridden["entry_id"] = entries[1]["entry_id"]
            assert overridden["entry_id"] != baseline["entry_id"]

            response = client.post(
                "/v1/runs",
                json={
                    "team_preset": "mock-success-single",
                    "run_id": "role-override-authority-01",
                    "message": "override one role",
                    "metadata": metadata,
                    "selection": baseline,
                    "overrides": {"mock-coder-success": overridden},
                },
            )
            assert response.status_code == 201, response.text

            frozen = _frozen_assignment(client, "role-override-authority-01")

        rendered = repr(frozen)
        assert overridden["entry_id"] in rendered, (
            "the overridden entry never reached the frozen assignment - the "
            "override was validated and then dropped"
        )

    def test_an_override_naming_an_unserved_entry_is_refused(
        self, session_factory: Any, checkpointer: Any
    ) -> None:
        """An override is revalidated, not trusted.

        The override channel is operator input arriving over the network, so it
        gets the same treatment as the run-wide selection: checked against the
        catalog actually served for this workspace. Accepting an unserved entry
        here would let a stale dashboard pin a role to a model the gateway does
        not offer, which is the failure the explicit-selection contract exists
        to prevent.
        """
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            fields = catalog_run_fields(client)
            metadata = dict(fields["metadata"])
            bogus = dict(fields["selection"])
            bogus["entry_id"] = "entry-that-no-catalog-serves"

            response = client.post(
                "/v1/runs",
                json={
                    "team_preset": "mock-success-single",
                    "run_id": "role-override-authority-02",
                    "message": "override with an unserved entry",
                    "metadata": metadata,
                    "selection": fields["selection"],
                    "overrides": {"mock-coder-success": bogus},
                },
            )

        assert response.status_code >= 400, (
            "an override naming an unserved entry was accepted; the override "
            "channel is not being revalidated against the served catalog"
        )
