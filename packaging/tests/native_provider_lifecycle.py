"""Explicit genuine-provider controls using a qualified artifact and selected login."""

from __future__ import annotations

import asyncio
import logging
import os
import runpy
import shutil
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

import psutil
import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.chat_model_stream import AsyncChatModelStream
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from vaultspec_a2a.desktop.native_isolation import (
    NativeLaunchAuthority,
    NativeWorkspaceAuthority,
)
from vaultspec_a2a.providers.codex_chat_model import CodexChatModel
from vaultspec_a2a.providers.provider_catalog import (
    DEFAULT_FAILURE_TTL,
    AuthenticationState,
    CatalogStatus,
    HealthState,
)
from vaultspec_a2a.providers.provider_catalog_service import ProviderCatalogService
from vaultspec_a2a.testing import armed_environment, settings_override

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

    from langchain_core.outputs import LLMResult
    from langchain_core.tracers.schemas import Run


_LONG_PROMPT = (
    "Print the integers 1 through 200, each on a separate line. Start with 1."
)


@dataclass(frozen=True)
class _Inputs:
    authority: NativeWorkspaceAuthority
    cli: Path
    home: Path
    model_name: str

    def model(self, *, disable_streaming: bool = False) -> CodexChatModel:
        return CodexChatModel(
            command=[str(self.cli), "app-server"],
            model_name=self.model_name,
            workspace_root=str(self.authority.workspace.path),
            codex_home=str(self.home),
            timeout=60,
            disable_streaming=disable_streaming,
        ).with_native_workspace(self.authority)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> Generator[_Inputs]:
    controls = runpy.run_path(
        str(Path(__file__).with_name("native_isolation_artifact.py"))
    )
    assemble = cast(
        "Callable[[Path], tuple[NativeLaunchAuthority, Path, Path]]",
        controls["_artifact"],
    )
    authority, binary, _ = assemble(
        tmp_path_factory.mktemp("native-provider-lifecycle")
    )
    package = authority.capsule.path / "codex"
    shutil.copytree(Path(os.environ["VAULTSPEC_A2A_TEST_LINUX_CODEX_TREE"]), package)
    shutil.copytree(binary.parent / "isolation", authority.capsule.path / "isolation")
    scope = NativeWorkspaceAuthority(
        authority.app_home, authority.capsule, authority.workspace
    )
    home = Path(os.environ["VAULTSPEC_A2A_TEST_CODEX_HOME"])
    with settings_override(
        a2a_home=authority.app_home.path,
        desktop_app_home=None,
        capsule_assets_root=None,
        codex_home=home,
    ):
        yield _Inputs(
            scope,
            package / "bin/codex",
            home,
            os.environ["VAULTSPEC_A2A_TEST_CODEX_MODEL"],
        )


def _processes(inputs: _Inputs) -> tuple[psutil.Process, ...]:
    owned: list[psutil.Process] = []
    for child in psutil.Process().children(recursive=True):
        try:
            if child.exe() == str(inputs.cli):
                owned.append(child)
        except psutil.NoSuchProcess:
            continue
    assert owned
    return tuple(owned)


def _released(inputs: _Inputs, processes: tuple[psutil.Process, ...] = ()) -> None:
    homes = inputs.authority.app_home.path / "tmp/homes"
    assert not tuple(homes.glob("vaultspec-codex-home-*"))
    assert all(not process.is_running() for process in processes)


class _TurnStarted(logging.Handler):
    """Notes the lane's own log line, emitted once the provider accepts a turn."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.started = False

    @override
    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == "Codex turn started":
            self.started = True


@contextmanager
def _observed_turn_start() -> Generator[_TurnStarted]:
    lane_logger = logging.getLogger(CodexChatModel.__module__)
    turn = _TurnStarted()
    level = lane_logger.level
    lane_logger.addHandler(turn)
    lane_logger.setLevel(logging.INFO)
    try:
        yield turn
    finally:
        lane_logger.removeHandler(turn)
        lane_logger.setLevel(level)


async def _active(turn: _TurnStarted, task: asyncio.Task[Any]) -> None:
    async with asyncio.timeout(30):
        while not turn.started:
            if task.done():
                await task
                pytest.fail("real provider ended before the lifecycle control")
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_completed_stream_preserves_content_usage_and_final_chunk(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    content = ""
    usage = False
    final = False
    async with asyncio.timeout(120):
        async with aclosing(
            model.astream(
                [HumanMessage(content="Reply with exactly: stream-qualified")]
            )
        ) as stream:
            async for chunk in stream:
                content += str(chunk.content)
                usage |= chunk.usage_metadata is not None
                final |= chunk.chunk_position == "last"
    assert "stream-qualified" in content
    assert usage and final
    _released(inputs)


@pytest.mark.asyncio
async def test_live_stream_closes_across_tasks_before_return(inputs: _Inputs) -> None:
    model = inputs.model()
    async with aclosing(model.astream([HumanMessage(content=_LONG_PROMPT)])) as stream:
        async with asyncio.timeout(120):
            while not (await asyncio.wait_for(anext(stream), timeout=60)).content:
                pass
        processes = _processes(inputs)
    _released(inputs, processes)


@pytest.mark.asyncio
async def test_cancelling_a_real_invocation_joins_cleanup(inputs: _Inputs) -> None:
    model = inputs.model()
    with _observed_turn_start() as turn:
        task = asyncio.create_task(model.ainvoke([HumanMessage(content=_LONG_PROMPT)]))
        try:
            await _active(turn, task)
            processes = _processes(inputs)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=30)
            _released(inputs, processes)
        finally:
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task


class _InlineContentObserver(AsyncCallbackHandler):
    run_inline = True

    def __init__(self) -> None:
        self.content_seen = asyncio.Event()
        self.release = asyncio.Event()

    @override
    async def on_llm_new_token(
        self, token: str | list[str | dict[str, Any]], **kwargs: Any
    ) -> None:
        if token:
            self.content_seen.set()
            await self.release.wait()


@pytest.mark.asyncio
async def test_repeated_cancellation_in_a_streaming_callback_joins_cleanup(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    observer = _InlineContentObserver()
    task = asyncio.create_task(
        model.ainvoke(
            [HumanMessage(content=_LONG_PROMPT)],
            config={"callbacks": [observer]},
            stream=True,
        )
    )
    try:
        await asyncio.wait_for(observer.content_seen.wait(), timeout=120)
        processes = _processes(inputs)
        task.cancel()
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, processes)
    finally:
        observer.release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_closing_one_stream_preserves_another_on_the_same_model(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    first = model.astream([HumanMessage(content=_LONG_PROMPT)])
    second = model.astream([HumanMessage(content=_LONG_PROMPT)])
    async with aclosing(second):
        async with aclosing(first):
            async with asyncio.timeout(120):
                while not (await anext(first)).content:
                    pass
                first_processes = _processes(inputs)
                while not (await anext(second)).content:
                    pass
            first_pids = {process.pid for process in first_processes}
            second_processes = tuple(
                process
                for process in _processes(inputs)
                if process.pid not in first_pids
            )
            assert second_processes
        assert all(not process.is_running() for process in first_processes)
        assert all(process.is_running() for process in second_processes)
    _released(inputs, first_processes + second_processes)


@pytest.mark.asyncio
async def test_disabled_streaming_fallback_completes_and_cleans_up(
    inputs: _Inputs,
) -> None:
    model = inputs.model(disable_streaming=True)
    async with asyncio.timeout(120):
        async with aclosing(
            model.astream(
                [HumanMessage(content="Reply with exactly: fallback-qualified")]
            )
        ) as stream:
            content = "".join([str(chunk.content) async for chunk in stream])
    assert "fallback-qualified" in content
    _released(inputs)


@pytest.mark.asyncio
async def test_beta_event_stream_close_joins_the_provider(inputs: _Inputs) -> None:
    model = inputs.model()
    stream = await model.astream_events(
        [HumanMessage(content=_LONG_PROMPT)], version="v3"
    )
    async with stream:
        async with asyncio.timeout(120):
            async for text in stream.text:
                if text:
                    break
        processes = _processes(inputs)
    _released(inputs, processes)


@pytest.mark.asyncio
async def test_cancellation_of_beta_stream_closure_still_joins_cleanup(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    stream = await model.astream_events(
        [HumanMessage(content=_LONG_PROMPT)], version="v3"
    )
    try:
        async with asyncio.timeout(120):
            async for text in stream.text:
                if text:
                    break
        processes = _processes(inputs)
        task = asyncio.create_task(stream.aclose())
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, processes)
    finally:
        await stream.aclose()


class _CompletionObserver(AsyncCallbackHandler):
    run_inline = True

    def __init__(self) -> None:
        self.completions = 0

    @override
    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.completions += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["config", "types", "listeners", "composed"])
async def test_public_binding_close_joins_real_provider(
    inputs: _Inputs, kind: str
) -> None:
    model = inputs.model()
    listener_started: list[str] = []

    def on_start(run: Run) -> None:
        listener_started.append(run.id.hex)

    if kind == "types":
        bound = model.with_types(output_type=AIMessage)
    elif kind == "listeners":
        bound = model.with_listeners(on_start=on_start)
    else:
        bound = model.with_config({"tags": ["binding-control"]})
        if kind == "composed":
            bound = (
                bound.bind()
                .with_types(output_type=AIMessage)
                .with_listeners(on_start=on_start)
            )
    generation = cast(
        "AsyncGenerator[AIMessageChunk]",
        bound.astream([HumanMessage(content=_LONG_PROMPT)]),
    )
    async with aclosing(generation) as stream:
        async with asyncio.timeout(120):
            while not (await asyncio.wait_for(anext(stream), timeout=60)).content:
                pass
        processes = _processes(inputs)
        if kind in {"listeners", "composed"}:
            assert len(listener_started) == 1
    _released(inputs, processes)


@pytest.mark.asyncio
async def test_cancelling_public_binding_closure_joins_cleanup(inputs: _Inputs) -> None:
    model = inputs.model()
    stream = model.with_config().astream([HumanMessage(content=_LONG_PROMPT)])
    try:
        async with asyncio.timeout(120):
            while not (await anext(stream)).content:
                pass
        processes = _processes(inputs)
        task = asyncio.create_task(stream.aclose())
        asyncio.get_running_loop().call_soon(task.cancel)
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, processes)
    finally:
        await stream.aclose()


class _BindingObserver(_CompletionObserver):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.stop: object = None

    @override
    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        self.tags = kwargs["tags"]
        self.stop = kwargs["invocation_params"]["stop"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invoke", [False, True])
async def test_public_binding_preserves_work_callbacks_and_merging(
    inputs: _Inputs, invoke: bool
) -> None:
    model = inputs.model()
    observer = _BindingObserver()
    bound = model.with_config({"callbacks": [observer], "tags": ["bound-tag"]}).bind(
        stop=["bound-stop"]
    )
    prompt = [HumanMessage(content="Reply with exactly: binding-qualified")]
    async with asyncio.timeout(120):
        if invoke:
            message = await bound.ainvoke(
                prompt, config={"tags": ["call-tag"]}, stop=["call-stop"]
            )
            content = str(message.content)
            assert isinstance(message, AIMessage)
            assert message.usage_metadata is not None
        else:
            async with aclosing(
                cast(
                    "AsyncGenerator[AIMessageChunk]",
                    bound.astream(
                        prompt, config={"tags": ["call-tag"]}, stop=["call-stop"]
                    ),
                )
            ) as stream:
                content = "".join([str(chunk.content) async for chunk in stream])
    assert "binding-qualified" in content
    assert observer.completions == 1
    assert {"bound-tag", "call-tag"}.issubset(observer.tags)
    assert observer.stop == ["call-stop"]
    _released(inputs)


@pytest.mark.asyncio
async def test_public_binding_preserves_bound_beta_version_and_close(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    bound = model.with_config().bind(version="v3")
    # The omitted call-time version must preserve the already bound choice.
    stream = await cast(
        "Awaitable[AsyncChatModelStream]",
        bound.astream_events([HumanMessage(content=_LONG_PROMPT)]),
    )
    assert isinstance(stream, AsyncChatModelStream)
    async with stream:
        async with asyncio.timeout(120):
            async for text in stream.text:
                if text:
                    break
        processes = _processes(inputs)
    _released(inputs, processes)


@pytest.mark.asyncio
async def test_beta_stream_completion_preserves_resource_and_callbacks(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    observer = _CompletionObserver()
    stream = await model.astream_events(
        [HumanMessage(content="Reply with exactly: events-qualified")],
        config={"callbacks": [observer]},
        version="v3",
    )
    assert isinstance(stream, AsyncChatModelStream)
    async with stream:
        async with asyncio.timeout(120):
            message = await stream
            text = await stream.text
        assert "events-qualified" in str(message.content)
        assert "events-qualified" in text
        assert message.usage_metadata is not None
        assert observer.completions == 1
        _released(inputs)
    assert observer.completions == 1
    _released(inputs)


@pytest.mark.asyncio
async def test_failed_live_catalog_refresh_clears_historical_authentication(
    inputs: _Inputs,
) -> None:
    # The public factory resolves the real selected CLI from its service PATH.
    # A broken owned executable then forces a real OS acquisition failure.
    service = ProviderCatalogService(ttl=timedelta(milliseconds=20))
    workspace = str(inputs.authority.workspace.path)
    with (
        armed_environment(PATH=str(inputs.cli.parent)),
        settings_override(install_root=inputs.authority.capsule.path),
    ):
        healthy = next(
            item
            for item in await service.records(workspace)
            if item.provider_id == "codex"
        )
        assert healthy.health.authentication is AuthenticationState.AUTHENTICATED
        assert healthy.catalog.state.status is CatalogStatus.AVAILABLE
        assert healthy.catalog.models
        await asyncio.sleep(0.06)
        backup = inputs.cli.with_name("codex-catalog-genuine-backup")
        assert inputs.cli.resolve().is_relative_to(inputs.authority.capsule.path)
        assert not backup.exists()
        mode = inputs.cli.stat().st_mode
        inputs.cli.rename(backup)
        try:
            inputs.cli.write_bytes(b"invalid executable qualification control\n")
            inputs.cli.chmod(mode)
            for _ in range(2):
                failed = next(
                    item
                    for item in await service.records(workspace)
                    if item.provider_id == "codex"
                )
                assert failed.catalog.state.status is CatalogStatus.STALE
                assert failed.catalog.state.revision == healthy.catalog.state.revision
                assert failed.catalog.models == healthy.catalog.models
                assert failed.health.authentication is AuthenticationState.UNKNOWN
                assert failed.health.configured is HealthState.UNKNOWN
                assert failed.health.transport is HealthState.UNKNOWN
                assert not failed.health.selectable
        finally:
            inputs.cli.unlink(missing_ok=True)
            backup.rename(inputs.cli)
        await asyncio.sleep(DEFAULT_FAILURE_TTL.total_seconds() + 0.1)
        recovered = next(
            item
            for item in await service.records(workspace)
            if item.provider_id == "codex"
        )
        assert recovered.catalog.state.status is CatalogStatus.AVAILABLE
        assert recovered.catalog.state.checked_at > healthy.catalog.state.checked_at
        assert recovered.catalog.models
        assert recovered.health.authentication is AuthenticationState.AUTHENTICATED
        assert recovered.health.configured is HealthState.AVAILABLE
        assert recovered.health.transport is HealthState.AVAILABLE
