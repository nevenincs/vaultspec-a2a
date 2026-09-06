---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-09-06'
body_schema: 'body-v1'
body_hash: 'sha256:7ecde793a55e042fdf8523099c89424e1d798122fdd658ada3331dd77ede6655'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-reference]]"
---
# `provider-model-catalog` audit: `P01.S10 policy retirement review`

## Scope

Review of product preset policy removal, static model-map retirement, exact
catalog-frozen compiler and factory authority, public schema contraction,
retired-state refusal, ACP catalog compatibility removal, and complete retirement
of the Gemini provider lane.

## Findings

### exact-catalog-selection-is-the-only-construction-authority | resolved

Commit `15766f92` removes `Model`, `MODEL_MAP`,
`PROVIDER_DEFAULT_MODELS`, preset provider/model/default/profile fields, profile
DTOs, and model-profile resolution. `ProviderFactory.create` requires an exact
model argument. Compilation requires schema-v1 catalog-frozen role and supervisor
selections and carries the exact provider value, execution mode, controls and
fallback selections without consulting product presets or a static external map.

### retired-stored-model-policy-fails-closed | resolved

Redispatch accepts only `provider_catalog_selection`. A stored `model_profile`
key produces `RetiredModelProfileStateError`, marks the run failed with a bounded
unsupported-state reason, and continues the sweep without constructing a model
or contacting the worker. Missing, malformed, stale or invalid current selection
also fails before `DispatchRequest`; no retired value is read, disclosed,
translated, migrated, substituted or redispatched.

### deprecated-provider-and-catalog-surfaces-are-absent | resolved

The Gemini provider enum, `gemini-cli-acp` registration, readiness, settings,
auth refresh, subprocess construction, permission branches, provisioning and
artifacts are removed. ACP discovery consumes `configOptions` only and ignores
`models.availableModels`. Codex discovery consumes `serviceTiers` only and ignores
`additionalSpeedTiers`. Retired Kimi environment aliases are ignored. OpenAPI has
no Gemini provider value or profile/model-profile field.

Antigravity remains a distinct supported lane. Its provider-owned credential path
is `.gemini/antigravity-cli`, and its provider-advertised catalog may contain
Gemini-branded model labels. Those facts do not register, construct or translate
a Gemini provider lane. Workspace environment scrubbing retains `GEMINI_API_KEY`
only as a deny-list key so an ambient retired credential cannot leak into a child
process.

### deleted-compatibility-tests-have-current-discriminators | resolved

- Deleted model-profile resolver and lane-admission groups are replaced by exact
  served-selection freeze/compiler tests, in-process executable-selector tests,
  required-model factory tests, and the zero-authority source/schema assertion.
- Deleted preset profile/web-policy tests are replaced by preset source scans,
  schema rejection, and current persona/topology tests.
- Deleted legacy API evidence is replaced by current catalog-selection gateway
  persistence evidence and OpenAPI rejection assertions.
- Deleted legacy restart support is replaced by typed stale-key refusal and real
  redispatch tests proving terminal failure with no worker contact.
- Deleted Gemini auth/factory tests are replaced by enum/registration absence,
  nonconstructibility, and source-symbol discriminators.
- Removed ACP and Codex fallback acceptance tests are replaced by assertions that
  retired payload fields yield no catalog authority.

### postgres-sync-driver-test-environment | medium | queued

Type: dependency and test-environment provisioning. Status: open and nonblocking
for P01.S10. Eight full-suite tests derive the correct psycopg URL and then fail
because `psycopg` is absent from the active environment. Owner: database and
repository-tooling maintenance.

### desktop-terminal-context-fixture-drift | medium | queued

Type: test contract drift. Status: open and nonblocking for P01.S10. The desktop
owned-process-tree fixture supplies a terminal context without the current
`closing` field, so the handler returns an error before the test can inspect the
terminal id. Owner: desktop process-lifecycle tests. The associated closed-pipe
unraisable warning is a low-severity secondary symptom owned with this finding.

### missing-canonical-prek-hooks | medium | queued

Type: repository tooling drift. Status: open and nonblocking for P01.S10. Core
doctor reports that `prek.toml` lacks the canonical Vaultspec hooks. Owner:
repository-tooling-hardening; repair requires the Core migration verb outside
this Step.

### stale-process-and-mixed-provider-host-state | low | queued

Type: operational and host-provisioning hygiene. Status: open and nonblocking for
P01.S10. Core doctor reports six stale process records and mixed Claude, Gemini
and Codex host directories. Owner: process/workspace lifecycle and operator
provider provisioning. The inert Gemini directory is host state, not runtime
support.

### starlette-anyio-alias-deprecation | low | queued

Type: upstream dependency debt. Status: open and nonblocking for P01.S10. The
suite reports Starlette's deprecated AnyIO `BlockingPortal` alias. Owner:
dependency maintenance.

## Verification

- Focused provider/catalog/factory/config/API set: 147 passed.
- Provider, team, graph, catalog/control, gateway and schema domain set: 1,536
  passed, 38 deselected.
- Post-fix provider/compiler/worker set: 208 passed, 6 deselected.
- Full repository suite: 4,355 passed, 3 skipped, 188 deselected, 11 failed;
  the two S10 test-contract failures were corrected, leaving the nine queued
  environment/baseline failures above.
- Ruff lint and format checks pass for every changed Python path; compileall and
  `git diff --check` pass.
- OpenAPI generation passes and the generated enum contains exactly nine current
  providers with no Gemini value or retired profile fields.
- Ty has no S10 diagnostic and stops on five missing optional dependencies outside
  this Step. Strict Basedpyright remains a known repository-wide red baseline.
- Feature-scoped Core validation passes every check. Core doctor embeds a clean
  Vault Check and reports only the queued operational/tooling warnings above.
- Architecture curation formal review passes at
  `45a0a0093cfc38d7595583b8289d2c744429bd7a`.

## Recommendations

- Keep P01.S11 open for its independent real-behavior proof boundary.
- Keep remediation W01.P02.S05 open until its assembled provider-selection
  prerequisites and formal review close on their own evidence.
- Resolve the queued environment, desktop and repository-tooling findings in
  their owning workstreams without restoring any retired provider or model
  authority.

## Formal code review of `15766f92`

### frozen-selection-accepts-retired-and-unknown-nested-authority | high | open

Type: state compatibility and schema validation. Status: review-blocking for
`P01.S10`. `frozen_team_selection_from_record()` validates persisted selection
layers as generic JSON objects and then reads only recognized keys. Unknown keys
are omitted from the canonical digest input rather than rejected. Independent
review took a real selection produced by `freeze_team_selection()`, added
`profile_id` at the record root, `model_profile` inside `selection`, or
`profile_id` inside a native control without changing the digest, and every
variant was accepted. The IPC boundary has the same gap:
`DispatchRequest.model_assignment` is `dict[str, dict[str, Any]]` and accepts a
nested retired profile field. Consequently a retired or future authority can
cross durable-state and worker boundaries while the implementation reports that
all such state fails terminally.

Ownership: correct `P01.S10` by applying a closed, exact-key typed schema at the
record root, selection, override, fallback, control and IPC assignment layers.
Reject every unknown field and explicitly discriminate `profile_id`,
`default_profile_id`, `profile`, and `model_profile`. Add real redispatch tests
for each nested retired shape that prove the affected thread becomes terminal
before a dispatch request, model construction, or worker/provider contact, plus
IPC negative-validation tests.

### corrupt-execution-mode-is-treated-as-lane-unavailability | high | open

Type: safety, state compatibility, and fail-closed behavior. Status:
review-blocking for `P01.S10`. The persisted-selection parser validates only that
`execution_mode` is nonempty and that `provider_id` belongs to the provider enum;
it does not validate the exact provider/mode pair against the current catalog
inventory. A coherent-digest record containing `codex/unavailable-mode` was
accepted. In worker compilation, `ProviderFactory.create()` rejects that mode
with `ValueError`, but `_resolve_model_for_worker()` catches the same broad
exception as runtime `ConfigError` and advances to the next frozen fallback. The
committed `test_compiler_uses_the_next_exact_frozen_lane_when_primary_is_unavailable`
encodes this behavior with the literal impossible mode `unavailable-mode`.
Structurally corrupt durable authority is therefore substituted rather than
failed terminally before provider construction.

Ownership: correct `P01.S10` by validating every primary, override and fallback
provider/mode/control shape as current catalog-frozen structure before any
factory call. Keep structural validation failures distinct from bounded runtime
lane unavailability. A corrupt or retired shape must terminally fail the thread;
only a structurally valid frozen fallback may follow a true runtime-unavailable
result. Add gateway-restart/redispatch proof with a coherent digest and invalid
mode, asserting no provider or worker contact.

### lane-admission-integrity-regressions-lost-with-deleted-suite | medium | open

Type: test coverage and evidence integrity. Status: open and nonblocking only
after the two HIGH runtime defects are corrected. Deleting the 500-line
`test_lane_admission.py` removed current discriminators that are not replaced by
the in-process or route suites: every provider classified, generic unknown lane
deny-by-default, every proof citation resolving to a live test, rotten-citation
detection, proof-map immutability, and web-proof implying completed-turn proof.
Profile eligibility cases in that file are legitimately obsolete, but these
remaining checks still protect `lane_admission.py` and catalog admission.
Ownership: `P01.S10` test replacement map; retain adapted current-catalog tests
for the still-live invariants without restoring profile authority.

### preset-web-claim-regression-guard-was-deleted | medium | open

Type: product-truth test coverage. Status: open. The deleted
`test_preset_web_claims.py` was the only anti-vacuous scan of every shipped team
preset description for live-web/research claims. Persona and graph web tests
cover different surfaces. With presets now topology-only, the applicable
invariant is stronger and simpler: no shipped preset description may promise
online research or web access. Ownership: `P01.S10` test replacement map; restore
an anti-vacuous topology-only preset-description scan without provider, model,
profile, or eligibility policy.

### p01-s10-formal-code-review | high | fail

Type: formal implementation review disposition. Status: open at implementation
commit `15766f92bdb094a78ab783620522547e3223ea5a` against exact parent
`45a0a0093cfc38d7595583b8289d2c744429bd7a`. The commit has the declared
121-path, +1,146/-6,558 scope. It successfully removes Model/MODEL_MAP/default
model and profile authority, the Gemini lane/config/auth/RPC/factory/artifact
surface, ACP `models.availableModels` compatibility, deprecated Kimi aliases and
Codex `additionalSpeedTiers`; preserves Antigravity's vendor-owned `.gemini`
data; keeps exactly seven external and two explicitly armed in-process modes;
requires exact model arguments at production compiler/factory call sites; keeps
supervisor/worker arity and current-schema restart evidence; contracts public
API/OpenAPI/snapshot surfaces; and retains non-Gemini project confinement tests.

Formal review fails because the two preceding HIGH findings allow retired nested
state and coherent corrupt execution modes through persisted/IPC authority, then
permit substitution through fallback. The earlier `retired-stored-model-policy-
fails-closed` and `deleted-compatibility-tests-have-current-discriminators`
entries describe implementation intent but are superseded for closure by this
review evidence. Do not close `P01.S10` until corrections and re-review pass.

Focused verification at the exact commit produced 235 passes after supplying the
repository's installed Node dependencies to the detached review worktree; the
initial single failure was only the absent worktree-local ACP JS artifact and
passed when the same locked dependency tree was exposed. OpenAPI artifact
regeneration, Ruff lint, Ruff formatting for 85 changed retained Python paths,
and `git diff --check` pass. Independent adversarial probes reproduced all
retired-field and invalid-mode acceptances above. The implementer's full-run
accounting remains 4,355 passed, 3 skipped, 188 deselected, and 11 failed, with
the nine unrelated server-profile/desktop baseline failures already queued.

## Formal re-review of correction `e2934a2e`

### frozen-selection-and-ipc-schema-closure | low | prior high resolved

Type: state compatibility and schema validation. Correction
`e2934a2e136a434bac4852af0902ed9cf5d204c6` applies exact required/optional key
sets at the persisted root, primary lane, override, fallback, native-control and
replay layers and rejects additional provenance keys. IPC model assignments
apply the same closed nested shape. Existing-digest additions of `profile_id`,
`default_profile_id`, `profile`, `model_profile` or any other field are refused;
redispatch marks invalid records terminal without worker contact. The first
formal review's nested-authority HIGH is resolved.

### whole-assignment-provider-mode-prevalidation | low | prior high narrowed

Type: safety and fail-closed behavior. Compilation now parses every role's
primary and fallback lanes and validates every current provider/execution-mode
pair before the first provider-factory call. Persisted reconstruction validates
the same 7 external plus 2 explicitly armed in-process mode inventory. Tests
cover a corrupt later role and corrupt fallback with zero factory calls, while a
valid lane whose construction raises runtime `ConfigError` may use an exact
valid fallback. The first review's impossible-mode substitution is resolved.

### structural-factory-value-errors-still-enter-fallback | high | open

Type: safety, state compatibility, and fail-closed behavior. Status:
review-blocking for `P01.S10`. Whole-assignment prevalidation validates control
record keys and string shapes but not provider-specific control ids,
duplicates after provider field normalization, or allowed control semantics.
`_resolve_model_for_worker()` still catches every `ValueError` raised by
`ProviderFactory.create()` together with runtime `ConfigError` and advances to
the next fallback. The real factory uses `ValueError` for unsupported Codex and
Kimi native controls, duplicate normalized Codex controls, controls on providers
that support none, backend conflicts, invalid authentication configuration and
other structural failures. Independent review supplied a closed, current
`codex/codex-app-server` primary with `retired-control`; a factory raising the
real unsupported-control `ValueError` was logged as unavailable and the valid
fallback was constructed and returned. In-process mock/deterministic branches
also return before rejecting nonempty controls.

Ownership: finish `P01.S10` by prevalidating provider-specific native-control
semantics for every primary/override/fallback before any construction and by
replacing the broad exception contract with a typed runtime-lane-unavailable
outcome. Catch only that typed runtime condition for fallback. Structural,
auth/configuration and unsupported-control errors must substitute nothing and
must fail the run terminally. Add multi-role tests with unsupported, duplicate,
and provider-inapplicable controls in a later role and fallback, proving zero
factory calls, plus a production-factory discriminator showing only the typed
runtime-unavailable condition reaches fallback.

### current-admission-and-preset-claim-coverage | low | prior mediums resolved

Type: evidence integrity and product-truth coverage. New current-only tests cover
every provider's explicit classification and deny-by-default result, exact
provider resolution, live and rotten proof citations, immutable declarations,
and the web-proof-implies-turn invariant. The topology-only preset scan reaches
at least ten shipped presets, proves real/nonempty surfaces, and forbids live-web
or online-research claims without restoring profile policy. Both MEDIUM coverage
findings from the first review are resolved.

### p01-s10-correction-formal-rereview | high | FAIL

Type: formal implementation review disposition. Status: open at correction
`e2934a2e136a434bac4852af0902ed9cf5d204c6`, exact parent
`6f1b33963408170df08c6dcd59edd5aaf7b23ad0`. The thirteen-path correction is
scoped to the reported trust boundaries, tests, and two stale fixtures updated
to current exact schema values. It resolves the original two HIGH cases for
unknown nested fields and impossible provider/mode pairs and restores both
MEDIUM test surfaces. The no-legacy removals, exact 7+2 inventory,
current-schema restart, required factory model signatures/call sites,
API/IPC/OpenAPI contraction, Gemini retirement, ACP configOptions-only behavior,
Kimi alias refusal, Codex tier retirement, project confinement, streaming
snapshots and deletion replacement map remain intact.

Formal re-review fails because the remaining structural-control `ValueError`
path still substitutes a fallback. Independent exact-commit focused verification
passes 136 tests across selection, IPC, admission, preset claims, redispatch,
graph compilation and factory behavior; the recorded correction evidence also
reports 135 focused and 63 graph passes plus 14 correction-specific cases.
Ruff lint/format for all thirteen retained paths and `git diff --check` pass.
The independent broad-suite terminal result is recorded separately when its
running exact-commit invocation completes. Do not close `P01.S10` until the HIGH
finding is corrected and formally re-reviewed.

## Final formal re-review through `6e7015a6`

### structural-native-control-fallback-gap | high | resolved

Type: safety and fail-closed behavior. Final correction
`6e7015a6c55fdf8633dbd35e4d8f40caa13425ed` retains whole-assignment
provider/mode and provider-specific native-control validation for every primary,
override and fallback before any provider construction. Unsupported,
duplicate-normalized and provider-inapplicable controls raise structural
`ValueError`; missing API authentication also remains structural. The compiler
catches only `ProviderRuntimeUnavailableError`, a dedicated `ConfigError`
subtype emitted by the production factory when a structurally valid ACP lane's
required runtime executable is absent. No broad `ValueError` can enter fallback.
Later-role, primary and fallback-control tests prove zero factory contact, while
a valid typed runtime outage alone reaches an exact frozen fallback. The
remaining HIGH from the preceding correction review is resolved.

### production-runtime-unavailability-proof-used-monkeypatch | medium | resolved

Type: test integrity. Superseded correction `98b61322` briefly used pytest
monkeypatching to replace `_classify_acp_command`, contrary to the repository's
real-behavior test rule. Final correction `6e7015a6` removes that test and uses
the real repository filesystem boundary: when the optional binary ACP artifact
is absent, production `ProviderFactory.create()` classifies the missing
executable as `ProviderRuntimeUnavailableError`. On the reviewed checkout the
artifact is absent and the discriminator runs and passes. The composed compiler
test separately proves that this typed condition, and only this condition,
selects the next structurally valid frozen lane.

### p01-s10-final-correction-rereview | low | PASS

Type: formal implementation review disposition. Status: resolved through
`6e7015a6c55fdf8633dbd35e4d8f40caa13425ed`. Final review confirms closed
exact-key validation at persisted root, replay, lane, override, fallback,
control, provenance and nested IPC layers; valid-digest retired or unknown keys
fail terminally without contact; every role and fallback is prevalidated against
the current provider/mode and native-control inventory; structural corruption
cannot reach fallback; and only a typed, structurally valid runtime outage can
select an exact frozen fallback. The restored admission suite covers every provider, deny-by-default, live and
rotten citations, declaration immutability and web-proof-implies-turn. The
anti-vacuous preset scan covers real topology descriptions and forbids unearned
web claims.

The full original review surface remains conformant: exactly seven external and
two explicit in-process modes; current-schema restart and terminal refusal of
absent, corrupt or retired state; required exact factory model values and
production call sites; contracted API, IPC, OpenAPI and streaming snapshots;
complete Gemini removal with Antigravity vendor data preserved; ACP
configOptions-only discovery; ignored Kimi aliases; retired Codex additional
speed tiers; retained project confinement; and a complete deletion replacement
map. The two stale fixture edits use the current exact Codex mode and required
provenance and do not weaken their bounds.

Independent exact-commit factory verification passes 46 tests. The final broad
exact-commit provider, team, graph, IPC, redispatch and catalog-restart suite
passes 1,378 tests with 38 deselected and zero failures in 270.47 seconds. Ruff,
format, Ty and diff checks pass. Feature Core validation is clean at the final
audit commit. No critical, high or medium runtime defect remains. This review
passes, while Core plan closure and the uncommitted S10 Step Record remain owned
by the executor.
