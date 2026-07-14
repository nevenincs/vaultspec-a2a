---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `a2a-edge-conformance` audit: `W02 code review: deletion mandates and write-seam closure`

## Scope

Formal code review of wave W02 (Deletion mandates and write-seam closure;
8 steps S07-S14). Reviewed commits: `ca68e44`, `be40616`, `8a75c90`
(frontend deletion), `5047550` (protocol stubs + probes rider), `07f8c9c`
(deny policy + adversarial tests), `f229618`/`c7dffc2` (queue to DB,
migration 0006), `3578fe9` (observed-negative zero-write proof), with
`84daa2c` and `5c3f8ed` as context. Dimensions: dashboard D7
deletion-mandate completeness verified against the LIVE TREE (not
records), ADR R2/R5 conformance, the S14 evidence standard, the
executor's peer-review notes, scope drift, and the acceptance criterion
"no UI code, no Google-A2A stub, no agent-reachable filesystem write into
a vault".

**Verdict: PASS. W03 may dispatch.**

## Findings

### d7-deletions-live-verified | low | all deletion mandates hold on the live tree

Verified live: `src/ui/` gone; `protocols/a2a/` and `protocols/adapter/`
gone; `providers/probes/` husk gone (rider executed). The root
`package.json` survives CORRECTLY - reduced to the single runtime
dependency `@zed-industries/claude-agent-acp@0.20.2` (the ACP CLI host,
which is production, not UI tooling). Remaining `src/ui` mentions in
`src/` are two explanatory comments/docstrings, not code. The full
default suite passes live at this review: 1204 passed, 0 failed, 0
skipped - a net +27 over the W01 baseline even after deleting the UI-era
tests, because the wave added deny-policy, SSE, queue-repository, and
isolation coverage.

### r2-deny-policy-conforms | low | denial shape matches wire-shapes section 2; adversarial tests are live and mock-free

`_targets_vault` operates on the sandbox-resolved path (symlinks and
traversal collapsed by resolve()), checks path components case-insensitively
(casefold), and the denial is value-typed exactly per the engine pattern:
JSON-RPC `result` (never `error`) carrying `status: denied`,
`denial_kind: forbidden_actor` (snake_case discriminator), and
`eligibility.reason` steering to the authoring tools. The ten adversarial
tests drive the REAL handlers against a real temp workspace - zero mocks,
zero monkeypatching - covering direct, nested, dotdot-traversal,
dot-prefixed, three case variants, and symlink/junction (with a Windows
junction fallback so the test runs unelevated), plus the two surgical
positives: non-vault writes land and vault READS stay permitted
(dashboard D4). Assertions check both the denial shape and that nothing
landed on disk.

### r2-workspace-inside-vault-edge | low | a workspace rooted inside a .vault directory would evade the component check

`_targets_vault` inspects components of the path RELATIVE to the
workspace root. If an operator (mis)configures `workspace_root` to a
directory inside a `.vault` tree, agent writes there would not be denied.
Not agent-reachable (workspace roots are host-configured, never
agent-supplied), so LOW: harden opportunistically by also checking the
absolute resolved parts, or validate at workspace-creation time that the
root is not vault-interior. Assigned to W03's executor as a rider-sized
hardening, not a blocker.

### r5-queue-migration-conforms | low | schema, population closure, idempotency, and injection format all match the ruling

Migration 0006 and `TaskQueueEntryModel` implement the R5 schema
faithfully: thread-owned rows with cascade delete, unique
(thread_id, position) and (thread_id, task_key), bounded status enum
defaulting to pending, nullable `plan_changeset_id`/`plan_step_key` D5
references. `mark_task_complete` is an idempotent transition (completed
row re-completion is a no-op; pending/failed rows are not silently
completed) and the tool ACKs unknown/ineligible keys with "not found or
not in_progress" - the peer-review "dropped not-found ack" concern is
resolved in the landed code. Population is closed: `seed_task_queue` is
reachable only from the database facade and tests - no route, no tool,
no agent path. The `TaskQueuePort` protocol keeps the database out of the
graph domain (a clean improvement over the ruling's minimum). The
markdown read/write path is deleted.

### queue-view-header-change | low | injected queue header is now a stable label; tape impact nil today, watch at W03

The injected queue block's separator now labels the block `task-queue`
instead of the old `<feature>-queue.md` path. No recorded mock tape
exercises the queue-injection path (the thread-create API carries no
workspace-root/feature field, per the S14 record), so nothing breaks
today - but tape authors at W03+ must treat the new header as the stable
contract.

### s14-evidence-standard-met | low | observed-negative delivered; watcher adequacy assessed and accepted

S14 upgraded W01's no-write-path argument to an observed negative, twice:
a committed default-profile test running a 5ms-interval filesystem
watcher (mtime+size accumulation over every vault file) across
mount -> mark-complete -> re-mount on real aiosqlite, and a full-stack
native probe (gateway + auto-spawned worker + pinned sha256-verified
VidaiMock v0.1.3, per the S02 precedent) with the watcher spanning boot
to teardown - `vault_write_events: []`, thread terminal, queue advanced.
Adequacy: a polling watcher can in principle miss a sub-interval
create-then-delete transient; layered over the deny policy's direct
handler tests and the closed population path, the residual is
negligible and the standard is met. The honest caveat that the mock run
itself does not enter the vault-mount path (so the probe exercised the
queue directly against the gateway database) is recorded in the step
record rather than papered over - correct behaviour.

### acceptance-criterion-partial | low | the D7 repository criterion now holds; the full criterion remains W03+ work

Of the brief's acceptance criteria, the repository-state criterion ("no
UI code, no Google-A2A stub, no engine import, no agent-reachable
filesystem write into a vault") is now satisfied on the live tree - no
engine import exists (the authoring package is not yet built, and the
edge remains HTTP-only by construction). The proposals-only and
kill-honesty criteria are W03/W05 deliverables and remain open by design.

### scope-drift-none | low | every commit maps to a step or an authorized rider

All eight wave commits map cleanly to S07-S14 plus the authorized probes
rider and plan-progress bookkeeping. No unauthorized surface changed; the
five-verb gateway and streaming (W04 territory) were not touched beyond
the S09 net-new SSE coverage the plan ordered.

## Recommendations

- Dispatch W03. Its brief must carry: (1) the workspace-inside-vault
  hardening rider on the deny policy; (2) the SSE coverage debt
  disposition - S09's net-new test covers the deleted-UI surface, but the
  W04.P10 versioned-frame work still owes live-loop coverage under the
  five-verb reshape; (3) the `task-queue` header as the stable injection
  contract for any new tapes; (4) the W01 review's standing requirement
  that the real-ACP-turn evidence lands at P08 - the OAuth-gated presumed
  item must not survive the solo-coder proof; (5) authoring-package work
  codes against the wire-shapes reference including the engine runbook
  section (live engine on loopback, bearer read back from the discovery
  file, actor tokens minted via the bare bootstrap route).
- The adopted capability audit's `control/` coverage cliff and
  execution-mode findings remain successor-plan inputs; nothing in W02
  changed that disposition.
