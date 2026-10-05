"""Explicit genuine-provider controls using a qualified artifact and selected login."""

from __future__ import annotations

import asyncio
import os
import runpy
import shutil
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

import psutil
import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.chat_model_stream import AsyncChatModelStream
from langchain_core.messages import HumanMessage

from vaultspec_a2a.desktop.native_isolation import (
    NativeLaunchAuthority,
    NativeWorkspaceAuthority,
)
from vaultspec_a2a.providers._codex_protocol import _CodexProtocolError
from vaultspec_a2a.providers.codex_chat_model import CodexChatModel
from vaultspec_a2a.testing import settings_override

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from langchain_core.outputs import LLMResult


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


def _released(
    inputs: _Inputs,
    model: CodexChatModel,
    processes: tuple[psutil.Process, ...] = (),
) -> None:
    assert not model.active_native_control_targets()
    homes = inputs.authority.app_home.path / "tmp/homes"
    assert not tuple(homes.glob("vaultspec-codex-home-*"))
    assert all(not process.is_running() for process in processes)


async def _active(model: CodexChatModel, task: asyncio.Task[Any]) -> None:
    async with asyncio.timeout(30):
        while not model.active_native_control_targets():
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
    _released(inputs, model)


@pytest.mark.asyncio
async def test_live_stream_closes_across_tasks_before_return(inputs: _Inputs) -> None:
    model = inputs.model()
    async with aclosing(model.astream([HumanMessage(content=_LONG_PROMPT)])) as stream:
        async with asyncio.timeout(120):
            while not (await asyncio.wait_for(anext(stream), timeout=60)).content:
                pass
        assert model.active_native_control_targets()
        processes = _processes(inputs)
    _released(inputs, model, processes)


@pytest.mark.asyncio
async def test_cancelling_a_real_invocation_joins_cleanup(inputs: _Inputs) -> None:
    model = inputs.model()
    task = asyncio.create_task(model.ainvoke([HumanMessage(content=_LONG_PROMPT)]))
    try:
        await _active(model, task)
        processes = _processes(inputs)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, model, processes)
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
        assert model.active_native_control_targets()
        processes = _processes(inputs)
        task.cancel()
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, model, processes)
    finally:
        observer.release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_exact_provider_interruption_settles_before_cleanup(
    inputs: _Inputs,
) -> None:
    model = inputs.model()
    task = asyncio.create_task(model.ainvoke([HumanMessage(content=_LONG_PROMPT)]))
    try:
        await _active(model, task)
        thread_id, turn_id = model.active_native_control_targets()[0]
        processes = _processes(inputs)
        result = await model.execute_native_control(
            "interrupt", thread_id=thread_id, turn_id=turn_id
        )
        assert result.outcome == "completed"
        with pytest.raises(_CodexProtocolError, match="interrupted"):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, model, processes)
    finally:
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
                first_keys = set(model.active_native_control_targets())
                first_processes = _processes(inputs)
                while not (await anext(second)).content:
                    pass
            second_keys = set(model.active_native_control_targets()) - first_keys
            assert len(second_keys) == 1
            first_pids = {process.pid for process in first_processes}
            second_processes = tuple(
                process
                for process in _processes(inputs)
                if process.pid not in first_pids
            )
            assert second_processes
        assert set(model.active_native_control_targets()) == second_keys
        assert all(not process.is_running() for process in first_processes)
        assert all(process.is_running() for process in second_processes)
    _released(inputs, model, first_processes + second_processes)


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
    _released(inputs, model)


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
        assert model.active_native_control_targets()
        processes = _processes(inputs)
    _released(inputs, model, processes)


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
        assert model.active_native_control_targets()
        processes = _processes(inputs)
        task = asyncio.create_task(stream.aclose())
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=30)
        _released(inputs, model, processes)
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
        _released(inputs, model)
    assert observer.completions == 1
    _released(inputs, model)
