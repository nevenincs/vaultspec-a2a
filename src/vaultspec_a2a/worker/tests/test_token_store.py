"""Token isolation and lifecycle for the worker-scoped actor token store (R7).

Exercises the real :class:`ActorTokenBundle` and :class:`RunTokenStore` — no
mocks, no monkeypatching. These assert the structural guarantees R7 demands:
each role only ever reads its own token, raw tokens never survive a repr/str
(the log surface), an empty bundle registers nothing, and disposal is idempotent.
The executor-driven end-to-end lifecycle (register-during-run, drop-at-run-end,
checkpoint absence, log absence) lives in ``test_executor_token_lifecycle``.
"""

from __future__ import annotations

import pytest

from ...thread.actor_tokens import ActorTokenBundle
from ..token_store import RunTokenStore


def _bundle() -> ActorTokenBundle:
    return ActorTokenBundle(
        tokens={"coder": "tok-coder", "reviewer": "tok-reviewer"},
        engine_bearer="bearer-machine",
    )


class TestActorTokenBundle:
    """Structural token hygiene on the wire model."""

    def test_per_role_lookup_returns_only_that_role(self) -> None:
        bundle = _bundle()
        assert bundle.actor_token("coder") == "tok-coder"
        assert bundle.actor_token("reviewer") == "tok-reviewer"
        # A role absent from the bundle never falls back to another role's token.
        assert bundle.actor_token("supervisor") is None

    def test_repr_and_str_redact_every_token(self) -> None:
        bundle = _bundle()
        for surface in (repr(bundle), str(bundle), f"{bundle}"):
            assert "tok-coder" not in surface
            assert "tok-reviewer" not in surface
            assert "bearer-machine" not in surface
        # But the role names remain visible for diagnostics.
        assert "coder" in repr(bundle)

    def test_model_dump_still_carries_raw_tokens_for_transport(self) -> None:
        # Redaction is a log-surface property only; the loopback transport must
        # still serialize the real values or the worker cannot use them.
        dumped = _bundle().model_dump()
        assert dumped["tokens"]["coder"] == "tok-coder"
        assert dumped["engine_bearer"] == "bearer-machine"

    def test_is_empty_true_only_when_no_tokens_and_no_bearer(self) -> None:
        assert ActorTokenBundle().is_empty()
        assert not ActorTokenBundle(tokens={"a": "x"}).is_empty()
        assert not ActorTokenBundle(engine_bearer="b").is_empty()

    def test_empty_role_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty role key"):
            ActorTokenBundle(tokens={"  ": "x"})

    def test_empty_token_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="is empty"):
            ActorTokenBundle(tokens={"coder": ""})

    def test_oversized_token_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            ActorTokenBundle(tokens={"coder": "x" * 600})


class TestRunTokenStore:
    """Per-run holder isolation and disposal."""

    def test_register_then_per_role_read(self) -> None:
        store = RunTokenStore()
        store.register("run-1", _bundle())
        assert store.has("run-1")
        assert store.actor_token("run-1", "coder") == "tok-coder"
        assert store.actor_token("run-1", "reviewer") == "tok-reviewer"
        assert store.engine_bearer("run-1") == "bearer-machine"

    def test_runs_are_isolated_from_each_other(self) -> None:
        store = RunTokenStore()
        store.register("run-1", ActorTokenBundle(tokens={"coder": "tok-A"}))
        store.register("run-2", ActorTokenBundle(tokens={"coder": "tok-B"}))
        # The same role key in two runs resolves to each run's own token.
        assert store.actor_token("run-1", "coder") == "tok-A"
        assert store.actor_token("run-2", "coder") == "tok-B"
        # A run that holds nothing leaks no other run's token.
        assert store.actor_token("run-3", "coder") is None

    def test_empty_or_none_bundle_registers_nothing(self) -> None:
        store = RunTokenStore()
        store.register("run-1", None)
        store.register("run-2", ActorTokenBundle())
        assert not store.has("run-1")
        assert not store.has("run-2")
        assert store.active_run_count() == 0

    def test_drop_removes_the_run_and_is_idempotent(self) -> None:
        store = RunTokenStore()
        store.register("run-1", _bundle())
        store.drop("run-1")
        assert not store.has("run-1")
        assert store.actor_token("run-1", "coder") is None
        # Dropping an already-dropped or never-registered run does not raise.
        store.drop("run-1")
        store.drop("never")

    def test_repr_reports_only_active_run_count(self) -> None:
        store = RunTokenStore()
        store.register("run-1", _bundle())
        assert repr(store) == "RunTokenStore(active_runs=1)"
        assert "tok-coder" not in repr(store)
