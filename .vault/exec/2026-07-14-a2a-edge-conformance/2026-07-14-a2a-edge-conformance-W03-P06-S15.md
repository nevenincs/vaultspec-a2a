---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S15'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Build the authoring package skeleton: loopback httpx client with machine-bearer plus per-actor auth, shared-envelope and tiers decoding, denial-as-value handling keyed on denial_kind

## Scope

- `src/vaultspec_a2a/authoring/`

## Description

Built the greenfield authoring package as the single seam this repo uses to reach the dashboard engine, per ADR R3. The loopback httpx client carries the two auth layers in distinct headers: the machine bearer as the outer gate and the per-actor principal for authoring commands. Mutating commands are wrapped in a command envelope with the idempotency key as a body field; the bare actor-token bootstrap route is the sole exception. Id and idempotency-key material is validated client-side against the engine grammar (non-empty, trimmed, at most 160 bytes, restricted charset). Responses decode through the shared envelope into a success value, a first-class denial value keyed on the snake_case denial_kind discriminator, or a typed transport error; the two 401 shapes are distinguishable (the outer bare bearer-gate rejection carries no error_kind, the inner actor-token rejection does). Token hygiene per R7: the client repr is redacted and no token or payload is ever logged.

- Created: `src/vaultspec_a2a/authoring/` (`__init__.py`, `client.py`, `_envelope.py`, `_errors.py`, `_ids.py`, and the `tests/` package)

## Outcome

Committed f504a0a. 27 mock-free unit tests exercise the pure decoders, id validation, idempotency derivation, header assembly, and the client decoder against real response objects; live HTTP behaviour is deferred to S17. ruff, format, and ty all clean.

## Notes

No mocks were used: the decoders and validators are pure and the client decoder is tested against real response objects rather than a transport double. Live-engine behaviour was intentionally deferred to the S17 integration tests.
