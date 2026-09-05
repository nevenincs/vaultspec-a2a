---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:e938a34b2fa21cf5ee343bcea5890a484374225caf4a62f95cbc7f0669352b6b'
related:
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-09-05-embedded-runtime-remediation-adr]]'
  - '[[2026-07-15-model-profiles-adr]]'
  - '[[2026-07-15-multi-provider-execution-adr]]'
  - '[[2026-08-02-provider-model-catalog-plan]]'
  - '[[2026-09-05-embedded-runtime-remediation-plan]]'
  - '[[2026-08-02-provider-model-catalog-reference]]'
  - '[[2026-09-05-embedded-runtime-remediation-provider-selection-prerequisites-reference]]'
  - '[[2026-09-05-embedded-runtime-remediation-implementation-review-audit]]'
---
# `embedded-runtime-remediation` audit: `no-legacy architecture reconciliation`

## Scope

Semantic reconciliation of the active provider-model-catalog and
embedded-runtime-remediation lifecycle against the owner's 2026-09-05 direction
that deprecated and legacy behavior is neither retained nor supported. The
review covered the governing catalog, remediation, model-profile and
multi-provider ADRs; active catalog/remediation plans and references; historical
audits and execution records; A2A provider/profile/dispatch/API/config source;
and the Dashboard agent-store projection. Completed historical records were
read as evidence and left unchanged.

The single active decision home is
`2026-08-02-provider-model-catalog-adr`, as amended 2026-09-05. Current
schema-v1 catalog selection is the only provider/model authority. Retired
provider/model/preset/profile and static-map state receives a typed
unsupported/incompatible outcome before construction or dispatch, with no
translation, migration, substitution, restart, redispatch, or product-wire
projection.

## Findings

### governing-legacy-restart-conflict | high | resolved in the catalog ADR

The accepted catalog ADR preserved legacy frozen-profile reads and restart,
including its 2026-08-03 run-status disclosure amendment. That directly
conflicted with the owner's superseding no-legacy direction. A dated amendment
now replaces those clauses, makes current catalog selection the sole authority,
and requires direct removal or typed refusal.

### multi-provider-static-authority-fragment | high | resolved by authoritative pointer

The accepted multi-provider ADR still required `MODEL_MAP`,
`PROVIDER_DEFAULT_MODELS`, and the superseded profile schema for mixed-provider
runs. Its dated amendment retains the provider-lane choices while deferring all
provider/model selection authority to the catalog ADR. The superseded
model-profiles ADR now states that none of its profile, tier-map, or legacy-read
clauses remain active.

### active-plan-legacy-success-gates | high | resolved in unchecked rows

Catalog steps `P01.S10`, `P01.S11`, and `P03.S20` required preserving and proving
legacy restart. Those unchecked rows now require removal and negative real-
behavior proof: retired requests, responses, settings aliases, and durable state
must fail before construction or dispatch, without disclosure or redispatch.
The remediation plan now carries the same governing pointer, and `W02.P03.S77`
refuses pre-current ownership state rather than translating it.

### active-reference-legacy-proof-fork | high | resolved in current references

The catalog reference described legacy profile restart, deprecated Kimi settings
fallback, and profile-readiness compatibility as current requirements. The
provider-selection prerequisite reference made legacy redispatch a closing
proof. Both now classify those live paths as implementation drift and require
typed refusal plus independent current-schema restart proof. Historical raw
captures remain intact as evidence of the earlier source state.

### runtime-legacy-provider-profile-authority | critical | open under catalog P01.S10

The committed A2A baseline `194f4fa6e469a9d849719f3ff8a2e8adaa604712`
contains retired execution authority: `graph/enums.py` exports static model
maps; `providers/model_profiles.py` resolves and freezes profiles;
`team/team_config.py` accepts profile overlays; `control/dispatch.py` reads
stored `model_profile` state; `api/schemas/gateway.py` and
`api/routes/gateway.py` expose profile-era status and preset summaries; and
`control/config.py` accepts deprecated Kimi aliases. Dashboard
`frontend/src/stores/server/agent/a2aTeam.ts` retains a legacy assignment
projection. Concurrent runtime work has begun removing some A2A paths, but none
of that uncommitted state is treated as closure evidence.
Ownership is catalog `P01.S10`; proof is `P01.S11` and cross-repository
`P03.S20`. Remediation `W01.P02.S05` must verify the corrected owner result and
must not close from the ER19 host-state test alone.

### historical-review-obligation-reversed | high | resolved as lifecycle interpretation

Historical catalog audits and the reopened `P01.S11` execution record correctly
reported that legacy redispatch proof was missing under the former decision.
They remain unchanged. The 2026-09-05 amendment reverses that active gate:
successful legacy restart or disclosure is now a defect, while typed refusal is
the required proof. Current plan state and this curation record carry the new
owner interpretation without rewriting completed history.

## Recommendations

- Complete catalog `P01.S10` by deleting every enumerated legacy authority and
  compatibility path in both repositories; do not leave dormant readers or DTO
  fields behind feature flags.
- Close `P01.S11` only after current-schema catalog restart/replay passes and
  representative legacy input and stored-state cases prove typed refusal before
  construction or dispatch.
- Keep `P03.S20` open until the Dashboard request, response, store, and rendering
  surfaces contain no legacy provider/model/profile projection.
- Treat any later implementation finding that reintroduces a migration,
  substitute default, tolerant reader, alias, or redispatch path as a new audit
  finding under the same decision.
