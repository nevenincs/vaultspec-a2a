"""Unit tests for the authoring client's pure logic.

No mocks: id validation, idempotency derivation, envelope/denial/error
decoding, header assembly, and URL resolution are pure functions, and the
client decoder is exercised against real ``httpx.Response`` objects. Live HTTP
behaviour against the running engine is covered by the live integration tests.
"""

import httpx
import pytest

from .. import AuthoringError
from .._envelope import (
    CommandEnvelope,
    Denial,
    decode_success_envelope,
    extract_denial,
)
from .._errors import AuthoringTransportError, raise_for_typed_error
from .._ids import (
    MAX_ID_BYTES,
    derive_idempotency_key,
    is_valid_id,
    validate_id,
)
from ..client import ACTOR_TOKEN_HEADER, BEARER_HEADER, AuthoringClient


class TestIds:
    def test_valid_id_passes(self) -> None:
        assert validate_id("run_1:step-2.a/b") == "run_1:step-2.a/b"
        assert is_valid_id("abcABC012_-:./")

    def test_empty_or_whitespace_rejected(self) -> None:
        for bad in ("", "  ", " x", "x ", "\tx"):
            assert not is_valid_id(bad)
            with pytest.raises(ValueError, match=r"non-empty|whitespace"):
                validate_id(bad)

    def test_charset_enforced(self) -> None:
        for bad in ("has space", "bang!", "star*", "hash#", "a+b", "a=b"):
            assert not is_valid_id(bad)
            with pytest.raises(ValueError, match="ASCII"):
                validate_id(bad)

    def test_length_bound_enforced(self) -> None:
        too_long = "a" * (MAX_ID_BYTES + 1)
        assert not is_valid_id(too_long)
        with pytest.raises(ValueError, match="exceeds"):
            validate_id(too_long)
        assert is_valid_id("a" * MAX_ID_BYTES)

    def test_idempotency_key_is_deterministic_and_valid(self) -> None:
        a = derive_idempotency_key("run-1", "create_proposal", "0")
        b = derive_idempotency_key("run-1", "create_proposal", "0")
        c = derive_idempotency_key("run-1", "create_proposal", "1")
        assert a == b
        assert a != c
        assert is_valid_id(a)

    def test_idempotency_key_rejects_empty_material(self) -> None:
        with pytest.raises(ValueError):
            derive_idempotency_key()
        with pytest.raises(ValueError):
            derive_idempotency_key("run-1", "")


class TestCommandEnvelope:
    def test_body_shape(self) -> None:
        env = CommandEnvelope(
            command="create_proposal",
            idempotency_key="idk:abc",
            payload={"summary": "x"},
        )
        body = env.to_body()
        assert body == {
            "api_version": "v1",
            "command": "create_proposal",
            "idempotency_key": "idk:abc",
            "payload": {"summary": "x"},
        }

    def test_invalid_command_rejected(self) -> None:
        with pytest.raises(ValueError, match="command"):
            CommandEnvelope(command="bad command", idempotency_key="idk:abc")

    def test_invalid_idempotency_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="idempotency_key"):
            CommandEnvelope(command="create_proposal", idempotency_key="bad key")


class TestEnvelopeDecoding:
    def test_decode_success(self) -> None:
        resp = decode_success_envelope(
            {"data": {"receipt": "ok"}, "tiers": {"declared": {"available": True}}}
        )
        assert resp.data == {"receipt": "ok"}
        assert resp.tiers == {"declared": {"available": True}}
        assert resp.next_cursor is None

    def test_decode_success_with_cursor(self) -> None:
        resp = decode_success_envelope({"data": [], "tiers": {}, "next_cursor": "c1"})
        assert resp.next_cursor == "c1"

    def test_extract_denial_positive(self) -> None:
        denial = extract_denial(
            {
                "data": {
                    "status": "denied",
                    "denial_kind": "forbidden_actor",
                    "eligibility": {"reason": "agents must propose changesets"},
                },
                "tiers": {"declared": {"available": True}},
            }
        )
        assert isinstance(denial, Denial)
        assert denial.denial_kind == "forbidden_actor"
        assert denial.reason == "agents must propose changesets"

    def test_extract_denial_reads_flat_top_level_reason(self) -> None:
        # An eligibility denial (`denial_value`) emits its fields FLAT under `data`
        # (`{status, command, allowed, reason}`) with no `eligibility` sub-object.
        # The reason must be read from the top level, not dropped to None.
        denial = extract_denial(
            {
                "data": {
                    "status": "denied",
                    "command": "request_apply",
                    "allowed": False,
                    "reason": (
                        "a different live proposal's create predicts the SAME "
                        "path `.vault/adr/x-adr.md`; only one can land"
                    ),
                },
                "tiers": {"declared": {"available": True}},
            }
        )
        assert isinstance(denial, Denial)
        assert denial.reason is not None
        assert "only one can land" in denial.reason

    def test_extract_denial_negative_on_success(self) -> None:
        assert extract_denial({"data": {"receipt": "ok"}, "tiers": {}}) is None


class TestTypedErrors:
    def test_success_passes_through(self) -> None:
        raise_for_typed_error(200, {"data": {}, "tiers": {}})  # no raise

    def test_outer_bearer_401_has_no_error_kind(self) -> None:
        with pytest.raises(AuthoringTransportError) as exc:
            raise_for_typed_error(401, {"error": "Unauthorized", "tiers": {}})
        assert exc.value.is_machine_bearer_rejection
        assert not exc.value.is_actor_token_rejection

    def test_inner_actor_401_carries_error_kind(self) -> None:
        with pytest.raises(AuthoringTransportError) as exc:
            raise_for_typed_error(
                401,
                {
                    "error": "actor token missing",
                    "error_kind": "authoring_actor_token_missing",
                    "tiers": {},
                },
            )
        assert exc.value.is_actor_token_rejection
        assert not exc.value.is_machine_bearer_rejection

    def test_unknown_route_404(self) -> None:
        with pytest.raises(AuthoringTransportError) as exc:
            raise_for_typed_error(
                404,
                {
                    "error": "unknown API path",
                    "error_kind": "authoring_unknown_route",
                    "tiers": {},
                },
            )
        assert exc.value.status_code == 404
        assert exc.value.error_kind == "authoring_unknown_route"

    def test_status_error_without_body_still_raises(self) -> None:
        with pytest.raises(AuthoringTransportError) as exc:
            raise_for_typed_error(503, {})
        assert exc.value.status_code == 503


class TestClientPureLogic:
    def _client(self) -> AuthoringClient:
        # A real httpx.AsyncClient with no network use in these assertions.
        return AuthoringClient(
            "http://127.0.0.1:8767", "bearer-xyz", actor_token="actor-abc"
        )

    def test_url_nests_under_authoring(self) -> None:
        client = self._client()
        assert client._url("/v1/sessions") == "/authoring/v1/sessions"
        assert client._url("v1/sessions") == "/authoring/v1/sessions"
        assert client._url("/authoring/v1/sessions") == "/authoring/v1/sessions"

    def test_headers_bearer_always_present(self) -> None:
        client = self._client()
        headers = client._headers(actor_token=None, with_actor=False)
        assert headers[BEARER_HEADER] == "Bearer bearer-xyz"
        assert ACTOR_TOKEN_HEADER not in headers

    def test_headers_actor_added_when_required(self) -> None:
        client = self._client()
        headers = client._headers(actor_token=None, with_actor=True)
        assert headers[ACTOR_TOKEN_HEADER] == "actor-abc"

    def test_headers_actor_override(self) -> None:
        client = self._client()
        headers = client._headers(actor_token="override", with_actor=True)
        assert headers[ACTOR_TOKEN_HEADER] == "override"

    def test_headers_missing_actor_raises(self) -> None:
        client = AuthoringClient("http://127.0.0.1:8767", "bearer-xyz")
        with pytest.raises(AuthoringError, match="actor token is required"):
            client._headers(actor_token=None, with_actor=True)

    def test_repr_redacts_tokens(self) -> None:
        client = self._client()
        rendered = repr(client)
        assert "bearer-xyz" not in rendered
        assert "actor-abc" not in rendered
        assert "actor_token=<set>" in rendered

    def test_decode_success_response(self) -> None:
        client = self._client()
        resp = httpx.Response(200, json={"data": {"receipt": "ok"}, "tiers": {}})
        decoded = client._decode(resp)
        assert not isinstance(decoded, Denial)
        assert decoded.data == {"receipt": "ok"}

    def test_decode_denial_value(self) -> None:
        client = self._client()
        resp = httpx.Response(
            200,
            json={
                "data": {"status": "denied", "denial_kind": "forbidden_actor"},
                "tiers": {},
            },
        )
        decoded = client._decode(resp)
        assert isinstance(decoded, Denial)
        assert decoded.denial_kind == "forbidden_actor"

    def test_decode_typed_error_raises(self) -> None:
        client = self._client()
        resp = httpx.Response(401, json={"error": "Unauthorized", "tiers": {}})
        with pytest.raises(AuthoringTransportError) as exc:
            client._decode(resp)
        assert exc.value.is_machine_bearer_rejection
