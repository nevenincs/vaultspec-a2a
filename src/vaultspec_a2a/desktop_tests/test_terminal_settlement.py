"""Certify desktop settlement of a real completed broker run.

A test-hosted dashboard settlement receiver - a real HTTP server in the test
process modelling the dashboard's endpoint - captures the production settlement
handler's callback from a durable terminal run. The parent
proves, over real loopback HTTP:

- the gateway settles a completed run by authenticating with the dashboard-created
  attach-control credential and never the private worker interprocess-communication
  secret; the callback body carries only the run and its non-secret lease identity
  plus the terminal status, and no raw actor token;
- delivery is retried: a receiver that transiently rejects the first attempt and
  accepts the second still receives the settlement, and the run's lease is revoked
  exactly once.

The valid database is seated by the real ``migrate`` entrypoint; the
broker gateway is a real process and the worker a real gateway-owned one. The
desktop settlement handler reads that run's real database under desktop settings;
this exercises settlement below the currently refused desktop run admission. No mock,
monkeypatch, stub, skip, or expected failure is used; children are reaped when
each test ends.
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..control.event_handlers import (
    RelayServices,
    _handle_terminal_event,
    _settlement_tasks,
)
from ..database import get_thread
from ..desktop.profile import derive_state_paths
from ..testing import (
    DEFAULT_ATTACH_AUTHORIZATION,
    DEFAULT_ATTACH_CREDENTIAL,
    DEFAULT_REQUIRED_ROLE,
    JsonReplyHandler,
    ProgressDeadline,
    armed_desktop_app_home,
    booted_gateway,
    broker_gateway_env,
    gateway_run_verbs,
    gateway_script,
    read_worker_ipc_secret,
    seat_app_home,
    serve_handler,
    wait_for_run_status_async,
    wait_until,
)
from ..thread.enums import TERMINAL_STATUS_VALUES, ThreadStatus
from ..utils import bearer_matches

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_ACTOR_TOKEN = "tok-coder-secret-value"


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
        self._attempts_by_run: dict[str, int] = {}


@dataclass(frozen=True, slots=True)
class _SettlementHarness:
    """The seated home and the settlement receiver the armed gateway reports to."""

    app_home: Path
    receiver_port: int
    state: _ReceiverState


def _make_handler(state: _ReceiverState) -> type[BaseHTTPRequestHandler]:
    """Build a settlement-receiver request handler bound to *state*."""

    class _Handler(JsonReplyHandler, BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            auth = self.headers.get("Authorization")
            with state.lock:
                state.attempts.append((auth, raw))
                # The dashboard authenticates settlement with attach-control only.
                if not bearer_matches(auth, state.attach_secret):
                    self._reply(401, {})
                    return
                body = json.loads(raw)
                run_id = str(body.get("run_id", ""))
                seen = state._attempts_by_run.get(run_id, 0) + 1
                state._attempts_by_run[run_id] = seen
                # Transiently reject the first authenticated attempt to force a
                # retry, then accept and revoke exactly that run's lease.
                if state.fail_first and seen == 1:
                    self._reply(503, {})
                    return
                state.accepted.append(body)
                state.revoked_leases.append(str(body.get("lease_id", "")))
                self._reply(200, {})

    return _Handler


@contextmanager
def _receiver(
    attach_secret: str, *, fail_first: bool
) -> Generator[tuple[int, _ReceiverState]]:
    """Run a real threaded settlement receiver; yield its port and state."""
    state = _ReceiverState(attach_secret, fail_first=fail_first)
    with serve_handler(_make_handler(state)) as port:
        yield port, state


def _assert_settlement_state(
    state: _ReceiverState,
    run_id: str,
    lease_id: str,
    worker_ipc: str,
) -> None:
    # The deterministic run completes on its own; poll the receiver until it accepts the
    # settlement for this run (retry included).
    def _accepted() -> bool:
        with state.lock:
            return any(b.get("run_id") == run_id for b in state.accepted)

    wait_until(
        _accepted,
        deadline=ProgressDeadline(idle_window_s=60.0),
        interval_s=0.5,
        stalled=lambda: "settlement was never delivered to the dashboard receiver",
    )

    with state.lock:
        accepted = [b for b in state.accepted if b.get("run_id") == run_id]
        attempts = list(state.attempts)
        revoked = list(state.revoked_leases)
    settlement = accepted[0]

    # --- Authenticated with attach-control, never worker IPC. ---
    settle_attempts = [
        (auth, raw) for auth, raw in attempts if json_run_id(raw) == run_id
    ]
    assert settle_attempts, attempts
    for auth, _raw in settle_attempts:
        assert auth == DEFAULT_ATTACH_AUTHORIZATION, auth
        assert not bearer_matches(auth, worker_ipc), auth

    # --- Body carries only non-secret identities, no raw actor token. ---
    assert set(settlement) == {
        "api_version",
        "run_id",
        "lease_id",
        "terminal_status",
    }, settlement
    assert settlement["run_id"] == run_id
    assert settlement["lease_id"] == lease_id
    assert settlement["terminal_status"] in TERMINAL_STATUS_VALUES
    for _auth, raw in settle_attempts:
        assert _ACTOR_TOKEN not in raw, "settlement must not leak an actor token"

    # --- Retried: at least two attempts, and exactly one lease revoked. ---
    assert len(settle_attempts) >= 2, settle_attempts
    assert revoked.count(lease_id) == 1, revoked
    assert set(revoked) == {lease_id}, revoked


def _assert_terminal_settlement(harness: _SettlementHarness, base_url: str) -> None:
    commit = _prepare_and_commit(base_url)
    run_id = commit["run_id"]
    lease_id = commit["lease_id"]
    with armed_desktop_app_home(
        harness.app_home,
        desktop_settlement_url=f"http://127.0.0.1:{harness.receiver_port}/settle",
    ):
        asyncio.run(_settle_completed_run(harness.app_home, run_id))

    # The worker-IPC secret the gateway minted at boot: settlement must never
    # authenticate with it, so it is read here to prove the callback does not.
    worker_ipc = read_worker_ipc_secret(harness.app_home)
    _assert_settlement_state(harness.state, run_id, lease_id, worker_ipc)


async def _settle_completed_run(app_home: Path, run_id: str) -> None:
    """Settle the actual durable terminal using the production callback handler."""
    database_path = derive_state_paths(app_home).database_path
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    factory = async_sessionmaker(engine)

    async def _read_status() -> dict[str, str]:
        async with factory() as db:
            thread = await get_thread(db, run_id)
        assert thread is not None
        return {"status": thread.status}

    try:
        terminal = await wait_for_run_status_async(
            _read_status,
            timeout=60.0,
            interval=0.1,
            label=f"broker run {run_id}",
        )
        assert ThreadStatus(terminal["status"]) is ThreadStatus.COMPLETED
        prior_tasks = set(_settlement_tasks)
        async with AsyncSqliteSaver.from_conn_string(
            str(derive_state_paths(app_home).checkpoint_path)
        ) as saver:
            await _handle_terminal_event(
                run_id,
                {"event_type": "thread_terminal", "status": "completed"},
                services=RelayServices(session_factory=factory, checkpointer=saver),
            )
            scheduled = _settlement_tasks - prior_tasks
            assert len(scheduled) == 1, "terminal event must schedule settlement"
            await asyncio.gather(*scheduled)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Real armed gateway harness
# ---------------------------------------------------------------------------


def _prepare_and_commit(base: str) -> dict[str, Any]:
    """Prepare then commit one deterministic run; return the commit response body."""
    run_id = "run-terminal-settlement"
    # The verbs resolve the selection once and cache it: prepare and commit
    # describe the same run, so the commit is only recognised as that run's
    # commit while its selection matches.
    verbs = gateway_run_verbs(base, tokens={DEFAULT_REQUIRED_ROLE: _ACTOR_TOKEN})
    prep = verbs.prepare(run_id)
    assert prep.status_code == 201, prep.text
    commit = verbs.commit(run_id, prep.json()["reservation_id"])
    assert commit.status_code == 201, commit.text
    return commit.json()


def test_terminal_settlement_authenticates_with_attach_retries_and_revokes_once(
    tmp_path: Path,
) -> None:
    """A completed run settles with attach-control, retries, and revokes one lease."""
    app_home = tmp_path / "app-home"
    seat_app_home(app_home)
    # The INFO variant, so the gateway's settlement narration reaches the log.
    with (
        _receiver(DEFAULT_ATTACH_CREDENTIAL, fail_first=True) as (port, state),
        booted_gateway(
            broker_gateway_env(app_home, gateway_token=DEFAULT_ATTACH_CREDENTIAL),
            log_path=tmp_path / "gateway.log",
            script=gateway_script(log_level="info"),
        ) as gateway,
    ):
        _assert_terminal_settlement(
            _SettlementHarness(app_home=app_home, receiver_port=port, state=state),
            gateway.base_url,
        )


def json_run_id(raw: str) -> str | None:
    """Return the ``run_id`` from a settlement body, or ``None`` if unparseable."""
    try:
        return json.loads(raw).get("run_id")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
