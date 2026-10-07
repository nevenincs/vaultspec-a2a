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
cannot evidence execution. The expected text is imported from the deterministic
script that defines it rather than pasted from an observed run, so a script edit
moves the expectation with it instead of leaving a stale constant behind.

What turns this test RED, named before it was authored:

- a worker that records a dispatch without executing a graph (the shape charged
  above): no assistant turn is ever produced, so the run never reaches
  ``completed`` carrying the scripted content;
- a break anywhere in the model chain - an unresolvable effective model, a
  provider the factory cannot build, a lane the worker cannot select: the run
  fails or stalls instead of completing, which is the defect class every
  transport assertion was structurally unable to observe;
- a graph that completes but loses the model's output, or emits different
  content: the equality fails even though the run reached a terminal state.

Absence is loud, never silent: a gateway that serves no in-process lane is a
skip naming the missing serving, never a pass.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ..acceptance.tests._harness import certified_gateway
from ..providers.deterministic_chat_model import UNATTENDED_REPLY
from ..team import load_team_config
from ..testing import ok_body, wait_for_run_status
from ..testing.payloads import json_object, json_object_list

if TYPE_CHECKING:
    from pathlib import Path

# The deterministic supervisor-routing team: its supervisor routes the turn to
# its one worker, and that worker's unattended reply is the script this test
# asserts content equality against.
_PRESET = "deterministic-supervisor-routing"

# The gateway's default budget for its freshly spawned worker to answer is tuned
# for a warm host. A cold interpreter importing the whole worker stack for the
# first time can exceed it on Windows, which fails the boot for a reason that has
# nothing to do with what is under test. Widening a startup budget cannot make a
# worker that never executes a graph produce the scripted content below, so this
# buys tolerance without buying leniency.
_WORKER_READY_BUDGET_SECONDS = "120"


def test_real_worker_run_reaches_terminal_state_with_scripted_content(
    tmp_path: Path,
) -> None:
    """A gateway-owned worker executes a real graph and completes with the script.

    Drives one run through the production chain and requires COMPLETION, not
    contact: the terminal status must be ``completed`` and the run's assistant
    turn must equal, character for character, the reply the deterministic script
    gives this preset's worker on an unattended turn. A recorder that captures
    the dispatch without executing a graph satisfies neither.
    """
    role = load_team_config(_PRESET).workers[0].agent_id

    run_id = f"runtime-proof-{uuid.uuid4().hex[:12]}"
    with certified_gateway(
        tmp_path,
        VAULTSPEC_A2A_WORKER_READY_TIMEOUT_SECONDS=_WORKER_READY_BUDGET_SECONDS,
    ) as gateway:
        started = gateway.start(
            run_id,
            team_preset=_PRESET,
            role=role,
            message="Complete the task and stop.",
        )
        assert started.status_code == 201, started.text

        snapshot = wait_for_run_status(
            lambda: ok_body(gateway.status(run_id)),
            timeout=180.0,
            label=f"run {run_id}",
        )
        assert snapshot.get("status") == "completed", snapshot

        history = gateway.thread_state(run_id)
        assert history.status_code == 200, history.text
        history_body = json_object(history.json(), at="thread history")
        state = json_object(history_body.get("state"), at="thread history state")
        messages = json_object_list(state.get("messages"), at="thread history messages")

    # The graph really ran the model: the worker's own turn is present, and its
    # content is exactly what the script gives - not merely non-empty.
    worker_turns = [
        message
        for message in messages
        if message.get("role") == "assistant" and message.get("agent_id") == role
    ]
    assert worker_turns, (
        f"preset {_PRESET!r} completed without any assistant turn from {role!r}; "
        f"the graph did not execute the model. messages={messages}"
    )
    content = worker_turns[-1].get("content")
    assert content == UNATTENDED_REPLY
