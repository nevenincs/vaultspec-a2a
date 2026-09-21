"""The harness registry's root-pin axis, its refusal, and the per-run pin seam.

Real objects only, no mocks: composition runs against a production
``AcpChatModel``, the registry entries a refusal is shown are built through the
production construction seam, and the pin channel itself is exercised against the
real search server over a real MCP stdio session.

Two things are deliberately NOT claimed here. The live case proves the declared
channel is the SERVER's own root authority and outranks the working directory it
was launched in; it does not prove the strict claude lane delivers that value to
the spawned server, because the lane placeholder-substitutes advertised spec env
values and hoists only the authoring bridge's real values into the spawn
environment (a registry entry can declare no env of its own to substitute). And
composition pins only when a caller states a project: no test here asserts that a
run reaches this seam with one, because that wiring lives outside this module and
asserting it from inside would prove nothing about the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import tomllib
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import httpx
import psutil
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ...thread.errors import ConfigError
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME
from .._acp_mcp import (
    _require_trust_root,
    codex_mcp_server_specs,
    compose_harness_mcp_servers,
    harness_spawn_env,
    pin_harness_mcp_servers,
    resolve_harness_mcp_servers,
)
from .._acp_session import session_surface_mcp_servers
from .._acp_types import AcpModelConfig
from .._harness_mcp_registry import (
    _KNOWN_MCP_SERVERS,
    _declare_registry,
    _launch_spec,
    _require_root_pin,
)
from .._json_contract import JsonObject
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from typing import Protocol

    from .._json_contract import FrozenJsonObject, JsonObject, JsonValue

    class _BinaryCapture(Protocol):
        def flush(self) -> None: ...

        def seek(self, offset: int, /) -> int: ...

        def read(self, size: int = -1, /) -> bytes: ...


RAG = "vaultspec-rag"
RAG_PIN_VARIABLE = "VAULTSPEC_RAG_ROOT"

# A live stdio handshake plus one tool call against the runtime-acquired search
# server. Warm it is seconds; the ceiling covers a cold `uvx` acquisition without
# letting a wedged handshake hang the suite.
_LIVE_PROBE_TIMEOUT_SECONDS = 120.0
_SERVICE_CONTROL_TIMEOUT_SECONDS = 120.0
_SERVICE_STOP_ATTEMPT_SECONDS = 10.0
_SERVICE_CLEANUP_RESERVE_SECONDS = 15.0
_SERVICE_LATE_RECORD_RESERVE_SECONDS = 5.0
_SERVICE_FALLBACK_RESERVE_SECONDS = 8.0
_CONTROL_OUTPUT_LIMIT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class _OwnedRagService:
    """Exact private daemon identity retained before cleanup can degrade."""

    process: psutil.Process = field(repr=False)
    port: int
    service_token_sha256: str
    record_path: Path


@dataclass(slots=True)
class _CleanupReceipt:
    """Non-secret evidence that every private-service cleanup obligation ran."""

    fallback_used: bool = False
    late_service_record_observed: bool = False
    process_absent: bool = False
    port_absent: bool = False


@dataclass(frozen=True, slots=True)
class _CleanupContext:
    """Owned service state needed by the bounded cleanup operation."""

    owner: _OwnedRagService
    receipt: _CleanupReceipt


@dataclass(frozen=True, slots=True)
class _RagServiceOptions:
    """Optional control and cleanup settings for an isolated RAG service."""

    start_timeout_seconds: float = _SERVICE_CONTROL_TIMEOUT_SECONDS
    cleanup_receipt: _CleanupReceipt | None = None
    start_control_prefix: tuple[str, ...] = ()
    stop_control_prefix: tuple[str, ...] = ()


@dataclass(slots=True)
class _IsolatedRagServiceState:
    """Configuration and mutable lifecycle state for one private service."""

    requirement: str
    locked_version: str
    port: int
    status_dir: Path
    env: dict[str, str]
    receipt: _CleanupReceipt
    operation_deadline: float
    cleanup_start_deadline: float
    control_deadline: float
    start_control_prefix: tuple[str, ...]
    stop_control_prefix: tuple[str, ...]
    started: bool = False
    start_attempted: bool = False

    @property
    def service_record_path(self) -> Path:
        return self.status_dir / "service.json"


def _isolated_rag_service_state(
    project_root: Path,
    sandbox: Path,
    options: _RagServiceOptions | None,
) -> _IsolatedRagServiceState:
    """Prepare isolated service configuration without owning a process yet."""
    service_options = options or _RagServiceOptions()
    requirement = _locked_rag_requirement(project_root)
    port = _reserve_loopback_port()
    status_dir = sandbox / "service-status"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_") and key != RAG_PIN_VARIABLE
    }
    env.update(
        {
            "VAULTSPEC_RAG_STATUS_DIR": str(status_dir),
            "VAULTSPEC_RAG_DATA_DIR": str(sandbox / "service-data"),
            "VAULTSPEC_RAG_QDRANT_STORAGE_DIR": str(sandbox / "qdrant-storage"),
            "VAULTSPEC_RAG_PORT": str(port),
        }
    )
    operation_deadline = (
        asyncio.get_running_loop().time() + service_options.start_timeout_seconds
    )
    cleanup_start_deadline = operation_deadline - _SERVICE_CLEANUP_RESERVE_SECONDS
    return _IsolatedRagServiceState(
        requirement=requirement,
        locked_version=requirement.rsplit("==", maxsplit=1)[1],
        port=port,
        status_dir=status_dir,
        env=env,
        receipt=service_options.cleanup_receipt or _CleanupReceipt(),
        operation_deadline=operation_deadline,
        cleanup_start_deadline=cleanup_start_deadline,
        control_deadline=cleanup_start_deadline - _SERVICE_LATE_RECORD_RESERVE_SECONDS,
        start_control_prefix=service_options.start_control_prefix,
        stop_control_prefix=service_options.stop_control_prefix,
    )


async def _reap_timed_out_rag_process(
    process: asyncio.subprocess.Process,
    control_owner: psutil.Process,
    *,
    total_deadline: float,
) -> None:
    """Reap a timed-out RAG command and every child it retained."""
    try:
        owned_tree = [*control_owner.children(recursive=True), control_owner]
    except psutil.NoSuchProcess:
        owned_tree = []
    for owned in reversed(owned_tree):
        try:
            if owned.is_running():
                owned.kill()
        except psutil.NoSuchProcess:
            pass
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    loop = asyncio.get_running_loop()
    remaining = max(0.0, total_deadline - loop.time())
    async with asyncio.timeout(remaining):
        await process.wait()
        if owned_tree:
            remaining = max(0.0, total_deadline - loop.time())
            async with asyncio.timeout_at(total_deadline):
                _, alive = await asyncio.to_thread(
                    psutil.wait_procs, owned_tree, timeout=remaining
                )
            assert not alive, "the exact RAG control process tree survived its deadline"


def _locked_rag_requirement(project_root: Path) -> str:
    """Return the exact RAG distribution selected by this checkout's lockfile."""
    with (project_root / "uv.lock").open("rb") as lock_file:
        lock = tomllib.load(lock_file)
    versions = [
        package.get("version")
        for package in lock.get("package", [])
        if package.get("name") == RAG
    ]
    assert len(versions) == 1 and isinstance(versions[0], str), (
        "uv.lock must select exactly one vaultspec-rag version"
    )
    return f"vaultspec-rag[mcp]=={versions[0]}"


def _reserve_loopback_port() -> int:
    """Ask the OS for a currently-free loopback port for an owned test service."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    assert isinstance(port, int)
    return port


async def _run_rag_cli(
    requirement: str,
    *args: str,
    env: dict[str, str],
    timeout_seconds: float = _SERVICE_CONTROL_TIMEOUT_SECONDS,
    command_prefix: tuple[str, ...] = (),
    absolute_deadline: float | None = None,
) -> dict[str, object]:
    """Run one exact-version command inside one launch/reap/output deadline."""
    loop = asyncio.get_running_loop()
    total_deadline = absolute_deadline or loop.time() + timeout_seconds
    available = max(0.0, total_deadline - loop.time())
    reap_reserve = min(5.0, max(1.0, available * 0.4))
    operation_deadline = total_deadline - reap_reserve
    process: asyncio.subprocess.Process | None = None
    control_owner: psutil.Process | None = None

    def read_capped(handle: _BinaryCapture) -> str:
        handle.flush()
        handle.seek(0)
        captured = handle.read(_CONTROL_OUTPUT_LIMIT_BYTES + 1)
        truncated = len(captured) > _CONTROL_OUTPUT_LIMIT_BYTES
        rendered = captured[:_CONTROL_OUTPUT_LIMIT_BYTES].decode(
            "utf-8", errors="replace"
        )
        return f"{rendered}\n[output truncated]" if truncated else rendered

    with (
        tempfile.TemporaryFile() as stdout_handle,
        tempfile.TemporaryFile() as stderr_handle,
    ):
        try:
            async with asyncio.timeout_at(operation_deadline):
                process = await asyncio.create_subprocess_exec(
                    *command_prefix,
                    "uvx",
                    "--from",
                    requirement,
                    "vaultspec-rag",
                    *args,
                    env=env,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                )
                control_owner = psutil.Process(process.pid)
                await process.wait()
        except TimeoutError:
            if process is not None and control_owner is not None:
                await _reap_timed_out_rag_process(
                    process,
                    control_owner,
                    total_deadline=total_deadline,
                )
            raise
        rendered_stdout = read_capped(stdout_handle)
        rendered_stderr = read_capped(stderr_handle)
    assert process is not None
    if process.returncode != 0:
        raise RuntimeError(rendered_stderr or rendered_stdout)
    raw_payload: object = json.loads(rendered_stdout)
    assert isinstance(raw_payload, dict), raw_payload
    return cast("dict[str, object]", raw_payload)


def _loopback_port_is_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


async def _terminate_owned_process_tree(owner: psutil.Process) -> None:
    """Terminate only the retained process identity and its observed children."""
    if not owner.is_running():
        return
    descendants = owner.children(recursive=True)
    for process in [*reversed(descendants), owner]:
        try:
            if process.is_running():
                process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = await asyncio.to_thread(
        psutil.wait_procs, [*descendants, owner], timeout=5.0
    )
    for process in alive:
        try:
            if process.is_running():
                process.kill()
        except psutil.NoSuchProcess:
            pass
    if alive:
        _, alive = await asyncio.to_thread(psutil.wait_procs, alive, timeout=5.0)
    assert not alive, "the exact owned private RAG process tree survived cleanup"


async def _private_endpoint_matches(owner: _OwnedRagService) -> bool:
    """Confirm the retained daemon still owns its private health endpoint."""
    __tracebackhide__ = True
    if not owner.process.is_running():
        return False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"http://127.0.0.1:{owner.port}/health")
        raw_payload: object = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return False
    payload = (
        cast("dict[str, object]", raw_payload)
        if isinstance(raw_payload, dict)
        else None
    )
    token = payload.get("service_token") if payload is not None else None
    token_digest = (
        hashlib.sha256(token.encode()).hexdigest() if isinstance(token, str) else None
    )
    return bool(
        response.status_code == 200
        and payload is not None
        and payload.get("pid") == owner.process.pid
        and payload.get("port") == owner.port
        and token_digest == owner.service_token_sha256
    )


async def _await_private_service_absent(
    owner: _OwnedRagService, *, absolute_deadline: float
) -> None:
    """Prove both the retained process identity and private listener are gone."""
    while asyncio.get_running_loop().time() < absolute_deadline:
        if not owner.process.is_running() and _loopback_port_is_closed(owner.port):
            return
        await asyncio.sleep(0.05)
    assert not owner.process.is_running(), "the owned private RAG process is alive"
    assert _loopback_port_is_closed(owner.port), "the private RAG port is still open"


async def _cleanup_private_rag_service(
    context: _CleanupContext,
    *,
    requirement: str,
    env: dict[str, str],
    absolute_deadline: float,
    stop_control_prefix: tuple[str, ...] = (),
) -> None:
    """Stop the private daemon, falling back only through its retained identity."""
    owner = context.owner
    receipt = context.receipt
    async with asyncio.timeout_at(absolute_deadline):
        try:
            loop = asyncio.get_running_loop()
            stop_deadline = min(
                loop.time() + _SERVICE_STOP_ATTEMPT_SECONDS,
                absolute_deadline - _SERVICE_FALLBACK_RESERVE_SECONDS,
            )
            if stop_deadline <= loop.time():
                raise TimeoutError("no stop-control budget remains before fallback")
            stopped = await _run_rag_cli(
                requirement,
                "server",
                "stop",
                "--port",
                str(owner.port),
                "--json",
                env=env,
                command_prefix=stop_control_prefix,
                absolute_deadline=stop_deadline,
            )
            if stopped.get("ok") is not True:
                raise RuntimeError("the private RAG stop command refused cleanup")
        except (OSError, RuntimeError, TimeoutError, json.JSONDecodeError):
            receipt.fallback_used = True

        if owner.process.is_running():
            # A matching private health identity provides a fresh confirmation.
            # If stop already removed the endpoint, the retained psutil Process
            # object still protects against PID reuse through its creation time.
            endpoint_matches = await _private_endpoint_matches(owner)
            if not endpoint_matches and not _loopback_port_is_closed(owner.port):
                raise RuntimeError(
                    "refusing fallback because the private port changed identity"
                )
            receipt.fallback_used = True
            await _terminate_owned_process_tree(owner.process)

        await _await_private_service_absent(owner, absolute_deadline=absolute_deadline)
        receipt.process_absent = not owner.process.is_running()
        receipt.port_absent = _loopback_port_is_closed(owner.port)
        owner.record_path.unlink(missing_ok=True)


async def _shield_private_cleanup(cleanup: asyncio.Task[None]) -> None:
    """Finish owned cleanup even when its caller is concurrently cancelled."""
    cancellation: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as exc:
            cancellation = exc
    cleanup.result()
    if cancellation is not None:
        raise cancellation


def _shared_service_digest() -> tuple[int, int, str] | None:
    """Read a comparison-safe fingerprint without returning credential material."""
    record_path = Path.home() / ".vaultspec-rag" / "service.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        token = record["service_token"]
        pid = record["pid"]
        port = record["port"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None
    if not isinstance(token, str) or type(pid) is not int or type(port) is not int:
        return None
    return pid, port, hashlib.sha256(token.encode()).hexdigest()


def _read_private_service_owner(
    record_path: Path, *, expected_port: int, expected_version: str
) -> _OwnedRagService | None:
    """Read one private identity without allowing its credential to escape."""
    __tracebackhide__ = True
    record = json.loads(record_path.read_text(encoding="utf-8"))
    pid = record.get("pid")
    port = record.get("port")
    version = record.get("package_version")
    token = record.get("service_token")
    if (
        type(pid) is not int
        or port != expected_port
        or version != expected_version
        or not isinstance(token, str)
    ):
        raise RuntimeError("the private RAG service record has invalid identity")
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None
    return _OwnedRagService(
        process=process,
        port=expected_port,
        service_token_sha256=token_digest,
        record_path=record_path,
    )


@asynccontextmanager
async def _isolated_rag_service(
    *,
    project_root: Path,
    sandbox: Path,
    options: _RagServiceOptions | None = None,
) -> AsyncGenerator[tuple[str, dict[str, str], _CleanupReceipt]]:
    """Run the lockfile-selected RAG service behind owned state and cleanup."""
    state = _isolated_rag_service_state(project_root, sandbox, options)
    owner: _OwnedRagService | None = None
    try:
        state.start_attempted = True
        start = await _run_rag_cli(
            state.requirement,
            "--target",
            str(project_root),
            "server",
            "start",
            "--port",
            str(state.port),
            "--local-only",
            "--no-updates",
            "--json",
            env=state.env,
            command_prefix=state.start_control_prefix,
            absolute_deadline=state.control_deadline,
        )
        assert start.get("ok") is True, start
        raw_start_data = start.get("data")
        assert isinstance(raw_start_data, dict), start
        start_data = cast("dict[str, object]", raw_start_data)
        assert start_data.get("port") == state.port, start
        state.started = True

        owner = _read_private_service_owner(
            state.service_record_path,
            expected_port=state.port,
            expected_version=state.locked_version,
        )
        assert owner is not None, "the private RAG service exited before use"
        assert await _private_endpoint_matches(owner), (
            "the private RAG health identity does not match its service record"
        )
        yield state.requirement, state.env, state.receipt
    finally:
        # A bounded start may time out after the daemon has published its owned
        # identity. The private status record is the authority to clean that
        # process up; without it, never issue a stop against a merely reserved
        # port that another process could have acquired.
        if (
            owner is None
            and state.start_attempted
            and not state.service_record_path.exists()
        ):
            # The CLI control process can time out just before its detached
            # daemon atomically publishes identity. Fund a bounded discovery
            # window so that late-owned service is still reaped.
            while (
                not state.service_record_path.exists()
                and asyncio.get_running_loop().time() < state.cleanup_start_deadline
            ):
                await asyncio.sleep(0.05)
        if owner is None and (state.started or state.service_record_path.exists()):
            state.receipt.late_service_record_observed = True
            owner = _read_private_service_owner(
                state.service_record_path,
                expected_port=state.port,
                expected_version=state.locked_version,
            )
            if owner is None:
                state.receipt.process_absent = True
                state.receipt.port_absent = _loopback_port_is_closed(state.port)
                state.service_record_path.unlink(missing_ok=True)
        if owner is not None:
            cleanup = asyncio.create_task(
                _cleanup_private_rag_service(
                    _CleanupContext(owner=owner, receipt=state.receipt),
                    requirement=state.requirement,
                    env=state.env,
                    absolute_deadline=state.operation_deadline,
                    stop_control_prefix=state.stop_control_prefix,
                )
            )
            await _shield_private_cleanup(cleanup)


def _declared_entry(name: str, root_pin: str | None) -> FrozenJsonObject:
    """Build one registry entry through the production construction seam.

    The registry is closed and frozen by design and its single shipped entry is
    pinnable, so a guard that only ever saw ``_KNOWN_MCP_SERVERS`` could never be
    shown the case it exists to refuse. Declaring an entry through
    :func:`_declare_registry` gives the guards a REAL entry - constructor-
    validated, frozen, identical in kind to a shipped one - rather than a stand-in
    for one, which is what keeps the refusal tests honest without reaching for a
    patch.
    """
    registry = _declare_registry(
        {
            name: {
                "name": name,
                "command": "uvx",
                "args": ["--from", "example", "example-mcp"],
                "tools": ["search"],
                "read_only": True,
                "network_egress": False,
                "root_pin": root_pin,
                "exact_surface": False,
            }
        }
    )
    entry = registry[name]
    assert isinstance(entry, MappingProxyType)
    return entry


def _shipped_entry(name: str) -> FrozenJsonObject:
    """Return one entry of the closed registry, narrowed as the readers narrow it."""
    entry = _KNOWN_MCP_SERVERS[name]
    assert isinstance(entry, MappingProxyType)
    return entry


def test_every_registry_entry_declares_the_root_pin_axis() -> None:
    """No shipped entry may reach a run with its project binding unstated."""
    for name, entry in _KNOWN_MCP_SERVERS.items():
        assert isinstance(entry, MappingProxyType)
        assert "root_pin" in entry, f"{name} declares no root-pin axis"
        pin = entry["root_pin"]
        assert pin is None or (isinstance(pin, str) and pin), (
            f"{name} declares a malformed root pin: {pin!r}"
        )


def test_registry_construction_refuses_an_omitted_root_pin() -> None:
    """Omission must not read as permission, exactly as for the other two axes."""
    with pytest.raises(ConfigError) as excinfo:
        _declare_registry(
            {
                "probe": {
                    "name": "probe",
                    "command": "uvx",
                    "args": [],
                    "read_only": True,
                    "network_egress": False,
                }
            }
        )
    message = str(excinfo.value)
    assert "root_pin" in message
    assert "probe" in message


@pytest.mark.parametrize("declared", [True, "", 7, []])
def test_registry_construction_refuses_a_malformed_root_pin(
    declared: JsonValue,
) -> None:
    # The axis names a channel; a boolean, an empty string, or any other shape
    # cannot be acted on, so it is refused where entries are written.
    with pytest.raises(ConfigError):
        _declare_registry(
            {
                "probe": {
                    "name": "probe",
                    "command": "uvx",
                    "args": [],
                    "read_only": True,
                    "network_egress": False,
                    "root_pin": declared,
                    "exact_surface": False,
                }
            }
        )


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"PROBE_LOG": "info"}, id="flat-mapping-the-codex-shape"),
        pytest.param(
            [{"name": "PROBE_LOG", "value": "info"}], id="pair-list-the-acp-shape"
        ),
    ],
)
def test_registry_construction_refuses_an_env_declaration(env: JsonValue) -> None:
    """BOTH candidate shapes are refused, because neither is servable to both.

    Not a style rule and not a preference between the two shapes: the ACP stdio
    spec models env as a list of name/value pairs and the Codex block models it as
    a flat mapping, and a registry entry is read by both. Before this refusal the
    constructor admitted either, so whichever an author wrote, one transport got
    it wrong - the flat mapping reaching an UNPINNED ACP session wrong and silent,
    which is the half nobody investigates.

    Parametrizing over both shapes is what keeps that the claim. A test refusing
    only one would read as a shape preference and would still admit the other.
    """
    with pytest.raises(ConfigError) as excinfo:
        _declare_registry(
            {
                "probe": {
                    "name": "probe",
                    "command": "uvx",
                    "args": [],
                    "env": env,
                    "read_only": True,
                    "network_egress": False,
                    "root_pin": "PROBE_ROOT",
                    "exact_surface": False,
                }
            }
        )
    message = str(excinfo.value)
    assert "env" in message
    assert "probe" in message


def test_no_shipped_entry_declares_an_environment() -> None:
    """The admitted case: the closed registry satisfies the refusal it now imposes.

    The complement of the test above, and the reason the refusal costs nothing -
    a constructor rule the shipped registry itself violated would be a rule that
    could never ship.
    """
    for name, entry in _KNOWN_MCP_SERVERS.items():
        assert isinstance(entry, MappingProxyType)
        assert "env" not in entry, f"{name} declares an environment"


def test_registry_construction_admits_an_explicitly_unpinnable_entry() -> None:
    """Declaring unpinnable is constructible; SURFACING it is what is refused.

    The same division the read-only axis draws: the constructor enforces that the
    axis was declared, and the composition guards decide what a declared value may
    do. Without this the refusal below would be unreachable and the axis would
    collapse into a constructor check.
    """
    entry = _declared_entry("unpinnable", None)
    assert entry["root_pin"] is None


def test_the_root_pin_axis_stays_registry_metadata() -> None:
    # Like ``tools``, the axis is registry metadata and not part of the advertised
    # stdio shape; a run must never advertise its own trust declarations.
    spec = resolve_harness_mcp_servers([RAG])[0]
    assert "root_pin" not in spec
    assert set(spec) <= {"name", "command", "args", "env"}


def test_launch_spec_rendering_refuses_an_unpinnable_server() -> None:
    """The single ACP spec renderer refuses rather than surfacing unpinned.

    Both public ACP paths - ``resolve_harness_mcp_servers`` and the composition
    seam - render through this function, so the refusal cannot be reached by one
    and missed by the other.
    """
    with pytest.raises(ConfigError) as excinfo:
        _launch_spec("unpinnable", _declared_entry("unpinnable", None))
    message = str(excinfo.value)
    assert "unpinnable" in message
    assert "root pin" in message
    # The shipped entry renders through the same call unchanged.
    rendered = _launch_spec(RAG, _shipped_entry(RAG))
    assert rendered["name"] == RAG


def test_the_trust_root_holds_the_pin_axis_with_the_other_two() -> None:
    # The guard both delivery shapes share: the shipped entry satisfies all three
    # axes, and an unpinnable entry is refused by the same pin guard the trust
    # root calls.
    _require_trust_root(RAG)
    with pytest.raises(ConfigError):
        _require_root_pin("unpinnable", _declared_entry("unpinnable", None))
    assert _require_root_pin(RAG, _shipped_entry(RAG)) == RAG_PIN_VARIABLE


def test_pin_carries_the_bound_project_through_the_declared_channel(
    tmp_path: Path,
) -> None:
    project = str(tmp_path)
    [spec] = pin_harness_mcp_servers(
        resolve_harness_mcp_servers([RAG]), project_root=project
    )
    assert spec["env"] == [{"name": RAG_PIN_VARIABLE, "value": project}]
    # The pin is additive: what to launch is unchanged, only which project it
    # serves is now stated.
    assert spec["command"] == "uvx"
    assert spec["args"] == ["--from", "vaultspec-rag[mcp]", "vaultspec-search-mcp"]


def test_pin_returns_fresh_specs_and_mutates_no_input(tmp_path: Path) -> None:
    resolved = resolve_harness_mcp_servers([RAG])
    pinned = pin_harness_mcp_servers(resolved, project_root=str(tmp_path))
    assert "env" not in resolved[0]
    assert pinned[0] is not resolved[0]


def test_pin_leaves_a_non_registry_spec_untouched(tmp_path: Path) -> None:
    """The run's own bridge travels in the same list and is not this seam's call.

    Whether a non-registry spec belongs in the surface at all is the declared-
    surface allowlist's question; silently pinning one here would apply a registry
    server's channel to something the registry never reviewed.
    """
    bridge: JsonObject = {
        "name": "vaultspec-authoring",
        "command": "python",
        "args": ["-m", "example"],
        "env": [{"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}],
    }
    pinned = pin_harness_mcp_servers([bridge], project_root=str(tmp_path))
    assert pinned[0]["env"] == [
        {"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}
    ]


def test_pin_refuses_an_environment_expansion_marker() -> None:
    """The literals rule survives the seam that takes an outside value.

    A ``${...}`` in an env value is expanded by whatever parses the surfacing
    config, so a pin carrying one would bind the server to the serving process's
    environment rather than to the run's project.
    """
    with pytest.raises(ConfigError) as excinfo:
        pin_harness_mcp_servers(
            resolve_harness_mcp_servers([RAG]), project_root="${PROJECT_ROOT}"
        )
    assert "${" in str(excinfo.value)


@pytest.mark.parametrize("project_root", ["", "   ", "relative/project"])
def test_pin_refuses_a_project_root_that_binds_nothing(project_root: str) -> None:
    # A blank pin names no project; a relative one is resolved against the
    # launched server's working directory, which is the undeclared inheritance
    # the pin exists to replace.
    with pytest.raises(ConfigError):
        pin_harness_mcp_servers(
            resolve_harness_mcp_servers([RAG]), project_root=project_root
        )


def test_pin_refuses_a_spec_that_already_declares_the_variable(
    tmp_path: Path,
) -> None:
    # Two statements of the run's project are a disagreement, not a default.
    [spec] = pin_harness_mcp_servers(
        resolve_harness_mcp_servers([RAG]), project_root=str(tmp_path)
    )
    with pytest.raises(ConfigError) as excinfo:
        pin_harness_mcp_servers([spec], project_root=str(tmp_path))
    assert RAG_PIN_VARIABLE in str(excinfo.value)


def test_compose_pins_the_advertised_server_to_the_run_project(
    tmp_path: Path,
) -> None:
    """The real composition seam: what an ACP session would advertise."""
    project = str(tmp_path)
    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, [RAG], project_root=project)
    assert isinstance(composed, AcpChatModel)
    [spec] = composed.mcp_servers
    assert spec["name"] == RAG
    assert spec["env"] == [{"name": RAG_PIN_VARIABLE, "value": project}]


def test_compose_pins_beside_an_existing_bridge_without_touching_it(
    tmp_path: Path,
) -> None:
    model = AcpChatModel(
        command=["echo"],
        env_vars={},
        mcp_servers=[
            {
                "name": "vaultspec-authoring",
                "command": "python",
                "env": [{"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}],
            }
        ],
    )
    composed = compose_harness_mcp_servers(model, [RAG], project_root=str(tmp_path))
    assert isinstance(composed, AcpChatModel)
    by_name = {spec["name"]: spec for spec in composed.mcp_servers}
    assert by_name["vaultspec-authoring"]["env"] == [
        {"name": "VAULTSPEC_AUTHORING_RUN_ID", "value": "run-1"}
    ]
    assert by_name[RAG]["env"] == [{"name": RAG_PIN_VARIABLE, "value": str(tmp_path)}]


def test_composition_never_invents_a_project_pin() -> None:
    """A caller that states no project gets no pin - not a derived one.

    Deriving the pin from the working directory would restate the undeclared
    inheritance the axis exists to replace, spelled as a default and therefore
    invisible. The seam either carries a project a caller stated or carries none.
    """
    model = AcpChatModel(command=["echo"], env_vars={})
    composed = compose_harness_mcp_servers(model, [RAG])
    assert isinstance(composed, AcpChatModel)
    [spec] = composed.mcp_servers
    assert "env" not in spec


def test_codex_specs_carry_the_pin_in_that_transports_env_shape(
    tmp_path: Path,
) -> None:
    # One registry, two serializations: the Codex config.toml block models env as
    # a flat mapping where the ACP stdio shape models it as name/value pairs, so
    # the same declared channel is rendered twice rather than pinned once.
    project = str(tmp_path)
    [spec] = codex_mcp_server_specs([RAG], project_root=project)
    assert spec["env"] == {RAG_PIN_VARIABLE: project}
    [unpinned] = codex_mcp_server_specs([RAG])
    assert unpinned["env"] == {}


@pytest.mark.parametrize("project_root", ["${PROJECT_ROOT}", "relative/project", ""])
def test_codex_specs_refuse_an_unusable_pin(project_root: str) -> None:
    with pytest.raises(ConfigError):
        codex_mcp_server_specs([RAG], project_root=project_root)


@pytest.mark.service
@pytest.mark.resource("rag-service-control")
@pytest.mark.asyncio
async def test_the_declared_channel_is_the_servers_own_root_authority(
    tmp_path: Path,
) -> None:
    """Live: the pinned server addresses the pin, not the directory it launched in.

    The whole axis rests on this being true of the real server rather than assumed
    of it, so the composed spec is handed to a real MCP stdio session: the server
    is launched IN this repository - itself a resolvable workspace - and pinned to
    a directory that is not one. A tool call naming no project of its own must then
    fail naming the PIN, which it can only do if the declared channel outranks the
    working directory the run would otherwise have inherited.

    The spawn environment is built the way the transport builds it: the pin rides
    the spec, and the launching host lifts the spec's env into the child's. That
    hoist is what a session delivery must perform; this test performs it explicitly
    rather than asserting any lane already does.
    """
    launch_root = Path(__file__).resolve().parents[4]
    assert (launch_root / ".vaultspec").is_dir(), (
        "the launch root must itself resolve as a workspace for this test to "
        "distinguish the pin from the working directory"
    )
    project = str(tmp_path)
    assert not (tmp_path / ".vaultspec").exists()

    async with _isolated_rag_service(
        project_root=launch_root, sandbox=tmp_path / "rag-service"
    ) as (rag_requirement, env, cleanup_receipt):
        [spec] = pin_harness_mcp_servers(
            resolve_harness_mcp_servers([RAG]), project_root=project
        )
        # Preserve the production registry command and entry point, but acquire
        # the exact distribution selected by this checkout so the stdio client
        # and its private data-plane service cannot drift independently.
        spec_args = spec["args"]
        assert spec_args == ["--from", "vaultspec-rag[mcp]", "vaultspec-search-mcp"]
        spec["args"] = ["--from", rag_requirement, "vaultspec-search-mcp"]
        spec_env = spec["env"]
        assert isinstance(spec_env, list)
        for item in spec_env:
            assert isinstance(item, dict)
            name = item["name"]
            value = item["value"]
            assert isinstance(name, str) and isinstance(value, str)
            env[name] = value
        assert env[RAG_PIN_VARIABLE] == project
        # The server renders its traceback with rich, which wraps to a default
        # width off a pipe and would break the pinned path across lines before the
        # assertion below could match it. Widening the child's notion of the
        # terminal keeps the one string this test reads intact.
        env["COLUMNS"] = "300"

        command = spec["command"]
        args = spec["args"]
        assert isinstance(command, str)
        assert isinstance(args, list)
        params = StdioServerParameters(
            command=command,
            args=[arg for arg in args if isinstance(arg, str)],
            env=env,
            cwd=launch_root,
        )
        # A real on-disk temporary file, text-wrapped: the stdio client hands the
        # handle to the OS as the child's stderr, so it needs a true file descriptor
        # (the runner's captured stderr has none), and a wedged launch stays
        # diagnosable rather than silent.
        with io.TextIOWrapper(
            tempfile.TemporaryFile(), encoding="utf-8", errors="replace"
        ) as captured_stderr:
            async with asyncio.timeout(_LIVE_PROBE_TIMEOUT_SECONDS):
                async with (
                    stdio_client(params, errlog=captured_stderr) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    result = await session.call_tool(
                        "search_vault", {"query": "project binding"}
                    )
            captured_stderr.seek(0)
            server_stderr = captured_stderr.read()
    assert cleanup_receipt.process_absent
    assert cleanup_receipt.port_absent
    reported = "\n".join(
        text
        for block in result.content
        if isinstance(text := getattr(block, "text", None), str)
    )
    assert result.is_error, (
        f"the pinned server resolved a project it should not have: {reported}"
    )
    # The refusal has to name the PIN, because an error alone proves nothing:
    # a crashed launch, a renamed tool, and a correctly-pinned server all
    # report is_error. Both channels are read because the server library wraps
    # an unexpected tool exception in a generic "Error executing tool" and
    # keeps the cause on ITS stderr, so the naming moved off the client
    # channel without the server ever changing what it decided.
    diagnosis = "\n".join((reported, server_stderr))
    assert project in diagnosis, diagnosis
    assert str(launch_root) not in diagnosis, diagnosis


@pytest.mark.service
@pytest.mark.resource("rag-service-control")
@pytest.mark.asyncio
async def test_cancelled_probe_reaps_private_service_when_stop_command_fails(
    tmp_path: Path,
) -> None:
    """Cancellation and a failed control launch cannot leak the private daemon."""
    launch_root = Path(__file__).resolve().parents[4]
    entered = asyncio.Event()
    receipts: list[_CleanupReceipt] = []
    shared_before = _shared_service_digest()

    async def cancelled_probe() -> None:
        async with _isolated_rag_service(
            project_root=launch_root, sandbox=tmp_path / "cancelled-rag-service"
        ) as (_requirement, env, receipt):
            receipts.append(receipt)
            # The service is already running. Removing executable lookup from
            # this private environment makes its normal stop-control launch fail
            # through a real process boundary and drives the retained-owner
            # fallback without changing production code or replacing a call.
            env["PATH"] = ""
            entered.set()
            await asyncio.Future()

    probe = asyncio.create_task(cancelled_probe())
    await asyncio.wait_for(entered.wait(), timeout=_SERVICE_CONTROL_TIMEOUT_SECONDS)
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.fallback_used
    assert receipt.process_absent
    assert receipt.port_absent
    assert _shared_service_digest() == shared_before


@pytest.mark.service
@pytest.mark.resource("rag-service-control")
@pytest.mark.asyncio
async def test_hung_real_stop_preserves_fallback_and_absence_budget(
    tmp_path: Path,
) -> None:
    """A launched but hung exact stop control cannot consume fallback time."""
    launch_root = Path(__file__).resolve().parents[4]
    marker = tmp_path / "hung-stop-control.json"
    wrapper = tmp_path / "hold-exact-rag-stop.py"
    wrapper.write_text(
        """import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

marker = Path(sys.argv[1])
command = sys.argv[2:]
creationflags = 0x00000004 if os.name == "nt" else 0
child = subprocess.Popen(command, creationflags=creationflags)
if creationflags == 0:
    os.kill(child.pid, signal.SIGSTOP)
marker.write_text(
    json.dumps({"pid": child.pid, "command": command}), encoding="utf-8"
)
while True:
    time.sleep(1.0)
""",
        encoding="utf-8",
    )
    receipt = _CleanupReceipt()
    shared_before = _shared_service_digest()
    started_at = asyncio.get_running_loop().time()

    async with _isolated_rag_service(
        project_root=launch_root,
        sandbox=tmp_path / "hung-stop-service",
        options=_RagServiceOptions(
            start_timeout_seconds=120.0,
            cleanup_receipt=receipt,
            stop_control_prefix=(sys.executable, str(wrapper), str(marker)),
        ),
    ):
        pass

    elapsed = asyncio.get_running_loop().time() - started_at
    assert elapsed < 120.0, "hung stop and fallback exceeded one total bound"
    launched = json.loads(marker.read_text(encoding="utf-8"))
    command = launched["command"]
    assert command[:3] == ["uvx", "--from", _locked_rag_requirement(launch_root)]
    assert command[3:6] == ["vaultspec-rag", "server", "stop"]
    assert command[6] == "--port"
    assert int(command[7]) > 0
    assert command[8:] == ["--json"]
    if shared_before is not None:
        assert int(command[7]) != shared_before[1]
    assert isinstance(launched["pid"], int)
    assert receipt.fallback_used
    assert receipt.process_absent
    assert receipt.port_absent
    assert _shared_service_digest() == shared_before


@pytest.mark.service
@pytest.mark.resource("rag-service-control")
@pytest.mark.asyncio
async def test_timed_out_start_reaps_a_late_published_private_service(
    tmp_path: Path,
) -> None:
    """The readiness deadline includes control-tree and late-daemon cleanup."""
    launch_root = Path(__file__).resolve().parents[4]
    sandbox = tmp_path / "timed-out-rag-service"
    service_record_path = sandbox / "service-status" / "service.json"
    publication_marker = tmp_path / "wrapper-observed-service-record"
    wrapper = tmp_path / "hold-real-rag-control.py"
    wrapper.write_text(
        """from pathlib import Path
import subprocess
import sys
import time

marker = Path(sys.argv[1])
service_record = Path(sys.argv[2])
child = subprocess.Popen(sys.argv[3:])
deadline = time.monotonic() + 120.0
while time.monotonic() < deadline and child.poll() is None:
    if service_record.exists():
        marker.write_text("observed", encoding="utf-8")
        break
    time.sleep(0.05)
while True:
    time.sleep(1.0)
""",
        encoding="utf-8",
    )
    receipt = _CleanupReceipt()
    shared_before = _shared_service_digest()
    started_at = asyncio.get_running_loop().time()

    with pytest.raises(TimeoutError):
        async with _isolated_rag_service(
            project_root=launch_root,
            sandbox=sandbox,
            options=_RagServiceOptions(
                start_timeout_seconds=60.0,
                cleanup_receipt=receipt,
                start_control_prefix=(
                    sys.executable,
                    str(wrapper),
                    str(publication_marker),
                    str(service_record_path),
                ),
            ),
        ):
            pytest.fail("the deliberately short readiness budget was not enforced")

    elapsed = asyncio.get_running_loop().time() - started_at
    assert elapsed < 60.0, "readiness and cleanup exceeded their one total bound"
    assert publication_marker.read_text(encoding="utf-8") == "observed"
    assert receipt.late_service_record_observed
    assert receipt.process_absent
    assert receipt.port_absent
    assert _shared_service_digest() == shared_before


def _strict_config(specs: list[JsonObject]) -> AcpModelConfig:
    """A minimal claude-family config, which is what makes the surface strict."""
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=None,
        command=["claude"],
        env_vars={},
        session_id=None,
        mcp_servers=specs,
        use_exec=False,
        provider="claude",
        runtime_authority=None,
        acp_backend="node",
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
    )


class TestThePinReachesTheSpawnedChild:
    """The pin is only real if the value arrives where the server reads it.

    On the strict claude lane the advertised surface carries ``${NAME}``
    references rather than values, because the surface is serialized onto the
    CLI argv. The CLI expands each reference from its own process environment at
    config parse time, so a reference whose value was never hoisted expands to
    nothing and the server starts with its pin unset - falling back to the
    directory it inherited while the spec still looks pinned.
    """

    def test_the_hoist_carries_the_pinned_value_the_surface_only_references(
        self, tmp_path: Path
    ) -> None:
        variable = RAG_PIN_VARIABLE

        pinned = pin_harness_mcp_servers(
            [_launch_spec(RAG, _shipped_entry(RAG))], project_root=str(tmp_path)
        )
        surface = session_surface_mcp_servers(_strict_config(pinned))
        first = surface[0]
        assert isinstance(first, dict)
        advertised_env = first["env"]
        assert isinstance(advertised_env, list)
        advertised: dict[str, str] = {}
        for item in advertised_env:
            assert isinstance(item, dict)
            name, value = item["name"], item["value"]
            assert isinstance(name, str) and isinstance(value, str)
            advertised[name] = value
        assert advertised[variable] == f"${{{variable}}}", (
            "the strict surface must carry a reference, never the value"
        )

        hoisted = harness_spawn_env(pinned, exclude=AUTHORING_MCP_SERVER_NAME)
        assert hoisted[variable] == str(tmp_path), (
            "the reference the CLI expands must resolve to the run's project"
        )

    def test_the_authoring_bridge_is_left_to_its_own_gatekeeper(self) -> None:
        """Its values are split off by the validator that admits it."""
        bridge: JsonObject = {
            "name": AUTHORING_MCP_SERVER_NAME,
            "command": "python",
            "args": ["-m", "whatever"],
            "env": [{"name": "VAULTSPEC_AUTHORING_TOKEN", "value": "a-real-token"}],
        }
        hoisted = harness_spawn_env([bridge], exclude=AUTHORING_MCP_SERVER_NAME)
        assert hoisted == {}, "the bridge hoists through its own authority"

    def test_an_unpinned_composition_hoists_nothing(self) -> None:
        """No project means no pin, and therefore no value to carry."""
        unpinned = [_launch_spec(RAG, _shipped_entry(RAG))]
        assert harness_spawn_env(unpinned, exclude=AUTHORING_MCP_SERVER_NAME) == {}
