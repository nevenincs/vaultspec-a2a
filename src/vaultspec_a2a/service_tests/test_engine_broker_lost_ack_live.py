"""Cross-repository lost-ack certification over production process boundaries.

This service test boots the production dashboard engine, production A2A gateway,
and gateway-owned production worker. A transparent TCP relay forwards every byte
but deliberately drops the first completed run-start acknowledgement. It models
transport loss only: no response or application behavior is synthesized.

The dashboard is a separate repository, so this proof carries an external
prerequisite. It is reported under the repository's one rule (see the root
conftest): absent ``VAULTSPEC_A2A_ENGINE_SERVE_CMD`` is an honest skip naming the
runbook, exactly like the sibling live suites, and a caller that declares
``--require-prerequisite=dashboard-engine`` gets a failure instead.
"""

from __future__ import annotations

import hashlib
import json
import socket
import socketserver
import sqlite3
import threading
import time
from contextlib import contextmanager, suppress
from http import HTTPStatus
from typing import TYPE_CHECKING, TextIO, TypedDict, Unpack, override

import httpx
import pytest

from ..authoring.tests._engine_peer import private_engine_dir
from ..desktop.profile import derive_state_paths
from ..service_tests._live_desktop_gateway import armed_gateway
from ..testing import (
    LIVE_PROVIDER_PREREQUISITES,
    ProgressDeadline,
    free_port,
    json_object,
    selection_from_served_catalog,
    wait_for,
)
from ..utils import bearer_header
from ..utils.coercion import coerce_nonempty_str, coerce_object_mapping
from ._dashboard_engine import dashboard_engine, provision_workspace

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from pathlib import Path

    from ..providers import JsonObject

_RUN_ID = "run-cross-repo-lost-ack"
_MAX_RELAY_MESSAGE_BYTES = 4 * 1024 * 1024


class _WorkerLogScanOptions(TypedDict):
    """State and bounds carried between worker log scans."""

    offset: int
    pending: str
    observed_tail: str
    dispatch_count: int
    hard_deadline: float


class _LostAckFlowOptions(TypedDict):
    """Resources needed for the HTTP side of the lost-ack proof."""

    app_home: Path
    workspace: Path
    engine_base: str
    gateway_base: str
    auth: str
    relay: _RelayServer
    token: str


def _read_http_request(stream: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = stream.recv(4096)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > 128 * 1024:
            raise AssertionError("relay request head exceeded 128 KiB")
    head, body = bytes(data).split(b"\r\n\r\n", 1)
    content_length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.lower() == b"content-length":
            content_length = int(value.strip())
            break
    if content_length > _MAX_RELAY_MESSAGE_BYTES:
        raise AssertionError("relay request body exceeded 4 MiB")
    while len(body) < content_length:
        chunk = stream.recv(min(64 * 1024, content_length - len(body)))
        if not chunk:
            raise AssertionError("relay client closed before request body completed")
        body += chunk
    return head + b"\r\n\r\n" + body


class _RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, upstream_port: int) -> None:
        self.upstream_port = upstream_port
        self.prepare_posts = 0
        self.commit_posts = 0
        self.dropped_commit_acknowledgements = 0
        self.commit_digests: list[str] = []
        self._actor_token: str | None = None
        self.errors: list[str] = []
        self._lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _RelayHandler)

    def take_actor_token(self) -> str:
        """Return and clear the one credential needed by the mutation proof."""
        with self._lock:
            token = self._actor_token
            self._actor_token = None
        assert token is not None, "relay did not observe the required role token"
        return token


def _actor_token_from_body(parsed_body: Mapping[str, object]) -> str | None:
    actor_tokens = coerce_object_mapping(parsed_body.get("actor_tokens"))
    tokens = (
        coerce_object_mapping(actor_tokens.get("tokens"))
        if actor_tokens is not None
        else None
    )
    token = tokens.get("vaultspec-coder") if tokens is not None else None
    return coerce_nonempty_str(token)


def _record_relay_stage(
    relay: _RelayServer,
    stage: str | None,
    request_body: bytes,
    parsed_body: Mapping[str, object],
) -> bool:
    if stage not in {"prepare", "commit"}:
        return False
    with relay._lock:
        if stage == "prepare":
            relay.prepare_posts += 1
        else:
            relay.commit_posts += 1
            relay.commit_digests.append(hashlib.sha256(request_body).hexdigest())
            if relay._actor_token is None:
                relay._actor_token = _actor_token_from_body(parsed_body)
            if relay.dropped_commit_acknowledgements == 0:
                relay.dropped_commit_acknowledgements = 1
                return True
    return False


class _RelayHandler(socketserver.BaseRequestHandler):
    def _relay_server(self) -> _RelayServer:
        """Narrow the base handler's server at the construction boundary."""
        if not isinstance(self.server, _RelayServer):
            raise TypeError("lost-ack relay handler requires a relay server")
        return self.server

    @override
    def handle(self) -> None:
        relay = self._relay_server()
        try:
            request = _read_http_request(self.request)
            request_line = request.split(b"\r\n", 1)[0]
            is_run_start = request_line == b"POST /v1/runs HTTP/1.1"
            request_body = request.split(b"\r\n\r\n", 1)[1]
            parsed_body: JsonObject = (
                json_object(json.loads(request_body), at="run-start request")
                if is_run_start
                else {}
            )
            stage_value = parsed_body.get("stage")
            stage = stage_value if isinstance(stage_value, str) else None
            drop = _record_relay_stage(relay, stage, request_body, parsed_body)
            with socket.create_connection(
                ("127.0.0.1", relay.upstream_port), timeout=120
            ) as upstream:
                upstream.sendall(request)
                if drop:
                    # Lose the client response while the upstream commit is still
                    # in flight. The engine retries immediately; the gateway's
                    # per-run single-flight must wait for this first request to
                    # durably create the run, then replay it exactly.
                    with suppress(OSError):
                        self.request.shutdown(socket.SHUT_RDWR)
                response = bytearray()
                while True:
                    chunk = upstream.recv(64 * 1024)
                    if not chunk:
                        break
                    response.extend(chunk)
                    if len(response) > _MAX_RELAY_MESSAGE_BYTES:
                        raise AssertionError("relay response exceeded 4 MiB")

            if not drop:
                self.request.sendall(response)
        except Exception as exc:  # surfaced by the owning test after shutdown
            with relay._lock:
                relay.errors.append(repr(exc))


@contextmanager
def _ack_dropping_relay(upstream_base: str) -> Generator[_RelayServer]:
    upstream_port = int(upstream_base.rsplit(":", 1)[1])
    server = _RelayServer(upstream_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "relay thread did not stop"


def _one_durable_a2a_run(app_home: Path) -> None:
    database = derive_state_paths(app_home).database_path
    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM threads WHERE id = ?", (_RUN_ID,)
        ).fetchone()[0]
    assert count == 1


def _one_active_engine_lease_per_required_actor(workspace: Path) -> None:
    database = (
        workspace / ".vault" / "data" / "a2a-run-leases" / "a2a-run-leases.sqlite3"
    )
    with sqlite3.connect(database) as connection:
        leases = connection.execute(
            """
            SELECT run_id, state, gateway_lease_id
            FROM a2a_run_leases
            """,
        ).fetchall()
        tokens = connection.execute(
            """
            SELECT role, actor_id
            FROM a2a_run_lease_tokens
            ORDER BY role
            """
        ).fetchall()
    assert len(leases) == 1
    assert leases[0][:2] == (_RUN_ID, "active")
    assert isinstance(leases[0][2], str) and leases[0][2].startswith("lease-")
    assert tokens == [("vaultspec-coder", "agent:vaultspec-coder")]


def _scan_worker_log(
    log: TextIO,
    **options: Unpack[_WorkerLogScanOptions],
) -> tuple[int, str, str, int, bool]:
    log.seek(options["offset"])
    saw_data = False
    while chunk := log.read(64 * 1024):
        if time.monotonic() >= options["hard_deadline"]:
            raise AssertionError(
                "worker log scan exceeded its hard deadline: "
                f"{options['observed_tail']}"
            )
        saw_data = True
        options["offset"] = log.tell()
        options["observed_tail"] = (options["observed_tail"] + chunk)[-64 * 1024 :]
        complete = (options["pending"] + chunk).splitlines(keepends=True)
        options["pending"] = ""
        if complete and not complete[-1].endswith(("\n", "\r")):
            options["pending"] = complete.pop()
            if len(options["pending"]) > 1024 * 1024:
                raise AssertionError(
                    "worker emitted an unterminated log record over 1 MiB"
                )
        for line in complete:
            if not line.strip():
                continue
            record = json_object(json.loads(line), at="worker log record")
            if (
                record.get("thread_id") == _RUN_ID
                and record.get("action") == "dispatch_accepted"
                and record.get("dispatch_action") == "ingest"
            ):
                options["dispatch_count"] += 1
                if options["dispatch_count"] > 1:
                    raise AssertionError(
                        "worker accepted more than one matching dispatch: "
                        f"{options['observed_tail']}"
                    )
    return (
        options["offset"],
        options["pending"],
        options["observed_tail"],
        options["dispatch_count"],
        saw_data,
    )


def _await_exactly_one_worker_dispatch(app_home: Path) -> None:
    logs_dir = derive_state_paths(app_home).logs_dir
    hard_deadline = time.monotonic() + 20
    quiet_since: float | None = None
    observed_tail = ""
    dispatch_count = 0
    offset = 0
    pending = ""

    def _quiet_after_dispatch() -> int | None:
        nonlocal offset, pending, observed_tail, dispatch_count, quiet_since
        worker_logs = list(logs_dir.glob("worker-autospawn-*.stderr.log"))
        if len(worker_logs) == 1:
            with worker_logs[0].open("r", encoding="utf-8", errors="replace") as log:
                offset, pending, observed_tail, dispatch_count, saw_data = (
                    _scan_worker_log(
                        log,
                        offset=offset,
                        pending=pending,
                        observed_tail=observed_tail,
                        dispatch_count=dispatch_count,
                        hard_deadline=hard_deadline,
                    )
                )
            # The duplicate-free quiet window starts only after the scanner has
            # caught up to EOF; any subsequent log activity restarts it.
            if dispatch_count and saw_data:
                quiet_since = time.monotonic()
        if quiet_since is not None and time.monotonic() - quiet_since >= 2:
            return dispatch_count
        return None

    # The first dispatch must land within the idle window; its arrival is the
    # progress that opens the quiet window the duplicate-free proof needs.
    dispatches = wait_for(
        _quiet_after_dispatch,
        deadline=ProgressDeadline(idle_window_s=10.0),
        fingerprint=lambda: dispatch_count,
        interval_s=0.05,
        stalled=lambda: (
            f"worker dispatches seen: {dispatch_count}; log tail: {observed_tail}"
        ),
    )
    assert dispatches == 1, observed_tail


def _exercise_lost_ack_flow(**options: Unpack[_LostAckFlowOptions]) -> None:
    """Run and assert the HTTP portion of the lost-ack proof."""
    session = httpx.get(
        f"{options['engine_base']}/session",
        headers=bearer_header(options["token"]),
        timeout=10,
    )
    session.raise_for_status()
    scope = session.json()["data"]["active_scope"]
    catalog_response = httpx.post(
        f"{options['engine_base']}/ops/a2a/provider-catalog",
        headers=bearer_header(options["token"]),
        json={"expected_scope": scope},
        timeout=30,
    )
    assert catalog_response.status_code == HTTPStatus.OK, catalog_response.text
    catalog_body = json_object(
        catalog_response.json(), at="engine provider-catalog response"
    )
    catalog_data = json_object(
        catalog_body.get("data"), at="engine provider-catalog response.data"
    )
    selection = selection_from_served_catalog(catalog_data.get("envelope"))
    started = httpx.post(
        f"{options['engine_base']}/ops/a2a/run-start",
        headers=bearer_header(options["token"]),
        json={
            "run_id": _RUN_ID,
            "team_preset": "vaultspec-solo-coder",
            "selection": selection.model_dump(mode="json"),
            "message": "Prove one durable dispatch after a lost ack.",
            "expected_scope": scope,
            "feature_tag": "cross-repo-lost-ack",
        },
        timeout=90,
    )
    assert started.status_code == HTTPStatus.OK, started.text
    payload = started.json()
    assert payload["data"]["envelope"].get("run_id") == _RUN_ID, payload

    direct = httpx.get(
        f"{options['gateway_base']}/v1/runs/{_RUN_ID}",
        headers={"Authorization": options["auth"]},
        timeout=10,
    )
    assert direct.status_code == HTTPStatus.OK, direct.text
    _one_durable_a2a_run(options["app_home"])
    _one_active_engine_lease_per_required_actor(options["workspace"])
    assert options["relay"].prepare_posts == 1
    assert options["relay"].commit_posts == 2
    assert options["relay"].dropped_commit_acknowledgements == 1
    assert not options["relay"].errors, options["relay"].errors

    assert len(options["relay"].commit_digests) == 2
    assert len(set(options["relay"].commit_digests)) == 1
    actor_token = options["relay"].take_actor_token()
    mutation = httpx.post(
        f"{options['engine_base']}/authoring/v1/sessions",
        headers={
            **bearer_header(options["token"]),
            "x-authoring-actor-token": actor_token,
        },
        json={
            "api_version": "v1",
            "command": "create_session",
            "idempotency_key": "idem:cross-repo:role-actor",
            "payload": {
                "scope": "cross-repo-proof",
                "title": "Prepared role actor proof",
            },
        },
        timeout=30,
    )
    assert mutation.status_code == HTTPStatus.OK, mutation.text

    _await_exactly_one_worker_dispatch(options["app_home"])


@pytest.mark.requires_prerequisites(*LIVE_PROVIDER_PREREQUISITES)
def test_production_engine_recovers_lost_run_start_ack_exactly_once(
    tmp_path: Path,
) -> None:
    """One accepted start survives response loss without duplicate dispatch."""
    workspace = tmp_path / "dashboard-workspace"
    provision_workspace(workspace)
    app_home = tmp_path / "app-home"
    engine_port = free_port()
    engine_base = f"http://127.0.0.1:{engine_port}"

    with (
        private_engine_dir() as engine_discovery,
        armed_gateway(
            tmp_path,
            VAULTSPEC_A2A_ENGINE_SERVICE_JSON=str(engine_discovery / "service.json"),
        ) as (
            gateway_base,
            auth,
        ),
        _ack_dropping_relay(gateway_base) as relay,
        # The engine discovers the relay, not the gateway, so every run-start
        # it sends crosses the relay that drops the first acknowledgement.
        dashboard_engine(
            tmp_path,
            workspace=workspace,
            engine_port=engine_port,
            engine_log=tmp_path / "engine.log",
            engine_service_json=engine_discovery / "service.json",
            a2a_port=int(relay.server_address[1]),
        ) as token,
    ):
        _exercise_lost_ack_flow(
            app_home=app_home,
            workspace=workspace,
            engine_base=engine_base,
            gateway_base=gateway_base,
            auth=auth,
            relay=relay,
            token=token,
        )
