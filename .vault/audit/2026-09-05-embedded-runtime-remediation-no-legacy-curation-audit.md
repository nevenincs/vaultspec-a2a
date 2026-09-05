---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:4ec7418a844c07f5fcff8f5df2214981d19b4fc0e6b074066be4c370c55160a8'
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

### active-served-contract-eligibility-equivalence-resolution | high | resolved in unchecked plan row

Type: lifecycle conflict resolution. Status: corrected on 2026-09-05 after review commit `bdeb379482eabbb26a6af09e79a3d69de18565e4`; formal re-review remains pending. Active unchecked step `W05.P10.S44` now keeps the S28 preset-list signal within topology readiness and gives it zero provider, model, control, fallback, profile, selection, admission or dispatch authority. The step independently requires removal of the redundant run-start eligibility boolean or confines any retained result to the accepted dispatch outcome after current catalog selection and all live admission gates. It can no longer make preset or profile eligibility authoritative for selection or admission. The row remains unchecked and no runtime work is claimed.

### no-legacy-curation-second-correction | high | remaining active-row conflict corrected

Type: architecture lifecycle correction. Status: corrected in the active plan and recorded as resolution evidence. The obsolete requirement that preset-list eligibility equal run-start eligibility has been removed from `W05.P10.S44`. The plan now treats topology readiness and post-selection dispatch acceptance as separate facts with separate authority. Historical FAIL findings remain above as review evidence; provider-model-catalog `P01.S10`, its proof steps and remediation work remain open.

### no-legacy-curation-final-formal-rereview | low | PASS - one catalog decision owns provider and model selection

Type: formal architecture review disposition. Status: resolved through `665a26f94fe3a1f4af84a72bef0c3d8c2bf36d7e`. Final re-review confirms `W05.P10.S44` treats any retained preset signal only as topology readiness with zero provider, model, control, fallback, profile, selection, admission or dispatch authority, while the independent run-start result is removed or limited to accepted dispatch after current catalog selection and all live gates. The Kimi amendment preserves ACP transport, current authentication, exact permissions, per-run isolation and provisioning while making its former static maps, profile overlay, preset assignment, deprecated aliases and alternate fallback non-governing. S28 still removes profile fields unconditionally.

Repository-wide accepted-ADR, active unchecked-plan and current-reference scans find no remaining competing provider/model/profile selection authority. The multi-provider and Kimi records use dated supersession pointers; the model-profiles record is superseded; current references classify legacy paths as source drift or refusal evidence; historical execution and audit facts remain unchanged. Provider-model-catalog remains 14/21 with `P01.S10`, `P01.S11` and `P03.S20` open; served-capability `S28` and `S44` remain unchecked. The live runtime CRITICAL remains accurately open under `P01.S10`, with proof owned by `P01.S11` and `P03.S20`; this documentation review claims no runtime correction or plan closure. The correction commit changes exactly the served-capability plan and the two rolling audit documents. Core reports zero errors and zero warnings for provider-model-catalog, embedded-runtime-remediation, kimi-provider and served-capability-contract. No critical, high or medium defect remains in the architecture curation itself.

### acp-available-models-compatibility-fallback | high | active authority resolved; runtime removal remains P01.S10

Type: provider catalog compatibility conflict. Live source audit found generic
ACP discovery accepting `models.availableModels` when current `configOptions`
were absent. That path converts an obsolete response into current catalog
selection authority and violates the no-translation rule. The accepted catalog
ADR now makes negotiated `configOptions` the only ACP catalog collection; the
catalog plan requires direct removal and typed negative proof. Runtime and test
completion remain open under `P01.S10` and `P01.S11`; no row is closed here.

### gemini-old-config-compatibility-lane | high | active authority resolved; runtime removal remains P01.S10

Type: provider inventory and lifecycle conflict. Live source and document audit
found `gemini/gemini-cli-acp` retained as a registered but unadmitted lane solely
to keep old configurations working. Accepted provider-abstraction,
agent-harness, and catalog wording plus current references could therefore be
read as ongoing provider, auth, provisioning, permission, construction, catalog,
or wire support. Dated amendments now retire that lane in full, and the active
catalog plan requires its absence rather than a blocked disposition. Frozen S01
and S03 mode captures remain historical evidence and are explicitly bounded to
their captured commits. Runtime removal and proof remain open under `P01.S10`,
`P01.S11`, `P03.S19`, and `P03.S20`; no plan row is closed.

### acp-gemini-no-legacy-curation | high | active documents reconciled

Type: architecture lifecycle correction. Status: corrected on 2026-09-06;
formal re-review pending. Provider-model-catalog is the single current authority:
ACP catalogs are configOptions-only, the external product inventory has seven
lanes, and Gemini-specific provider support has no dormant compatibility
posture. Historical research, execution, audit, and frozen inventory output are
preserved as dated evidence. Live runtime work remains owned by the executor.

### accepted-tool-cores-gemini-proof-obligation | high | open

Type: accepted-ADR and active-plan conflict. Status: open at expanded curation commit `e76aff0dd5550d5fb041150760eb70ce0725f327`; blocks the no-legacy curation review and catalog `P01.S10` closure. Accepted `2026-08-01-tool-cores-web-grounding-adr` still defines Gemini as one of five command-line lanes, says every provider lane must receive web search, and treats a lane left unproven as unfinished delivery. Active unchecked `2026-08-01-tool-cores-plan` `P03.S16` requires completed-retrieval proof for every remaining command-line lane. Read together, they retain a future Gemini activation and proof obligation after the catalog ADR retired `gemini/gemini-cli-acp` completely. Amend the tool-cores ADR so universal web delivery ranges only over current catalog lanes, makes its Gemini lane clauses historical, and creates no proof or activation debt for the retired lane; align P03.S16 without closing it.

### accepted-integration-smoke-gemini-compatibility | high | open

Type: accepted-ADR compatibility conflict. Status: open at `e76aff0dd5550d5fb041150760eb70ce0725f327`; blocks the no-legacy curation review and catalog `P01.S10` closure. Accepted `2026-03-31-integration-testing-smoke-tests-api-verification-adr` states that the repository supports a real Gemini path, that real provider paths remain available, and that a retained opt-in compatibility track may exercise Gemini. Those are current availability and testing obligations, not immutable execution evidence, and they contradict total retirement. Add a dated amendment retaining deterministic service certification and opt-in compatibility testing for current catalog lanes while explicitly removing Gemini availability, smoke, and future-proof obligations. Its completed historical plan and test facts need no rewrite.

### accepted-rule-propagation-gemini-example | medium | open

Type: single-home documentation drift. Status: open, non-blocking by itself. The accepted `2026-03-31-universal-rule-propagation-adr` was accepted for its provider-agnostic RuleManager mechanism, and its 2026-07-15 reconciliation note identifies that mechanism as the live decision. Its original body still calls Gemini supported, uses a Gemini CLI equivalence example, and mentions `.gemini/rules`. Those examples do not register, provision, select, construct, or dispatch a lane, but they can be misread as current provider inventory. Add a short dated interpretation that the examples are historical and current applicability follows the catalog inventory. Preserve the generic rule-injection decision.

### non-authoritative-gemini-history-and-antigravity-vendor-data | low | verified

Type: review disposition. The dependency-hygiene ADR's Gemini sentence records why a package was removed; the multi-provider ADR has a dated catalog-authority amendment; completed plans, frozen eight-mode captures, executable-version capture, and old source references remain historical facts. None creates current selection authority. Current Antigravity code's `.gemini/antigravity-cli` credential path and Gemini-branded model labels are vendor storage and opaque catalog data under `antigravity/antigravity-cli`; they do not recreate a Gemini provider, execution mode, auth path, factory branch, or wire value.

### expanded-gemini-retirement-curation-formal-review | high | FAIL - two accepted obligations remain

Type: formal architecture review disposition. Status: open through A2A `e76aff0dd5550d5fb041150760eb70ce0725f327` and Dashboard `5cae73928c8ffb4b47dcb322971a002ef208a258`. The expanded catalog, provider-abstraction, harness, current references, and active catalog steps correctly establish configOptions-only ACP discovery, exact seven-mode current inventory, complete Gemini retirement, typed fail-closed old-state handling, and historical-only interpretation for frozen eight-mode records. Dashboard's edge, flow, shell, and unchecked agent-panel rows correctly require topology-only presets, schema-v1 catalog selection, no profile/legacy restart/Gemini compatibility, and close no row; its generic provisioning ADRs promise only generic runtime/provider-asset lifecycle and need no amendment. Exact scopes are nine A2A paths and six Dashboard paths; historical records are preserved, and runtime removal remains open. Feature Core reports zero errors and zero warnings for all six reviewed A2A features and Dashboard agent-panel. The tool-cores and integration-testing accepted obligations above prevent PASS; the rule-propagation example is additional MEDIUM drift.

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
