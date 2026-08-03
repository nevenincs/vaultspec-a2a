"""Certify authenticated terminal settlement against a real armed desktop gateway.

A test-hosted dashboard settlement receiver - a real HTTP server in the test
process modelling the dashboard's endpoint - captures the callbacks a real armed
desktop gateway emits when a run reaches a durable terminal state. The parent
proves, over real loopback HTTP:

- the gateway settles a completed run by authenticating with the dashboard-created
  attach-control credential and never the private worker interprocess-communication
  secret; the callback body carries only the run and its non-secret lease identity
  plus the terminal status, and no raw actor token;
- delivery is retried: a receiver that transiently rejects the first attempt and
  accepts the second still receives the settlement, and the run's lease is revoked
  exactly once;
- the receiver, applying the dashboard's authentication rule, rejects a callback
  presenting the worker interprocess-communication secret or an unrelated
  credential and accepts only the attach-control credential.

The valid database is seated by the real ``migrate`` entrypoint; the
gateway is a real process and the worker a real gateway-owned one. No mock,
monkeypatch, stub, skip, or expected failure is used; children are reaped in a
``finally``.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from ..desktop.credentials import (
    WORKER_IPC_CREDENTIAL_NAME,
    create_worker_ipc_credential,
)
from ..desktop.profile import derive_state_paths
from ..tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ._catalog import catalog_selection

if TYPE_CHECKING:
    import subprocess

_ATTACH = "attach-credential-settlement-1234567890abcdef"
_OWNERSHIP = "ownership-capability-settlement-fedcba0987654321"
_UNRELATED = "unrelated-credential-000000000000000000"
_PRESET = "mock-success-single"
_REQUIRED_ROLE = "mock-coder-success"
_ACTOR_TOKEN = "tok-coder-secret-value"

# The INFO variant, so the gateway's settlement narration reaches the log.
_GATEWAY = gateway_script(log_level="info")


# ---------------------------------------------------------------------------
# Test-hosted dashboard settlement receiver
# ---------------------------------------------------------------------------


class _ReceiverState:
    """Mutable capture of a real settlement receiver's observations."""

    def __init__(self, attach_secret: str, *, fail_first: bool) -> None:
        self.attach_secret = attach_secret
        self.fail_first = fail_first
        self.lock = threading.Lock()
        self.attempts: list[tuple[str | None, str]] = []  # (auth header, raw body)
        self.accepted: list[dict[str, Any]] = []
        self.revoked_leases: list[str] = []
        self.rejected_auth: list[str | None] = []
        self._attempts_by_run: dict[str, int] = {}


def _make_handler(state: _ReceiverState) -> type[BaseHTTPRequestHandler]:
    """Build a settlement-receiver request handler bound to *state*."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            """Silence the default per-request stderr logging."""
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            auth = self.headers.get("Authorization")
            with state.lock:
                state.attempts.append((auth, raw))
                # The dashboard authenticates settlement with attach-control only.
                if auth != f"Bearer {state.attach_secret}":
                    state.rejected_auth.append(auth)
                    self._respond(401)
                    return
                body = json.loads(raw)
                run_id = str(body.get("run_id", ""))
                seen = state._attempts_by_run.get(run_id, 0) + 1
                state._attempts_by_run[run_id] = seen
                # Transiently reject the first authenticated attempt to force a
                # retry, then accept and revoke exactly that run's lease.
                if state.fail_first and seen == 1:
                    self._respond(503)
                    return
                state.accepted.append(body)
                state.revoked_leases.append(str(body.get("lease_id", "")))
                self._respond(200)

        def _respond(self, code: int) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

    return _Handler


def _start_receiver(
    attach_secret: str, *, fail_first: bool
) -> tuple[ThreadingHTTPServer, int, _ReceiverState]:
    """Start a real threaded settlement receiver; return server, port, and state."""
    state = _ReceiverState(attach_secret, fail_first=fail_first)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], state


# ---------------------------------------------------------------------------
# Real armed gateway harness
# ---------------------------------------------------------------------------


def _prepare_and_commit(base: str, auth: str) -> dict[str, Any]:
    """Prepare then commit one mock run; return the commit response body."""
    run_id = "run-terminal-settlement"
    workspace = str(Path.cwd())
    # Resolved ONCE: prepare and commit describe the same run, so the commit is
    # only recognised as that run's commit while its selection matches.
    selection = catalog_selection(base, auth, workspace)
    run_fields = {
        "metadata": {"workspace_root": workspace},
        "selection": selection,
    }
    with httpx.Client(base_url=base, timeout=60.0) as client:
        prep = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={
                "team_preset": _PRESET,
                "stage": "prepare",
                "run_id": run_id,
                "autonomous": True,
                **run_fields,
            },
        )
        assert prep.status_code == 201, prep.text
        reservation_id = prep.json()["reservation_id"]
        commit = client.post(
            "/v1/runs",
            headers={"Authorization": auth},
            json={
                "team_preset": _PRESET,
                "stage": "commit",
                "reservation_id": reservation_id,
                "run_id": run_id,
                "message": "build it",
                "autonomous": True,
                **run_fields,
                "actor_tokens": {
                    "tokens": {_REQUIRED_ROLE: _ACTOR_TOKEN},
                    "engine_bearer": "bearer",
                },
            },
        )
    assert commit.status_code == 201, commit.text
    return commit.json()


def test_terminal_settlement_authenticates_with_attach_retries_and_revokes_once(
    tmp_path: Path,
) -> None:
    """A completed run settles with attach-control, retries, and revokes one lease."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)

    server, receiver_port, state = _start_receiver(_ATTACH, fail_first=True)

    log_path = tmp_path / "gateway.log"
    auth = f"Bearer {_ATTACH}"
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        return spawn_gateway(
            script=_GATEWAY,
            gateway_port=gateway_port,
            env=armed_gateway_env(
                app_home,
                gateway_port=gateway_port,
                worker_port=worker_port,
                extra={
                    "VAULTSPEC_DESKTOP_SETTLEMENT_URL": (
                        f"http://127.0.0.1:{receiver_port}/settle"
                    )
                },
            ),
            log_handle=log_handle,
        )

    proc, _gateway_port, _worker_port, base = spawn_until_ready(
        _spawn, log_path=log_path
    )
    try:
        commit = _prepare_and_commit(base, auth)
        run_id = commit["run_id"]
        lease_id = commit["lease_id"]

        # The worker-IPC secret the gateway minted at boot: settlement must never
        # authenticate with it, so it is read here to prove the callback does not.
        worker_ipc = (
            (derive_state_paths(app_home).credentials_dir / WORKER_IPC_CREDENTIAL_NAME)
            .read_text(encoding="utf-8")
            .strip()
        )

        # The mock run completes on its own; poll the receiver until it accepts the
        # settlement for this run (retry included).
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            with state.lock:
                accepted = [b for b in state.accepted if b.get("run_id") == run_id]
            if accepted:
                break
            time.sleep(0.5)

        with state.lock:
            accepted = [b for b in state.accepted if b.get("run_id") == run_id]
            attempts = list(state.attempts)
            revoked = list(state.revoked_leases)
        assert accepted, "settlement was never delivered to the dashboard receiver"
        settlement = accepted[0]

        # --- Authenticated with attach-control, never worker IPC. ---
        settle_attempts = [
            (a, raw) for (a, raw) in attempts if json_run_id(raw) == run_id
        ]
        assert settle_attempts, attempts
        for a, _raw in settle_attempts:
            assert a == f"Bearer {_ATTACH}", a
            assert a != f"Bearer {worker_ipc}", a

        # --- Body carries only non-secret identities, no raw actor token. ---
        assert set(settlement) == {
            "api_version",
            "run_id",
            "lease_id",
            "terminal_status",
        }, settlement
        assert settlement["run_id"] == run_id
        assert settlement["lease_id"] == lease_id
        assert settlement["terminal_status"] in {"completed", "cancelled", "failed"}
        for _a, raw in settle_attempts:
            assert _ACTOR_TOKEN not in raw, "settlement must not leak an actor token"

        # --- Retried: at least two attempts, and exactly one lease revoked. ---
        assert len(settle_attempts) >= 2, settle_attempts
        assert revoked.count(lease_id) == 1, revoked
        assert set(revoked) == {lease_id}, revoked
    finally:
        server.shutdown()
        reap_gateway(proc)
        log_handle.close()


def json_run_id(raw: str) -> str | None:
    """Return the ``run_id`` from a settlement body, or ``None`` if unparseable."""
    try:
        return json.loads(raw).get("run_id")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def test_settlement_receiver_rejects_worker_ipc_and_unrelated_credentials(
    tmp_path: Path,
) -> None:
    """The dashboard settlement plane accepts only attach-control, not worker IPC."""
    # Mint a real worker-IPC secret through production code; it must be a distinct
    # value from the attach-control credential and rejected by the settlement plane.
    creds_dir = tmp_path / "creds"
    worker_ipc = create_worker_ipc_credential(creds_dir)
    assert worker_ipc != _ATTACH, "worker IPC and attach must be distinct secrets"

    server, receiver_port, state = _start_receiver(_ATTACH, fail_first=False)
    endpoint = f"http://127.0.0.1:{receiver_port}/settle"
    payload = {
        "api_version": "v1",
        "run_id": "run-xyz",
        "lease_id": "lease-xyz",
        "terminal_status": "completed",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            # Worker-IPC secret: rejected.
            ipc = client.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {worker_ipc}"},
            )
            assert ipc.status_code == 401, ipc.status_code
            # Unrelated credential: rejected.
            other = client.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {_UNRELATED}"},
            )
            assert other.status_code == 401, other.status_code
            # Attach-control credential: accepted.
            ok = client.post(
                endpoint, json=payload, headers={"Authorization": f"Bearer {_ATTACH}"}
            )
            assert ok.status_code == 200, ok.status_code
    finally:
        server.shutdown()

    with state.lock:
        assert state.rejected_auth == [
            f"Bearer {worker_ipc}",
            f"Bearer {_UNRELATED}",
        ], state.rejected_auth
        assert state.revoked_leases == ["lease-xyz"], state.revoked_leases
    # The minted worker-IPC file exists on disk under its own name, separate from
    # the attach plane, confirming the two planes are distinct files and secrets.
    assert (creds_dir / WORKER_IPC_CREDENTIAL_NAME).is_file()
