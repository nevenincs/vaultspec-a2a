---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - '[[2026-07-14-a2a-edge-conformance-worktree-reconciliation-audit]]'
---

# `a2a-edge-conformance` audit: `W01 code review: salvage verification and hygiene`

## Scope

Formal code review of wave W01 (Salvage verification and hygiene; 10 of 36
plan steps) per the mandatory verify phase. Reviewed commits: `9e995d4`,
`2b210fd`, `13f9667`, `d41c4c4`, `aa2c6cf` (the -17 review-merge),
`4064577` (marker partition), `64d62ea`, `08a0d7c`, `d4f3092`, `ee4b7e7`,
plus context commits `247b7aa`, `7d688e1`, `dd44793`, `0fde796`, `c013c01`,
`9f09959`. Review dimensions: safety (no-crash, resource, concurrency),
intent versus the plan and governing ADR (R1 gate satisfaction, mandate
adherence, drift), and quality (test integrity, marker taxonomy). Claims
were re-verified live where possible rather than trusted from step
records, per the owner's fluidity qualifier. Report format note: persisted
as an audit-type document via the owning scaffold verb - the CLI has no
first-class review scaffold, the current pipeline maps the verify phase to
the audit directory, and the legacy corpus establishes the
`-review-audit` topic-infix precedent.

**Verdict: PASS. W02 may dispatch.**

## Findings

### verification-gate-satisfied | low | R1 gate closed with live evidence; verified independently where possible

Marker partition (S03): re-verified live by this review - core 538 +
middleware 639 + service 11 = 1188 collected, zero unmarked, zero
cross-layer overlap, unit = 687 as an orthogonal purity axis; exactly the
executor's numbers. IPC dispatch (S01): probe evidence records
`worker_spawned`/`worker_connected` true with both directions exercised
(spawn/health, heartbeat round-trip), two clean runs, no orphans; the
research document's earlier false-negative is explained (lifespan
reconcile not yet complete). Full agent turn (S02): terminal-success
thread state through gateway, worker, graph, `MockChatModel` streaming
from a REAL sha256-verified VidaiMock v0.1.3 binary (Docker unavailable;
the pinned artifact was run natively rather than faking a double - the
right call under the test-integrity mandate), durable checkpoint recorded.
Provisioning audit (S33): handshake-layer proof against the real
`claude-agent-acp` subprocess with a proven-versus-presumed ledger,
including `mcpCapabilities: {http: true, sse: true}` - the load-bearing
protocol fact for ADR R4. Full default suite: 1177 passed, 0 failed, 0
skipped (executor baseline, independently corroborated by a second
session's run and re-run by this review).

### merge-17-safety | low | the review-merge is hardening-only and green; diffs read line-by-line

The `aa2c6cf` diff against `13f9667` was read in full on the
safety-critical paths. `graph/tools/task_queue.py`: fail-fast traversal
guard on `feature_tag` (empty, slash, dotdot) at tool-creation time -
correct place, config-validation ValueError is acceptable no-crash
behaviour. `providers/_acp_rpc_handlers.py`: subprocess-supplied terminal
timeout capped at 300s - closes an unbounded-wait resource hazard.
`api/routes/thread_stream.py`: SSE generator returns after
`thread_terminal` with subscriber removal in `finally` - correct
resource-safe close. `streaming/*`: per-thread state purge
(`clear_thread_state` cascade) cancels flush and fanout tasks before
dropping references - leak fix, cancellation-safe. Delete-boundary
hardening: `_cleanup_artifact_files` resolves against workspace root,
enforces `is_relative_to` confinement, suppresses `OSError`/`ValueError`
per best-effort contract; `_validate_artifact_path` rejects absolute,
drive-letter, and dotdot paths at the repository seam with new tests.
Baselines 1165 -> 1177 passed, zero regressions, `ruff`/`ty` clean,
`uv.lock` conflict resolved by regeneration. Merge intent matches the
owner's review-merge decision exactly.

### cleanup-matches-authorization | low | S36 and the parked-dir discard verified live against the owner grant

Verified against the live tree, not the step record: zero stashes; the
three merged worktrees and the orphan scratch directory are gone; `main`
plus the preserved `ci-resolve-vaultspec-core-dep-23` worktree remain;
`feature/control-layer` and `feature/entry-point-layer` are deleted;
every remote branch including `origin/claude/*` is intact; the parked
`.vault-local-state-moved-20260703/` directory is discarded per the owner
decision; no `.vault/runtime` reference survives in `src/` (rg-verified);
no push occurred.

### zero-vault-writes | low | no agent process wrote to .vault during the wave's live runs

Assessment on evidence: the wave's only live model was `MockChatModel`
(no file tools on its path) and the sole ACP subprocess was S33's
handshake-only probe, reaped before `session/prompt` - no code path to a
vault write existed in any live run, and `.vault/` git state across the
wave contains only the corpus documents authored by named doc agents.
Caveat recorded honestly: no filesystem watch ran (that instrumentation
is S21's deliverable), so this is a no-write-path argument, not an
observed-negative. Acceptable for W01.

### presumed-real-acp-turn | medium | a full ACP turn against real Claude remains unexercised - accepted for W01-exit with a named downstream gate

The OAuth-gated full turn (session/new + session/prompt + fs/terminal
round-trip) was deliberately not run in the audit step. Ruling: this is
acceptable residual risk for W01-exit - the gate's purpose was salvage
verification, the handshake layer is proven live, and the mock path
proves the graph side of the turn - but it must not survive W03: the
deny-policy tests (S12) exercise the fs handler directly without needing
real auth, and W03.P08's solo-coder proof intrinsically requires the real
turn. If P08 discovers the real-turn path broken, the failure was
deferred from here; the trade was made knowingly to avoid uncontrolled
agent actions and API spend inside an audit step.

### sse-coverage-debt | medium | /threads/{id}/stream has no direct test; the merge extended untested behaviour

The SSE endpoint carries zero direct coverage (its only exerciser was the
deleted-UI manual path), and `aa2c6cf` added close-after-terminal
behaviour to it. Known and scheduled (S09 deletion-proof and S25
replacement coverage), but W02.P03's executor must treat SSE coverage as
NET-NEW work, and evidence from `/ws` tests does not count for this
surface.

### probes-orphan | low | providers/probes is a source-deleted husk; fold into W02 as a rider

`providers/probes/` contains only `__pycache__` and an empty `tests/`
cache directory; the one dangling docstring reference was already fixed
(`13f9667`). Disposition recommendation: delete the directory as a rider
on W02's first hygiene commit (same class as S06's orphans) - no new plan
step warranted.

### step-record-scope-pollution | low | S34/S36 exec records carry non-path scope lines

The machine-filled Scope sections of the S34 and S36 records contain
prose fragments ("this step blocks W02", "NO remote deletions...") -
residue of semicolons in the step actions this architect authored, split
by the scope parser. Cosmetic; fix opportunistically on next touch of
those records; step-action authoring should avoid semicolons henceforth.

### minor-drift-chore-commit | low | one commit outside any step; accepted

`2b210fd` (drop redundant casts flagged by ty) maps to no plan step. It
is a two-file lint chore required to keep the merged tree `ty`-clean and
is accepted as wave hygiene, noted for drift bookkeeping only.

### adopted-parallel-audit | low | owner's parallel-session audit adopted as successor-plan input

The untracked orchestration-capabilities audit was confirmed as the
owner's own parallel session and adopted by decision of 2026-07-14 (the
adoption pass follows this review). Its material findings - the
provider/execution-mode conflation defect, the `control/` package
coverage cliff (19 source files, 3 test files), `protocols/adapter/` as a
second zero-importer stub for W02's deletion manifest, and the absence of
any trace-review/benchmarking substrate - are flagged as candidate
successor-plan inputs under the plan's program clause; none blocks W02.

## Recommendations

- Dispatch W02. Its brief must carry: the post-merge re-read requirement
  for `task_queue.py` and `_acp_rpc_handlers.py` before implementing
  R2/R5 (both files changed in the merge); SSE replacement coverage as
  net-new work; the `providers/probes/` deletion rider; and
  `protocols/adapter/` added to the stub-deletion sweep alongside
  `protocols/a2a/` (manifest-verified zero importers).
- Hold the real-ACP-turn evidence requirement against W03.P08
  explicitly; do not let it slip past the solo-coder proof.
- Route the adopted audit's execution-mode-axis and control-coverage
  findings into the successor-plan pipeline (research -> ADR first for
  the execution-mode split); they are out of this plan's fixed scope.
- Avoid semicolons in future plan step actions (scope-parser split).
