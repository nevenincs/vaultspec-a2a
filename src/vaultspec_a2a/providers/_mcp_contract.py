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
root's OS containment. The probe itself enters the same configured identity
launcher before executing the server. Keeping the probe out of :mod:`._acp_mcp`
preserves that module's asserted no-spawn invariant.

The one exception to "served tool surface only": vaultspec-rag's stdio server is
a thin forwarder over a versioned background daemon it does not control, so its
``tools/list`` answer is a property of the STDIO CLIENT release alone and never
changes with the daemon's. A daemon running a different release, or one old
enough to omit its own version report, fails every real search - but not
``tools/list`` - so admission would otherwise pass a lane already broken end to
end. :func:`verify_declared_tool_contract` calls one real, side-effect-free tool
on the same handshake for that one server and classifies the vaultspec-rag
client's own compatibility verdict, never inventing a signal the protocol does
not carry: a daemon that is merely absent is unaffected, since the run's own
tool-call error already names that plainly.
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO, TypedDict, Unpack

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import TextContent

from ..thread.errors import HarnessToolContractError
from ..utils import redact_text
from ..utils.async_cleanup import complete_cleanup
from ..workspace.environment import scrub_agent_environment
from ._config_home_roots import temp_home_root
from ._harness_mcp_registry import (
    declared_harness_tools,
    harness_server_exact_surface,
    is_known_harness_server,
    registry_launch_divergence,
    withheld_harness_tools,
)
from ._provider_execution import provider_execution_launch

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mcp.types import CallToolResult

    from ..desktop.native_isolation import NativeLaunchAuthority
    from ._json_contract import JsonValue

__all__ = [
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
_verified: set[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], bool]] = (
    set()
)
_probe_lock = asyncio.Lock()


def _probe_environment(env: Mapping[str, str] | None) -> dict[str, str]:
    """Keep run configuration, but never use workspace executable search paths."""
    result = scrub_agent_environment(env if env is not None else os.environ)
    # storage-anchor-ok: launch search inherits the host authority, not workspace env.
    host_path = os.environ.get("PATH", os.defpath)  # storage-anchor-ok
    result["PATH"] = os.pathsep.join(
        directory
        for directory in host_path.split(os.pathsep)
        if os.path.isabs(directory)
    )
    for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        result.pop(key, None)
    result["NoDefaultCurrentDirectoryInExePath"] = "1"
    return result


# Enough of the server's own stderr to explain a refusal (an unresolvable
# requirement, a missing interpreter, a server-side traceback) without dumping an
# unbounded build log into the run's error. This is a hard ceiling on the
# returned tail, elision marker included - a marker added on top of a full-width
# slice would put the result back over the very bound it was applied to satisfy.
_STDERR_TAIL_CHARS = 2000
_STDERR_ELISION = "..."

# vaultspec-rag's own stdio server name and the one read-only, side-effect-free
# tool its client uses to learn whether the background daemon it forwards to is
# even reachable and release-compatible. Keyed by name rather than a new
# registry axis: this is how the CONTRACT is verified, not what the server
# declares, and every other registered server is a fresh process per session
# with no persistent counterpart to drift out of step with.
_RAG_SERVER_NAME = "vaultspec-rag"
_RAG_READINESS_TOOL = "get_index_status"
_READINESS_TOOLS: Mapping[str, str] = {_RAG_SERVER_NAME: _RAG_READINESS_TOOL}

# The stable prefixes of ``vaultspec_rag.serviceclient._compat``'s own
# compatibility verdict codes (``VERSION_ERROR_MISMATCH`` /
# ``VERSION_ERROR_UNREPORTED``), reproduced here because every real tool call
# already raises text carrying one of them once a reachable daemon runs a
# different release or omits its version report - a fact ``tools/list`` cannot
# see, since the stdio client serves the same static names regardless of which
# daemon, if any, answers behind it. Matching the prefix rather than the full
# sentence keeps this independent of the remediation wording, which names live
# version numbers that change every release.
_RAG_VERSION_MISMATCH_PREFIX = "service_version_mismatch:"
_RAG_VERSION_UNREPORTED_PREFIX = "service_version_unreported:"


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
    text = redact_text(text)
    if len(text) > _STDERR_TAIL_CHARS:
        kept = text[-(_STDERR_TAIL_CHARS - len(_STDERR_ELISION)) :]
        text = _STDERR_ELISION + _drop_orphaned_combining_marks(kept)
    return f" Server stderr: {text}"


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


def _result_text(result: CallToolResult) -> str:
    """Return the concatenated text content of one real tool call result."""
    return "".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


@dataclass(frozen=True, slots=True)
class _StdioLaunch:
    """The three facts that decide which server a probe actually launches.

    They travel together everywhere: the identity the memo key is built from,
    the description a refusal quotes, and the parameters handed to the stdio
    client. Carried as one value so a probe cannot be described by one spelling
    of the launch and then performed with another.
    """

    command: str
    args: Sequence[str]
    env: Mapping[str, str] | None = None
    cwd: str | None = None

    def description(self) -> str:
        """Return the probed launch command as a single readable string."""
        return " ".join([self.command, *self.args])

    def parameters(self) -> StdioServerParameters:
        """Return the stdio client parameters for this launch."""
        return StdioServerParameters(
            command=self.command,
            args=list(self.args),
            env=dict(self.env) if self.env is not None else None,
            cwd=self.cwd,
        )


async def _served_tool_names(
    launch: _StdioLaunch,
    *,
    timeout: float,
    captured_stderr: TextIO,
    readiness_tool: str | None,
) -> tuple[frozenset[str], str | None]:
    """Bound the handshake while joining SDK teardown before returning."""
    probe = asyncio.create_task(
        _probe_tool_names(launch, captured_stderr, readiness_tool)
    )
    try:
        async with asyncio.timeout(timeout):
            return await asyncio.shield(probe)
    except BaseException:
        # Native repeated cancellation can interrupt the SDK's AnyIO shield.
        # Cancel once, with the deadline disarmed, then join its cleanup.
        probe.cancel()

        async def join() -> None:
            with suppress(asyncio.CancelledError):
                await probe

        await complete_cleanup(join())
        raise


async def _probe_tool_names(
    launch: _StdioLaunch,
    captured_stderr: TextIO,
    readiness_tool: str | None,
) -> tuple[frozenset[str], str | None]:
    """Launch the server over stdio; return its tools and a readiness failure.

    *readiness_tool*, when given and actually served, is called on this SAME
    handshake rather than a second connection - the launch cost this function's
    caller already pays (``uvx`` resolution included) is paid once whichever way.
    Only a FAILED call's text is returned: a successful call carries nothing
    this module classifies, and an absent readiness tool or one the server does
    not serve leaves the daemon side unobserved rather than refused.
    """
    params = launch.parameters()
    async with (
        stdio_client(params, errlog=captured_stderr) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        served = frozenset(tool.name for tool in listed.tools)
        diagnostic: str | None = None
        if readiness_tool is not None and readiness_tool in served:
            result = await session.call_tool(readiness_tool, {})
            if result.is_error:
                diagnostic = _result_text(result)
        return served, diagnostic


def _rag_incompatibility_reason(diagnostic: str) -> str | None:
    """Classify one real readiness failure as a fail-closed refusal, or not.

    Only the vaultspec-rag client's own compatibility verdict is actionable
    here: a daemon that is merely unreachable, or a failure unrelated to
    release compatibility, describes daemon-side operator state this
    admission check has no business refusing - a daemon started (or upgraded)
    a moment later would put either right without this launch spec, the
    registry, or the run itself changing anything.
    """
    if _RAG_VERSION_MISMATCH_PREFIX in diagnostic:
        return "runs a different vaultspec-rag release than this stdio client"
    if _RAG_VERSION_UNREPORTED_PREFIX in diagnostic:
        return "does not report a vaultspec-rag release this client can confirm"
    return None


def _tool_contract_differences(
    *,
    declared: Sequence[str],
    served: frozenset[str],
    exact_surface: bool,
    withheld: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """Return missing and, when requested, undeclared served tool names.

    A withheld tool is part of the surface the registry expects the server to
    serve, so serving it is not a lost restriction; it is never required,
    because a release that stops serving it only narrows what no run could call.
    """
    missing = [tool for tool in declared if tool not in served]
    expected = {*declared, *withheld}
    undeclared = (
        sorted(tool for tool in served if tool not in expected) if exact_surface else []
    )
    return missing, undeclared


class _VerifyDeclaredToolContractRequired(TypedDict):
    name: str
    command: str
    args: Sequence[str]
    declared: Sequence[str]


class _VerifyDeclaredToolContractOptions(
    _VerifyDeclaredToolContractRequired, total=False
):
    exact_surface: bool
    withheld: Sequence[str]
    env: Mapping[str, str] | None
    timeout: float
    readiness_tool: str | None
    native_authority: NativeLaunchAuthority | None


async def verify_declared_tool_contract(
    **options: Unpack[_VerifyDeclaredToolContractOptions],
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

    *readiness_tool*, when given, names one side-effect-free tool the server
    serves but a run is not permitted to call (it is outside the declared
    ``tools``), called here by this probe and never by a run, and only when
    ``tools/list`` shows it served. It reads the server's own readiness and
    writes nothing, which is what keeps probing past the declared surface in
    bounds. It runs on this same handshake, and its FAILURE text is checked for a
    known compatibility-verdict prefix (currently vaultspec-rag's own
    ``service_version_mismatch:`` / ``service_version_unreported:`` - see the
    module docstring) and refused if found. This exists for the one kind of
    server whose ``tools/list`` answer is the stdio client's own static
    declaration and never reflects a versioned background daemon it forwards to
    - a fact no listing can carry. A daemon that is simply not running, or any
    other failure, is left admitted: that failure names itself plainly the
    moment a real call is attempted, and is not this check's to pre-empt.

    Verification is memoized per launch identity for the process lifetime, so the
    per-session cost is paid once rather than per run.

    Raises:
        HarnessToolContractError: If a declared tool is not served, the probe
            could not be completed, or a reachable daemon reports itself
            incompatible with the launched client.
    """
    name = options["name"]
    command = options["command"]
    args = options["args"]
    declared = options["declared"]
    exact_surface = options.get("exact_surface", False)
    withheld = options.get("withheld", ())
    timeout = options.get("timeout", CONTRACT_PROBE_TIMEOUT_SECONDS)
    readiness_tool = options.get("readiness_tool")
    prepared = provider_execution_launch(
        [command, *args],
        environment=_probe_environment(options.get("env")),
        cwd=None,
        native_authority=options.get("native_authority"),
        supervise=True,
    )
    execution = prepared.command
    stdio_launch = _StdioLaunch(
        command=execution[0],
        args=execution[1:],
        env=prepared.environment,
        cwd=prepared.cwd,
    )
    key = (
        execution[0],
        tuple(execution[1:]),
        tuple(declared),
        tuple(withheld),
        exact_surface,
    )
    if key in _verified:
        return
    async with _probe_lock:
        if key in _verified:
            return
        # Masked HERE rather than inside the description helper: this binding is
        # what escapes, embedded into every refusal below and from there into a
        # run's client-visible failure reason. The helper stays a plain
        # description for any caller whose output does not leave the process. No
        # bound is applied to this string anywhere, so unlike the stderr tail
        # there is no cut for the mask to have to precede.
        launch = redact_text(stdio_launch.description())
        # A real on-disk temporary file, text-wrapped: the stdio client hands the
        # handle to the OS as the child's stderr, so it needs a true file
        # descriptor - an in-memory buffer cannot serve as one.
        with io.TextIOWrapper(
            tempfile.TemporaryFile(dir=temp_home_root()),
            encoding="utf-8",
            errors="replace",
        ) as captured_stderr:
            try:
                served, readiness_diagnostic = await _served_tool_names(
                    stdio_launch,
                    timeout=timeout,
                    captured_stderr=captured_stderr,
                    readiness_tool=readiness_tool,
                )
            except Exception as exc:
                # ``asyncio.timeout`` surfaces its deadline as ``TimeoutError``
                # rather than a bare cancellation, so every reachable probe failure
                # - an unresolvable requirement, an absent command, a broken
                # handshake, the deadline - arrives here as one actionable refusal.
                reason = redact_text(str(exc))
                raise HarnessToolContractError(
                    f"harness MCP server {name!r} could not be verified: probing "
                    f"{launch!r} failed ({type(exc).__name__}: {reason}). The run "
                    f"declares the tools {', '.join(declared)} and refuses to "
                    f"launch an agent whose grounding tools cannot be confirmed."
                    f"{_stderr_tail(captured_stderr)}"
                ) from exc

            missing, undeclared = _tool_contract_differences(
                declared=declared,
                served=served,
                exact_surface=exact_surface,
                withheld=withheld,
            )
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

            if readiness_diagnostic is not None:
                reason = _rag_incompatibility_reason(readiness_diagnostic)
                if reason is not None:
                    raise HarnessToolContractError(
                        f"harness MCP server {name!r} {reason}: "
                        f"{readiness_diagnostic} Launched as {launch!r}, its "
                        f"served tools already match the declaration, but every "
                        f"real search through this client fails the same way the "
                        f"daemon just reported, so the lane is refused before an "
                        f"agent is handed grounding tools that cannot work."
                    )
        _verified.add(key)


async def verify_harness_mcp_contract(
    mcp_servers: Sequence[Mapping[str, JsonValue]],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float = CONTRACT_PROBE_TIMEOUT_SECONDS,
    native_authority: NativeLaunchAuthority | None = None,
) -> None:
    """Verify every registry-known server among *mcp_servers* against its contract.

    Entries the harness registry does not own - notably the run's own authoring
    bridge, which is composed into the same session list - are skipped: their tool
    surface is the engine's live catalog, verified at its own seam, not a static
    registry declaration.

    *env* supplies run configuration. Executable search uses the service PATH,
    and the probe enters the same configured identity boundary as providers.

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
        # Refused BEFORE the probe, which is what makes this the second half of
        # the same closure rather than a restatement of it. The arguments below
        # are read off the spec in hand, so a spec borrowing a reviewed name would
        # otherwise have its own command SPAWNED here - and then admitted, because
        # the served-tool contract is satisfied by any server that serves the
        # declared names. This seam runs on every lane; the session allowlist that
        # holds the same line runs only on the strict claude one.
        divergence = registry_launch_divergence(spec, name=name)
        if divergence is not None:
            raise HarnessToolContractError(
                f"harness MCP server {name!r} {divergence}; refusing to probe a "
                "launch the registry did not declare. Verifying the served tools "
                "of an unreviewed command would certify the name rather than the "
                "server behind it."
            )
        await verify_declared_tool_contract(
            name=name,
            command=command,
            args=_launch_args(spec, name=name),
            declared=declared_harness_tools(name),
            exact_surface=harness_server_exact_surface(name),
            withheld=withheld_harness_tools(name),
            env=env,
            timeout=timeout,
            readiness_tool=_READINESS_TOOLS.get(name),
            native_authority=native_authority,
        )
