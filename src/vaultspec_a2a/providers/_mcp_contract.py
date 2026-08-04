"""Verify a declared harness MCP server actually serves its declared tools.

The harness registry (:mod:`._acp_mcp`) declares, per server, the read-only tools
a run expects it to serve. Those names are load-bearing: they become the
autonomous allowlist (``mcp__<server>__<tool>``) on the ACP lane and the
``enabled_tools`` set on the Codex lane. Until now the declaration was asserted
against nothing - the launch spec pinned an exact package version and trusted
that version to serve them. This module replaces that trust with a check.

Why the contract rather than a version: the harness servers are released
independently of this project, so pinning an exact version stalls every consumer
behind our upgrade cadence and buys only an indirect proxy for the thing we
actually care about - that the tools we are about to advertise exist. The
compatibility boundary is the SERVED TOOL SURFACE, so that is what gets asserted.
There is deliberately no floor version, no compatibility range, and no
"minimum supported" constant here; each of those is the same pin wearing a
different hat.

Why here and not at composition: :func:`._acp_mcp.resolve_harness_mcp_capabilities`
adjudicates a static fact - whether a name is a key of a closed dict - so it can
be free and synchronous. The served surface is a runtime fact learnable only by
launching the server and issuing ``initialize`` + ``tools/list``, and composition
is synchronous and runs per model invocation inside async graph nodes. The check
therefore lands at the two seams where a run COMMITS to launching the declared
set: the ACP spawn (beside the existing isolation refusal) and the Codex
``CODEX_HOME`` emission. Both still refuse before the model ever sees the surface,
which is what the composition-time precedent is actually for.

The probe is a short-lived, separate stdio client, not the run's server: the
run's copy is spawned by the provider CLI as its own child so it inherits that
root's OS containment. Keeping the probe out of :mod:`._acp_mcp` preserves that
module's asserted no-spawn invariant.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import unicodedata
from typing import TYPE_CHECKING, TextIO

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ..thread.errors import HarnessToolContractError
from ._acp_mcp import (
    declared_harness_tools,
    harness_server_exact_surface,
    is_known_harness_server,
)
from ._subprocess import redact_secrets

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ._json_contract import JsonValue

__all__ = [
    "CONTRACT_PROBE_TIMEOUT_SECONDS",
    "verify_declared_tool_contract",
    "verify_harness_mcp_contract",
]

# Generous by design: the first probe of a runtime-acquired server pays that
# server's whole acquisition cost (``uvx`` resolving, downloading, and building
# the environment), which the provider CLI would otherwise pay a moment later out
# of sight. Paying it here makes an unresolvable launch spec a loud refusal
# instead of an agent that silently has no grounding tools.
CONTRACT_PROBE_TIMEOUT_SECONDS = 180.0

# Successful verifications, keyed by launch IDENTITY (command, args, declared
# tools) - deliberately NOT by env. The env carries per-run tokens and paths that
# would defeat the cache entirely, while the served tool surface is a property of
# the command being launched. A failure is never cached: a transient acquisition
# failure must be re-probed on the next run rather than poisoning the process.
_verified: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
_probe_lock = asyncio.Lock()

# Enough of the server's own stderr to explain a refusal (an unresolvable
# requirement, a missing interpreter, a server-side traceback) without dumping an
# unbounded build log into the run's error. This is a hard ceiling on the
# returned tail, elision marker included - a marker added on top of a full-width
# slice would put the result back over the very bound it was applied to satisfy.
_STDERR_TAIL_CHARS = 2000
_STDERR_ELISION = "..."


def _drop_orphaned_combining_marks(text: str) -> str:
    """Drop leading combining marks left without the base they attach to.

    Slicing a tail is safe per character but not per grapheme: cutting between a
    base character and its combining marks strands those marks, and a stranded
    mark does not render as itself - it composes onto whatever now precedes it,
    putting an accent on the elision marker. Dropping them loses one already-cut
    character and keeps the diagnostic readable.
    """
    index = 0
    while index < len(text) and unicodedata.combining(text[index]):
        index += 1
    return text[index:]


def _stderr_tail(captured: TextIO) -> str:
    """Return a trimmed, prefixed, redacted tail of the server's stderr, or ``""``.

    The capture is a real on-disk temporary file rather than an in-memory buffer
    because the stdio client hands the handle straight to the OS as the child's
    stderr, which needs a true file descriptor.

    Redaction happens HERE rather than at the raise sites, because this return
    value is embedded verbatim into a refusal whose message reaches a run's
    client-visible failure reason: masking at the single point the text escapes
    is a property no future caller of the tail can forget to apply. The servers
    reached by this probe include runtime-acquired ones, so what a failing child
    writes about its own configuration is not text this project controls.
    """
    try:
        captured.flush()
        captured.seek(0)
        text = captured.read().strip()
    except (OSError, ValueError):  # pragma: no cover - diagnostics must never mask
        return ""
    if not text:
        return ""
    # Redact BEFORE the cut, in both directions. A cut through a credential
    # discards the name that introduces it and leaves the tail opening on a bare
    # fragment of the value, which nothing downstream can still recognise as one;
    # and the mask is not the same width as what it replaces, so applying it
    # afterwards would move the result off the ceiling enforced just below.
    text = redact_secrets(text)
    if len(text) > _STDERR_TAIL_CHARS:
        kept = text[-(_STDERR_TAIL_CHARS - len(_STDERR_ELISION)) :]
        text = _STDERR_ELISION + _drop_orphaned_combining_marks(kept)
    return f" Server stderr: {text}"


def _launch_description(command: str, args: Sequence[str]) -> str:
    """Return the probed launch command as a single readable string."""
    return " ".join([command, *args])


def _launch_args(spec: Mapping[str, JsonValue], *, name: str) -> list[str]:
    """Read an optional JSON array of string launch arguments or refuse it."""
    value = spec.get("args")
    if value is None:
        return []
    if not isinstance(value, list):
        raise HarnessToolContractError(
            f"harness MCP server {name!r} has non-list launch args to verify"
        )
    args: list[str] = []
    for argument in value:
        if not isinstance(argument, str):
            raise HarnessToolContractError(
                f"harness MCP server {name!r} has non-string launch args to verify"
            )
        args.append(argument)
    return args


async def _served_tool_names(
    *,
    command: str,
    args: Sequence[str],
    env: Mapping[str, str] | None,
    timeout: float,
    captured_stderr: TextIO,
) -> frozenset[str]:
    """Launch the server over stdio and return the tool names it advertises."""
    params = StdioServerParameters(
        command=command,
        args=list(args),
        env=dict(env) if env is not None else None,
    )
    async with asyncio.timeout(timeout):
        async with (
            stdio_client(params, errlog=captured_stderr) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            return frozenset(tool.name for tool in listed.tools)


async def verify_declared_tool_contract(
    *,
    name: str,
    command: str,
    args: Sequence[str],
    declared: Sequence[str],
    exact_surface: bool = False,
    env: Mapping[str, str] | None = None,
    timeout: float = CONTRACT_PROBE_TIMEOUT_SECONDS,
) -> None:
    """Fail loud unless the launched server serves every tool in *declared*.

    Completes a real MCP handshake against the launch spec and compares the
    server's own ``tools/list`` against the names the registry declares for it.
    A server serving MORE than the declared set is not an error - the declaration
    is the run's allowlist, so extra tools are simply never permitted - but a
    server missing any declared tool is refused: the run would advertise and
    auto-permit a tool name the model can never call, which is precisely the
    silent-degradation failure the declaration exists to prevent.

    A probe that cannot complete at all (the requirement will not resolve, the
    command is absent, the handshake fails or times out) is the same refusal:
    an unverifiable contract is an unmet one.

    Verification is memoized per launch identity for the process lifetime, so the
    per-session cost is paid once rather than per run.

    Raises:
        HarnessToolContractError: If a declared tool is not served, or the probe
            could not be completed.
    """
    key = (command, tuple(args), tuple(declared))
    if key in _verified:
        return
    async with _probe_lock:
        if key in _verified:
            return
        launch = _launch_description(command, args)
        # A real on-disk temporary file, text-wrapped: the stdio client hands the
        # handle to the OS as the child's stderr, so it needs a true file
        # descriptor - an in-memory buffer cannot serve as one.
        with io.TextIOWrapper(
            tempfile.TemporaryFile(), encoding="utf-8", errors="replace"
        ) as captured_stderr:
            try:
                served = await _served_tool_names(
                    command=command,
                    args=args,
                    env=env,
                    timeout=timeout,
                    captured_stderr=captured_stderr,
                )
            except Exception as exc:
                # ``asyncio.timeout`` surfaces its deadline as ``TimeoutError``
                # rather than a bare cancellation, so every reachable probe failure
                # - an unresolvable requirement, an absent command, a broken
                # handshake, the deadline - arrives here as one actionable refusal.
                raise HarnessToolContractError(
                    f"harness MCP server {name!r} could not be verified: probing "
                    f"{launch!r} failed ({type(exc).__name__}: {exc}). The run "
                    f"declares the tools {', '.join(declared)} and refuses to "
                    f"launch an agent whose grounding tools cannot be confirmed."
                    f"{_stderr_tail(captured_stderr)}"
                ) from exc

            missing = [tool for tool in declared if tool not in served]
            if missing:
                offered = ", ".join(sorted(served)) if served else "no tools at all"
                raise HarnessToolContractError(
                    f"harness MCP server {name!r} does not serve its declared "
                    f"tool(s): {', '.join(missing)}. Launched as {launch!r}, it "
                    f"served {offered}. Update the declared tool names in the "
                    f"harness registry to match the server, or install a release "
                    f"that serves them."
                    f"{_stderr_tail(captured_stderr)}"
                )

            # Serving MORE than was declared is also a contract break, because for
            # a server whose RESTRICTED LAUNCH is the safety case the extra tools
            # are the unsafe ones. A registry entry that lost its restricting
            # argument would start the full server, still satisfy the check above,
            # and hand the model every verb the restriction existed to withhold -
            # a silently widened surface that reads as a passing verification.
            #
            # Declared-equals-served is the assertion, not declared-subset-of; the
            # strict session surface mounts exactly what a server offers, so what
            # the run may CALL is bounded by the permission layer while what it is
            # HANDED is bounded only here.
            undeclared = (
                [tool for tool in served if tool not in declared]
                if exact_surface
                else []
            )
            if undeclared:
                raise HarnessToolContractError(
                    f"harness MCP server {name!r} serves tool(s) it does not "
                    f"declare: {', '.join(sorted(undeclared))}. Launched as "
                    f"{launch!r}. A server that offers more than the registry "
                    f"declares is refused rather than surfaced: the undeclared "
                    f"tools reach the model's tool list even though the run may "
                    f"not call them. Either the launch lost a restricting "
                    f"argument, or the registry declaration is stale."
                    f"{_stderr_tail(captured_stderr)}"
                )
        _verified.add(key)


async def verify_harness_mcp_contract(
    mcp_servers: Sequence[Mapping[str, JsonValue]],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float = CONTRACT_PROBE_TIMEOUT_SECONDS,
) -> None:
    """Verify every registry-known server among *mcp_servers* against its contract.

    Entries the harness registry does not own - notably the run's own authoring
    bridge, which is composed into the same session list - are skipped: their tool
    surface is the engine's live catalog, verified at its own seam, not a static
    registry declaration.

    *env* should be the environment the servers will actually be launched under,
    so the probe exercises the same resolution the provider CLI will.

    Raises:
        HarnessToolContractError: On the first server that fails its contract.
    """
    for spec in mcp_servers:
        name = spec.get("name")
        if not isinstance(name, str) or not is_known_harness_server(name):
            continue
        command = spec.get("command")
        if not isinstance(command, str) or not command:
            raise HarnessToolContractError(
                f"harness MCP server {name!r} has no launch command to verify"
            )
        await verify_declared_tool_contract(
            name=name,
            command=command,
            args=_launch_args(spec, name=name),
            declared=declared_harness_tools(name),
            exact_surface=harness_server_exact_surface(name),
            env=env,
            timeout=timeout,
        )
