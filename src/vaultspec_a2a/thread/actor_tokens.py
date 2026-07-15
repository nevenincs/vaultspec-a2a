"""Per-role actor token bundle provisioned by the engine at run-start (ADR R7).

The dashboard engine mints one actor token per role at run-start and forwards
the bundle inside the ``run-start`` payload. Each token authorizes authoring
calls under exactly one role's principal; roles never share a token. This module
defines the wire model the gateway accepts and threads to the worker.

Token hygiene (R7) is enforced structurally by this model, not by caller
discipline: ``__repr__``/``__str__`` redact every raw token, so the bundle is
safe to interpolate into any log line or exception message, while
``model_dump``/``model_dump_json`` still emit the real values for the
gateway->worker loopback transport. Tokens live only in worker-scoped runtime
state for a run's active window and are never checkpointed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["ActorTokenBundle"]

# Bounds keep the forwarded payload self-describing and safe to wrap verbatim
# inside the engine's pass-through envelope (ADR R6). The engine mints tokens
# under a 160-byte restricted-charset rule; the caps here carry headroom without
# admitting an unbounded field.
_MAX_ROLES = 64
_MAX_TOKEN_BYTES = 512


class ActorTokenBundle(BaseModel):
    """A run's per-role actor tokens plus the engine machine bearer (ADR R7).

    Parameters
    ----------
    tokens:
        Mapping of role identifier (the worker ``agent_id`` or the supervisor
        constant) to that role's engine-minted actor token. A role only ever
        receives its own token via :meth:`actor_token`.
    engine_bearer:
        The machine bearer minted at engine boot, forwarded so a worker's
        authoring bridge can reach the engine. Optional: when absent the worker
        resolves the bearer from the engine discovery file instead.
    """

    model_config = ConfigDict(frozen=True)

    tokens: dict[str, str] = Field(default_factory=dict)
    engine_bearer: str | None = None

    @field_validator("tokens")
    @classmethod
    def _validate_tokens(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > _MAX_ROLES:
            msg = f"actor token bundle carries {len(value)} roles; max is {_MAX_ROLES}"
            raise ValueError(msg)
        for role, token in value.items():
            if not role or not role.strip():
                raise ValueError("actor token bundle has an empty role key")
            if not token:
                raise ValueError(f"actor token for role {role!r} is empty")
            if len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
                msg = f"actor token for role {role!r} exceeds {_MAX_TOKEN_BYTES} bytes"
                raise ValueError(msg)
        return value

    def actor_token(self, role: str) -> str | None:
        """Return *role*'s actor token, or ``None`` when the run carries none."""
        return self.tokens.get(role)

    def is_empty(self) -> bool:
        """Return ``True`` when the bundle carries neither tokens nor a bearer."""
        return not self.tokens and self.engine_bearer is None

    def __repr__(self) -> str:
        """Redacted representation — never leaks a raw token (R7)."""
        roles = ",".join(sorted(self.tokens))
        bearer = "<set>" if self.engine_bearer else None
        return f"ActorTokenBundle(roles=[{roles}], engine_bearer={bearer})"

    __str__ = __repr__
