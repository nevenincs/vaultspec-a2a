"""Cross-repository lost-ack certification over production process boundaries.

This service test boots the production dashboard engine, production A2A gateway,
and gateway-owned production worker. A transparent TCP relay forwards every byte
but deliberately drops the first completed run-start acknowledgement. It models
transport loss only: no response or application behavior is synthesized.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager, suppress
from http import HTTPStatus
from importlib.resources import files
from typing import TYPE_CHECKING

import httpx

from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.lifecycle.discovery import write_service_json
from vaultspec_a2a.service_tests._live_desktop_gateway import (
    ATTACH_CREDENTIAL,
    armed_gateway,
)
from vaultspec_a2a.utils.process import ProcessContainment

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_RUN_ID = "run-cross-repo-lost-ack"
_ENGINE_COMMAND_ENV = "VAULTSPEC_ENGINE_SERVE_CMD"
_MAX_RELAY_MESSAGE_BYTES = 4 * 1024 * 1024


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


class _RelayHandler(socketserver.BaseRequestHandler):
    server: _RelayServer

    def handle(self) -> None:
        try:
            request = _read_http_request(self.request)
            request_line = request.split(b"\r\n", 1)[0]
            is_run_start = request_line == b"POST /v1/runs HTTP/1.1"
            request_body = request.split(b"\r\n\r\n", 1)[1]
            parsed_body = json.loads(request_body) if is_run_start else {}
            stage = parsed_body.get("stage")
            drop = False
            if stage in {"prepare", "commit"}:
                with self.server._lock:
                    if stage == "prepare":
                        self.server.prepare_posts += 1
                    else:
                        self.server.commit_posts += 1
                        self.server.commit_digests.append(
                            hashlib.sha256(request_body).hexdigest()
                        )
                        if self.server._actor_token is None:
                            actor_tokens = parsed_body.get("actor_tokens")
                            tokens = (
                                actor_tokens.get("tokens")
                                if isinstance(actor_tokens, dict)
                                else None
                            )
                            token = (
                                tokens.get("vaultspec-coder")
                                if isinstance(tokens, dict)
                                else None
                            )
                            if isinstance(token, str) and token:
                                self.server._actor_token = token
                        if self.server.dropped_commit_acknowledgements == 0:
                            self.server.dropped_commit_acknowledgements = 1
                            drop = True
            with socket.create_connection(
                ("127.0.0.1", self.server.upstream_port), timeout=120
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
            with self.server._lock:
                self.server.errors.append(repr(exc))


@contextmanager
def _ack_dropping_relay(upstream_base: str) -> Iterator[_RelayServer]:
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


def _provision_workspace(workspace: Path) -> None:
    workspace.mkdir()
    core = shutil.which("vaultspec-core")
    assert core is not None, "vaultspec-core executable is required"
    install = subprocess.run(
        [core, "install", "--target", str(workspace)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert install.returncode == 0, install.stderr
    plan = workspace / ".vault" / "plan" / "cross-repo-proof.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "---\ntags:\n  - '#plan'\ndate: '2026-07-20'\n---\n\n# proof\n",
        encoding="utf-8",
    )
    teams = workspace / ".vaultspec" / "teams"
    teams.mkdir(parents=True, exist_ok=True)
    bundled_solo = (
        files("vaultspec_a2a.team.presets.teams")
        .joinpath("vaultspec-solo-coder.toml")
        .read_text(encoding="utf-8")
    )
    (teams / "vaultspec-solo-coder.toml").write_text(
        bundled_solo
        + """

[team.profiles.codex]
display_name = "Codex live certification"
description = "Route the production solo coder through the authenticated Codex lane."

[team.profiles.codex.roles.vaultspec-coder]
provider = "codex"
""",
        encoding="utf-8",
    )
    git = shutil.which("git")
    assert git is not None, "git executable is required"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "cross-repo-proof",
        "GIT_AUTHOR_EMAIL": "proof@vaultspec.test",
        "GIT_COMMITTER_NAME": "cross-repo-proof",
        "GIT_COMMITTER_EMAIL": "proof@vaultspec.test",
    }
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["commit", "-qm", "cross-repo fixture"],
    ):
        result = subprocess.run(
            [git, *args],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr


def _engine_command(port: int, workspace: Path) -> list[str]:
    template = os.environ.get(_ENGINE_COMMAND_ENV, "").strip()
    assert template, (
        f"{_ENGINE_COMMAND_ENV} must name the dashboard serve command when this "
        "cross-repository service test is selected"
    )
    rendered = template.format(port=port, workspace=str(workspace))
    command = shlex.split(rendered, posix=os.name != "nt")
    assert command and os.path.isabs(command[0]), (
        "engine command must use an absolute binary"
    )
    assert os.path.isfile(command[0]), f"engine binary is missing: {command[0]}"
    assert "serve" in command and "--no-seat" in command, (
        "engine command must be a non-seating serve invocation"
    )
    return command


def _wait_for_engine(
    workspace: Path, base_url: str, process: subprocess.Popen[bytes]
) -> str:
    discovery = workspace / ".vault" / "data" / "engine-data" / "service.json"
    deadline = time.monotonic() + 40
    last_error = "not started"
    while time.monotonic() < deadline:
        assert process.poll() is None, "dashboard engine exited during startup"
        try:
            token = json.loads(discovery.read_text(encoding="utf-8"))["service_token"]
            response = httpx.get(
                f"{base_url}/status",
                headers={"Authorization": f"Bearer {token}"},
                timeout=2,
            )
            if response.status_code == HTTPStatus.OK:
                return str(token)
            last_error = response.text
        except (OSError, KeyError, json.JSONDecodeError, httpx.HTTPError) as exc:
            last_error = repr(exc)
        time.sleep(0.1)
    raise AssertionError(f"dashboard engine did not become ready: {last_error}")


def _shutdown_engine(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    base_url: str,
    token: str,
) -> None:
    try:
        response = httpx.post(
            f"{base_url}/shutdown",
            headers={"Authorization": f"Bearer {token}"},
            json={},
            timeout=5,
        )
        assert response.status_code == HTTPStatus.OK, response.text
        process.wait(timeout=15)
    finally:
        _force_engine_tree_exit(process, containment)


def _force_engine_tree_exit(
    process: subprocess.Popen[bytes], containment: ProcessContainment
) -> None:
    """Boundedly terminate the OS-owned engine containment and reap its root."""
    killed = asyncio.run(containment.terminate(term_timeout=5.0, kill_timeout=5.0))
    if process.poll() is None:
        process.wait(timeout=10)
    if not killed:
        raise AssertionError(f"engine process containment {process.pid} did not empty")


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


def _await_exactly_one_worker_dispatch(app_home: Path) -> None:
    first_dispatch_deadline = time.monotonic() + 10
    hard_deadline = time.monotonic() + 20
    quiet_deadline: float | None = None
    observed_tail = ""
    dispatch_count = 0
    offset = 0
    pending = ""
    while time.monotonic() < min(
        hard_deadline, quiet_deadline or first_dispatch_deadline
    ):
        worker_logs = list((app_home / "runtime").glob("worker-autospawn-*.stderr.log"))
        if len(worker_logs) == 1:
            saw_data = False
            with worker_logs[0].open("r", encoding="utf-8", errors="replace") as log:
                log.seek(offset)
                while chunk := log.read(64 * 1024):
                    if time.monotonic() >= hard_deadline:
                        raise AssertionError(
                            "worker log scan exceeded its hard deadline: "
                            f"{observed_tail}"
                        )
                    saw_data = True
                    offset = log.tell()
                    observed_tail = (observed_tail + chunk)[-64 * 1024 :]
                    complete = (pending + chunk).splitlines(keepends=True)
                    pending = ""
                    if complete and not complete[-1].endswith(("\n", "\r")):
                        pending = complete.pop()
                        if len(pending) > 1024 * 1024:
                            raise AssertionError(
                                "worker emitted an unterminated log record over 1 MiB"
                            )
                    for line in complete:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        if (
                            record.get("thread_id") == _RUN_ID
                            and record.get("action") == "dispatch_accepted"
                            and record.get("dispatch_action") == "ingest"
                        ):
                            dispatch_count += 1
                            if dispatch_count > 1:
                                raise AssertionError(
                                    "worker accepted more than one matching dispatch: "
                                    f"{observed_tail}"
                                )
            # The duplicate-free quiet window starts only after the scanner has
            # caught up to EOF; any subsequent log activity restarts it.
            if dispatch_count and saw_data:
                quiet_deadline = time.monotonic() + 2
        time.sleep(0.05)
    assert dispatch_count == 1, observed_tail


def test_production_engine_recovers_lost_run_start_ack_exactly_once(
    tmp_path: Path,
) -> None:
    """One accepted start survives response loss without duplicate dispatch."""
    workspace = tmp_path / "dashboard-workspace"
    _provision_workspace(workspace)
    app_home = tmp_path / "app-home"
    engine_port = _free_port()
    engine_base = f"http://127.0.0.1:{engine_port}"
    engine_log = tmp_path / "engine.log"

    with (
        armed_gateway(
            tmp_path,
            VAULTSPEC_ENGINE_SERVICE_JSON=str(
                workspace / ".vault" / "data" / "engine-data" / "service.json"
            ),
        ) as (
            gateway_base,
            auth,
        ),
        _ack_dropping_relay(gateway_base) as relay,
    ):
        discovery_home = tmp_path / "a2a-discovery"
        write_service_json(
            discovery_home / "service.json",
            port=int(relay.server_address[1]),
            pid=os.getpid(),
            service_token=ATTACH_CREDENTIAL,
        )
        environment = {
            **{
                key: value
                for key, value in os.environ.items()
                if key not in {"VAULTSPEC_APP_HOME", "VAULTSPEC_DESKTOP_APP_HOME"}
            },
            "VAULTSPEC_A2A_HOME": str(discovery_home),
            "VAULTSPEC_APP_HOME": str(tmp_path / "dashboard-product-home"),
        }
        with engine_log.open("wb") as output:
            containment = ProcessContainment.create()
            # Pass the containment's session flag explicitly rather than
            # ``**spawn_kwargs()`` so the binary-stdout Popen resolves to
            # ``Popen[bytes]`` (the sanctioned worker-management spawn pattern);
            # ``start_new_session`` is a no-op on Windows where the flag is unset.
            new_session = bool(containment.spawn_kwargs().get("start_new_session"))
            process: subprocess.Popen[bytes] | None = None
            token: str | None = None
            try:
                process = subprocess.Popen(
                    _engine_command(engine_port, workspace),
                    cwd=workspace,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=new_session,
                )
                containment.assign(process.pid)
                token = _wait_for_engine(workspace, engine_base, process)
                session = httpx.get(
                    f"{engine_base}/session",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                session.raise_for_status()
                scope = session.json()["data"]["active_scope"]
                started = httpx.post(
                    f"{engine_base}/ops/a2a/run-start",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "run_id": _RUN_ID,
                        "team_preset": "vaultspec-solo-coder",
                        "profile_id": "codex",
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
                    f"{gateway_base}/v1/runs/{_RUN_ID}",
                    headers={"Authorization": auth},
                    timeout=10,
                )
                assert direct.status_code == HTTPStatus.OK, direct.text
                _one_durable_a2a_run(app_home)
                _one_active_engine_lease_per_required_actor(workspace)
                assert relay.prepare_posts == 1
                assert relay.commit_posts == 2
                assert relay.dropped_commit_acknowledgements == 1
                assert not relay.errors, relay.errors

                assert len(relay.commit_digests) == 2
                assert len(set(relay.commit_digests)) == 1
                actor_token = relay.take_actor_token()
                mutation = httpx.post(
                    f"{engine_base}/authoring/v1/sessions",
                    headers={
                        "Authorization": f"Bearer {token}",
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

                _await_exactly_one_worker_dispatch(app_home)
            finally:
                if process is None:
                    containment.close()
                elif token is not None:
                    _shutdown_engine(process, containment, engine_base, token)
                else:
                    _force_engine_tree_exit(process, containment)
