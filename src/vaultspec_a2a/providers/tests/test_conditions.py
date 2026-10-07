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

from .._acp_prompt_outcomes import raise_prompt_error
from .._codex_app_server_client import _CodexAppServerClient
from .._codex_protocol import _CodexProtocolError
from .._subprocess import spawn_acp_process
from ..acp_exceptions import AcpErrorCode, AcpPromptError
from ..codex_chat_model import CodexChatModel
from ..conditions import (
    ProviderCondition,
    condition_from_acp_error,
    condition_from_codex_error_info,
    condition_from_codex_turn_error,
)
from ._installed_vocabulary import (
    acp_adapter_error_kinds,
    acp_adapter_failure_categories,
    acp_error_kinds,
    codex_error_info_variants,
    read_installed,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule
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


@pytest.fixture
def installed_acp_kinds(
    external_prerequisite: ExternalPrerequisiteRule,
) -> frozenset[str]:
    """Every error kind the installed ACP lane can put on the wire."""
    return read_installed(
        external_prerequisite, lambda: acp_error_kinds() | acp_adapter_error_kinds()
    )


@pytest.fixture
def installed_acp_categories(
    external_prerequisite: ExternalPrerequisiteRule,
) -> dict[str, str]:
    """The remedy category the installed adapter assigns each kind."""
    return read_installed(external_prerequisite, acp_adapter_failure_categories)


@pytest.fixture
def installed_codex_variants(
    external_prerequisite: ExternalPrerequisiteRule, tmp_path: Path
) -> frozenset[str]:
    """Every error-info variant the installed Codex app-server declares."""
    return read_installed(
        external_prerequisite,
        lambda: codex_error_info_variants(tmp_path / "codex-schema"),
    )


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


def test_the_acp_mapping_resolves_every_installed_kind_to_a_member(
    installed_acp_kinds: frozenset[str],
) -> None:
    """Every installed kind resolves, through the real frame shape, to a member."""
    for kind in sorted(installed_acp_kinds):
        frame = {"code": AcpErrorCode.INTERNAL_ERROR, "data": {"errorKind": kind}}
        assert isinstance(condition_from_acp_error(frame), ProviderCondition)


#: The adapter's own name for "I could not classify this either".
_ADAPTER_UNCLASSIFIED = "provider_error"


def _acp_condition(kind: str) -> ProviderCondition:
    """Resolve one error kind through the real frame shape the adapter sends."""
    frame = {"code": AcpErrorCode.INTERNAL_ERROR, "data": {"errorKind": kind}}
    return condition_from_acp_error(frame)


def test_a_kind_the_adapter_classifies_never_lands_on_our_floor(
    installed_acp_categories: dict[str, str],
) -> None:
    """The floor is for kinds nobody classified, not for kinds we never mapped.

    The adapter states, in the artefact that runs, which remedy each error kind
    calls for. Where it names one, resolving that kind to the unknown member
    throws away a diagnosis the wire DID carry - which is exactly what an SDK
    bump does when it adds a member to the kind union and nothing here notices.
    Only the adapter's own unclassified category justifies this project's floor.
    """
    classified = {
        kind
        for kind, category in installed_acp_categories.items()
        if category != _ADAPTER_UNCLASSIFIED
    }
    assert classified, "the installed adapter classifies no error kind at all"
    unresolved = sorted(
        kind for kind in classified if _acp_condition(kind) is ProviderCondition.UNKNOWN
    )
    assert not unresolved, (
        f"the installed adapter classifies {unresolved} but this mapping "
        "resolves them to the unknown floor"
    )


def test_kinds_the_adapter_files_together_resolve_together(
    installed_acp_categories: dict[str, str],
) -> None:
    """Kinds sharing one remedy in the adapter share one condition here.

    The adapter groups its kinds by the action a user has to take. This project's
    vocabulary is coarser but answers the same question, so two kinds the adapter
    cannot tell apart must not be told apart here either - a split would claim a
    distinction the wire never made, and it is how a newly added kind drifts away
    from the established member its own group already resolves to.
    """
    by_category: dict[str, set[ProviderCondition]] = {}
    for kind, category in installed_acp_categories.items():
        by_category.setdefault(category, set()).add(_acp_condition(kind))
    disagreeing = {
        category: sorted(conditions)
        for category, conditions in by_category.items()
        if len(conditions) > 1
    }
    assert not disagreeing, (
        f"the installed adapter files these kinds under one remedy each, but "
        f"this mapping splits them: {disagreeing}"
    )


def test_the_acp_rate_limit_kind_never_claims_usage_exhaustion(
    installed_acp_kinds: frozenset[str],
) -> None:
    """The one distinction this lane's wire cannot carry is not asserted.

    The CLI assigns its rate-limit kind to both a short-term refusal and an
    exhausted usage window, branching only on a header it consumes internally.
    Reporting the finer member here would be a claim the wire never made.
    """
    kind = "rate_limit"
    assert kind in installed_acp_kinds, (
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
        raise_prompt_error(observed)
    assert raised.value.condition is ProviderCondition.UNAUTHENTICATED


def test_the_acp_raise_site_falls_back_to_the_code_and_then_the_floor() -> None:
    """A frame with no kind resolves from its code; one with neither is unknown."""
    from_code_frame: JsonObject = {
        "error": {"code": -32000, "message": "Authentication required"}
    }
    with pytest.raises(AcpPromptError) as from_code:
        raise_prompt_error(from_code_frame)
    assert from_code.value.condition is ProviderCondition.UNAUTHENTICATED

    with pytest.raises(AcpPromptError) as from_nothing:
        raise_prompt_error({})
    assert from_nothing.value.condition is ProviderCondition.UNKNOWN


# ---------------------------------------------------------------------------
# Codex lane
# ---------------------------------------------------------------------------


def test_the_codex_mapping_resolves_every_installed_variant_to_a_member(
    installed_codex_variants: frozenset[str],
) -> None:
    """Every installed variant resolves in both of the shapes it can arrive in."""
    for variant in sorted(installed_codex_variants):
        as_string = condition_from_codex_error_info(variant)
        as_object = condition_from_codex_error_info({variant: {}})
        assert isinstance(as_string, ProviderCondition)
        assert isinstance(as_object, ProviderCondition)


def test_the_codex_usage_and_budget_members_come_from_the_wire(
    installed_codex_variants: frozenset[str],
) -> None:
    """The two members only this lane can emit are emitted for the named variants.

    The installed schema is consulted first, so if either variant is renamed
    upstream this fails rather than quietly asserting a member no wire produces.
    """
    assert {"usageLimitExceeded", "sessionBudgetExceeded"} <= installed_codex_variants
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
