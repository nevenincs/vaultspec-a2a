"""Unit tests for AuthoringSession pure logic and guards (ADR R3).

No mocks and no network: id generation, run-local id derivation, reference
accumulation, and the pre-flight guards all execute before any HTTP call. The
verbs' live wire behaviour is covered by the S17 integration tests.
"""

import pytest

from .._ids import is_valid_id
from ..client import AuthoringClient
from ..session import AuthoringSession, mint_actor_token


def _session(run_id: str = "run-1") -> AuthoringSession:
    client = AuthoringClient("http://127.0.0.1:8767", "bearer-xyz", actor_token="a")
    return AuthoringSession(client, run_id)


class TestConstruction:
    def test_rejects_invalid_run_id(self) -> None:
        client = AuthoringClient("http://127.0.0.1:8767", "bearer-xyz")
        with pytest.raises(ValueError, match="run_id"):
            AuthoringSession(client, "bad run id")

    def test_session_id_none_until_created(self) -> None:
        assert _session().session_id is None


class TestIdGeneration:
    def test_new_changeset_id_is_valid_and_deterministic(self) -> None:
        session = _session("run-42")
        a = session.new_changeset_id("research-doc")
        b = session.new_changeset_id("research-doc")
        assert a == b
        assert is_valid_id(a)
        assert "run-42" in a

    def test_new_changeset_id_rejects_bad_label(self) -> None:
        with pytest.raises(ValueError, match="label"):
            _session().new_changeset_id("bad label")


class TestReferences:
    def test_references_start_empty(self) -> None:
        refs = _session().state_references()
        assert refs == {
            "authoring_session_id": None,
            "authoring_changeset_ids": [],
            "authoring_proposal_ids": [],
        }


class TestGuards:
    @pytest.mark.asyncio
    async def test_start_turn_requires_session(self) -> None:
        with pytest.raises(RuntimeError, match="create_session"):
            await _session().start_turn(prompt="hi")

    @pytest.mark.asyncio
    async def test_create_proposal_requires_session(self) -> None:
        with pytest.raises(RuntimeError, match="create_session"):
            await _session().create_proposal(
                changeset_id="cs:run-1:x", summary="s", operations=[]
            )


class TestActorTokenValidation:
    @pytest.mark.asyncio
    async def test_mint_rejects_invalid_actor_id_before_http(self) -> None:
        client = AuthoringClient("http://127.0.0.1:8767", "bearer-xyz")
        with pytest.raises(ValueError, match=r"actor\.id"):
            await mint_actor_token(client, actor_id="bad id")
