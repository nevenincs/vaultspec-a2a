---
tags:
  - '#reference'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:7b15ce82240b1eccc93133fb08295e2af03bc52f4754e18d571289cefb261d49'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-qualification-inputs-reference]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-reference]]"
  - "[[2026-08-02-provider-model-catalog-p03-integration-preflight-audit]]"
  - "[[2026-08-02-provider-capability-evidence-plan]]"
  - "[[2026-08-02-provider-capability-evidence-adr]]"
---
# `embedded-runtime-remediation` reference: `Provider Selection Prerequisite Evidence`

## Summary

Provider-model-catalog `P03.S19` and `P03.S20` are open prerequisites, not completed evidence. Current source contains most catalog, selection, freeze, Dashboard broker, and UI mechanics, but the owner plan still has `P01.S10`, `P01.S11`, `P03.S19`, and `P03.S20` open. The capability-evidence owner plan is 0/4. Catalog enumeration, a selectable flag, a historical admission citation, a provider handshake, a skipped live test, or an in-process lane cannot close either cross-repository step.

Capture identities are A2A `803dca968945d703092dbe8ecfaee0c6290cbd9f` and Dashboard `89706fb2641bd5482667437ae1e4abf2d8194fd8`. Later remediation Step `W05.P12.S57` must repeat the dependency check against the actual released A2A binary and receipt-matched Dashboard consumer; this record does not substitute the S01 build or either current source checkout for that final pair.

## Governing no-legacy update (2026-09-06)

Provider-model-catalog `P01.S10`, `P01.S11`, `P03.S19`, and `P03.S20` now
apply the catalog ADR's 2026-09-06 correction. Generic ACP discovery uses only
negotiated `configOptions`; `models.availableModels` must be refused or ignored
as an unsupported compatibility shape and cannot produce a catalog entry.
`gemini/gemini-cli-acp` is retired rather than retained as a denied lane.

The required current external-mode inventory after `P01.S10` contains seven
lanes: Antigravity, Claude ACP node, Codex app-server, Kimi ACP, OpenAI API,
Z.AI ACP node, and Zhipu OpenAI-compatible API. `P03.S19` must retain that exact
inventory and its configOptions-only ACP source. `P03.S20` must prove no Gemini
provider, mode, configuration, construction, catalog, admission, or Dashboard
wire value remains and must prove typed refusal of retired identifiers. The
Gemini row and eight-mode JSON below are immutable S03 capture evidence from
A2A `803dca968945d703092dbe8ecfaee0c6290cbd9f`, not current support or an
eligible blocked disposition.

## Frozen prerequisite status at the S03 capture

`vaultspec-core vault plan status` reports provider-model-catalog at 14/21 complete and flags checked `S08` as lacking a Step Record. The historical feature ledger lists target paths, including unchecked work, and is not positive execution evidence. Provider-capability-evidence reports 0/4; `provider_capabilities.py` exists, but source presence and its one ledger target entry do not close composition, population, exact-lane proof, invalidation, or served disclosure.

The captured exact-mode registry had eight external registrations. Only `codex/codex-app-server` is admitted, by a literal historical completed-turn citation to `test_pw7_research_adr_materializes_two_documents[codex]`. The other seven modes remain denied for lack of an exact-mode completed-turn proof: `antigravity/antigravity-cli`, `claude/claude-agent-acp:node`, `gemini/gemini-cli-acp`, `kimi/kimi-code-acp`, `openai/openai-api`, `zai/zai-claude-agent-acp:node`, and `zhipu/zhipu-openai-compatible-api`. Provider-level turn citations for Claude and Z.AI do not transfer to their catalog execution modes. Web citations for Claude and Codex prove only their exact retrieval capability and do not prove S19/S20. In-process deterministic/mock lanes remain excluded from external-provider and Dashboard product proof.

## Exact evidence required from `P03.S19`

The owner step closes only with one retained, rerunnable, non-skipped positive path using a real selectable external catalog lane and real processes across Dashboard client, Rust broker, A2A gateway, worker, provider factory, and provider transport:

1. Record clean repository revisions, the served A2A executable/version/hash, Dashboard generation and component receipt, host/tool versions, exact commands, environment boundary, and retained logs. A source-only or mismatched pair is insufficient for `W05.P12.S57`.
2. Issue an authenticated catalog query from Dashboard. Retain the A2A-produced `api_version`, provider and execution-mode key, health axes, catalog schema/revision/timestamps/expiry, opaque entry id, model choice, attached native controls, selectability, and exact scope. Prove Dashboard and Rust forward these values without hard-coded replacement or cross-scope reuse.
3. Select the currently served entry and at least one provider-native control when the lane advertises one. Send a stable run identity through Rust prepare and commit. Prove A2A revalidates the same live workspace catalog, exact mode, revision, membership, controls, required roles, overrides, and ordered fallbacks before durable creation.
4. Retain the normalized selection and complete selection digest. At worker prompt setup, observe the exact internal provider model value and provider-native control values resolved from that selection. Compare provider id, execution mode, catalog revision, entry id, control ids/options/values, default provenance, per-role overrides, ordered fallbacks, and digest with the persisted freeze and `run-status`; every compared value must be unchanged.
5. Prove a real prompt reaches the intended exact provider lane and returns completed work through that production construction. A catalog response, `selectable=true`, executable presence, account handshake, model construction, or a skipped credential-gated test is not this evidence. Any newly admitted mode needs its own separately identified completed-turn proof and matrix update before it can be selected.

At the current posture, Codex app-server is the only eligible external candidate. This observation does not declare its live catalog available on this host and does not re-earn its historical admission.

## Exact evidence required from `P03.S20`

The owner step closes only when the assembled two-repository path retains positive and negative evidence for every named state without mocks, monkeypatches, expected failures, or a skip counted as a pass:

- **Refresh:** drive real A2A refresh/expiry, observe a new authoritative revision or refreshed timestamp, and prove Dashboard schedules from served expiry, clears prior-scope data, and consumes the refreshed catalog without inventing freshness.
- **Stale selection:** retain a served reference, change or expire its authoritative catalog, submit it, and prove refusal before reservation/dispatch/durable run creation. No cached Dashboard choice may override A2A membership and revision checks.
- **Unauthenticated:** make catalog and run-selection calls with absent/invalid attach authentication and prove typed refusal, no catalog/model disclosure beyond the contract, no durable state, and no credential in browser state or logs.
- **Unavailable and unadmitted:** exercise a real registered lane with a controlled missing command, credential/auth failure, unavailable/expired catalog, or exact-mode admission absence. Preserve each independent health axis and safe reason, keep it unselectable, and prove configured, enumerated, or handshake-ready state cannot outvote admission.
- **Admitted:** use a separately proven exact execution mode and show admission combines with current configuration, transport, authentication, fresh catalog, and membership. Re-run the cited positive proof or retain new equivalent real-work evidence; do not inherit a provider-level or sibling-mode citation.
- **Replay/conflict:** lose or withhold the first run-start acknowledgement, replay the identical run id, prepare/commit identity and normalized selection, and prove one durable run, one dispatch and the identical frozen receipt without requiring current catalog membership. Reuse the identity with changed selection, controls, overrides, fallback order, or payload and prove a typed conflict with no second dispatch.
- **Legacy-state refusal:** submit every retired `profile_id`/assignment request and response shape and seed representative pre-catalog `model_profile` durable state. Prove each boundary returns a bounded typed unsupported/incompatible result before provider construction or dispatch, serves no retired provider/model fields, performs no translation, migration or substitution, and never redispatches the run. Prove current schema-v1 catalog-backed restart independently.
- **Dashboard state:** across a real local engine transport, prove exact scope fencing, no previous-scope placeholder, expiry-driven refetch, unavailable rendering, stale-choice clearing, current selection submission, and authoritative frozen assignment rendering. Browser-only fixture state or a Rust loopback body authored by the test is preparation, not A2A producer evidence.

Every case records whether a provider credential or external service was absent. Absence leaves that case `BLOCKED`; it does not become pass, unsupported, or non-applicable.

## Gated qualification and independent work

`W05.P12.S57` is the explicit gate: it must verify both owner steps against the intended released binary/consumer before external qualification. Until then, provider-selection portions of A05-A07 and the provider/Dashboard portions of A01/A04 remain blocked. The dependent provider steps `W05.P12.S58-S63` cannot use catalog selection, frozen assignment, capability, permission, command, fault, or stop claims as qualified evidence. `W05.P13.S64` may exercise provider-independent Dashboard CRUD, auth, readiness, and stream cases, but its live catalog/run-selection and frozen-assignment claims remain blocked. Packaged lifecycle `S65`, local load/latency `S66`, `S67`, `S73-S75`, and diagnostics `S68` may proceed on provider-independent substrates; they cannot be reported as external-provider evidence until S57 passes.

Independent remediation may continue through W01.P02 environment repairs, W02 durability/concurrency/cancellation work, W03 context and provider-control implementation, W04 broker/lifecycle/artifact conformance, provider-capability matrix work `W03.P08.S35-S36` under its own P01/P02 prerequisites, local qualification `W05.P11.S51-S56`, and deterministic/in-process drills. Missing S19/S20 evidence blocks only conclusions that consume real catalog selection, exact external-provider work, or the intended Dashboard pair. It does not authorize relaxing any acceptance threshold or admitting another lane.

## Reproducible live capture

Run from the A2A root:

```powershell
@'
import hashlib,json,re,subprocess
from pathlib import Path
from vaultspec_a2a.providers.factory import ProviderFactory
from vaultspec_a2a.providers.lane_admission import PROVEN_CATALOG_TURN_LANES,PROVEN_TURN_LANES,PROVEN_WEB_LANES,catalog_lane_admission_reason,is_catalog_lane_admissible
root=Path.cwd()
def states(path):
 text=path.read_text(encoding='utf-8'); return {m.group(2):m.group(1)=='x' for m in re.finditer(r'^- \[([ x])\] `([^`]+)`',text,re.M)}
external=[]
for registration in ProviderFactory().catalog_registrations(root,serve_in_process_lanes=False):
 key=registration.key; external.append({'provider_id':key.provider_id,'execution_mode':key.execution_mode,'admissible':is_catalog_lane_admissible(key),'reason':catalog_lane_admission_reason(key)})
out={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'catalog_plan':states(root/'.vault/plan/2026-08-02-provider-model-catalog-plan.md'),'capability_plan':states(root/'.vault/plan/2026-08-02-provider-capability-evidence-plan.md'),'external_modes':external,'catalog_turn_proofs':[{'provider_id':k.provider_id,'execution_mode':k.execution_mode,'test':v.test} for k,v in PROVEN_CATALOG_TURN_LANES.items()],'provider_turn_proofs':sorted(p.value for p in PROVEN_TURN_LANES),'web_proofs':sorted(p.value for p in PROVEN_WEB_LANES),'in_process_unarmed':[]}
raw=json.dumps(out,sort_keys=True,separators=(',',':')); print(raw); print(hashlib.sha256(raw.encode()).hexdigest().upper())
'@ | uv run --locked python -
```

The canonical compact output SHA-256 is `94A91AE6A4D9C4BB450BE9D9A35C26B1487248772A0E854196B509BF21877593`. Its exact JSON is:

```json
{"capability_plan":{"P01.S01":false,"P01.S02":false,"P02.S03":false,"P02.S04":false},"catalog_plan":{"P01.S01":true,"P01.S02":true,"P01.S03":true,"P01.S04":true,"P01.S05":true,"P01.S06":true,"P01.S07":true,"P01.S08":true,"P01.S09":true,"P01.S10":false,"P01.S11":false,"P02.S12":true,"P02.S13":true,"P02.S15":true,"P02.S16":true,"P02.S17":true,"P03.S19":false,"P03.S20":false,"P03.S21":false,"P03.S22":false,"P03.S23":false},"catalog_turn_proofs":[{"execution_mode":"codex-app-server","provider_id":"codex","test":"src/vaultspec_a2a/service_tests/test_pw7_acceptance.py::test_pw7_research_adr_materializes_two_documents[codex]"}],"external_modes":[{"admissible":false,"execution_mode":"antigravity-cli","provider_id":"antigravity","reason":"provider lane antigravity/antigravity-cli has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"claude-agent-acp:node","provider_id":"claude","reason":"provider lane claude/claude-agent-acp:node has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":true,"execution_mode":"codex-app-server","provider_id":"codex","reason":null},{"admissible":false,"execution_mode":"gemini-cli-acp","provider_id":"gemini","reason":"provider lane gemini/gemini-cli-acp has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"kimi-code-acp","provider_id":"kimi","reason":"provider lane kimi/kimi-code-acp has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"openai-api","provider_id":"openai","reason":"provider lane openai/openai-api has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"zai-claude-agent-acp:node","provider_id":"zai","reason":"provider lane zai/zai-claude-agent-acp:node has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"zhipu-openai-compatible-api","provider_id":"zhipu","reason":"provider lane zhipu/zhipu-openai-compatible-api has no exact completed-turn proof; evidence from another execution mode is not inherited"}],"head":"803dca968945d703092dbe8ecfaee0c6290cbd9f","in_process_unarmed":[],"provider_turn_proofs":["claude","codex","zai"],"web_proofs":["claude","codex"]}
```

The source manifest command is:

```powershell
$a2a=(Get-Location).Path; $dash='Y:\code\vaultspec-dashboard-worktrees\main'
$files=@(@{r='A2A';p='.vault/plan/2026-08-02-provider-model-catalog-plan.md';root=$a2a},@{r='A2A';p='.vault/plan/2026-08-02-provider-capability-evidence-plan.md';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/providers/lane_admission.py';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/providers/factory.py';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/providers/provider_capabilities.py';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/api/routes/gateway.py';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/api/schemas/gateway.py';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/providers/model_profiles.py';root=$a2a},@{r='A2A';p='src/vaultspec_a2a/graph/compiler.py';root=$a2a},@{r='Dashboard';p='engine/crates/vaultspec-api/src/routes/ops/a2a.rs';root=$dash},@{r='Dashboard';p='frontend/src/stores/server/agent/a2aProviderCatalog.ts';root=$dash},@{r='Dashboard';p='frontend/src/stores/server/agent/a2aTeam.ts';root=$dash})
$records=@($files|%{[ordered]@{repository=$_.r;source=$_.p;sha256=(Get-FileHash -LiteralPath (Join-Path $_.root $_.p) -Algorithm SHA256).Hash}}); $raw=$records|ConvertTo-Json -Compress; $raw; [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($raw)))
```

The compact manifest digest is `2525AAD195A153019183D3898D36C1634E502A6AE4AAEC06FCE7973417FABA47`. Its exact raw output is:

```json
[{"repository":"A2A","source":".vault/plan/2026-08-02-provider-model-catalog-plan.md","sha256":"B914B5CDD02AC6216B630133DD4CFBBE895CEDF277B96D394D264D8F9D88AF5A"},{"repository":"A2A","source":".vault/plan/2026-08-02-provider-capability-evidence-plan.md","sha256":"26CB0CE1A67AA5704B07DC9EEE1A68FF5D9CF04742B247B2410DE19833D326EE"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/lane_admission.py","sha256":"B32DC03D043B563E42DA49126085FBFACB4F8CF74E23D8779A9800F05B4010FF"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/factory.py","sha256":"2324098BE2A974066E9221BD46A351CD3C3B274C601CDAE0CEBE0FF49A0D7066"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/provider_capabilities.py","sha256":"43DDF43F8336A2DA91C8F3B0C5E71B484199518229BED4927C7AD9789FEE6561"},{"repository":"A2A","source":"src/vaultspec_a2a/api/routes/gateway.py","sha256":"F184422F81404E7C5AA06D02EC95CED239552DDC7D64D51CB6822B83945CB3FE"},{"repository":"A2A","source":"src/vaultspec_a2a/api/schemas/gateway.py","sha256":"1E208D9C470B089CB6893BEBCC9862996E92BD091B4C2AA15A9DB50585C971BD"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/model_profiles.py","sha256":"B440A36E7C4C8CF80A6768BBC0D0786F692973E48E1283EBD4BF9CA68FAFF99E"},{"repository":"A2A","source":"src/vaultspec_a2a/graph/compiler.py","sha256":"D9B83A54B84D5003D79A4B8D05F529A133447EB0CDD76D549CE34F1E3AF0A00E"},{"repository":"Dashboard","source":"engine/crates/vaultspec-api/src/routes/ops/a2a.rs","sha256":"B82A5893856840EDE50874D847F07C6F4FADB803CAE371CD58E3D5C52F78D5C0"},{"repository":"Dashboard","source":"frontend/src/stores/server/agent/a2aProviderCatalog.ts","sha256":"9ED7C056D58C3A3461DD31E62D0D84C0B881BE61F34CB085D817A9CA7F0486E7"},{"repository":"Dashboard","source":"frontend/src/stores/server/agent/a2aTeam.ts","sha256":"34D77E025FE3EBA189D3AAA554D10861C9095FD8FE12545AC2C85B776D1BE81F"}]
```
