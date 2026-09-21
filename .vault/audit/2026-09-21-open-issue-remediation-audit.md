---
tags:
  - '#audit'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:c25ac34cddbd7e3b53b5ee25fcd511dce115c798d55d55f63b1006ce9450d9ed'
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
