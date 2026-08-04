"""Certify that a real worker drives a run to a terminal state through the model chain.

This closes a specific, named hole rather than adding coverage. The gateway's
own live suite wires an in-process dispatch receiver that appends request bodies
to a list and answers ``{"status": "dispatched"}``; it never executes a graph, so
it proves dispatch TRANSPORT and can never observe dispatch EXECUTION. The
real-process harnesses this test reuses do spawn the production gateway and let it
own its worker, but their scenarios are deliberately provider-independent and hold
whether a run ultimately completes or fails. The consequence is that NO test
required a run to complete through the model chain, which is exactly where a live
model-resolution defect sat: a worker resolving its effective model to a value the
provider layer could not use is a fault upstream of any network call, so no
transport assertion anywhere could see it.

Everything here is real: the production gateway is a real process spawned over a
real migrated application home, the worker is a real process the gateway owns and
spawns, dispatch crosses real loopback HTTP, the graph really executes, the
checkpointer and thread store are real SQLite, and admission, the lease and event
aggregation are the production ones. The requests are shaped by the shared
certification handle, so this file re-derives no request bodies of its own.

The ONE substitution is the model, which is the whole point: determinism comes
from a scripted model reached through the real provider factory, never from
injecting the provider protocol, stubbing the worker, or faking the transport.

The assertion is content equality against that script, because a frame count, a
connection success or a merely non-empty transcript are transport proofs and
cannot evidence execution. The expected text is parsed from the bundled tape that
defines it rather than pasted from an observed run, so a tape edit moves the
expectation with it instead of leaving a stale constant behind.

What turns this test RED, named before it was authored:

- a worker that records a dispatch without executing a graph (the shape charged
  above): no assistant turn is ever produced, so the run never reaches
  ``completed`` carrying the scripted content;
- a break anywhere in the model chain - an unresolvable effective model, a
  provider the factory cannot build, an unreachable scripted backend: the run
  fails or stalls instead of completing, which is the defect class every
  transport assertion was structurally unable to observe;
- a graph that completes but loses the model's output, or emits different
  content: the equality fails even though the run reached a terminal state.

Absence is loud, never silent: the scripted backend is probed over real loopback
and a missing one is a skip naming the substrate and the command that supplies
it, never a pass.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
import yaml

from ..acceptance import DEFAULT_REQUIRED_ROLE, DEFAULT_TEAM_PRESET, certified_gateway
from ..testing.payloads import json_object, json_object_list

if TYPE_CHECKING:
    from ..acceptance import CertifiedGateway
    from ..providers._json_contract import JsonObject

# The scripted backend the mock provider proxies to. The compose service publishes
# it on this loopback port; an environment that already runs one points at it with
# the same variable the production provider reads.
_TAPE_SERVER_DEFAULT = "http://127.0.0.1:8100"
_TAPE_SERVER_ENV = "MOCK_API_BASE"

_SUPPLY_TAPE_SERVER = (
    "docker compose -f service/docker-compose.integration.yml up -d vidaimock"
)

# The bundled tape defining this preset worker's scripted turns - the script this
# test asserts content equality against.
_TAPE_PATH = (
    Path(__file__).resolve().parents[1]
    / "team"
    / "presets"
    / "mock"
    / "tapes"
    / "providers"
    / f"{DEFAULT_REQUIRED_ROLE}.yaml"
)

# The tape branches on conversation length: the opening turn drives a tool call,
# and the branch after this marker is the closing turn whose text the completed
# run must carry.
_TAPE_FINAL_BRANCH_MARKER = "{%- else -%}"
_TAPE_TEXT_BLOCK = re.compile(r'"type":"text","text":"((?:[^"\\]|\\.)*)"')

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "error"})

# The gateway's default budget for its freshly spawned worker to answer is tuned
# for a warm host. A cold interpreter importing the whole worker stack for the
# first time can exceed it on Windows, which fails the boot for a reason that has
# nothing to do with what is under test. Widening a startup budget cannot make a
# worker that never executes a graph produce the scripted content below, so this
# buys tolerance without buying leniency.
_WORKER_READY_BUDGET_SECONDS = "120"


def _scripted_final_text() -> str:
    """Return the closing assistant text the bundled tape scripts for this role.

    Every failure to read the script raises rather than returning a default: an
    empty or missing expectation would turn the content assertion below into one
    that cannot fail, which is the exact failure mode this test exists to end.
    """
    tape = json_object(
        yaml.safe_load(_TAPE_PATH.read_text(encoding="utf-8")), at="scripted tape"
    )
    body = tape.get("response_body")
    if not isinstance(body, str):
        raise AssertionError(f"tape {_TAPE_PATH} carries no response_body string")

    _, marker, final_branch = body.partition(_TAPE_FINAL_BRANCH_MARKER)
    if not marker:
        raise AssertionError(
            f"tape {_TAPE_PATH} no longer branches on {_TAPE_FINAL_BRANCH_MARKER!r}; "
            "the closing turn cannot be identified"
        )

    blocks = _TAPE_TEXT_BLOCK.findall(final_branch)
    if len(blocks) != 1:
        raise AssertionError(
            f"expected exactly one scripted text block in the closing turn of "
            f"{_TAPE_PATH}, found {len(blocks)}"
        )

    text = json.loads(f'"{blocks[0]}"')
    if not text.strip():
        raise AssertionError(f"tape {_TAPE_PATH} scripts an empty closing turn")
    return str(text)


def _tape_server_base() -> str:
    """The scripted backend's base URL, overridable by the production variable."""
    return (os.environ.get(_TAPE_SERVER_ENV) or "").strip() or _TAPE_SERVER_DEFAULT


def _tape_server_listening(base: str) -> bool:
    """Whether something is actually accepting connections at *base*."""
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        return probe.connect_ex((host, port)) == 0


def _await_terminal(
    gateway: CertifiedGateway, run_id: str, *, budget: float
) -> JsonObject:
    """Poll the authoritative status snapshot until the run stops running."""
    deadline = time.monotonic() + budget
    last: JsonObject = {}
    while time.monotonic() < deadline:
        response = gateway.status(run_id)
        if response.status_code == 200:
            last = json_object(response.json(), at="terminal run status")
            if last.get("status") in _TERMINAL_STATUSES:
                return last
        time.sleep(1.0)
    raise AssertionError(
        f"run {run_id} never reached a terminal state within {budget:.0f}s; "
        f"last status snapshot: {last or 'never readable'}"
    )


def test_real_worker_run_reaches_terminal_state_with_scripted_content(
    tmp_path: Path,
) -> None:
    """A gateway-owned worker executes a real graph and completes with the script.

    Drives one run through the production chain and requires COMPLETION, not
    contact: the terminal status must be ``completed`` and the run's assistant
    turn must equal, character for character, the closing text the bundled tape
    scripts for this preset's worker. A recorder that captures the dispatch
    without executing a graph satisfies neither.
    """
    expected_text = _scripted_final_text()

    tape_server = _tape_server_base()
    if not _tape_server_listening(tape_server):
        pytest.skip(
            f"the scripted model backend is unavailable at {tape_server} "
            f"(set {_TAPE_SERVER_ENV} to an existing one, or supply it: "
            f"{_SUPPLY_TAPE_SERVER})"
        )

    run_id = f"runtime-proof-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        **{
            _TAPE_SERVER_ENV: tape_server,
            "VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS": _WORKER_READY_BUDGET_SECONDS,
        },
    ) as gateway:
        started = gateway.start(run_id, message="Complete the task and stop.")
        assert started.status_code == 201, started.text

        snapshot = _await_terminal(gateway, run_id, budget=180.0)
        assert snapshot.get("status") == "completed", snapshot

        history = gateway.thread_state(run_id)
        assert history.status_code == 200, history.text
        history_body = json_object(history.json(), at="thread history")
        state = json_object(history_body.get("state"), at="thread history state")
        messages = json_object_list(state.get("messages"), at="thread history messages")

    # The graph really ran the model: the worker's own turn is present, and its
    # content is exactly what the tape scripts - not merely non-empty.
    worker_turns = [
        message
        for message in messages
        if message.get("role") == "assistant"
        and message.get("agent_id") == DEFAULT_REQUIRED_ROLE
    ]
    assert worker_turns, (
        f"preset {DEFAULT_TEAM_PRESET!r} completed without any assistant turn from "
        f"{DEFAULT_REQUIRED_ROLE!r}; the graph did not execute the model. "
        f"messages={messages}"
    )
    content = worker_turns[-1].get("content")
    assert content == expected_text
