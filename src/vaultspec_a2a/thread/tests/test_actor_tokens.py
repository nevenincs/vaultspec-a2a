"""Bounds and redaction guarantees for the production actor-token wire model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vaultspec_a2a.api.schemas.gateway import RunStartRequest
from vaultspec_a2a.thread.actor_tokens import ActorTokenBundle


def test_actor_token_bundle_accepts_production_role_grammar_and_redacts() -> None:
    bundle = ActorTokenBundle(
        tokens={"vaultspec-coder_2": "actor-secret"},
        engine_bearer="engine-secret",
    )

    assert bundle.actor_token("vaultspec-coder_2") == "actor-secret"
    assert "actor-secret" not in repr(bundle)
    assert "engine-secret" not in repr(bundle)


@pytest.mark.parametrize("role", ["", "has space", "9starts-numeric", "a" * 64])
def test_actor_token_bundle_rejects_out_of_contract_role_keys(role: str) -> None:
    with pytest.raises(ValidationError, match="empty role key|actor token role"):
        ActorTokenBundle(tokens={role: "actor-secret"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tokens", {"coder": "x" * 513}, "exceeds 512 bytes"),
        ("engine_bearer", "x" * 513, "exceeds 512 bytes"),
        ("engine_bearer", "", "engine bearer is empty"),
    ],
)
def test_actor_token_bundle_rejects_unbounded_or_empty_secrets(
    field: str, value: object, message: str
) -> None:
    payload: dict[str, object] = {field: value}
    with pytest.raises(ValidationError, match=message):
        ActorTokenBundle.model_validate(payload)


def test_actor_token_bundle_forbids_unknown_wire_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ActorTokenBundle.model_validate({"tokens": {}, "raw_debug_token": "secret"})


def test_run_start_forbids_unknown_wire_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RunStartRequest.model_validate(
            {"team_preset": "solo", "message": "start", "unreviewed": True}
        )
