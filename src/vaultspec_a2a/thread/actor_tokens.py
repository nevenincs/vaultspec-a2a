"""Per-role actor token bundle provisioned by the engine at run-start.

The dashboard engine mints one actor token per role at run-start and forwards
the bundle inside the ``run-start`` payload. Each token authorizes authoring
calls under exactly one role's principal; roles never share a token. This module
defines the wire model :mod:`vaultspec_a2a.api.routes.gateway` accepts and
:mod:`vaultspec_a2a.worker.app` receives.

Token hygiene is enforced structurally by this model, not by caller
discipline: ``__repr__``/``__str__`` redact every raw token, so the bundle is
safe to interpolate into any log line or exception message, while
``model_dump``/``model_dump_json`` still emit the real values for the
gateway->worker loopback transport. Tokens live only in worker-scoped runtime
state for a run's active window and are never checkpointed.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["ActorTokenBundle"]

# Bounds keep the forwarded payload self-describing and safe to wrap verbatim
# inside the engine's pass-through envelope. The engine mints tokens
# under a 160-byte restricted-charset rule; the caps here carry headroom without
# admitting an unbounded field.
_MAX_ROLES = 64
_MAX_TOKEN_BYTES = 512
_MAX_ROLE_LENGTH = 63
_ROLE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,62}\Z")


class ActorTokenBundle(BaseModel):
    """A run's per-role actor tokens plus the engine machine bearer.

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

    model_config = ConfigDict(frozen=True, extra="forbid")

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
            if len(role) > _MAX_ROLE_LENGTH or _ROLE_PATTERN.fullmatch(role) is None:
                raise ValueError(
                    "actor token role must match [A-Za-z_][A-Za-z0-9_-]{0,62}"
                )
            if not token:
                raise ValueError(f"actor token for role {role!r} is empty")
            if len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
                msg = f"actor token for role {role!r} exceeds {_MAX_TOKEN_BYTES} bytes"
                raise ValueError(msg)
        return value

    @field_validator("engine_bearer")
    @classmethod
    def _validate_engine_bearer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value:
            raise ValueError("engine bearer is empty")
        if len(value.encode("utf-8")) > _MAX_TOKEN_BYTES:
            raise ValueError(f"engine bearer exceeds {_MAX_TOKEN_BYTES} bytes")
        return value

    def actor_token(self, role: str) -> str | None:
        """Return *role*'s actor token, or ``None`` when the run carries none."""
        return self.tokens.get(role)

    def is_empty(self) -> bool:
        """Return ``True`` when the bundle carries neither tokens nor a bearer."""
        return not self.tokens and self.engine_bearer is None

    def __repr__(self) -> str:
        """Redacted representation — never leaks a raw token."""
        roles = ",".join(sorted(self.tokens))
        bearer = "<set>" if self.engine_bearer else None
        return f"ActorTokenBundle(roles=[{roles}], engine_bearer={bearer})"

    __str__ = __repr__
