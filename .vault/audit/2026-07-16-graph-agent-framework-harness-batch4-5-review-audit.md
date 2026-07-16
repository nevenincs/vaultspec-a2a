---
tags:
  - '#audit'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
  - "[[2026-07-15-graph-agent-framework-harness-adr]]"
---
# `graph-agent-framework-harness` audit: `batch-4 and batch-5 reviewer verdict: P05.S11 receipt proof, verify_harness rules-leg fix, and MCP composition`

## Scope

Reviewer-persona verdict covering the campaign's remaining `graph-agent-
framework-harness` commits after the batch-2/3 audit
(`2026-07-16-graph-agent-framework-harness-batch2-3-review-audit`): the
P05.S11 receipt-proof service test and its follow-on hardening (batch 4),
the `verify_harness` rules-leg arbitration fix (batch 5), and the P04.S15
MCP-composition wiring. Commits: `2500eb3` (P05.S11 receipt proof),
`664bd49` and `a160bfb` (LOW-5/LOW-6 fixes), `90c3522` (rules-leg fix) and
`5fdf4f6` (LOW-7 fix), `357d87a` (MCP composition, P04.S15).

## Findings

### p05s11-receipt-proof | low | PASS, both LOW findings fixed in-batch

**PASS** on `2500eb3` — the live service-level assertion that a
`research_adr` worker turn's compiled system messages actually contain the
P02 role-scoped rule content, run against a real provisioned workspace
rather than a static `RuleManager.compile()` call in isolation. This closes
P05.S11 with a genuine receipt: the test proves the rule content reaches
the real graph turn, not just that the compiler can produce it.

Two low findings surfaced during review, both already fixed in the same
batch:

- **LOW-5** — the `service` pytest marker's docstring/comment did not note
  that it also covers members with no live engine dependency, which could
  mislead a future contributor into skipping engine-free tests unnecessarily
  under that marker. Fixed by `664bd49` (comment-only correction).
- **LOW-6** — a broad exception suppress around the supervisor-config read
  path caught more than the one expected failure mode. Fixed by `a160bfb`,
  narrowing the suppress to `AgentConfigNotFoundError` specifically.

### verify-harness-rules-leg | low | PASS after fix; rules leg re-scoped as a bundled-integrity check

`90c3522` fixes the `verify_harness` rules leg so it is bundled-aware
(Path B) rather than on-disk-only: the prior on-disk-only check could pass
even when the bundled document-authoring rule set the batch-2/3 review
covered (`e975850`/`76eb559`/`138f76f`) was broken or missing, because it
never inspected the bundled path at all. **PASS.** Reviewer observation
carried into the record: this reframes what the rules leg actually
verifies — it is now effectively a bundled-integrity check (does the
bundled document-authoring rule set resolve and compile correctly) rather
than a generic on-disk rules-directory presence check, which is a narrower
and more useful guarantee than the leg's name suggests.

**LOW-7** — the rules-leg's compile step could raise and crash the whole
`verify_harness` run on a malformed rules probe, rather than reporting the
failure as a harness-ineligibility reason. Fixed by `5fdf4f6`, degrading a
compile failure to a reported reason instead of an unhandled crash.

### p04s15-mcp-composition | low | PASS, LOW-9 open, scope boundary noted

**PASS** on `357d87a` (P04.S15 — composing declared team-harness MCP
servers into ACP sessions, resolving each declared server name to a launch
spec and threading it per-role through `AcpChatModel.with_mcp_servers` into
`session/new`). This closes the `agent-harness-provisioning` ADR's
previously-unowned per-role MCP-composition Opens item at the protocol
layer: the assertion is that advertised servers are present in `session/new`
params, not that the model can see or use them — model-visible surfacing
stays upstream-gated per the standing S20 constraint, and this commit does
not claim otherwise.

**LOW-9** — open, fix in flight (not detailed further in this record;
tracked for the executor's follow-up). Scope boundary noted for future
readers: this composition wiring is inert outside the `research_adr` team
topology — it does not activate for other presets, which is the intended
scope, not an oversight.

## Recommendations

- Land the LOW-9 fix when ready; non-blocking for this record.
- No further action needed on `2500eb3`/`664bd49`/`a160bfb`/`90c3522`/
  `5fdf4f6`/`357d87a`; all six close clean or with an already-landed fix.
- Any future work touching `verify_harness`'s rules leg should preserve the
  bundled-integrity framing this review re-scoped it to, rather than
  reverting to an on-disk-only presence check.
