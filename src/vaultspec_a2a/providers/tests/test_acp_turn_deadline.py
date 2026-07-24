"""A turn against a live-but-silent agent must end, not park forever.

The chunk-queue poll in ``_yield_chunks`` only leaves the loop on a sentinel or
on ``prompt_done``, and both require the subprocess to say something. An agent
that stays alive while going silent - a wedged tool call, a dropped upstream
connection - therefore held the caller indefinitely: the loop just kept
re-arming its 0.1s poll. This drives that exact shape with a real subprocess
that is alive and deliberately mute.

The deadline is read from the real settings object, which loads once at import,
so each scenario runs in its own process with the env var set. That is the
supported way to configure it rather than a reach into module internals.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

# Alive and mute: it never writes a frame and never closes stdout, so the client
# sees neither protocol activity nor EOF. Sleeping well past the observation
# window keeps the "still connected, still silent" condition true throughout.
_SILENT_AGENT = "import time; time.sleep(600)"

# Drives the real model against that agent and reports how the turn ended.
# `outcome` is the whole point of the probe: "deadline" only when the production
# guard raised with its own marker, "still_waiting" when the turn was still
# parked when the observation window closed.
_TURN_PROBE_SCRIPT = textwrap.dedent(
    """
    import asyncio, json, sys
    from typing import cast

    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel
    from vaultspec_a2a.providers.acp_exceptions import AcpPromptError
    from vaultspec_a2a.providers._acp_protocol import process_stdout_loop
    from vaultspec_a2a.providers._acp_types import _AcpSessionContext
    from vaultspec_a2a.providers._subprocess import spawn_acp_process
    from vaultspec_a2a.control.config import settings

    OBSERVE_SECONDS = float(sys.argv[2])


    async def main() -> dict:
        process = await spawn_acp_process(
            [sys.executable, "-c", sys.argv[1]], env={}, cwd=".", use_exec=True
        )
        model = AcpChatModel(command=["echo"], env_vars={})
        ctx = _AcpSessionContext(
            process=process,
            stdin=cast("asyncio.StreamWriter", process.stdin),
            stdout=cast("asyncio.StreamReader", process.stdout),
            response_futures={},
            chunk_queue=asyncio.Queue(),
            prompt_done=asyncio.Event(),
            prompt_id_ref=[0],
            interrupt_exc=[],
        )
        loop_task = asyncio.create_task(process_stdout_loop(ctx, model._config, {}))
        prompt_future = asyncio.get_running_loop().create_future()

        async def drain() -> None:
            async for _chunk in model._yield_chunks(ctx, prompt_future, None):
                pass

        started = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(drain(), timeout=OBSERVE_SECONDS)
            outcome, detail = "completed", None
        except AcpPromptError as exc:
            data = exc.data if isinstance(exc.data, dict) else {}
            outcome, detail = "deadline", data.get("acp_outcome")
        except TimeoutError:
            outcome, detail = "still_waiting", None
        finally:
            elapsed = asyncio.get_running_loop().time() - started
            loop_task.cancel()
            process.kill()
            await process.wait()

        return {
            "outcome": outcome,
            "detail": detail,
            "elapsed": elapsed,
            "configured_idle_limit": settings.acp_turn_idle_timeout_seconds,
        }


    print(json.dumps(asyncio.run(main()), sort_keys=True))
    """
).strip()

_IDLE_LIMIT_SECONDS = 1.5
_OBSERVE_SECONDS = 6.0


def _run_turn_probe(tmp_path: Path, idle_limit: str) -> dict[str, Any]:
    """Run one turn against the silent agent with a given configured deadline."""
    script = tmp_path / "acp_turn_probe.py"
    script.write_text(_TURN_PROBE_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    env["VAULTSPEC_ACP_TURN_IDLE_TIMEOUT_SECONDS"] = idle_limit
    result = subprocess.run(
        [sys.executable, str(script), _SILENT_AGENT, str(_OBSERVE_SECONDS)],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_silent_agent_ends_the_turn_at_the_idle_deadline(tmp_path: Path) -> None:
    """The turn fails with the deadline marker instead of polling forever."""
    report = _run_turn_probe(tmp_path, str(_IDLE_LIMIT_SECONDS))

    assert report["configured_idle_limit"] == _IDLE_LIMIT_SECONDS
    assert report["outcome"] == "deadline"
    assert report["detail"] == "turn_idle_deadline_expired"
    # It waited for the deadline rather than failing straight away, and it did
    # not run to the observation window - so the deadline is what ended it.
    assert _IDLE_LIMIT_SECONDS <= report["elapsed"] < _OBSERVE_SECONDS


def test_the_same_silent_agent_keeps_waiting_when_the_deadline_is_long(
    tmp_path: Path,
) -> None:
    """Control: silence alone does not end a turn.

    Identical agent, identical window, only the configured deadline differs. If
    this also ended the turn, the failure above would prove nothing about the
    deadline - it would just mean a mute subprocess ends turns by itself.
    """
    report = _run_turn_probe(tmp_path, "3600")

    assert report["configured_idle_limit"] == 3600.0
    assert report["outcome"] == "still_waiting"


def test_the_deadline_can_be_disabled(tmp_path: Path) -> None:
    """A non-positive deadline restores the unbounded wait for operators."""
    report = _run_turn_probe(tmp_path, "0")

    assert report["configured_idle_limit"] == 0.0
    assert report["outcome"] == "still_waiting"
