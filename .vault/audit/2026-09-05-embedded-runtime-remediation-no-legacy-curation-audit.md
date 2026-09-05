---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:d667dbd0aab21d9f3e316ca55a2e66d3fc6685099c94222b106378a74af596e3'
related:
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-09-05-embedded-runtime-remediation-adr]]'
  - '[[2026-07-15-model-profiles-adr]]'
  - '[[2026-07-15-multi-provider-execution-adr]]'
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-08-02-provider-model-catalog-plan]]'
  - '[[2026-08-05-served-capability-contract-plan]]'
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

### accepted-kimi-static-authority-conflict | high | open

Type: architecture contradiction and single-home-fact violation. Status: open; blocks this curation review and catalog `P01.S10` closure. The accepted `2026-07-17-kimi-provider-adr` still requires `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries in its lane-shape decision and a `[team.profiles.kimi]` overlay in its settings/provisioning decision. Those are current normative clauses, not historical audit or execution evidence, and they conflict with the amended catalog ADR's sole-authority rule. Amend the Kimi ADR with a dated authoritative pointer that preserves its Kimi transport, authentication, permission and provisioning decisions while explicitly superseding static model maps, profile overlays, retired aliases/fallbacks and any preset-carried provider/model authority.

### no-legacy-curation-formal-review | high | FAIL - one accepted ADR still governs retired authority

Type: formal architecture review disposition. Status: open at `41519f11bd093311cebedc0f34bd575a845eac30`. Review against parent `194f4fa6e469a9d849719f3ff8a2e8adaa604712` confirms the exact eleven-path scope, clean diff mechanics, unchanged historical execution records, aligned unchecked catalog/remediation steps, current-schema restart/replay, typed fail-closed legacy-state refusal, and accurately open runtime drift under catalog `P01.S10`/proof `P01.S11` and `P03.S20`. Core reports zero errors and zero warnings for both provider-model-catalog and embedded-runtime-remediation. The unresolved accepted Kimi ADR contradiction means the single active authority and no-conflicting-accepted-ADR acceptance conditions are not met; S10 must not close until that ADR is reconciled and this review is repeated.

### active-served-contract-profile-option | high | open

Type: lifecycle conflict and ambiguous execution authority. Status: open; blocks this curation review and catalog `P01.S10` closure. Active unchecked served-capability-contract step `W05.P10.S28` still offers two alternatives: retire the eligible flag and profiles from preset listing, or redefine eligibility. The second branch does not require profile removal and therefore permits an execution path that violates the catalog ADR's unconditional prohibition on profile summaries and preset-carried provider/model authority. Amend the active row so profile disclosure is retired unconditionally; any independent decision to retain or redefine a topology-only eligibility signal must state that it carries no provider, model, control, fallback or profile authority.

### accepted-kimi-static-authority-conflict-resolution | high | resolved by dated ADR amendment

Type: architecture contradiction and single-home-fact reconciliation. Status:
resolved in the 2026-09-05 Kimi ADR amendment; formal curation re-review pending.
The Kimi transport, current authentication, exact permission, isolation, and
provisioning decisions remain active. Static model maps, profile overlays,
preset-carried Kimi selection, deprecated settings aliases, and the documented
alternate-transport fallback are explicitly non-governing. Kimi provider,
model, and control authority now resolves exclusively through the current
provider-model-catalog decision.

### active-served-contract-profile-option-resolution | high | resolved in unchecked plan row

Type: lifecycle conflict. Status: resolved in active unchecked
`W05.P10.S28`; formal curation re-review pending. The row now retires every
profile field from preset disclosure unconditionally. Its only permitted
retained eligibility signal is topology readiness, explicitly barred from
carrying provider, model, control, fallback, profile, or execution-selection
authority.

### no-legacy-curation-correction | high | two review-blocking conflicts corrected

Type: formal architecture review correction. Status: implemented; formal
re-review pending. Both HIGH conflicts reported at `e1996691` and `5b182057`
now have authoritative corrections. Runtime decision-vs-code drift remains open
under catalog `P01.S10`; no plan row is closed by this documentation correction.

### active-served-contract-eligibility-equivalence | high | open

Type: lifecycle conflict and semantic authority leak. Status: open at correction commit `d9fd625587fbcb45857741bd8c8de94483f61ca9`; blocks the curation re-review and catalog `P01.S10` closure. Active unchecked served-capability-contract step `W05.P10.S44` still requires preset-list `eligible` and run-start-response `eligible` to mean the same thing. Corrected `W05.P10.S28` permits a retained preset signal only as topology readiness with zero provider, model, control, fallback, profile or execution-selection authority. Run-start eligibility is the accepted dispatch/admission result after catalog selection and other live gates. Equating the two either restores selection authority to preset discovery or makes run admission report only topology readiness. Retire S44's obsolete profile-eligibility equivalence; constrain any preset signal to S28 topology readiness, and independently remove the redundant run-start boolean or define it only as the accepted dispatch result.

### no-legacy-curation-corrected-formal-rereview | high | FAIL - requested corrections pass but one active row remains contradictory

Type: formal architecture re-review disposition. Status: open at `d9fd625587fbcb45857741bd8c8de94483f61ca9`. The Kimi amendment fully resolves the accepted-ADR conflict while preserving Kimi ACP transport, current authentication, exact permission handling, per-run isolation and provisioning; it explicitly removes static maps, profiles, preset selection, deprecated aliases and the rejected alternate transport as fallback authority. Corrected S28 unconditionally removes every profile field and bounds any retained eligibility signal to topology readiness with zero provider/model/control/fallback/profile/selection authority. Historical execution records remain unchanged, runtime drift remains open under catalog `P01.S10` with proof in `P01.S11` and `P03.S20`, and no plan row closes. Accepted-ADR rescan finds no remaining conflict, but active S44 contradicts S28 as described above. Core reports zero errors and zero warnings for provider-model-catalog, embedded-runtime-remediation, kimi-provider and served-capability-contract. Formal PASS remains blocked until S44 is corrected and re-reviewed.

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
