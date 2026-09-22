---
tags:
  - '#audit'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:3933b6107f098557910f049698cd0bf3b8cdf00ea223fb9729c1a5e7c8e9bc1b'
related:
  - "[[2026-09-21-open-issue-remediation-plan]]"
---

# `open-issue-remediation` audit: `rolling backlog implementation review`

## Scope

Rolling review of plan execution against current A2A and Dashboard contracts.
Completed review covers P01.S02's Dashboard relay mapping and issue disposition.
P01.S03's Compose workspace-boundary defect remains open pending its execution
boundary Step P01.S10. P01.S06's read-only-hook defect is resolved below, with
its implementation, focused verification, and review evidence recorded before
Step closure. P01.S02 is PASS with no critical or high finding in that lane.

## Findings

### workspace-admission-hardening | high | validation could be bypassed before canonical workspace admission | resolved

P01.S03's independent Terra review confirmed the prior prepare/commit preset
read-before-validation defect is fixed: `gateway.py:277` canonicalizes before
validation, and managed foreign, ancestor, and symlink cases are exercised at
both stages. `test_workspace_root_authority.py` passed all 14 tests with a clean
diff; the Sol full review (67 tests) plus Ruff and Ty also passed. The admission
portion of the issue #25 boundary is resolved. The issue remains open for the
separate P01.S10 OS execution-identity and ACP confinement proof.
### compose-provider-service-state | high | admitted roots and shared identity expose credentials and durable state | open

Development, integration, and production Compose profiles mount one `/app/data`
volume into gateway and worker under the same UID/GID. The database,
`a2a-home/service.token`, and workspaces are siblings below that mount. Run
admission accepts any existing absolute directory, so an authenticated request
selecting `/app/data` gives ACP `fs/read_text_file` direct, confirmed reach to
the bearer handoff and database. Mode 0600 does not separate processes with
the same UID. A path-prefix rule alone is insufficient because provider and
terminal children inherit the worker identity and can name absolute paths outside
their working directory.

The superseded workspace-root ADR incorrectly treated mounts as the complete
boundary. The accepted replacement requires Compose-only canonical descendant
admission plus a distinct, capability-free agent UID/GID for every provider and
terminal/tool child, owner-only service state, and a gateway-only credential
mount. P01.S03 owns admission; P01.S10 owns the OS boundary and negative live
proof. Issue #25 remains open until both pass.

### compose-provider-acp-toctou | high/security | privileged ACP callbacks resolve paths before no-follow access | open

P01.S03/P01.S10 review identified a resolve-to-open time-of-check/time-of-use
exposure in privileged ACP read/write callbacks: a path can be resolved and
validated before an attacker swaps a directory or symlink before the open or
create operation. P01.S10 now owns `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
and `src/vaultspec_a2a/providers/tests/test_project_confinement.py` in addition
to its existing Compose/provider boundary paths. The required proof is
Linux/Compose descriptor-relative, no-follow traversal for reads and
write/create ancestor traversal, directory anchoring, bounded handle lifetime,
and fail-closed behavior, while preserving desktop compatibility. No proof is
claimed yet; issue #25 remains open pending S03 admission and S10 OS-boundary
implementation plus negative live tests.
### staged-hook-isolation | low | shared dirty worktree hid concurrent S03 symbols from staged hooks | resolved

The first shared-worktree S06 commit attempt correctly ran the normal hooks but
Ty isolated unstaged S03 changes and reported the staged snapshot's missing
`require_admitted_workspace_root` import. No hook was bypassed and no concurrent
source was staged. The exact ten-file S06 snapshot was reproduced in a clean
sibling worktree from the index, with the locked project environment including
the `server` extra, and the complete hook suite passed before commit. S05 was
then validated and committed separately on that branch. Main remains dirty with
other workers' changes; integration is deliberately left to the coordinator.
This is a low process constraint, not a source defect.
### kimi-provider-gate | medium | CI credential cases could silently skip without kimi-cli | resolved

P01.S05 found that the provider gate installed Codex but did not provision or
require the pinned Kimi CLI, allowing the three historical Kimi configuration
and credential cases to disappear as skips in CI. Resolution: the workflow now
installs the project-authoritative `kimi-cli==1.49.0` and exposes its `uv tool`
bin directory through `GITHUB_PATH`; `Justfile` requires `kimi-cli` and names
all three Kimi cases explicitly alongside the three Codex controls. The
isolated locked run passed all six cases with zero skips, and actionlint plus
the CI contract check passed. The served-provider completed-turn eligibility
lane remains separate and unchanged; no paid live provider turn was used.
Independent review found no remaining critical, high, or medium finding in this
lane. Issue #57 is ready for coordinated closure after commit integration.
### prek-annotation-enforcement | high | read-only Core check warns but exits successfully | resolved

The P01.S06 implementation review found that the direct
`vaultspec-core vault check annotations` command reports a malformed annotation
as WARNING and exits zero. A hook that merely replaces the mutating sanitizer
with that command is read-only but silently admits the condition it is meant to
reject.

Resolution: Core 0.2.2 exposes no strict or fail-on-warning option for this
check. `dev/vault_annotations_gate.py` now invokes the locked Core module with
`vault check annotations --json`, forwards its real diagnostic envelope, and
fails when Core reports a positive `data.diagnostics.total` (or malformed
output), without reimplementing annotation parsing. `prek.toml` keeps the
historical managed hook ID for migration compatibility while routing validation
through this wrapper. The explicit `Justfile` maintenance sanitizer remains
separate and operator-invoked.

The behavioral regression in `dev/tests/test_prek_config.py` uses real isolated
Core workspaces: the clean fixture exits 0 and the bad fixture exits 1 on
Core's warning diagnostic, while complete fixture byte snapshots remain
unchanged in both cases. `pytest dev/tests/test_prek_config.py -q` passed 3/3;
`prek run vault-sanitize-annotations --all-files --no-progress`,
`prek validate-config prek.toml`, and Core precommit migration dry-run all
passed (migration status `unchanged`). Ruff, Ty, and diff checks also passed.
The HIGH gate-semantics finding is therefore resolved with no remaining
critical or high finding in this lane.

### prek-format-baseline | low | locked Taplo formatting check conflicts with Core-managed block | queued

`taplo lint prek.toml` passes, while the locked `taplo fmt --check prek.toml`
command reports the pre-existing Core-generated managed hook block as
unformatted on both the baseline and this patch. Reformatting that block would
rewrite Core-owned output outside this Step's authority. This is a pre-existing
validation/tooling baseline, not a defect introduced by the read-only wrapper;
keep it queued for the Core/tooling owner and do not treat it as an S06 blocker.

### plan-ordering | low | plan check warns on intentional phase ordering | queued

`vaultspec-core vault plan check 2026-09-21-open-issue-remediation-plan`
reports PLAN022 because P02.S09 follows P01.S10 in document order while its
numeric identifier is lower than that preceding Step. The row placement reflects
the plan's explicit integration phase, not an S06 edit. It remains a low
metadata warning for the integrated plan review and is not an S06 blocker.

### dashboard-relay-live-proof | medium | replay behavior lacks one live connected recovery certification | open

The current engine and frontend implement sequence-aware reconnect, explicit
gap signaling, authoritative run-status reconciliation, a 4 MiB engine ring,
and a browser transcript bound of 256 events or 2 MiB. Focused frontend tests
passed 61 cases. The remaining gap is a live connected A2A gateway proof that
drops the browser relay after a known sequence and observes delta replay or an
honest gap followed by terminal status reconciliation. Dashboard issue #137 and
plan Step P01.S08 own it.

### locked-quality-type-policy | medium | pinned quality checks reject prohibited type suppressions | resolved

P01.S11 removed the prohibited `ty:ignore` directives from
`service/docker/service_entrypoint.py:32,174` without adding a suppression.
The independent S11 PASS reran the locked Ty/type-policy checks, targeted suites,
and the real Linux entrypoint proof with no new policy suppression. The governing
Compose/provider-boundary decision and the reviewed S03/S10 snapshots remain
unchanged.

### locked-quality-type-safety | medium | lock-pinned Ty reports nullable release metadata and broad race-test wrappers | resolved

P01.S11 corrected the nullable release metadata and retained the typed
descriptor-relative `os.open` seam in the provider race tests. Independent S11
PASS reran the locked official Ty/type-safety gate and targeted suites; the Ty
gate is clean. Five known strict-only basedpyright diagnostics remain separately
queued as a non-gating follow-up and do not reopen this official Ty finding.

### locked-quality-format | low | pinned formatter reports drift in four reviewed files | resolved

P01.S11 applied the bounded formatter corrections to the four reviewed files.
The independent PASS reran the pinned formatter and targeted suites with no
scope widening. The formatting finding is resolved.

### retired-ui-issues | low | five legacy issues no longer describe owned source surfaces | closed

Issues #30 and #31 are satisfied by the current relay replay and browser bounds.
Issues #33 and #34 prescribe retired Valibot, openapi-fetch, and rest-client
surfaces; current Dashboard adapters are intentionally hand-written and
tolerant. Issue #40 describes a removed in-repository UI and service-harness
bridge. All five issues were closed with their current disposition and the live
recovery residue linked to Dashboard issue #137.

### dashboard-rust-tooling | low | configured Cargo path blocked the Rust check | queued

The configured executable `X:/ci-shared/cargo/bin/cargo.exe` was absent, so the
Dashboard engine Rust tests did not run during this review. No conclusion was
drawn about whether another installed Rust toolchain exists. The passing 61-case
frontend result does not substitute for that engine-side check.

### compose-callback-root-anchor | high/security | intermediate run-root replacement bypassed descendant-only anchoring | resolved

P01.S10 review found that descriptor-relative callback traversal began from the
resolved run-root pathname, leaving its intermediate components subject to a
resolve-to-open replacement race. The correction now opens the configured
managed workspace boundary first and traverses every admitted run-root and
request component with no-follow directory handles. The real Linux image proof
replaces an intermediate run-root directory with a symlink to `/app` between
resolution and open; the callback refuses it without reading the service-state
sentinel.

### compose-workspace-sharing | high/compatibility | distinct identities could not exchange new or upgraded workspace files | resolved

P01.S10 review found that the service umask and top-directory-only ownership
change made agent-created files unreadable to worker callbacks, callback-created
files unreadable to the agent, and legacy UID/GID 1001 project content
non-writable by UID/GID 1002. The shipped worker profiles now explicitly opt
service-owned named volumes into a bounded no-follow migration that mirrors
owner access to the agent group and preserves executable bits. The launcher
sets a group-sharing umask only after dropping identity; callbacks explicitly
create shared workspace entries. Custom bind mounts receive validation rather
than recursive mutation. The real image proof starts from legacy ownership,
executes a migrated tool, performs bidirectional callback/agent reads and
writes, and confirms hard-linked service state fails closed without mutation.

### lifecycle-readiness-credential-probe | high/security | unresolved listener ownership can receive a credentialed health probe | open

P01.S01 review found `src/vaultspec_a2a/lifecycle/manager.py:798-800` and
`:859-880` can send the worker credential to `/health` while listener ownership
is still `UNRESOLVED`. A foreign listener can therefore capture the token.
P01.S01 must refuse the probe until ownership is established and prove that no
token is transmitted to an unresolved or foreign listener.

### release-input-shell-expansion | high/security | raw tag or user input reaches Bash command construction | open

P01.S04 review found raw release tag or user-controlled input reaches Bash at
`.github/workflows/release.yml:198`, `:409`, and `:436`. P01.S04 must pass values
through non-executable data channels and prove shell metacharacters cannot alter
commands.

### release-ref-binding | medium/integrity | publication is not bound to a tag at the current commit | open

P01.S04 review found publication permits a missing tag or branch-spoofed input
without proving `refs/tags/<tag>` resolves to `HEAD`. Bind publication to an
existing release tag at the current commit and add negative branch and stale-tag
proofs.

### release-artifact-persistence | medium/supply-chain | persistent download directory and wildcard upload admit stale extras | open

P01.S04 review found persistent `members/` downloads combined with wildcard
upload can publish stale artifacts from an earlier run. Use an empty per-run
staging directory and an exact four-member manifest before upload.

### release-ci-contract | medium/verification | CI contract rejects current release command forms | open

P01.S04 review found `dev.ci_contract` rejects the workflow commands at lines 85
and 110. Align the workflow with the repository contract and retain an
executable contract check before closing the Step.
### dashboard-live-worker-startup | high/integration | real demand starts the worker but the live relay lane does not become healthy | open

P01.S08 now uses a normal engine-origin run demand before waiting for the lazy
worker. In the live lane that demand starts a worker, after which worker health
returns 500 and the engine returns 504; a subsequent concurrent run times out
on gateway discovery, with no worker traceback captured. Static Prettier,
ESLint, TypeScript, and 28 Rust relay tests pass, but they do not discharge the
live connected recovery requirement. No environment or S10 cause is inferred.
P01.S08 and Dashboard issue #137 remain open pending diagnosis and a passing
live relay-recovery proof.

### dashboard-warmup-terminal-row | low/test-hygiene | cancelled warmup state persists only for the isolated harness lifetime | closed

Review considered whether the lazy-worker warmup leaks a broker thread because
it cancels and waits for terminal settlement without invoking a separate broker
delete. This is not a durable or production-state leak: the harness owns fresh
SQLite state beneath its temporary A2A home and fixture worktree, stops both
process trees, and recursively removes both roots in teardown
(`frontend/e2e/agent/harness.ts:507-525`, `:599-614`). The unique cancelled row
exists only for the remaining lifetime of that isolated suite and cannot survive
teardown. No production delete requirement or additional cleanup verb is
warranted; future test cleanup may remove it only if in-suite enumeration proves
observable interference.

### blocked-cancel-process-boundary | high/concurrency | blocked ingest read loses the accepted cancellation boundary | REVISION REQUIRED

Independent P01.S12 review found that an accepted cancellation can remain local to the
coordinator while the worker is blocked awaiting the next streamed event. The
cancellation signal does not yet race the blocked process-boundary read, so a
watchdog can observe a non-settling run rather than prompt cancellation. P01.S12
owns the ingest and focused cancellation-test paths; no architecture change is
claimed here. Keep the finding open pending the required architecture research and
the bounded race-cancellation implementation and proof.

### blocked-cancel-settlement-race | high/correctness | completion and cancellation can settle the wrong current receipt | REVISION REQUIRED

Independent P01.S12 review found a completion/cancellation settlement race: a
completion or failure event can arrive while cancellation is being accepted, and
current-receipt ownership is not yet proven to preserve the required
CancellationEvidence for the active cancellation. A stale or non-current receipt
must not settle the wrong action or leave the current cancellation without terminal
evidence. P01.S12 owns the bounded ingest, executor, aggregator, and new blocked
cancellation-test paths; architecture research remains pending.

### blocked-cancel-post-read-recheck | medium/concurrency | a post-read cancellation recheck cannot interrupt a blocked read | REVISION REQUIRED

Independent P01.S12 review found that checking cancel_event only after an event
read returns is insufficient: the read itself can remain blocked after cancellation
is accepted. The correction must race cancellation against the next-event await,
while preserving watchdog behavior and generator cleanup. P01.S12 owns the bounded
paths and remains open pending architecture research, implementation, and focused
proof.

### locked-env-example-service-identity | medium/CI-blocking | required Compose service identity variables are absent from the root operator example | resolved

P01.S11 added the required service-identity semantics to root `.env.example`
and reverified `src/vaultspec_a2a/control/tests/test_env_example_coverage.py`
deterministically. The independent PASS confirmed
`VAULTSPEC_PROVIDER_AGENT_UID`, `VAULTSPEC_PROVIDER_AGENT_GID`, and
`VAULTSPEC_PROVIDER_IDENTITY_LAUNCHER` remain documented rather than excluded;
the low wording correction was also reverified. The other 39 canonical failures
passed in isolation and remain classified as concurrent runtime contention, with
no source action unless recurrence is observed.

### basedpyright-strict-follow-up | low/type-safety | five known strict-only diagnostics remain outside the official Ty gate | queued

The independent S11 review recorded five known basedpyright strict diagnostics as
a non-gating follow-up: `scripts/prepare_release.py:37,243,262` and private
`os.open` access in
`src/vaultspec_a2a/providers/tests/test_project_confinement.py:524,567`.
The official Ty gate passed and is the S11 authority; these basedpyright-only
diagnostics must not be misclassified as Ty failures or reopen S11.

## Recommendations

- Complete P01.S03 before P01.S10, then close issue #25 only after real provider
  and terminal/tool children can work in the workspace but receive OS denial for
  token and database sentinels, while privileged callbacks reject symlink escape.
- Keep P01.S06 closed with the Core-diagnostic wrapper and byte-preserving
  regression; retain the explicit maintenance sanitizer outside validation.
- Keep the low Taplo managed-block baseline queued for the Core/tooling owner;
  do not reformat generated hook output in this Step.
- Resolve the PLAN022 ordering warning during the integrated plan review if the
  intentional phase ordering should be represented differently; it is not an
  S06 implementation blocker.
- Execute P01.S08 against a controlled live A2A gateway and close Dashboard
  issue #137 only on observed replay or honest gap and run-status convergence.
- Resolve or locate the Dashboard Rust toolchain before claiming engine-route
  test coverage; keep the absence classified as tooling until checked.
- Keep the five legacy A2A issues closed; future work belongs to current
  Dashboard paths and issue #137 rather than recreating the retired UI surface.
### integrated-dirty-worktree-review | low | PASS with no unresolved critical or high implementation findings

Type: integrated implementation review. Status: verified. The coordinated snapshot closes the implemented lifecycle readiness, workspace admission, release preparation, Compose execution isolation, and blocked-cancellation Steps. Focused verification passed 41 lifecycle tests, 67 workspace-admission tests, 200 cancellation/streaming tests, and 30 provider/workspace-isolation tests. Eight Linux identity-launcher cases were correctly platform-excluded on Windows and retain their prior real-image evidence. The complete `prek run --all-files` suite passed Ruff, formatting, Taplo, Ty, Markdown, canonical actionlint, Vault checks, provider-artifact checks, and spec diagnostics.

### prek-actionlint-owner-drift | medium | resolved

Type: repository tooling and ownership. Status: fixed. The hook invoked raw actionlint while hosted CI invoked `python -m dev.actionlint`; only the raw path treated the infrastructure-owned `dev-runner` label as a repository error. `prek.toml` now calls the canonical repository wrapper, preserving workflow syntax and code-owned checks while applying the already-reviewed runner-topology boundary consistently. The complete hook suite passes without suppressing source, type, format, or workflow diagnostics.

### blocked-cancel-race-rereview | low | resolved

Type: concurrency and settlement. Status: verified. The ingest path now races accepted cancellation against the blocked next-event await, preserves completion-first behavior and current-receipt cancellation evidence, and retains generator/watchdog cleanup. The focused 200-test suite passes, including the real blocked-stream cancellation service test and the direct-recovery, event-handler, executor, IPC, and aggregator cases. The prior high and medium P01.S12 findings are resolved.

### lifecycle-readiness-rereview | low | resolved

Type: credential boundary and readiness. Status: verified. Listener ownership is established before credentialed readiness probing, foreign listeners are rejected without receiving a probe or registry record, and the lifecycle suite passes 41 tests. The prior high credential-probe finding is resolved.
