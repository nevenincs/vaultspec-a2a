"""Each lane's condition mapping is total over the vocabulary that is INSTALLED.

Totality on its own is almost untestable: the mapping's floor means every input
returns a member, so "it returned something" would pass on the day a provider
adds a discriminator nobody has mapped. The property worth proving is stronger -
that every discriminator the installed adapter can actually emit reaches its
member by DECISION rather than by falling through - and that requires knowing
what the installed adapter can emit.

So the vocabularies are read from the artefacts that execute: the agent SDK's
shipped type declaration and the ACP adapter's own bundle for one lane, and a
protocol schema generated from the codex binary on the spot for the other. A
hand-copied list in this file would pass forever, including on exactly the day
it stopped being true, which is the failure these tests exist to prevent.

The raise sites are driven for real too - a genuine JSON-RPC failure frame
through the real ACP raise, and real notification frames through the real Codex
client over a real subprocess - because a mapping that is correct and unwired is
worth nothing.

Each test skips naming its missing prerequisite when the installed artefact is
absent, so an unarmed host reports coverage as unrun rather than as passed.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import AIMessage

from .._subprocess import spawn_acp_process
from ..acp_chat_model import _raise_prompt_error
from ..acp_exceptions import AcpErrorCode, AcpPromptError
from ..codex_chat_model import (
    CodexChatModel,
    _CodexAppServerClient,
    _CodexProtocolError,
)
from ..conditions import (
    ProviderCondition,
    acp_mapped_error_kinds,
    codex_mapped_error_infos,
    condition_from_acp_error,
    condition_from_codex_error_info,
    condition_from_codex_turn_error,
)
from ._installed_vocabulary import (
    MissingInstalledVocabularyError,
    acp_adapter_error_kinds,
    acp_error_kinds,
    codex_error_info_variants,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from .._json_contract import JsonObject

# Emits the given frames on stdout and then CLOSES it, which is what tells the
# consumer the turn produced no further result.
#
# This used to linger instead, on the reasoning that the consumer always ends the
# process by raising. That holds only for a frame set carrying a terminal
# outcome. A `willRetry` error is an ATTEMPT, not an outcome: the consumer
# deliberately defers it and keeps reading, because raising there once reported a
# refused credential as "Reconnecting... 1/5". For such a set nothing ever
# raised, so the reader waited on a frame the script had already decided never to
# send - a hung test, not a slow one.
#
# Closing does not race the reader: every frame is written and flushed first, and
# a closed pipe delivers what it holds before it reports EOF.
_FRAME_SERVER = r"""
import json, sys
for frame in json.loads(sys.argv[1]):
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()
sys.stdout.close()
"""


def _installed_acp_kinds() -> frozenset[str]:
    """Return every error kind the installed ACP lane can put on the wire."""
    try:
        return acp_error_kinds() | acp_adapter_error_kinds()
    except MissingInstalledVocabularyError as exc:
        pytest.skip(str(exc))


async def _drive_codex_frames(
    frames: list[dict[str, object]], workspace: Path
) -> _CodexProtocolError:
    """Run the real turn consumer against a real subprocess emitting *frames*."""
    process = await spawn_acp_process(
        [sys.executable, "-c", _FRAME_SERVER, json.dumps(frames)],
        {},
        str(workspace),
        use_exec=True,
    )
    client = _CodexAppServerClient(process)
    try:
        stream: AsyncIterator[object] = CodexChatModel()._consume_turn(client, "T1")
        with pytest.raises(_CodexProtocolError) as raised:
            async for _chunk in stream:
                pass
        return raised.value
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# ACP lane
# ---------------------------------------------------------------------------


def test_every_installed_acp_error_kind_is_mapped_by_decision() -> None:
    """No kind the installed adapter can emit reaches its member by fall-through.

    Fails when the SDK union or the adapter's own kinds grow a member the
    mapping has never considered - which is the drift a hand-written list of
    kinds would hide, because the floor would silently absorb the new member.
    """
    installed = _installed_acp_kinds()
    unmapped = installed - acp_mapped_error_kinds()
    assert not unmapped, (
        f"the installed ACP lane can emit {sorted(unmapped)}, which the "
        "condition mapping does not decide; they would fall through to the "
        "unknown member without anyone choosing that"
    )


def test_the_acp_mapping_resolves_every_installed_kind_to_a_member() -> None:
    """Every installed kind resolves, through the real frame shape, to a member."""
    installed = _installed_acp_kinds()
    for kind in sorted(installed):
        frame = {"code": AcpErrorCode.INTERNAL_ERROR, "data": {"errorKind": kind}}
        assert isinstance(condition_from_acp_error(frame), ProviderCondition)


def test_the_acp_rate_limit_kind_never_claims_usage_exhaustion() -> None:
    """The one distinction this lane's wire cannot carry is not asserted.

    The CLI assigns its rate-limit kind to both a short-term refusal and an
    exhausted usage window, branching only on a header it consumes internally.
    Reporting the finer member here would be a claim the wire never made.
    """
    kind = "rate_limit"
    assert kind in _installed_acp_kinds(), (
        "the installed adapter no longer declares a rate-limit kind; the "
        "collapse this test guards may no longer be the right shape"
    )
    frame = {"code": AcpErrorCode.INTERNAL_ERROR, "data": {"errorKind": kind}}
    assert condition_from_acp_error(frame) is ProviderCondition.THROTTLED


def test_the_acp_mapping_is_total_over_inputs_it_has_never_seen() -> None:
    """An unrecognised, absent or malformed discriminator yields the floor."""
    unmapped_kind = {
        "code": AcpErrorCode.INTERNAL_ERROR,
        "data": {"errorKind": "a_kind_from_a_later_release"},
    }
    assert condition_from_acp_error(unmapped_kind) is ProviderCondition.UNKNOWN
    assert condition_from_acp_error({"code": 4242}) is ProviderCondition.UNKNOWN
    assert condition_from_acp_error({}) is ProviderCondition.UNKNOWN
    assert condition_from_acp_error(None) is ProviderCondition.UNKNOWN
    assert condition_from_acp_error("not a frame") is ProviderCondition.UNKNOWN
    assert (
        condition_from_acp_error({"code": AcpErrorCode.INTERNAL_ERROR, "data": []})
        is ProviderCondition.UNKNOWN
    )


def test_the_acp_raise_site_carries_the_condition_it_resolved() -> None:
    """The real raise attaches the condition, not just the message.

    Driven with the frame shape captured live from the Z.ai gateway, so this
    pins the wiring against an observed payload rather than an invented one.
    """
    observed: JsonObject = {
        "error": {
            "code": -32603,
            "message": (
                "Internal error: Failed to authenticate. "
                "API Error: 401 token expired or incorrect"
            ),
            "data": {"errorKind": "authentication_failed"},
        }
    }
    with pytest.raises(AcpPromptError) as raised:
        _raise_prompt_error(observed)
    assert raised.value.condition is ProviderCondition.UNAUTHENTICATED


def test_the_acp_raise_site_falls_back_to_the_code_and_then_the_floor() -> None:
    """A frame with no kind resolves from its code; one with neither is unknown."""
    from_code_frame: JsonObject = {
        "error": {"code": -32000, "message": "Authentication required"}
    }
    with pytest.raises(AcpPromptError) as from_code:
        _raise_prompt_error(from_code_frame)
    assert from_code.value.condition is ProviderCondition.UNAUTHENTICATED

    with pytest.raises(AcpPromptError) as from_nothing:
        _raise_prompt_error({})
    assert from_nothing.value.condition is ProviderCondition.UNKNOWN


# ---------------------------------------------------------------------------
# Codex lane
# ---------------------------------------------------------------------------


def test_every_installed_codex_error_info_variant_is_mapped_by_decision(
    tmp_path: Path,
) -> None:
    """No variant the installed app-server declares reaches its member by default.

    The schema is generated from the binary during the test, so adding a variant
    upstream fails this immediately instead of waiting for someone to refresh a
    committed copy.
    """
    try:
        installed = codex_error_info_variants(tmp_path / "codex-schema")
    except MissingInstalledVocabularyError as exc:
        pytest.skip(str(exc))

    unmapped = installed - codex_mapped_error_infos()
    assert not unmapped, (
        f"the installed codex app-server declares {sorted(unmapped)}, which the "
        "condition mapping does not decide; they would fall through to the "
        "unknown member without anyone choosing that"
    )


def test_the_codex_mapping_resolves_every_installed_variant_to_a_member(
    tmp_path: Path,
) -> None:
    """Every installed variant resolves in both of the shapes it can arrive in."""
    try:
        installed = codex_error_info_variants(tmp_path / "codex-schema")
    except MissingInstalledVocabularyError as exc:
        pytest.skip(str(exc))

    for variant in sorted(installed):
        as_string = condition_from_codex_error_info(variant)
        as_object = condition_from_codex_error_info({variant: {}})
        assert isinstance(as_string, ProviderCondition)
        assert isinstance(as_object, ProviderCondition)


def test_the_codex_usage_and_budget_members_come_from_the_wire(
    tmp_path: Path,
) -> None:
    """The two members only this lane can emit are emitted for the named variants.

    The installed schema is consulted first, so if either variant is renamed
    upstream this fails rather than quietly asserting a member no wire produces.
    """
    try:
        installed = codex_error_info_variants(tmp_path / "codex-schema")
    except MissingInstalledVocabularyError as exc:
        pytest.skip(str(exc))

    assert {"usageLimitExceeded", "sessionBudgetExceeded"} <= installed
    assert (
        condition_from_codex_error_info("usageLimitExceeded")
        is ProviderCondition.USAGE_EXHAUSTED
    )
    assert (
        condition_from_codex_error_info("sessionBudgetExceeded")
        is ProviderCondition.BUDGET_EXHAUSTED
    )


def test_a_forwarded_status_refines_a_codex_connection_variant() -> None:
    """A variant that forwards an HTTP status is resolved from the status.

    A status means the provider answered, which is a stronger statement than
    the variant's own "the connection failed", so it wins.
    """
    assert (
        condition_from_codex_error_info({"responseStreamDisconnected": {}})
        is ProviderCondition.NETWORK_UNREACHABLE
    )
    assert (
        condition_from_codex_error_info(
            {"responseStreamDisconnected": {"httpStatusCode": 429}}
        )
        is ProviderCondition.THROTTLED
    )
    assert (
        condition_from_codex_error_info(
            {"httpConnectionFailed": {"httpStatusCode": None}}
        )
        is ProviderCondition.NETWORK_UNREACHABLE
    )
    # A server-side status is deliberately not refined into overload: the lane
    # names overload explicitly when it means it.
    assert (
        condition_from_codex_error_info(
            {"httpConnectionFailed": {"httpStatusCode": 503}}
        )
        is ProviderCondition.NETWORK_UNREACHABLE
    )


def test_the_codex_mapping_is_total_over_inputs_it_has_never_seen() -> None:
    """An unrecognised variant, shape or turn error yields the floor."""
    assert (
        condition_from_codex_error_info("aVariantFromALaterRelease")
        is ProviderCondition.UNKNOWN
    )
    assert (
        condition_from_codex_error_info({"aVariantFromALaterRelease": {}})
        is ProviderCondition.UNKNOWN
    )
    assert condition_from_codex_error_info(None) is ProviderCondition.UNKNOWN
    assert condition_from_codex_error_info(17) is ProviderCondition.UNKNOWN
    assert condition_from_codex_error_info({7: "not a variant"}) is (
        ProviderCondition.UNKNOWN
    )
    assert condition_from_codex_turn_error({"message": "no info"}) is (
        ProviderCondition.UNKNOWN
    )
    assert condition_from_codex_turn_error(None) is ProviderCondition.UNKNOWN


@pytest.mark.asyncio
async def test_a_codex_error_notification_carries_its_condition_and_retry_hint(
    tmp_path: Path,
) -> None:
    """The real turn consumer keeps both signals the notification stated."""
    failure = await _drive_codex_frames(
        [
            {
                "method": "error",
                "params": {
                    "threadId": "T1",
                    "turnId": "U1",
                    "willRetry": True,
                    "error": {
                        "message": "You have hit your usage limit.",
                        "codexErrorInfo": "usageLimitExceeded",
                    },
                },
            }
        ],
        tmp_path,
    )
    assert failure.condition is ProviderCondition.USAGE_EXHAUSTED
    assert failure.will_retry is True
    assert "usage limit" in failure.message


@pytest.mark.asyncio
async def test_a_failed_codex_turn_reports_its_own_error_not_just_the_status(
    tmp_path: Path,
) -> None:
    """The terminal frame's error object reaches the raise, typed and quoted.

    Without this the branch reports the word ``failed`` and nothing else, which
    reads identically for a rejected credential and an unreachable endpoint.
    """
    failure = await _drive_codex_frames(
        [
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "T1",
                    "turn": {
                        "id": "U1",
                        "items": [],
                        "status": "failed",
                        "error": {
                            "message": "unauthorized",
                            "codexErrorInfo": "unauthorized",
                        },
                    },
                },
            }
        ],
        tmp_path,
    )
    assert failure.condition is ProviderCondition.UNAUTHENTICATED
    assert "unauthorized" in failure.message
    # The turn frame carries no retry flag, so the lane genuinely said nothing -
    # which must not be reported as a stated refusal to retry.
    assert failure.will_retry is None


@pytest.mark.asyncio
async def test_an_interrupted_codex_turn_invents_no_condition(tmp_path: Path) -> None:
    """A turn that was interrupted carries no error object and gets no member."""
    failure = await _drive_codex_frames(
        [
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "T1",
                    "turn": {"id": "U1", "items": [], "status": "interrupted"},
                },
            }
        ],
        tmp_path,
    )
    assert failure.condition is ProviderCondition.UNKNOWN
    assert "interrupted" in failure.message


@pytest.mark.asyncio
async def test_a_completed_codex_turn_still_ends_the_stream_cleanly(
    tmp_path: Path,
) -> None:
    """The success path is untouched: a completed turn raises nothing.

    Guards the failure-path work above from having quietly turned every turn
    into an error, which the failure tests alone could not detect.
    """
    process = await spawn_acp_process(
        [
            sys.executable,
            "-c",
            _FRAME_SERVER,
            json.dumps(
                [
                    {
                        "method": "item/agentMessage/delta",
                        "params": {"threadId": "T1", "delta": "pong"},
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "T1",
                            "turn": {"id": "U1", "items": [], "status": "completed"},
                        },
                    },
                ]
            ),
        ],
        {},
        str(tmp_path),
        use_exec=True,
    )
    client = _CodexAppServerClient(process)
    try:
        chunks = [chunk async for chunk in CodexChatModel()._consume_turn(client, "T1")]
    finally:
        await client.aclose()

    assert [str(chunk.message.content) for chunk in chunks] == ["pong"]
    assert isinstance(chunks[0].message, AIMessage) or chunks[0].message.content


# ---------------------------------------------------------------------------
# Cross-lane
# ---------------------------------------------------------------------------


def test_neither_lane_maps_a_discriminator_outside_its_installed_vocabulary(
    tmp_path: Path,
) -> None:
    """The mappings do not carry entries the installed adapters cannot produce.

    A stale entry is not a correctness bug, but it is a lie about what the lane
    can report, and it is how a consumer comes to render a remediation for a
    condition that no longer occurs.
    """
    installed_acp = _installed_acp_kinds()
    stale_acp = acp_mapped_error_kinds() - installed_acp
    assert not stale_acp, (
        f"the ACP mapping decides {sorted(stale_acp)}, which the installed "
        "adapter no longer declares"
    )

    try:
        installed_codex = codex_error_info_variants(tmp_path / "codex-schema")
    except MissingInstalledVocabularyError as exc:
        pytest.skip(str(exc))
    stale_codex = codex_mapped_error_infos() - installed_codex
    assert not stale_codex, (
        f"the Codex mapping decides {sorted(stale_codex)}, which the installed "
        "app-server no longer declares"
    )
