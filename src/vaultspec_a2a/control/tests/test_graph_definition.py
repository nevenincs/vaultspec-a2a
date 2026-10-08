"""The accepted graph definition is read only behind its own immutable receipt.

The journal row and the receipt it carries can diverge in exactly the way a
tamper would leave them: the row is untouched, but the stored receipt no
longer names the fingerprint of what the row actually holds. Reading the
initial graph authority past that divergence would compile and run a program
that was never the one this run was accepted under, so the read refuses
instead - the same typed refusal a dispatch rebuild (``build_followon_dispatch``)
turns into ``FailureType.INCOMPATIBLE_STATE``, which the published refusal map
serves as HTTP 409.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from ...control.dispatch_receipts import (
    validate_current_graph_receipt,
)
from ...control.graph_definition import read_accepted_graph_definition
from ...control.leased_dispatch import build_followon_dispatch
from ...database import (
    create_thread,
    get_control_action_by_idempotency_key,
    get_thread,
)
from ...ipc.schemas import DispatchRequest
from ...testing import (
    current_execution_metadata,
    seed_accepted_thread,
    seed_create_action,
)
from ...thread import RunWriteAuthority
from ...thread.action_receipts import control_action_payload_fingerprint
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType
from ...thread.idempotency import thread_create_action_key
from ...utils.coercion import decode_json_object

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: The SHA-256 fingerprint of an empty payload: syntactically a valid
#: :data:`~vaultspec_a2a.thread.action_receipts.Fingerprint`, but never the
#: fingerprint of this run's real accepted input, so the tamper trips the
#: receipt's own match check rather than a shape check.
_WRONG_FINGERPRINT = (
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


@pytest.mark.asyncio
@pytest.mark.parametrize("autonomous", [False, True])
@pytest.mark.parametrize("action", [ControlActionType.INGEST, ControlActionType.RESUME])
async def test_followon_preserves_the_initial_accepted_autonomy(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    autonomous: bool,
    action: ControlActionType,
) -> None:
    thread_id = "frozen-run-autonomy"
    metadata = current_execution_metadata(tmp_path)
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, "accepted"
            ),
            thread_id=thread_id,
            metadata=metadata,
        )
        await seed_create_action(
            session, thread_id, workspace=tmp_path, autonomous=autonomous
        )
        await session.commit()

    async with session_factory() as session:
        dispatch = await build_followon_dispatch(
            session,
            thread_id=thread_id,
            thread_metadata=metadata,
            action=action,
            content="follow-up",
        )

    assert isinstance(dispatch, DispatchRequest)
    assert dispatch.autonomous is autonomous


@pytest.mark.asyncio
@pytest.mark.parametrize("autonomous", [None, 1, "true"])
async def test_followon_refuses_non_boolean_accepted_autonomy(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    autonomous: object,
) -> None:
    async with session_factory() as session:
        thread_id, receipt = await seed_accepted_thread(session, workspace=tmp_path)
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=thread_create_action_key(thread_id),
        )
        assert action is not None
        assert action.payload_json is not None
        payload = decode_json_object(action.payload_json)
        assert payload is not None
        dispatch_fields = payload["dispatch"]
        assert isinstance(dispatch_fields, dict)
        dispatch_fields["autonomous"] = autonomous
        action.payload_json = json.dumps(payload)
        action.graph_receipt_json = receipt.model_copy(
            update={"payload_fingerprint": control_action_payload_fingerprint(payload)}
        ).model_dump_json()
        await session.commit()

    async with session_factory() as session:
        dispatch = await build_followon_dispatch(
            session,
            thread_id=thread_id,
            thread_metadata=current_execution_metadata(tmp_path),
            action=ControlActionType.RESUME,
        )

    assert not isinstance(dispatch, DispatchRequest)
    assert dispatch.failure_type is FailureType.INCOMPATIBLE_STATE
    assert dispatch.reason == "initial graph authority carries invalid autonomy"


@pytest.mark.asyncio
async def test_a_tampered_receipt_refuses_the_graph_definition_read(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    thread_id = "tampered-graph-receipt"
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.INGEST, "accepted"
            ),
            thread_id=thread_id,
            metadata=current_execution_metadata(tmp_path),
        )
        receipt = await seed_create_action(session, thread_id, workspace=tmp_path)
        await session.commit()

    # Confirmed untampered first: the same read the dispatch rebuild relies on
    # succeeds while the receipt still names what the row holds.
    async with session_factory() as session:
        await read_accepted_graph_definition(session, thread_id)

    tampered = receipt.model_copy(update={"payload_fingerprint": _WRONG_FINGERPRINT})
    async with session_factory() as session:
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=thread_create_action_key(thread_id),
        )
        assert action is not None
        action.graph_receipt_json = tampered.model_dump_json()
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ValueError, match="does not match its receipt"):
            await read_accepted_graph_definition(session, thread_id)

    async with session_factory() as session:
        dispatch = await build_followon_dispatch(
            session,
            thread_id=thread_id,
            thread_metadata=current_execution_metadata(tmp_path),
            action=ControlActionType.RESUME,
        )
    assert not isinstance(dispatch, DispatchRequest)
    assert dispatch.failure_type is FailureType.INCOMPATIBLE_STATE
    assert "does not match its receipt" in dispatch.reason


def test_the_accepted_payload_fingerprint_is_pinned_to_its_stored_bytes() -> None:
    """The fingerprint of a stored accepted payload, as an independent digest.

    An immutable receipt holds this value for the life of a run, so a change to
    how a stored payload is encoded before hashing would refuse every run
    accepted under the old encoding with nothing raising on the way. The oracle
    below is the documented encoding computed with the stdlib directly - sorted
    keys, compact separators, non-ASCII left as text - rather than through the
    module under test, and the literal pins it byte for byte.
    """
    payload: dict[str, object] = {
        "schema_version": "accepted-action-input-v2",
        "intent": {"content": "r\u00e9sum\u00e9"},
        "dispatch": {"thread_id": "run-1", "action": "ingest"},
        "actor_tokens_required": False,
    }
    golden = "f633a05d67513e229bfabd182341b21ede89452f069dad701bd5cadc81db39ab"
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert len(golden) == 64
    assert golden == hashlib.sha256(encoded).hexdigest()
    assert control_action_payload_fingerprint(payload) == f"sha256:{golden}"


@pytest.mark.asyncio
async def test_both_readers_of_an_accepted_action_fingerprint_one_encoding(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """One encoding decides whether a stored receipt matches its row.

    The dispatch boundary fingerprints the payload as the row stores it. The
    initial-authority read used to re-dump the model it had just validated,
    which is a second derivation of the same digest - equal for every payload
    that validates, and a difference nobody would see until a sound receipt
    refused a run. Both readers now take the stored bytes, so the receipt a row
    carries verifies the same way through either.
    """
    thread_id = "one-fingerprint-encoding"
    async with session_factory() as session:
        thread_id, _receipt = await seed_accepted_thread(
            session, thread_id=thread_id, workspace=tmp_path
        )
        await session.commit()

    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=thread_create_action_key(thread_id),
        )
        definition = await read_accepted_graph_definition(session, thread_id)
    assert thread is not None
    assert action is not None
    assert action.payload_json is not None
    stored = decode_json_object(action.payload_json)
    assert stored is not None

    bound = validate_current_graph_receipt(thread, action)
    assert bound is not None
    assert bound.payload_fingerprint == control_action_payload_fingerprint(stored)
    assert definition.digest()
