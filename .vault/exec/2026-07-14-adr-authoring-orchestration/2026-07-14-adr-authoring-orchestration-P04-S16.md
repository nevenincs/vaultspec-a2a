---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S16'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
  - "[[2026-07-14-adr-authoring-orchestration-P04-S10]]"
---

# Thread grounding research stem into ADR proposal related and enforce canonical adr-status token

## Scope

- `re-run live lane to a zero-error vault check`
- `src/vaultspec_a2a/authoring/submitter.py`

## Description

Landed on two repos, counterpart commits:

- Engine (`Y:/code/vaultspec-dashboard-worktrees/main`, `0c05f0dc5f`): `ProvisionalCreate` carries a `related: Vec<String>` (serde default empty); `build_write_invocation` passes it to `vault add --related`, so a `CreateDocument` apply op can ground its scaffold frontmatter on the feature's applied grounding documents. Pre-S16 changesets with no `related` scaffold exactly as before.
- a2a (`Y:/code/vaultspec-a2a-worktrees/main`, `3f5c5e8`): `submitter.py::_whole_document_op` resolves the feature's applied research/reference docs from the engine recovery snapshot (each grounding proposal's `created_at_ms` -> canonical dated stem) and rides them as `related:[[stem]]` on the ADR-phase provisional-create target - research is the pipeline root and carries no grounding of its own. The submit node also refuses an ADR body that declares status in a legacy `## Status` section instead of the canonical H1 token, and the `vaultspec-adr-author` persona is hardened to emit the H1 status token.

Drove a fresh, isolated live acceptance re-run to prove the fix end to end (own build, own workspace, own ports/PIDs, distinct from the parallel campaign): rebuilt the engine at `0c05f0dc5f` into an isolated `CARGO_TARGET_DIR` (the resident engine holds its own exe file locked), served `--no-seat` on `127.0.0.1:18770`; provisioned a fresh workspace `scratchpad/s16-ws1` (`vaultspec-core install core` + `git init`); booted the a2a gateway+worker at current HEAD (includes `3f5c5e8`) on `18110`/`18111` with a dedicated sqlite checkpoint DB and `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED=true`, attached via `VAULTSPEC_ENGINE_SERVICE_JSON`; ran `pytest -m service -k live` (the standing PW7 harness's `live-mixed` case: real Claude, research AUTO / ADR HUMAN MIXED shape) against the fresh stack.

## Outcome

PASSED. Run `pw7-1784190507` (15m04s) materialized both documents with a fully conformant ADR on the first post-fix run:

- `.vault/research/2026-07-16-pw7-acceptance-live-1784190507-research.md` (13,741 bytes)
- `.vault/adr/2026-07-16-pw7-acceptance-live-1784190507-adr.md` (9,076 bytes)

ADR frontmatter grounds `related:` to `[[2026-07-16-pw7-acceptance-live-1784190507-research]]` - non-empty, resolving to the real applied research doc's dated stem, matching its own frontmatter `date:`. The ADR H1 carries the canonical status token - `` # `pw7-acceptance-live-1784190507` adr: `SSE resume via Last-Event-ID with tiered replay and sessionStorage cursor persistence` | (**status:** `accepted`) `` - with no legacy `## Status` section. Full gate sequence proven: research AUTO-approved under `system:operation-modes`, mode downgraded to manual, ADR HUMAN gate hit its 409 `authoring_stale_review` fence probe, then reject-with-notes -> revision -> approve -> apply.

`vaultspec-core vault check all` over the run's workspace vault: zero errors. `schema: clean`, `adr-status: clean`, `references: clean`, `links: clean`, `body-links: clean`; only 3 cosmetic warnings (markdown final-newline on both new docs, missing feature-index for the ad-hoc harness feature tag).

Lead (team-lead) independently manually re-verified: fetched all 11 research references (10 live+on-topic, 1 kafka live-base anchor-only), confirmed the ADR's `related:` date matches the research file's own date (the `created_at_ms`-grounding fix works, not a hardcoded today), confirmed the H1 status token and substantive 4-option reasoned prose. P04.S16 PROVEN LIVE.

## Notes

No incidents, no data loss, no skipped work. The acceptance stack (engine PID, gateway PID, worker PID, workspace `scratchpad/s16-ws1`) is torn down by recorded PID after this record lands, per the lead's sign-off. This closes the P04.S16 row; P04.S09/S10/S16 are now all checked, completing Phase 04 of the plan.
