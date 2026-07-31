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
stub, skip, or expected failure is used; the child is always torn down in a
``finally``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from ..desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
)
from ..tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

_ATTACH = "attach-credential-token-1234567890abcdef"
_OWNERSHIP = "ownership-capability-token-fedcba0987654321"
_LIFECYCLE_HEADER = "X-Vaultspec-Lifecycle-Capability"


def test_credential_planes_are_isolated_and_secret_free(tmp_path: Path) -> None:
    """The three planes are non-interchangeable and no secret ever leaks."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    credentials_dir = seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)
    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")
    # A real armed desktop gateway booting the *production* lifespan: create_app
    # runs the armed credential loading, and the lifespan validates the seated
    # schema, seats the application state, and publishes the discovery record.
    # The quiet variant keeps the log free of routine INFO chatter, so the
    # secret-absence scan below reads a log carrying only real warnings.
    script = gateway_script(log_level="warning")

    def _spawn(port: int, worker_port: int) -> subprocess.Popen[bytes]:
        return spawn_gateway(
            script=script,
            gateway_port=port,
            env=armed_gateway_env(
                app_home,
                gateway_port=port,
                worker_port=worker_port,
                # The credential planes are the subject; keep the worker cold so
                # no worker process is started behind this test.
                auto_spawn_worker=False,
                extra={"VAULTSPEC_REPAIR_ON_STARTUP": "false"},
            ),
            log_handle=log_handle,
        )

    proc, _port, _worker_port, base = spawn_until_ready(_spawn, log_path=log_path)
    try:
        # The gateway minted the worker IPC secret; read it to scan for its leak.
        worker_ipc = (credentials_dir / "worker-ipc.cred").read_text(encoding="utf-8")
        assert worker_ipc and worker_ipc not in (_ATTACH, _OWNERSHIP)

        with httpx.Client(base_url=base, timeout=5.0) as client:
            # --- Discovery record carries no secret, only the ACL-protected ref ---
            discovery_text = (app_home / "service.json").read_text(encoding="utf-8")
            for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
                assert secret not in discovery_text
            assert ATTACH_CREDENTIAL_NAME in discovery_text  # the reference path

            # --- Unauthenticated liveness discloses nothing ---
            live = client.get("/health")
            assert live.status_code == 200
            for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
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
                    "/v1/service", headers={"Authorization": f"Bearer {_OWNERSHIP}"}
                ).status_code
                == 401
            )
            attach_ok = client.get(
                "/v1/service", headers={"Authorization": f"Bearer {_ATTACH}"}
            )
            assert attach_ok.status_code == 200, attach_ok.text
            for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
                assert secret not in attach_ok.text

            # --- Worker IPC plane: attach is rejected, worker IPC is accepted ---
            assert (
                client.get(
                    "/internal/health",
                    headers={"Authorization": f"Bearer {_ATTACH}"},
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
                "/api/admin/shutdown",
                headers={"Authorization": f"Bearer {_ATTACH}"},
            )
            assert attach_only.status_code == 403
            wrong_cap = client.post(
                "/api/admin/shutdown",
                headers={
                    "Authorization": f"Bearer {_ATTACH}",
                    _LIFECYCLE_HEADER: "not-the-capability",
                },
            )
            assert wrong_cap.status_code == 403

        # --- The process logs never printed a secret ---
        log_handle.flush()
        log_bytes = log_path.read_bytes()
        for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
            assert secret.encode("utf-8") not in log_bytes
    finally:
        # The TREE, not the handle: on Windows the virtual-environment
        # interpreter is a launcher stub, so a terminate() aimed at this handle
        # leaves the real uvicorn gateway alive holding its port and its SQLite
        # handles for the rest of the session.
        reap_gateway(proc)
        log_handle.close()
