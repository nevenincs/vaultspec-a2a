---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-19-a2a-edge-conformance-plan]]"
  - "[[2026-07-19-a2a-edge-conformance-active-run-discovery-research]]"
---

# `a2a-edge-conformance` audit: `active run discovery`

## Scope

Read-only review of commits `2860d8dc` and `726fae33` against the accepted edge-conformance ADR, active-run discovery research, approved plan, implementation, and live HTTP proof. The pass covered operational boundedness, malformed durable data, cross-platform workspace identity, information disclosure, route coexistence, D3/D5 authority boundaries, external engine adoption, and repository test integrity.

## Findings

### unbounded-database-materialization | high | The capped response performs an unbounded durable-row read

`list_active_threads` materializes every non-terminal ORM row before `discover_active_runs` filters metadata and stops at `limit + 1`. Wire size is capped, but request database work, allocation, and latency scale with the entire active population. Revision is required before merge.

### malformed-metadata-crash | high | A deeply nested metadata blob can make discovery return 500

Metadata parsing has no raw-size guard and catches ordinary JSON decoding failures but not `RecursionError`. A deeply nested persisted JSON value reproduces an uncaught exception, allowing one corrupt active row to make the collection read unavailable. Revision and a real-database regression are required.

### production-lifespan-not-proved | high | The live proof replaces resident startup wiring

The TCP test installs a no-op application lifespan and manually supplies database, checkpointer, and aggregator state. Although the HTTP router and file-backed database are real, this substitutes the production lifespan and violates the repository prohibition on fake or stub wiring. Revision must boot the production application with isolated real runtime configuration.

### workspace-identity-portability | medium | Workspace equivalence is incomplete on case-insensitive macOS filesystems

`normcase(realpath(...))` provides Windows casing behavior but `normcase` is a no-op on POSIX, including commonly case-insensitive macOS volumes. Existing coverage uses byte-identical resolved paths. Filesystem-aware identity or an explicitly documented lexical contract is needed.

### synchronous-path-resolution | medium | Candidate path resolution can block the async request loop

Discovery calls synchronous `realpath` for each candidate. UNC or unavailable network roots can block gateway request handling; the unbounded scan compounds the risk. Candidate resolution should be removed from the loop, cached, and bounded.

### governing-contract-drift | medium | The accepted ADR still describes an exact five-verb edge

The implementation adds the reviewed collection read, while the governing ADR and several current package/source descriptions still define the edge as exactly five verbs. Because the ADR itself says additions are cross-repository contract events, the contract trail needs an explicit additive decision before the new surface is considered ratified.

### external-engine-whitelist | medium | Dashboard reload recovery remains an external release dependency

The A2A gateway route exists, but the dashboard engine rejects unknown `/ops/a2a` operations before I/O. Engine whitelist adoption, selector scoping, and dashboard rebinding were outside these commits and remain open. Until that reviewed contract event lands, direct A2A discovery works but dashboard reload recovery does not.

### global-enumeration-policy | medium | Optional selectors require engine-enforced caller scope

The A2A endpoint permits a global active-run read when workspace and feature selectors are absent. This is bounded and non-authoritative, but the external engine must require or inject the caller's permitted workspace and feature scope so dashboard callers cannot enumerate unrelated run identities.

### stale-profile-expectation | low | A pre-existing gateway test rejects the newly bundled Kimi profile

The adjacent gateway suite expects the old four-profile set while the current bundled preset also exposes `kimi`. This failure is unrelated to active-run discovery and belongs to the model-profile owner, but it remains queued because the rolling audit mandate requires every surfaced issue to be recorded.

### verified-contract-properties | low | Minimality and D3/D5 authority separation are preserved

The new GET route coexists with POST on `/v1/runs`; state, selector, and limit validation are bounded; ordering is deterministic; terminal and malformed common cases are excluded; the response contains only run identity, status, and feature tag; and the viewer then uses authoritative per-run status. No transcript, prompt, token, topology, actor credential, or raw metadata is returned.

### unbounded-metadata-materialization | high | Full metadata text remained byte-unbounded after row-bounding

The second safety review found that keyset pages still selected the complete unbounded `thread_metadata` text before the service applied its 16,384-character guard. The revision now projects only a database-side 16,385-character prefix, using the final character as an oversize sentinel. SQLAlchemy can materialize at most that prefix per row; the 101-row page and 1,000-row scan caps remain intact. A production-lifespan live test includes a 250 KB durable metadata row. Resolved and verified by the final review.

### valid-large-metadata-exclusion | medium | Safe prefix rejection can omit otherwise valid large metadata documents

Current metadata persistence permits aggregate documents larger than discovery's 16,384-character parse boundary, particularly through context references. Those rows are now resource-safe but omitted from discovery even when their workspace and feature selectors are valid. Queue either an aligned aggregate persistence bound or bounded selector columns independent of the full metadata document.

### current-contract-wording | medium | Some distributable descriptions still call the whole edge five-verb

The accepted ADR now records the additive discovery event, source route/schema descriptions are current, and the contract mapping document includes the new operation. The dirty shared worktree's package description and README still use older five-verb wording; changing those overlapping user-owned edits was deliberately avoided. Reconcile those surfaces with their current owner before release.

### route-signature-coverage | low | Exact resident capability publication lacked a focused assertion

The service already derives its route signature from the registered application, but the initial live proof did not assert publication of this exact operation. The production-lifespan test now requires `GET /v1/runs` in `/v1/service.routes`. Resolved.

### review-resolution | low | All blocking findings are closed and the final review passes

The final implementation uses narrow database projection, bounded keyset pages, a hard scan budget with correct sentinel semantics, bounded metadata transfer and parsing, filesystem-aware workspace comparison off the event loop, and a normally booted installed gateway proof. Both formal reviewers report no critical or high findings. Review status: PASS.

## Recommendations

1. Replace full ORM materialization with a narrow, hard-capped keyset scan and stop after `limit + 1` matches or the scan budget, returning `truncated=true` whenever unseen candidates may remain.
2. Reject oversized metadata before parsing, catch bounded JSON recursion failure, and add a real SQLite regression row.
3. Replace the no-op-lifespan proof with a subprocess or otherwise normally booted production application using isolated real SQLite and checkpointer paths.
4. Move filesystem resolution off the event loop, add filesystem-aware equivalence where available, and cache comparisons within the bounded scan.
5. Record the additive discovery contract in the governing architecture trail and refresh only current descriptive surfaces; preserve historical five-verb evidence as history.
6. Keep the engine whitelist, engine-enforced scope, and dashboard rebind work open as an external release dependency.
7. Route the stale Kimi profile assertion to the model-profile audit queue without changing it in this feature pass.

Review status: REVISION REQUIRED. No critical findings; the three high findings block sign-off.

## Review Closeout

The three first-pass high findings and the later byte-boundedness high finding are resolved. Remaining medium items are queued above: valid large-metadata selector projection, external engine whitelist and caller scoping, and residual wording in overlapping user-owned package/README edits. The unrelated Kimi profile expectation remains queued to its owner. Final status: PASS.
