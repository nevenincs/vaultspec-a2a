"""Every idempotency-key builder is pinned byte-for-byte.

The journal compares a key as stored, so a builder that quietly changed its
shape would desynchronise the writer from a reader matching the old one (the
clarification recovery sweep's SQL ``LIKE``, the verdict receipt's
``startswith``) without either side raising. Each golden value below is an
independent oracle: the readable-prefix keys are literal strings, and the two
digest keys are SHA-256 hex digests of their documented input, computed with
the stdlib directly rather than through the module under test.
"""

from __future__ import annotations

import hashlib

import pytest

from ..idempotency import (
    CLARIFICATION_RESPONSE_KEY_PREFIX,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    MAX_PERMISSION_ASKS,
    ResumeIntent,
    authoring_verdict_action_key,
    clarification_response_action_key,
    default_cancel_key,
    default_permission_response_key,
    permission_duplicate_action_key,
    permission_rejection_action_key,
    permission_request_action_key,
    permission_response_action_key,
    permission_response_applied_action_key,
    resume_intent,
    thread_create_action_key,
)


def test_the_published_bound_is_255() -> None:
    """255 is the longest client-supplied key the gateway accepts (256 is refused)."""
    assert IDEMPOTENCY_KEY_MAX_LENGTH == 255


def test_readable_prefix_builders_are_pinned_byte_for_byte() -> None:
    assert thread_create_action_key("run-1") == "thread-create:run-1"
    assert permission_request_action_key("req-1") == "permission-request:req-1"
    assert permission_response_action_key("req-1") == "permission-response:req-1"
    assert permission_rejection_action_key("idem-1") == "permission-rejection:idem-1"
    assert permission_duplicate_action_key("idem-1") == "permission-duplicate:idem-1"
    assert (
        permission_response_applied_action_key("permission-response:req-1")
        == "permission-response-applied:req-1"
    )


def test_the_first_ask_of_a_permission_request_keeps_the_stored_key() -> None:
    """Generation 0 is the unsuffixed key every stored row was written under.

    Keys are compared as stored, so the ask a re-ask generation names must not
    change the value the builder already produced: an explicit first ask and the
    default spell the same key, and so does the application key derived from it.
    """
    assert permission_response_action_key("req-1", 0) == "permission-response:req-1"
    assert permission_response_action_key("req-1", 0) == permission_response_action_key(
        "req-1"
    )
    assert (
        permission_response_applied_action_key(
            permission_response_action_key("req-1", 0)
        )
        == "permission-response-applied:req-1"
    )


def test_a_reasked_permission_takes_a_suffixed_key_of_its_own() -> None:
    """A later ask of one request is a journal identity of its own.

    The suffix is outside the grammar of every handle this service mints, so a
    re-ask of one request can never spell the first ask of another, and the
    application key of each ask is derived from that ask's own key.
    """
    assert permission_response_action_key("req-1", 1) == "permission-response:req-1#1"
    assert permission_response_action_key("req-1", 7) == "permission-response:req-1#7"
    assert permission_response_action_key("req-1", 1) != permission_response_action_key(
        "req-1"
    )
    assert (
        permission_response_applied_action_key(
            permission_response_action_key("req-1", 1)
        )
        == "permission-response-applied:req-1#1"
    )


def test_an_ask_outside_the_bound_is_refused_rather_than_reusing_a_key() -> None:
    """Past the bound there is no key left to mint, so none is invented."""
    assert MAX_PERMISSION_ASKS == 64
    permission_response_action_key("req-1", MAX_PERMISSION_ASKS - 1)
    for generation in (-1, MAX_PERMISSION_ASKS):
        with pytest.raises(ValueError, match="outside the bound"):
            permission_response_action_key("req-1", generation)


def test_an_application_key_is_only_derived_from_a_response_key() -> None:
    """A key that is not an accepted answer's names no application of one."""
    with pytest.raises(ValueError, match="permission response"):
        permission_response_applied_action_key("permission-request:req-1")


def test_clarification_response_key_keeps_its_queryable_prefix() -> None:
    """The restart-recovery sweep matches this exact prefix with SQL ``LIKE``."""
    key = clarification_response_action_key("req-1")
    assert key == "clarification-response:req-1"
    assert key == f"{CLARIFICATION_RESPONSE_KEY_PREFIX}req-1"
    assert CLARIFICATION_RESPONSE_KEY_PREFIX == "clarification-response:"


def test_authoring_verdict_key_keeps_its_queryable_prefix() -> None:
    """The verdict receipt matches this exact prefix with ``str.startswith``."""
    key = authoring_verdict_action_key("prop-1")
    assert key == "authoring-verdict:prop-1"
    assert resume_intent(key) is ResumeIntent.AUTHORING_VERDICT


def test_default_cancel_key_is_the_digest_of_thread_id_and_cancel() -> None:
    golden = "0dbc71a57b368e75d40295314637adc829682b7ee068cc26b65af6ff271ac757"
    assert len(golden) == 64
    assert golden == hashlib.sha256(b"thread-1:cancel").hexdigest()
    assert default_cancel_key("thread-1") == golden


def test_default_permission_response_key_is_the_digest_of_request_and_option() -> None:
    golden = "6c442fa163f38377789bf85c6d856406dd0abe2fc485c7a5b8055d5f1a1ac078"
    assert len(golden) == 64
    assert golden == hashlib.sha256(b"req-1:opt-1").hexdigest()
    assert default_permission_response_key("req-1", "opt-1") == golden


def test_default_permission_response_key_keys_on_the_chosen_option() -> None:
    """Answering the SAME request with a DIFFERENT option must not collide."""
    first = default_permission_response_key("req-1", "allow_once")
    second = default_permission_response_key("req-1", "reject_once")
    assert first != second
