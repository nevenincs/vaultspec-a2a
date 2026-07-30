"""The Codex turn's idle backstop must be the ACP idle knob, not a call budget.

``_consume_turn`` re-arms its wait on every frame, so it bounds the GAP between
frames rather than the turn - the same quantity the other ACP-family providers
bound with ``acp_turn_idle_timeout_seconds`` (default 600s). It used
``self.timeout`` instead, which the factory fills from
``provider_timeout_seconds`` (default 120s, documented as a budget for a single
LLM provider API call) and which also governs this model's startup RPCs. A
Codex turn that was alive but quiet for over 120s - a long tool call, a
thinking gap - was therefore aborted as hung, while the identical workload
completed on Claude, Gemini, Kimi and Z.ai.

Both scenarios drive the real ``_consume_turn`` against a real, deliberately
mute subprocess wrapped in a real ``_CodexAppServerClient``, so the empty
notification queue is the genuine state a silent agent produces rather than a
stand-in for one. The settings object loads once at import, so each scenario
runs in its own process with the env var set - the supported way to configure
it, and the same pattern ``test_acp_turn_deadline.py`` uses.

The two scenarios are inverses of each other, which is what makes them
discriminating: they set the idle knob and the call budget to OPPOSITE
magnitudes. A run that simply honoured whichever value was smaller, or that
ignored the knob entirely, cannot satisfy both.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

# Alive and mute: it never writes a frame and never closes stdout, so the client
# sees neither a notification nor EOF for the whole observation window.
_SILENT_AGENT = "import time; time.sleep(600)"

# Drives the real turn consumer against that agent and reports how it ended.
# "deadline" only when the production wait actually expired; "still_waiting"
# when the turn was still parked when the observation window closed.
_PROBE = textwrap.dedent(
    """
    import asyncio, json, sys

    from vaultspec_a2a.providers.codex_chat_model import (
        CodexChatModel,
        _CodexAppServerClient,
    )

    AGENT_SRC = sys.argv[1]
    CALL_BUDGET = float(sys.argv[2])
    OBSERVE_SECONDS = float(sys.argv[3])


    async def main() -> dict:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            AGENT_SRC,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        client = _CodexAppServerClient(process)
        # `timeout` is what the factory injects from provider_timeout_seconds.
        model = CodexChatModel(command=["echo"], timeout=CALL_BUDGET)

        async def drive() -> str:
            try:
                async for _chunk in model._consume_turn(client, "thread-1"):
                    pass
            except TimeoutError:
                return "deadline"
            return "completed"

        try:
            outcome = await asyncio.wait_for(drive(), timeout=OBSERVE_SECONDS)
        except TimeoutError:
            outcome = "still_waiting"
        finally:
            process.kill()
            await process.wait()
        return {"outcome": outcome}


    print(json.dumps(asyncio.run(main())))
    """
)


def _run_probe(
    *, idle_limit: str, call_budget: float, observe_seconds: float
) -> dict[str, str]:
    """Run one scenario in its own process with the idle knob set in the env."""
    env = os.environ.copy()
    env["VAULTSPEC_ACP_TURN_IDLE_TIMEOUT_SECONDS"] = idle_limit
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROBE,
            _SILENT_AGENT,
            str(call_budget),
            str(observe_seconds),
        ],
        capture_output=True,
        text=True,
        timeout=observe_seconds + 60.0,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"probe failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_silent_turn_is_bounded_by_the_acp_idle_knob() -> None:
    """A short idle knob ends the turn even when the call budget is long.

    Discriminating: the call budget is an order of magnitude longer than the
    observation window, so the pre-fix wait - armed from ``self.timeout`` - was
    still parked when the window closed and reported ``still_waiting``. Only a
    wait armed from ``acp_turn_idle_timeout_seconds`` expires here.
    """
    probe = _run_probe(idle_limit="2", call_budget=120.0, observe_seconds=15.0)

    assert probe["outcome"] == "deadline", (
        "a turn silent past the ACP idle deadline must end; "
        f"the backstop is still armed from the call budget instead: {probe}"
    )


def test_long_idle_knob_outlives_a_short_call_budget() -> None:
    """Inverted control: the call budget must NOT cut a quiet turn short.

    Proves the fix changed which setting governs rather than merely making some
    timeout fire. Here the call budget is shorter than the observation window
    and the idle knob is far longer, so the pre-fix wiring expired at the budget
    and reported ``deadline``. A correctly wired turn is still waiting.
    """
    probe = _run_probe(idle_limit="600", call_budget=2.0, observe_seconds=15.0)

    assert probe["outcome"] == "still_waiting", (
        "a quiet turn inside the ACP idle deadline must survive; "
        f"the single-shot call budget is still cutting it off: {probe}"
    )
