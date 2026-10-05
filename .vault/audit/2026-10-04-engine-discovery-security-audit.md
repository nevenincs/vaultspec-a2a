---
tags:
  - '#audit'
  - '#engine-discovery-security'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:be9892c91ba65475c21c42ce9ecc8eac13db9131087228dd8504a847eb26ffdd'
related:
  - "[[2026-09-23-project-bound-state-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `engine-discovery-security` audit: `Engine discovery credential boundary`

## Scope

The reported Medium security finding at revision b973403, the current discovery-to-authoring path, filesystem provenance, retry attachment, and the external producer inspected read-only. Code discovery attempted semantic search; its index was unverifiable, so investigation used the supplied affected modules and targeted searches.

## Findings

### workspace-authority | medium | Repository JSON selects credential-bearing authoring destinations

Type: security. Status: confirmed; remediation in progress. `src/vaultspec_a2a/control/config.py:320` derives the engine record from the project, and `src/vaultspec_a2a/authoring/discovery.py:232` accepts legacy JSON plus an unauthenticated health response. `src/vaultspec_a2a/authoring/submitter.py:692` then sends independently provisioned actor tokens to that origin. The new real-loopback regression test fails against the original implementation by resolving the attacker's listener. Bearer retry in `src/vaultspec_a2a/authoring/client.py:197` is an equivalent attachment boundary.

### producer-contract | medium | Current Dashboard producer cannot authenticate discovery

Type: integration/security contract. Status: open; owned by the Dashboard engine producer. Read-only evidence: `Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/discovery.rs:71` publishes an unversioned inline bearer; its Windows writer inherits workspace ACLs at line 117. `engine/crates/vaultspec-api/src/lib.rs:109` serves unauthenticated health. Safe A2A refusal requires a coordinated versioned, private discovery producer and challenge response before authoring can attach again. No external repository writes are authorized yet.

### workspace-authority-resolution | medium | Private authenticated discovery rejects the original exploit

Type: security. Status: implemented and focused verification passed; final gate pending. The owner authorized producer work in both repositories. Initial and retry discovery refuse workspace/other-repository candidates, link/reparse aliases, non-private files/directories, oversize or malformed records, and missing/forged/replayed proofs. The original real-loopback trigger failed before the patch and now passes without sending any request to the repository-selected listener. Generic legacy gateway parsing remains intact.

### connection-takeover | high | Cached endpoint proof did not protect later authoring sockets

Type: security. Status: resolved in this pass. The independent candidate reviewer reproduced real actor and machine bearer disclosure after authenticating discovery, closing that listener, and rebinding the same port. The initial candidate proved a separate health connection. `_connection_proof.py` now proves every newly opened authoring TCP stream before HTTPX writes credentials, including reconnects. Real-socket regressions cover post-discovery takeover and reconnect after a successful authenticated command. The listener receives only the challenge; neither credential reaches it.

### dev-seat-collision | medium | Shared rendezvous could cause dev orchestration to kill the seated app

Type: lifecycle/compatibility. Status: resolved in the matching Dashboard pass. The independent reviewer traced same-project seated and dev publication collision to wrong-bearer proxy calls and PID termination. Dev now publishes to a separate private per-project/port namespace and rejects discovery ports differing from its declared dev port; its spawn, proxy and record readers share that path.

### dashboard-workflow-gate | low | Existing workflow policy failures prevent a green full gate

Type: CI contract/verification. Status: open, Dashboard follow-up. `just check-all` passes Rust formatting and workspace clippy, frontend lint/format/types and auxiliary scans but fails two existing `dev/guards/test_ci_lanes.py` checks: tracked unchanged `.github/workflows/runner-policy.yml` lacks the Dashboard name prefix and adds a push trigger. This security pass does not change workflow policy. Required full-gate verification remains blocked until the owning CI workstream resolves it.

### concurrent-mcp-test-types | low | Concurrent MCP test metadata edit blocks package-wide strict typing

Type: verification/type contract. Status: open in the concurrent MCP workstream. While this shared worktree was being verified, `test_dispatch_injection.py` gained provider-specific call-ID cases outside this fix. Package-wide Basedpyright reports a dynamically keyed dict assigned to `RequestParamsMeta` (currently around line 660). The discovery/connection modules, client and retry/takeover tests pass strict typing. The concurrent edit is preserved; this pass neither reverts it nor claims the package-wide strict gate is green.

### final-verification | low | Full completion remains blocked by existing repository gates

Type: verification. Status: pending external gate repairs. Final package pytest: 228 passed, 21 service cases deselected. Focused takeover/reconnect/retry cohort: 6 passed. Ruff lint and format, Ty over authoring, and Basedpyright over the discovery/connection/client cohort pass. Real producer default rendezvous and separate Node dev namespace match, and a default-path authenticated catalog request succeeds. All 13 real-engine live authoring cases pass. Core checks for this feature: zero errors and warnings after owning-verb hygiene repair. The original exploit and both confirmed candidate-review issues are remediated in the working tree; security workflow outcome is blocked solely from unresolved required full-gate evidence, not a claim of verified closure.

### workflow-gate-resolution | low | Authorized CI follow-up clears the remaining full-gate blocker

Type: CI contract/verification. Status: resolved. The owner authorized continuation after the prior blocked report. Dashboard's runner-policy workflow now uses the required Dashboard name prefix and runs on pull requests, consistent with the existing rule that only release automation runs on pushes. Its same-repository PR guard, self-hosted placement, pinned checkout, read-only permissions and runner-placement checker remain enforced. Review of the actual two-line patch found no new security or compatibility issue. `pytest dev/guards/test_ci_lanes.py`: 24 passed. Full `just check-all`: exit 0, including all 186 guard tests. The earlier workflow and final-verification entries are historical blocked observations; the current security-fix outcome is fixed.

## Recommendations

The engine-discovery-security decision must settle trusted record provenance and authenticated endpoint selection while preserving shared gateway parsing. Capture final verification and candidate-review findings here before reporting completion.

## Verification

Working-tree candidate, Windows, 2026-10-04. Pre-refinement nearest authoring/lifecycle/storage/health suite: 395 passed, 20 deselected. Final authoring package after connection refinement: 225 passed, 20 deselected (then an additional reconnect regression added). Ruff, Ty and Basedpyright cover the touched production modules and authoring tests. Actual rebuilt Rust engine under an isolated git fixture: protected discovery succeeds and all 13 live authoring tests pass with `-m service --require-prerequisite=loopback-stack`, no infrastructure skip. The regression and syntax/type checks are rerun after final changes. Reviewer findings were validated and repaired in one candidate-review cycle. Semantic discovery was unavailable (`index_unverifiable`); owning Core search/cross-reference and targeted source reads supplied decision coverage. POSIX permission paths are source-reviewed; runtime checks here execute on Windows.

Final update: package-wide `basedpyright src/vaultspec_a2a/authoring` now passes with zero errors; the concurrent metadata typing issue was repaired by its owning workstream. Its earlier audit entry records a transient verification failure, now resolved. Final authoring package run passed 228 tests with 21 deselected service cases. The six retry/takeover/reconnect cases pass after the final client error-message maintenance. Dashboard's 12 touched Rust serve integration cases pass, all owning-crate integration test targets pass, and Vitest's 4 live-setup cases pass. Required full completion remains blocked by the two unchanged Dashboard CI-policy guards.

Follow-up completion, 2026-10-04: the coordinated candidate now passes every applicable verification gate. Dashboard `just check-all` passes actionlint, CI contract, configuration lint, Rust fmt/workspace clippy, frontend lint/format/tsc and auxiliary scans, plus 186 dev guards. A2A current authoring suite: 236 passed, 21 service cases deselected; Ruff lint/format, Ty and package-wide Basedpyright pass. A fresh isolated real-engine run selected all 13 live authoring tests with `--require-prerequisite=loopback-stack`; all passed, with no skips. The original repository-discovery exploit and port takeover/reconnect regressions remain covered by the passing authoring suite. Prior Rust owning-crate and touched-launcher test evidence is reused because this follow-up changes only CI workflow configuration. Review and classified audit updates are complete. Outcome: fixed; no remaining in-scope blocker. POSIX behavior remains source-reviewed, while actual runtime verification used Windows.
