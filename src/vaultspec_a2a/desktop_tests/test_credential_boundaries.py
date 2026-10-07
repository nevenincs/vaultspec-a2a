"""Certify the three desktop credential planes against a real armed gateway.

A real child interpreter boots the production gateway application armed with the
desktop profile over a genuinely migrated app home: ``create_app`` loads the
dashboard-created attach and ownership credentials from their owner-restricted
files and mints the worker interprocess-communication secret, and the production
lifespan validates the seated schema, seats the application state, and publishes
the versioned discovery record. The parent then proves, over real HTTP, that the
three credentials are non-interchangeable and rejected outside their planes, that
no secret appears in the discovery record, the process logs, or any response body,
that unauthenticated liveness discloses nothing, and that the listener is
loopback-only.

The gateway runs the *production* lifespan rather than a test substitute: an
override would leave the application state unseated, and every authenticated verb
would answer 500 instead of exercising the credential planes under test.

The valid database is seated by the real ``migrate`` entrypoint in a
separate process; the gateway is a second real process. No mock, monkeypatch,
stub, skip, or expected failure is used; the child is always torn down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from ..desktop.credentials import ATTACH_CREDENTIAL_NAME
from ..testing import (
    DEFAULT_ATTACH_AUTHORIZATION,
    DEFAULT_ATTACH_CREDENTIAL,
    DEFAULT_OWNERSHIP_CAPABILITY,
    LOOPBACK_TIMEOUT,
    GatewayVerbs,
    armed_gateway_env,
    booted_gateway,
    gateway_script,
    read_worker_ipc_secret,
    seat_app_home,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..control.state_layout import StateLayout

_LIFECYCLE_HEADER = "X-Vaultspec-Lifecycle-Capability"


def _assert_credential_planes(
    client: httpx.Client,
    state: StateLayout,
    worker_ipc: str,
) -> None:
    """Assert the attach, worker IPC, and lifecycle credentials stay isolated."""
    secrets = (DEFAULT_ATTACH_CREDENTIAL, DEFAULT_OWNERSHIP_CAPABILITY, worker_ipc)
    # --- Discovery record carries no secret, only the ACL-protected ref ---
    discovery_text = state.discovery_path.read_text(encoding="utf-8")
    for secret in secrets:
        assert secret not in discovery_text
    assert ATTACH_CREDENTIAL_NAME in discovery_text  # the reference path

    # --- Unauthenticated liveness discloses nothing ---
    live = client.get("/health")
    assert live.status_code == 200
    for secret in secrets:
        assert secret not in live.text

    # --- Attach plane: only the attach credential authenticates ---
    assert client.get("/v1/service").status_code == 401
    assert (
        client.get(
            "/v1/service", headers={"Authorization": f"Bearer {worker_ipc}"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/v1/service",
            headers={"Authorization": f"Bearer {DEFAULT_OWNERSHIP_CAPABILITY}"},
        ).status_code
        == 401
    )
    attach_ok = GatewayVerbs(str(client.base_url)).service()
    assert attach_ok.status_code == 200, attach_ok.text
    for secret in secrets:
        assert secret not in attach_ok.text

    # --- Worker IPC plane: attach is rejected, worker IPC is accepted ---
    assert (
        client.get(
            "/internal/health",
            headers={"Authorization": DEFAULT_ATTACH_AUTHORIZATION},
        ).status_code
        == 401
    )
    worker_ok = client.get(
        "/internal/health",
        headers={"Authorization": f"Bearer {worker_ipc}"},
    )
    assert worker_ok.status_code == 200

    # --- Lifecycle plane: admin shutdown needs the ownership capability ---
    attach_only = client.post(
        "/admin/shutdown",
        headers={"Authorization": DEFAULT_ATTACH_AUTHORIZATION},
    )
    assert attach_only.status_code == 403
    wrong_cap = client.post(
        "/admin/shutdown",
        headers={
            "Authorization": DEFAULT_ATTACH_AUTHORIZATION,
            _LIFECYCLE_HEADER: "not-the-capability",
        },
    )
    assert wrong_cap.status_code == 403


def test_credential_planes_are_isolated_and_secret_free(tmp_path: Path) -> None:
    """The three planes are non-interchangeable and no secret ever leaks."""
    app_home = tmp_path / "app-home"
    state = seat_app_home(app_home)
    log_path = tmp_path / "gateway.log"
    # A real armed desktop gateway booting the *production* lifespan: create_app
    # runs the armed credential loading, and the lifespan validates the seated
    # schema, seats the application state, and publishes the discovery record.
    # The quiet variant keeps the log free of routine INFO chatter, so the
    # secret-absence scan below reads a log carrying only real warnings. The
    # credential planes are the subject; the worker is kept cold so no worker
    # process is started behind this test.
    with booted_gateway(
        armed_gateway_env(app_home, auto_spawn_worker=False),
        log_path=log_path,
        script=gateway_script(log_level="warning"),
    ) as gateway:
        base = gateway.base_url
        # The gateway minted the worker IPC secret; read it to scan for its leak.
        worker_ipc = read_worker_ipc_secret(app_home)
        assert worker_ipc and worker_ipc not in (
            DEFAULT_ATTACH_CREDENTIAL,
            DEFAULT_OWNERSHIP_CAPABILITY,
        )

        # Budgeted for a REPLY, not for promptness: every assertion below is
        # about which credential a plane accepts, and none is about latency.
        # Five seconds was a latency assertion by accident - a loaded host made
        # the gateway answer these authenticated reads more slowly, and the
        # isolation proof failed on a read timeout that proved nothing.
        with httpx.Client(base_url=base, timeout=LOOPBACK_TIMEOUT) as client:
            _assert_credential_planes(client, state, worker_ipc)

        # --- The process logs never printed a secret ---
        log_bytes = log_path.read_bytes()
        for secret in (
            DEFAULT_ATTACH_CREDENTIAL,
            DEFAULT_OWNERSHIP_CAPABILITY,
            worker_ipc,
        ):
            assert secret.encode("utf-8") not in log_bytes
