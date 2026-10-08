"""A harness server resolves on a host whose default interpreter is older.

The proof is a real launch in a child process with the interpreter variable
REMOVED from its environment, because that is the state of an ordinary host: the
package runner then takes the host's default Python, and a server whose floor is
higher than that default cannot be resolved at all. The child runs the production
contract probe, so what is exercised is the launch a run actually performs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...testing import combined_output, inherited_environment, run_child
from .._acp_mcp import codex_mcp_server_specs, resolve_harness_mcp_servers
from .._harness_mcp_registry import (
    _KNOWN_MCP_SERVERS,
    _launch_spec,
    _registry_entry,
    interpreter_pin_args,
)
from ..cli_resolution import resolve_service_executable

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_SOURCE_ROOT = Path(__file__).resolve().parents[3]
_RAG = "vaultspec-rag"
_UV_INTERPRETER_ENV = "UV_PYTHON"


def _args(spec: JsonObject) -> list[str]:
    args = spec["args"]
    assert isinstance(args, list)
    return [item for item in args if isinstance(item, str)]


def test_the_running_interpreter_is_the_pin() -> None:
    """The pin names the interpreter serving the run, not a literal."""
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"

    assert interpreter_pin_args("uvx") == ("--python", expected)
    # A command that resolves nothing takes no pin: the argument would be one the
    # launcher does not accept.
    assert interpreter_pin_args("claude") == ()


@pytest.mark.parametrize("name", sorted(_KNOWN_MCP_SERVERS))
def test_every_package_run_server_carries_the_pin(name: str) -> None:
    """Whatever the registry declares, the rendered launch states an interpreter."""
    spec = _launch_spec(name, _registry_entry(name))
    args = _args(spec)

    assert spec["command"] == resolve_service_executable("uvx")
    assert args[:2] == list(interpreter_pin_args("uvx"))
    # The pin leads, because the runner reads its own options before the package.
    assert args[2] == "--from"


def test_both_transports_render_the_same_pinned_launch() -> None:
    """One renderer, so the Codex config and the ACP session agree."""
    [acp] = [
        spec for spec in resolve_harness_mcp_servers([_RAG]) if spec["name"] == _RAG
    ]
    [codex] = [spec for spec in codex_mcp_server_specs([_RAG]) if spec["name"] == _RAG]

    assert _args(acp) == _args(codex)[: len(_args(acp))]
    assert "--python" in _args(codex)


@pytest.mark.usefixtures("isolated_harness_home")
def test_the_pinned_launch_resolves_with_no_interpreter_in_the_environment(
    tmp_path: Path,
) -> None:
    """The real probe succeeds on a host whose default Python is not the pin.

    Run in a child with the variable removed, so the parent's own pin cannot be
    what makes this pass - and through the production contract verifier, so the
    server is really launched and really asked for its tools.
    """
    script = f"""
import asyncio, os, sys
sys.path.insert(0, {str(_SOURCE_ROOT)!r})
from vaultspec_a2a.providers._acp_mcp import resolve_harness_mcp_servers
from vaultspec_a2a.providers._mcp_contract import verify_harness_mcp_contract

specs = resolve_harness_mcp_servers([{_RAG!r}])
assert {_UV_INTERPRETER_ENV!r} not in os.environ, "the child kept an inherited pin"
asyncio.run(verify_harness_mcp_contract(specs, env=dict(os.environ)))
print("contract verified")
"""
    env = inherited_environment(
        {_UV_INTERPRETER_ENV: None, "PYTHONPATH": str(_SOURCE_ROOT)}
    )

    completed = run_child(
        [sys.executable, "-c", script],
        what="harness MCP contract probe without an inherited interpreter pin",
        env=env,
        cwd=tmp_path,
    )

    assert completed.returncode == 0, combined_output(completed)
    assert "contract verified" in completed.stdout
