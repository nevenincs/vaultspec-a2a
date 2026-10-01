"""Contract verification of the declared harness MCP tool surface.

Real objects only, no mocks: every probe below completes a genuine MCP
``initialize`` + ``tools/list`` handshake against the production launch spec that
a run would actually advertise. The negative cases perturb the DECLARATION (the
side under this project's control), never the server, so a failing contract is
exercised against the same real server the passing one uses.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError, HarnessToolContractError
from .._acp_mcp import resolve_harness_mcp_servers
from .._harness_mcp_registry import declared_harness_tools, is_known_harness_server
from .._mcp_contract import (
    _rag_incompatibility_reason,
    verify_declared_tool_contract,
    verify_harness_mcp_contract,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .._json_contract import JsonObject


def _rag_spec() -> JsonObject:
    return resolve_harness_mcp_servers(["vaultspec-rag"])[0]


def test_declared_tools_are_the_registry_read_surface() -> None:
    assert declared_harness_tools("vaultspec-rag") == (
        "search_vault",
        "search_codebase",
        "get_code_file",
    )


def test_declared_tools_unknown_name_raises_naming_the_known_set() -> None:
    with pytest.raises(ConfigError) as excinfo:
        declared_harness_tools("does-not-exist")
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "vaultspec-rag" in message


def test_known_server_predicate_separates_registry_from_bridge() -> None:
    # The authoring bridge rides the same advertised list but carries no static
    # tool declaration, so the verifier must be able to tell them apart.
    assert is_known_harness_server("vaultspec-rag")
    assert not is_known_harness_server("vaultspec-authoring")


@pytest.mark.asyncio
async def test_production_launch_spec_serves_every_declared_tool() -> None:
    """The live contract: the unpinned spec serves exactly what the run declares.

    This is the assertion the removed version pin was a proxy for. It resolves the
    real registry spec, launches it, and confirms the server advertises every
    declared tool - so an incompatible release fails HERE, loudly, instead of
    leaving an agent advertising grounding tools it can never call.
    """
    spec = _rag_spec()
    command = spec["command"]
    raw_args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(raw_args, list)
    args: list[str] = []
    for arg in raw_args:
        assert isinstance(arg, str)
        args.append(arg)
    await verify_declared_tool_contract(
        name="vaultspec-rag",
        command=command,
        args=args,
        declared=declared_harness_tools("vaultspec-rag"),
        env=dict(os.environ),
    )


@pytest.mark.asyncio
async def test_session_shaped_verification_skips_the_authoring_bridge() -> None:
    """Only registry-owned servers are probed; the bridge is left to its own seam.

    Mirrors the real ACP session list, which carries the per-run authoring bridge
    beside the harness servers. The bridge entry names a command that does not
    exist, so were it probed the call would raise - passing proves it is skipped.
    """
    session: list[JsonObject] = [
        {
            "name": "vaultspec-authoring",
            "command": "no-such-authoring-bridge-executable",
            "args": [],
        },
        _rag_spec(),
    ]
    await verify_harness_mcp_contract(session, env=dict(os.environ))


@pytest.mark.asyncio
async def test_missing_declared_tool_is_refused_and_named() -> None:
    """A declared tool the real server does not serve fails loud and is named.

    The server is the real one; the DECLARATION is perturbed, which is the honest
    direction - drift happens when this project keeps declaring a tool a released
    server has renamed or dropped.
    """
    spec = _rag_spec()
    command = spec["command"]
    raw_args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(raw_args, list)
    args: list[str] = []
    for arg in raw_args:
        assert isinstance(arg, str)
        args.append(arg)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=command,
            args=args,
            declared=("search_vault", "tool_that_no_release_serves"),
            env=dict(os.environ),
        )
    message = str(excinfo.value)
    # Actionable: names the server, the missing tool, and what was served instead.
    assert "vaultspec-rag" in message
    assert "tool_that_no_release_serves" in message
    assert "search_vault" in message
    # A tool the server DOES serve is never reported missing.
    assert "does not serve its declared tool(s): tool_that_no_release_serves" in message


@pytest.mark.asyncio
async def test_unlaunchable_server_is_refused_rather_than_assumed_good() -> None:
    """An unverifiable contract is an unmet one, not a silent pass."""
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command="no-such-mcp-server-executable",
            args=["--serve"],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=30.0,
        )
    message = str(excinfo.value)
    assert "no-such-mcp-server-executable" in message
    assert "could not be verified" in message


@pytest.mark.asyncio
async def test_probe_deadline_is_refused_rather_than_hanging_the_run() -> None:
    """A server that never completes the handshake fails on the deadline."""
    spec = _rag_spec()
    command = spec["command"]
    assert isinstance(command, str)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=command,
            args=["--from", "vaultspec-rag[mcp]", "vaultspec-search-mcp"],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=0.01,
        )
    assert "could not be verified" in str(excinfo.value)


_PLANTED_TOKEN = "sk-ant-PLANTEDPROBE0001deadbeefcafe"
_PLANTED_BEARER = "sk-live-PLANTEDPROBE0002"
_ORDINARY_DIAGNOSTIC = "server exited before completing the handshake"


def _leaky_server(tmp_path: Path) -> Path:
    """Write a real server that reports its configuration to stderr, then dies.

    Delivered as a FILE rather than ``python -c``, because the refusal also
    echoes the launch command it probed: a credential passed on the command line
    would reach the message by a route this test is not about, and would make it
    pass or fail for the wrong reason.
    """
    script = tmp_path / "leaky_server.py"
    script.write_text(
        "import sys\n"
        f'sys.stderr.write("ANTHROPIC_AUTH_TOKEN={_PLANTED_TOKEN}\\n")\n'
        f'sys.stderr.write("Authorization: Bearer {_PLANTED_BEARER}\\n")\n'
        f'sys.stderr.write("{_ORDINARY_DIAGNOSTIC}\\n")\n'
        "sys.stderr.flush()\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    return script


@pytest.mark.asyncio
async def test_a_failing_servers_credentials_never_reach_the_refusal(
    tmp_path: Path,
) -> None:
    """The refusal message is client-visible, so the child's secrets are masked.

    A real subprocess on the real failure path: the server writes credential-
    shaped configuration to its own stderr and exits without ever speaking MCP,
    so the probe fails and the retained tail is embedded into the refusal. That
    message becomes a run's failure reason, and the servers reached here include
    runtime-acquired ones whose output this project does not control.
    """
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=sys.executable,
            args=[str(_leaky_server(tmp_path))],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=30.0,
        )
    message = str(excinfo.value)

    assert _PLANTED_TOKEN not in message
    assert _PLANTED_BEARER not in message
    assert "<redacted>" in message
    # The admitted case, asserted in the same breath: masking that swallowed the
    # diagnostic would defeat the only reason the tail is retained, and a
    # refusal-only assertion cannot tell that apart from an empty tail.
    assert _ORDINARY_DIAGNOSTIC in message
    assert "ANTHROPIC_AUTH_TOKEN" in message


_PLANTED_ARGUMENT_TOKEN = "sk-ant-PLANTEDARGV0001deadbeef"


def _argv_ignoring_server(tmp_path: Path) -> Path:
    """Write a server that IGNORES its own arguments and dies before handshake.

    Ignoring argv is the whole point. The sibling refusal field - the stderr
    tail - is already masked, so a child that echoed its arguments to stderr
    would have them masked THERE, and a test built on it would pass without the
    launch description ever being masked at all. The one line it does write is
    credential-free, which keeps that half available as an admitted case.
    """
    script = tmp_path / "arg_server.py"
    script.write_text(
        "import sys\n"
        f'sys.stderr.write("{_ORDINARY_DIAGNOSTIC}\\n")\n'
        "sys.stderr.flush()\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    return script


@pytest.mark.asyncio
async def test_a_credential_in_the_launch_arguments_never_reaches_the_refusal(
    tmp_path: Path,
) -> None:
    """Arguments are echoed into the same client-visible refusal as the stderr.

    The environment is correctly kept out of that description, but the argument
    vector is not: a server whose launch spec ever carries a token puts it in
    front of a client on the same disclosure path.
    """
    script = _argv_ignoring_server(tmp_path)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=sys.executable,
            args=[str(script), "--serve", f"--api-token={_PLANTED_ARGUMENT_TOKEN}"],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=30.0,
        )
    message = str(excinfo.value)

    assert _PLANTED_ARGUMENT_TOKEN not in message
    assert "--api-token=<redacted>" in message
    # Attribution, not decoration: the credential was never written to stderr,
    # so this can only be the launch description being masked - not the stderr
    # tail's mask covering for it. That the ordinary stderr line still arrives
    # confirms the tail was populated and simply had nothing to hide.
    assert _ORDINARY_DIAGNOSTIC in message
    # The description still tells an operator what was actually run.
    assert "arg_server.py" in message
    assert "--serve" in message


@pytest.mark.asyncio
async def test_a_credential_free_launch_description_reaches_the_refusal_intact(
    tmp_path: Path,
) -> None:
    """The admitted case: nothing is masked when there is nothing to mask.

    This description is the only record of what was launched, so redaction that
    ate it would trade one defect for another - and a masking-only assertion
    cannot tell "it masked the credential" apart from "it masked everything".
    """
    script = _argv_ignoring_server(tmp_path)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=sys.executable,
            args=[str(script), "--serve", "--read-only"],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=30.0,
        )
    message = str(excinfo.value)

    assert "<redacted>" not in message
    assert "arg_server.py" in message
    assert "--serve" in message
    assert "--read-only" in message


@pytest.mark.asyncio
async def test_spec_without_a_command_is_refused() -> None:
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_harness_mcp_contract([{"name": "vaultspec-rag", "args": []}])
    assert "no launch command" in str(excinfo.value)


_READINESS_MISMATCH_TEXT = (
    "service_version_mismatch: contrived probe verdict text, not a real daemon"
)
_READINESS_BENIGN_TEXT = "transient_network_hiccup: unrelated to release compatibility"


def _readiness_probe_server(tmp_path: Path, *, failure_text: str) -> Path:
    """Write a real, non-vaultspec-rag MCP server exposing a readiness tool.

    Proves ``_mcp_contract``'s OWN generic mechanism - call the named tool on
    the handshake already open, classify its failure text - independent of
    vaultspec-rag's actual behaviour, which
    ``test_rag_incompatibility_reason_recognizes_the_real_clients_own_text``
    exercises directly against the real dependency below. This server never
    claims to be vaultspec-rag; it only returns a fixed line, the same
    technique ``_leaky_server`` already uses in this file for other
    real-subprocess refusal paths.
    """
    script = tmp_path / "readiness_probe_server.py"
    script.write_text(
        "from mcp.server.mcpserver import MCPServer\n"
        "from mcp.server.mcpserver.exceptions import ToolError\n"
        "\n"
        'mcp = MCPServer("probe-server")\n'
        "\n"
        "@mcp.tool()\n"
        "def ping() -> str:\n"
        '    return "pong"\n'
        "\n"
        "@mcp.tool()\n"
        "def probe_readiness() -> str:\n"
        f"    raise ToolError({failure_text!r})\n"
        "\n"
        'mcp.run(transport="stdio")\n',
        encoding="utf-8",
    )
    return script


@pytest.mark.asyncio
async def test_readiness_tool_reporting_a_known_verdict_is_refused(
    tmp_path: Path,
) -> None:
    """A readiness call naming a real compatibility-verdict prefix is refused.

    ``tools/list`` alone cannot see this: the probe server serves exactly its
    one declared tool, so the refusal can only come from the readiness call
    ``verify_declared_tool_contract`` places on the same handshake.
    """
    script = _readiness_probe_server(tmp_path, failure_text=_READINESS_MISMATCH_TEXT)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="probe-server",
            command=sys.executable,
            args=[str(script)],
            declared=("ping",),
            env=dict(os.environ),
            timeout=30.0,
            readiness_tool="probe_readiness",
        )
    message = str(excinfo.value)
    assert "runs a different vaultspec-rag release" in message
    assert _READINESS_MISMATCH_TEXT in message


@pytest.mark.asyncio
async def test_readiness_tool_reporting_an_unrelated_failure_is_not_refused(
    tmp_path: Path,
) -> None:
    """A readiness failure unrelated to release compatibility never blocks admission.

    The declared tools still match, so only the readiness call could refuse
    this launch - proving it does NOT is the other half of the same wiring.
    """
    script = _readiness_probe_server(tmp_path, failure_text=_READINESS_BENIGN_TEXT)
    await verify_declared_tool_contract(
        name="probe-server",
        command=sys.executable,
        args=[str(script)],
        declared=("ping",),
        env=dict(os.environ),
        timeout=30.0,
        readiness_tool="probe_readiness",
    )


_COMPAT_VERDICT_SCRIPT = """
from vaultspec_rag.serviceclient._compat import classify_service_version


def render(payload):
    verdict = classify_service_version(payload)
    if verdict.is_compatible:
        return ""
    remediation = " ".join(verdict.remediation())
    return f"{verdict.error_code()}: {verdict.reason()}. {remediation}"


print(render({"package_version": "0.0.1-does-not-exist"}))
print("---")
print(render({}))
"""


async def _real_vaultspec_rag_compat_messages() -> tuple[str, str]:
    """Return the real mismatch and unreported messages the client itself raises.

    Generated by calling ``vaultspec_rag``'s own compatibility check in a
    throwaway interpreter - not reimplemented - so the classifier this module
    ships is proven against the dependency's actual wording rather than a
    frozen guess at its shape. Pinned to this project's Python floor so the
    resolution is deterministic regardless of the host's ambient default.
    """
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "--python",
        "3.13",
        "--with",
        "vaultspec-rag[mcp]",
        "python",
        "-c",
        _COMPAT_VERDICT_SCRIPT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    mismatch, _, unreported = stdout.decode().strip().partition("\n---\n")
    return mismatch, unreported


@pytest.mark.asyncio
async def test_rag_incompatibility_reason_recognizes_the_real_clients_own_text() -> (
    None
):
    """The classifier recognizes the exact verdicts the real client raises.

    A daemon that is merely absent - the common case in this environment - is
    the control: the client's own real refusal text for that case must NOT be
    read as an incompatibility.
    """
    mismatch_message, unreported_message = await _real_vaultspec_rag_compat_messages()
    assert _rag_incompatibility_reason(mismatch_message) is not None
    assert _rag_incompatibility_reason(unreported_message) is not None
    assert (
        _rag_incompatibility_reason(
            "vaultspec-rag service is not running. Start it with "
            "`vaultspec-rag server start`."
        )
        is None
    )
