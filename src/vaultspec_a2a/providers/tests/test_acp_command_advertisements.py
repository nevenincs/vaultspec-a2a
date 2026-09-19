"""Session-scoped ACP command advertisements are exact and fail closed."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from .._acp_protocol import handle_session_update
from .._acp_types import (
    AcpSessionContext,
    NativeCommandDisposition,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject, JsonValue


def _context() -> AcpSessionContext:
    return AcpSessionContext(
        process=cast("asyncio.subprocess.Process", None),
        stdin=cast("asyncio.StreamWriter", None),
        stdout=cast("asyncio.StreamReader", None),
        response_futures={},
        chunk_queue=asyncio.Queue(),
        prompt_done=asyncio.Event(),
        prompt_id_ref=[],
        interrupt_exc=[],
    )


def _update(
    available_commands: JsonValue,
    *,
    field: str = "availableCommands",
    session_id: str = "session-1",
) -> JsonObject:
    return {
        "sessionId": session_id,
        "update": {
            "sessionUpdate": "available_commands_update",
            field: available_commands,
        },
    }


def test_exact_protocol_advertisement_is_session_supported() -> None:
    ctx = _context()
    asyncio.run(
        handle_session_update(
            _update(
                [
                    {
                        "name": "compact",
                        "description": "Compact this session.",
                        "input": {"hint": "optional focus"},
                    }
                ]
            ),
            ctx,
        )
    )

    command = ctx.native_commands_for("session-1").resolve("compact")
    assert command.disposition is NativeCommandDisposition.SUPPORTED
    assert command.description == "Compact this session."
    assert command.input_hint == "optional focus"


def test_unadvertised_command_is_explicitly_unsupported_after_snapshot() -> None:
    ctx = _context()
    asyncio.run(handle_session_update(_update([]), ctx))

    command = ctx.native_commands_for("session-1").resolve("compact")
    assert command.disposition is NativeCommandDisposition.UNSUPPORTED
    assert command.reason is not None


def test_lookup_is_blocked_until_the_session_advertises_commands() -> None:
    command = _context().native_commands_for("session-1").resolve("compact")

    assert command.disposition is NativeCommandDisposition.BLOCKED
    assert command.reason is not None


@pytest.mark.parametrize(
    "commands",
    [
        [
            {"name": "compact", "description": "one"},
            {"name": "compact", "description": "two"},
        ],
        [{"name": " compact", "description": "bad name"}],
        [{"name": "compact"}],
        [{"name": "compact", "description": "ok", "input": {}}],
        ["compact"],
    ],
)
def test_malformed_snapshot_blocks_command_execution(commands: JsonValue) -> None:
    ctx = _context()
    asyncio.run(handle_session_update(_update(commands), ctx))

    command = ctx.native_commands_for("session-1").resolve("compact")
    assert command.disposition is NativeCommandDisposition.BLOCKED
    assert command.reason is not None


def test_snapshot_replacement_removes_commands_the_provider_withdrew() -> None:
    ctx = _context()
    asyncio.run(
        handle_session_update(
            _update([{"name": "compact", "description": "Compact."}]), ctx
        )
    )
    asyncio.run(handle_session_update(_update([]), ctx))

    assert (
        ctx.native_commands_for("session-1").resolve("compact").disposition
        is NativeCommandDisposition.UNSUPPORTED
    )


def test_nonprotocol_legacy_commands_key_is_blocked() -> None:
    ctx = _context()
    asyncio.run(
        handle_session_update(
            _update([{"name": "compact", "description": "Compact."}], field="commands"),
            ctx,
        )
    )

    assert (
        ctx.native_commands_for("session-1").resolve("compact").disposition
        is NativeCommandDisposition.BLOCKED
    )


def test_command_snapshots_are_isolated_by_exact_session_id() -> None:
    ctx = _context()
    asyncio.run(
        handle_session_update(
            _update(
                [{"name": "compact", "description": "Compact."}],
                session_id="session-a",
            ),
            ctx,
        )
    )
    asyncio.run(handle_session_update(_update([], session_id="session-b"), ctx))

    assert (
        ctx.native_commands_for("session-a").resolve("compact").disposition
        is NativeCommandDisposition.SUPPORTED
    )
    assert (
        ctx.native_commands_for("session-b").resolve("compact").disposition
        is NativeCommandDisposition.UNSUPPORTED
    )


def test_legal_empty_display_text_does_not_block_a_snapshot() -> None:
    ctx = _context()
    asyncio.run(
        handle_session_update(
            _update(
                [
                    {
                        "name": "compact",
                        "description": "",
                        "input": {"hint": ""},
                    }
                ]
            ),
            ctx,
        )
    )

    command = ctx.native_commands_for("session-1").resolve("compact")
    assert command.disposition is NativeCommandDisposition.SUPPORTED
    assert command.description == ""
    assert command.input_hint == ""


def test_missing_session_identity_cannot_mutate_any_catalog() -> None:
    ctx = _context()
    update = _update([{"name": "compact", "description": "Compact."}])
    del update["sessionId"]

    asyncio.run(handle_session_update(update, ctx))

    assert ctx.native_command_catalogs == {}


def test_oversized_session_identity_cannot_allocate_a_catalog() -> None:
    ctx = _context()

    asyncio.run(
        handle_session_update(
            _update([], session_id="s" * 513),
            ctx,
        )
    )

    assert ctx.native_command_catalogs == {}


def test_session_catalog_count_is_bounded() -> None:
    ctx = _context()
    for index in range(17):
        asyncio.run(
            handle_session_update(
                _update([], session_id=f"session-{index}"),
                ctx,
            )
        )

    assert len(ctx.native_command_catalogs) == 16
    with pytest.raises(ValueError, match="catalog limit"):
        ctx.native_commands_for("session-16")
