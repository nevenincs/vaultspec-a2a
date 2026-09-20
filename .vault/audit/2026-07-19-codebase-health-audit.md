---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-09-20'
body_hash: 'sha256:e482f6e5aa585871a7a07b4a1c12d40a99616368adb12a7ced4cc16428c7fff1'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-07-18-desktop-product-profile-plan]]"
  - "[[2026-07-15-a2a-edge-conformance-dead-code-campaign-audit]]"
  - "[[2026-07-16-test-double-closeout-audit]]"
  - "[[2026-07-17-tool-cores-dedup-audit]]"
  - "[[2026-07-17-kimi-provider-dedup-audit]]"
  - '[[2026-07-19-codebase-health-research]]'
---
# `codebase-health` audit: `repository-wide health and dashboard contract`

## Scope

This audit covers the 18 production packages under `src/vaultspec_a2a`, their
tests, packaging and service surfaces, governing decisions, and integration
with `vaultspec-dashboard`. It treats the agent-to-agent (A2A) service and the
dashboard as one product boundary.

Semantic discovery began with `vaultspec-rag`. Whole-file reads and exact `rg`
searches confirmed the results. Three read-only reviewer lanes inspected
foundation, execution, and dashboard-edge behavior.

Automated verification used:

- Ruff, Ty, Deptry, and Vulture;
- Pylint clone detection and Radon complexity analysis;
- abstract syntax tree (AST) import and exact-clone analysis; and
- Vaultspec checks, test collection, and the default test suite.

Verdict: **FAIL**. One critical cross-stack integrity defect and twelve high
findings prevent a hardening sign-off.

**Test results.** The default suite collected 2,035 tests, deselected 80, and
ran 1,955: 1,945 passed and 10 failed. Seven failures are non-hermetic
unavailable-server tests that pass when the gateway is explicitly unreachable.
Three are independently reproducible stale contract assertions.

**Static and vault checks.** Ruff passes, while Ty reports five diagnostics in
tests. The initial vault check reported one schema error and four warnings. A
concurrent session repaired the schema error during this audit.

An intermediate repository check found one placeholder error in a concurrently
authored reference. That writer resolved it during the architecture follow-up.
Later checks remained error-free while the warning count changed as concurrent
writers scaffolded and completed lifecycle records. This feature's audit,
research, proposed ADR, and index pass their document checks.

## Findings

### foreign-worker-adoption-after-failed-eviction | critical | A gateway can adopt a worker still paired to another gateway

Status: RESOLVED (2026-07-22) on the dev/compose adoption path. A single
provenance-aware readiness signal, `_worker_ready_and_ours`, now gates every
adoption decision (it pairs the `/health` 200 with the worker's declared
`gateway_url` and accepts only a same-gateway target; a legacy worker with no
declared target is still treated as ours, so no correctly-wired worker regresses).
Applied at: `_spawn_worker` now fails loud instead of spawning after an
unsuccessful eviction (refuses to spawn onto a foreign-held port); its readiness
loop checks OUR spawn's liveness before the health probe and requires same-gateway
provenance, so a surviving foreign worker on the port can no longer be handed back
as ready; and both `ensure_worker` fallbacks (auto-spawn and externally-managed)
require same-gateway provenance rather than a bare health check. Proven with real
loopback HTTP workers (a foreign-gateway worker is refused at every path). The
desktop armed profile's strict authenticated pairing is separately covered by
S93/S94; the plan's real-two-gateway-process proofs (S95/S153-157) remain open as
a higher-fidelity integration bar. Original finding retained below.

Module-level `_spawn_worker` in `control/worker_management.py:334-346` can see
the still-running foreign worker during its readiness probe. It can return the
new child handle before observing that child's bind failure.
`ensure_worker` adds a second plain-health fallback at `:474-478` without
rechecking `gateway_url`. Dispatch from gateway A can therefore reach a worker
that sends events to gateway B.

This escalates the previously low
failed-eviction finding. The dashboard can show an accepted run while another
stack receives and mutates its state.

Fail immediately after unsuccessful
eviction. Require same-gateway provenance in the readiness loop and every
fallback adoption path. Prove both with two real gateways and one worker.

### hard-delete-cross-store-nonatomic | high | Irreversible files are deleted before checkpoint and database commit

`control/thread_service.py:538` unlinks artifacts before checkpoint deletion
and the database commit. A later checkpoint or commit failure leaves a visible
thread with missing artifacts or recovery state. This is a new follow-on to
resolved REVIEW-080. Replace the operation with an idempotent tombstone/outbox
deletion saga and real checkpoint/commit failure tests.

### restart-registers-before-readiness | high | Resume and rerun publish an unproven process generation

This is a new finding. `lifecycle/manager.py:359`, `:377`, and
`_start_from_record` at `:655` spawn and
overwrite the registry without the readiness transaction used by `serve_up`;
`rerun` also ignores old-tree kill failure. Dashboard process ownership can
point to an unreachable or overlapping generation. Route every restart through
reserve, spawn, readiness, and commit, and require confirmed old-tree exit.

### serve-up-commit-failure-leaks-child | high | A ready child survives failed ownership commit

This is a new finding. `lifecycle/manager.py:556-590` does not kill a ready
child when `commit_reservation` raises after readiness, for example because a
live different-owner record is already present. The process becomes
undiscoverable while retaining its port. Kill and await the child on commit
failure and add a real distinct-owner concurrent-start or explicit
commit-failure test.

### worker-startup-timeout-orphans-process-tree | high | Startup timeout terminates only the direct worker

This remains an open branch of the Windows descendant-orphan risk documented
by desktop research. `control/worker_management.py:374` calls
`process.terminate`, although the
module's tree-safe shutdown path documents that this orphans grandchildren on
Windows. Provider children can retain files and ports and block later dashboard
starts. Use the tree shutdown helper and prove child-plus-grandchild cleanup.

### resident-discovery-is-not-a-singleton | high | Concurrent gateways overwrite one shared discovery record

`api/app.py:253` detects an existing resident but starts anyway and republishes
at `:259`; `lifecycle/discovery.py:205` replaces the record unconditionally.
Dashboard attachment can switch between gateways sharing mutable state. This
is known and scheduled in the active desktop plan, but remains open.

Acquire a
lifetime operating-system (OS) singleton before binding the port or publishing
the discovery record. Fail the second process closed.

### stale-acceptance-gate-disables-dashboard-profiles | high | Discovery and launch disagree on profile eligibility

`api/routes/gateway.py:716` summarizes profiles with
`acceptance_gate_passed=False`, while launch passes `True` at `:315`. The
dashboard is told a profile is unavailable even when the same request can
launch it. Drive both paths from one persisted acceptance result and add an
equivalence test at the Hypertext Transfer Protocol (HTTP) boundary.

### duplicate-harness-server-invalid-codex-toml | high | Duplicate Model Context Protocol declarations break Codex startup

`team/team_config.py:354` accepts duplicate Model Context Protocol (MCP)
servers, and `providers/_acp_mcp.py:379-409` preserves them because the
resolver's `seen` set is not updated. A read-only Python probe passed
`["vaultspec-rag", "vaultspec-rag"]` through `TeamHarnessConfig.mcp_servers`,
`codex_mcp_server_specs`, and `render_codex_config_toml`. The result contained
two `[mcp_servers.vaultspec-rag]` tables, and Python's parser for Tom's Obvious
Minimal Language (TOML) raised `TOMLDecodeError` for the duplicate declaration.
Enforce uniqueness at schema admission and
stable-deduplicate in the shared resolver, then test config-to-TOML behavior.

### codex-stderr-backpressure-deadlock | high | Codex stderr is piped but never drained

`providers/_subprocess.py:59` always uses `stderr=PIPE`, while
`providers/codex_chat_model.py:130-134` reads only stdout. Enough stderr blocks
the child and leaves the dashboard run hanging until an outer timeout. Drain
bounded stderr continuously and cancel/await the reader during cleanup.

### acp-background-rpc-errors-only-log-and-hang | high | Failed background remote procedure calls do not terminate the turn

In the Agent Client Protocol (ACP) path,
`providers/_acp_protocol.py:112-117` stores background remote procedure call
(RPC) tasks until completion. However, `providers/_acp_auth.py:34` only logs
completed-task exceptions. It does not convert them into a JavaScript Object
Notation Remote Procedure Call (JSON-RPC) response or fatal session signal.
`acp_chat_model.py:471` can then poll forever for `prompt_done`.

Send a JSON-RPC
error or fatal session signal on every handler failure. Enforce bounded RPC and
turn lifetimes.

### test-policy-regression-after-closeout | high | Prohibited doubles, skips, mutations, tautologies, and type suppressions returned

Examples include:

- `_StubProviderFactory` in `graph/tests/conftest.py:41`;
- `_FakeSubmitter` in `graph/tests/test_research_adr.py:66`;
- `_StubProposalSubmitter` in `service_tests/test_receipt_role_rules.py:138`;
- `FakeChatModel` in worker and graph tests;
- production-global mutation in `providers/tests/test_acp_mcp.py:278-320`;
- skip gates across provider and live suites;
- a compile-only `FINISH` test at `graph/tests/test_compiler.py:327`; and
- five Ty diagnostics.

This reopens the test-double closeout. It weakens evidence behind
dashboard-visible provider and team claims. Replace the examples with real
imported behavior. Required certification jobs must fail when prerequisites
are unavailable.

### unauthenticated-public-control-plane | high | Audited public run-control and client-stream surfaces lack authentication

`api/auth.py:19` is an unwired no-op. `api/routes/__init__.py:42-45` mounts
legacy and v1 routers without an authentication dependency.
`api/routes/admin.py:8` exposes `/api/admin/shutdown`, and `api/app.py:463`
accepts WebSocket connections. Production Compose publishes the gateway.

Internal inter-process communication (IPC) routes are separately protected by
a bearer token at `api/internal.py:69-92` and `:175-176`. The dashboard already
supplies a discovery bearer at
`engine/crates/vaultspec-api/src/routes/ops/a2a.rs:140,240` and
`a2a_stream.rs:274-279`, but the public A2A routes ignore it.

This allows
creation, deletion, permission response, stream inspection, and shutdown
outside dashboard policy.

Complete the active desktop attach-auth steps before
hardening sign-off. Replace the no-op facade and tautological auth tests.

### sse-content-exclusion-regression | high | The public server-sent event channel forwards forbidden bodies and diffs

`streaming/sse_frames.py:98` forwards any payload below 256 kibibytes (KiB)
verbatim.
`api/event_adapter.py:79-80` and `:208` expose edit text and artifact content;
`streaming/transformer.py:304` copies artifact bodies. This server-sent events
(SSE) channel reaches the dashboard, which retains every payload verbatim at
`frontend/src/stores/server/liveAdapters/a2aRelay.ts:45`.

It renders message and
thought content at `:185-186` and tool-diff `new_text` at `:218-226`. Artifact
bodies are demonstrably retained, but this evidence does not prove that they
are directly rendered.

Artifact bodies and edit diffs violate the content boundary. Follow-up research
also found that the completed A2A plan's token exclusion conflicts with the
authoritative dashboard decision, which permits bounded, versioned token
streams. Reopen the previously closed finding and introduce a versioned
allowlisted progress data-transfer object (DTO). Give token deltas one dedicated
bounded field, and add a cross-repository test excluding prompts, document and
artifact bodies, edit diffs, and raw provider payloads.

### repair-policy-shadow-map | medium | The tested repair-policy source of truth is not used by runtime

This reopens an incomplete prior closure: earlier audits separately fixed and
tested both runtime transitions and the unwired pure map.
`thread/repair_policy.py:24` defines `_REPAIR_MAP`, but only its tests import
it; runtime repeats the transitions in `control/repair_transitions.py:16`.
Tests can remain green while dashboard `repair_status` and
`execution_readiness` drift. Wire runtime to the pure policy or delete the
shadow module and name the control module authoritative.

### run-status-triple-checkpoint-read | medium | One response combines three independently changing checkpoints

This is a new finding. `control/thread_state_service.py:140`, `:190`, and
`:254` read the checkpoint
three times for one run-status response. An advance between reads can combine
status, proposal IDs, and semantic context from different versions. Read one
tuple and derive the response from that immutable snapshot.

### thread-list-sequential-checkpoint-n-plus-one | medium | Dashboard run listing can serialize hundreds of seconds of timeout work

`control/thread_service.py:183-234` performs per-thread execution-state,
checkpoint, and permission reads sequentially. At the two-second per-checkpoint
timeout, the default 50-row page exposes roughly 100 seconds of serialized
checkpoint waits. The permitted 200-row page exposes roughly 400 seconds.

Reopen the previously accepted tradeoff for a continuously consumed dashboard.
Use bulk database reads, limit checkpoint concurrency, and impose a
request-wide deadline.

### git-manager-orphaned-subsystem | high | Orphan worktree APIs share a module with a live file-write mutex

This reopens a March audit false-negative that declared `workspace/` clean.
`GitManager`, `MergeStrategy`, and `WorktreeInfo` in
`workspace/git_manager.py:48-66` are re-exported and extensively tested but
have no A2A runtime or dashboard compatibility consumer. `WorkspaceError` and
`MergeConflictError` become export-only when those APIs are removed. The module
itself is not dead: `providers/_acp_rpc_handlers.py:347` imports its private
`_git_mutex`, then uses the lock at line 368 to serialize production Agent
Client Protocol (ACP) file writes.

The earlier removal wording was unsafe because deleting the module would break
that live path. Move `_git_mutex` to `workspace/concurrency.py`, and route both
the Git manager and ACP handler through it. Prove real concurrent writes remain
serialized. Then remove the orphan APIs and errors, facade exports, and
worktree-only tests.

### cleanup-failure-cascades-artifact-leaks | medium | Sequential cleanup skips later sensitive cleanup after one failure

`providers/codex_chat_model.py:428-429` and `acp_chat_model.py:459-462` run
cleanup steps sequentially. A close failure can strand copied credentials,
temporary configuration directories, projected MCP files, or tasks. Use
independent nested finally blocks and aggregate errors.

### dead-public-api-cluster-after-dead-code-sweep | medium | Several exported application interfaces have only test or export references

The audit found no production callers for these application programming
interfaces (APIs):

- `AgentState` in `graph/enums.py:40`;
- `AcpProtocolError` in `providers/acp_exceptions.py:70`;
- `discover_agent_preset_ids` in `team/team_config.py:118`;
- `acceptance_gate_reason` in `providers/model_profiles.py:87`; and
- `projected_declared_names` in `providers/_acp_project_mcp.py:112`.

Remove or deprecate them, or identify a runtime compatibility owner.

### dependency-gate-is-drifted-and-too-noisy | medium | Current Deptry configuration obscures real dependency debt

`apscheduler` appears unused, `websockets` is duplicated across dependency
profiles, and Deptry reports more than two hundred issues dominated by
first-party false positives. Configure first-party and driver/command-line
interface (CLI) mappings, then remove genuine unused or duplicated
declarations. Recheck after the concurrent desktop dependency work lands.

### run-id-replay-does-not-bind-request | medium | Idempotent replay compares only the profile

This reopens the idempotency completion recorded for P01.S01.
`api/routes/gateway.py:111-124` compares only persisted `profile_id`, not
message, preset, feature, title, mode, feedback batch, or workspace metadata.
The `IntegrityError` path at `:202-210` performs no request-identity comparison.

Persist a canonical request fingerprint. Return HTTP `409 Conflict` on
mismatch.

### dashboard-up-path-has-no-joint-certification | medium | Neither repository certifies the combined product path

The dashboard test at
`frontend/src/stores/server/agent/a2aTeam.live.test.ts:7-10` proves only the
degraded path, while
`engine/crates/vaultspec-api/src/routes/ops/a2a.rs:1004-1010` substitutes a
synthetic resident. A2A acceptance explicitly excludes live dashboard and
Docker execution at `api/tests/test_acceptance_five_verb.py:3-7`. Add a
required real-process continuous integration (CI) job. It must use the
dashboard engine, an A2A gateway and worker, a deterministic real provider, the
`/ops/a2a` facade, streaming and reconnection, and proposal review.

### heartbeat-parser-accepts-malformed-as-fresh | medium | Invalid and stale string heartbeats bypass freshness classification

`authoring/discovery.py:56-66` treats non-numeric heartbeats as fresh. This
includes booleans and every string. The wire contract permits only `i64`
milliseconds or International Organization for Standardization (ISO) 8601
date-time strings.

`authoring/discovery.py:64-65` therefore accepts malformed
strings and valid but stale ISO 8601 values without parsing their age. Parse
both forms strictly. Reject stale, malformed, non-finite, or implausibly future
values.

### unbounded-stream-subscriber-cardinality | medium | Per-client queues are bounded but client and subscription counts are not

`streaming/subscribers.py:31-70` permits an unbounded `thread_ids` update at
line 70; `api/routes/thread_stream.py:53-55` allocates one subscriber per SSE
client. Unauthenticated WebSockets add another unbounded path.

Before
authentication lands, cap work per connection or client and globally. After
authentication, also cap work per authenticated principal. Reject excess work
and expose operational counters.

### stale-contract-assertions | medium | Three deterministic tests lag shipped public state

Status: resolved (W04.P12 S47/S125/S126). `api/tests/test_gateway_live.py` now
asserts the profile set `{team-defaults, fast, codex, zai, kimi}`,
`thread/tests/test_errors.py` asserts the exact 21-member `errors.__all__`, and
`thread/tests/test_state.py` includes `feedback_batch_id`. Each expectation is an
explicit literal matching the governing contract (verified equal to the live
`__all__`/profile/state contract, not copied failure output) and passes in
isolation.

### mcp-unavailable-tests-nonhermetic | medium | Seven error-path tests depend on no gateway listening on port 8000

The module claims resident services cannot affect its tests, but its
unavailable-server cases leave global `settings.gateway_url` at the real
default. They failed with the resident gateway and all passed when
`VAULTSPEC_GATEWAY_URL` was set to the closed loopback endpoint
`http://127.0.0.1:1`. Bind these tests to their own unavailable socket fixture
without mocks or global production-state mutation.

### dispatch-failure-policy-duplication | medium | Three services repeat the same dispatch failure transition block

Pylint confirmed near-identical post-`safe_dispatch` logic in
`control/message_service.py:170`, `thread_service.py:475`, and
`permission_service.py:542`. Centralize typed failure classification and
state-transition application so run creation, follow-up, and permission resume
cannot diverge.

### extreme-complexity-hotspots | medium | Core event and provider functions occupy Radon's highest complexity bands

Radon's cyclomatic-complexity ranks are D for scores 21-30, E for 31-40, and F
for 41 or more. The audit treats scores above 20 as review hot spots.

Radon reports:

- `process_langgraph_event` at F/69;
- `ProviderFactory.create` at F/45;
- `compose_harness_mcp_servers` at F/41;
- `respond_to_permission` at E/40;
- `print_trace_summary` at E/36;
- `normalize_tool_input_schema` at E/32;
- `sync_worker_event` at D/29; and
- `project_checkpoint_tuple` at D/28.

Split these functions at stable policy or translation seams. Preserve behavior
with real tests. Prioritize streaming and provider paths because they carry the
dashboard contract.

### a2a-adr-grounding-drift-resolved | low | Concurrent work repaired the accepted ADR's missing grounding

The initial check found no research, reference, or audit grounding on
`2026-07-19-a2a-edge-conformance-adr` and found two scaffold comment blocks. A
concurrent session added a governing research link and removed the hints;
follow-up schema and annotation checks pass. No action remains.

### duplicate-backpressure-fanout | low | WebSocket and subscriber paths duplicate drop-oldest fanout

`streaming/subscribers.py:111` and `api/websocket.py:649` repeat subscription
iteration, queue eviction, logging, and enqueue behavior. Consolidate on one
aggregator/subscriber implementation.

### headless-docs-still-advertise-deleted-ui | low | Service documentation retains Vite and frontend claims

`service/README.md:10`, `service/docker/README.md:33`, and
`service/.env.example:18` contradict the headless Dockerfile and the previous
dead-code audit's closure. Status: resolved through the documentation workflow.
The service guides now describe the live headless Compose profiles and
``just dev stack`` recipes, distinguish published from Compose-internal ports,
and link to the canonical operator guide. Deleted Vite, frontend, mock-seeder,
provider-overlay, and stale verifier claims were removed; Compose configuration
was validated for development, integration, production SQLite, and the
production PostgreSQL overlay.

### unused-trace-helper | low | LangSmith trace summary has no caller

This reopens a March audit false-negative that declared `utils/` clean.
The audit found no production or script callers for the high-complexity
diagnostic helper at `utils/trace.py:37`. Remove it or wire one explicit
operator command; do not keep testless latent integration code.

### timestamp-utility-module-is-export-only | low | Three timestamp helpers have no runtime or dashboard consumer

`utils/timestamp.py` exports `now_utc`, `parse_iso`, and `human_delta` through
`utils/__init__.py`, but exact A2A and dashboard searches find only the module's
own tests. No production module, command, script, entry point, or dashboard
compatibility surface imports any of the three helpers.

After confirming neither A2A nor the dashboard imports these helpers, remove
the timestamp module, its facade exports, and `utils/tests/test_timestamp.py`.
Do not reproduce the removed formatting or parsing logic in tests.

### dead-code-refresh-removal-ordering-review | high | Initial plan mutation permitted unsafe or unproved removal

Type: architecture and test-plan safety. Formal review found that the first
revision did not require mutex relocation before Git manager removal. It also
named a directory that the test runner does not collect and omitted a timestamp
ownership-proof step. The corrected plan orders `S57`, `S174`, and `S63`; uses
canonical provider and workspace tests; and orders `S176` before `S175`.
Status: resolved before commit.

### dead-code-refresh-clarity-review | medium | Initial plan rows obscured prerequisites and removal scope

Type: documentation clarity. Editorial review found vague ownership wording,
missing conditions, and ambiguous object lists. The revised rows name the lock
module, compatibility proofs, exact APIs, and collected evidence paths.
Status: resolved before commit.

### minor-exact-clone-cluster | low | Small policy and facade clones remain

Exact AST and Pylint matches include:

- integer coercion in `authoring/lifecycle.py:126` and
  `lifecycle/discovery.py:100`;
- lazy package facades in `graph/__init__.py` and `providers/__init__.py`;
- response mappings in cancel, message, and gateway routes; and
- parallel wire and domain field blocks.

Share only behavior-bearing helpers. Keep deliberate transport and domain model
separation explicit instead of mechanically merging schemas.

### facades-and-wire-domain-blocks-are-deliberate-non-duplicates | none | AST similarity is not duplication where the two copies answer different questions

Two of the four AST matches this audit reported are deliberate and must not be merged.
Verified against the code and the governing boundary decision rather than the similarity
score.

The lazy package facades in `graph/__init__.py` and `providers/__init__.py` are structurally
alike because a facade has one shape - re-export names, defer the import to break a cycle -
but they re-export disjoint symbol sets for two independent packages. Their similarity is the
pattern, not the content; merging them would couple two packages precisely to remove a
resemblance that carries no shared behaviour. The behaviour-bearing helpers that were
genuine duplicates - the integer coercion and the response mappings named in the same audit
list - have since been consolidated under their own Steps, which is the correct disposition
for those and the wrong one for these.

The parallel wire and domain field blocks - the run-start request against the thread
metadata, sharing `feature_tag`, `profile_id`, `team_preset` by name - are two models of two
concerns. The wire model bounds every field for an untrusted transport boundary: length
caps, a forbidden-extra policy, stage-aware validation. The domain model carries internal
defaults and no bounds, because by the time state reaches it the values are already trusted.
Collapsing them onto one schema would either impose transport bounds on internal state or
relax the boundary that keeps an oversized or malformed field from reaching the domain. The
core-layer-boundary decision governs this separation, and the field overlap is the seam
working as designed rather than duplication to remove.

The disposition of the four matches is therefore split: two consolidated as behaviour-bearing
duplicates under their Steps, two recorded here as deliberate and kept apart. A similarity
tool cannot make that distinction; it is a per-match judgement, and this records it so a
later reader does not reopen the two that are correct.

### vault-mechanical-drift | low | Concurrent lifecycle work leaves the vault mechanically unclean

During the architecture follow-up, the concurrent writer resolved the earlier
placeholder error. Remaining warnings fluctuate with active sessions. They
include template annotations in in-flight records, stale feature indexes, and
the legacy `ui-integration-wire-regen` plan without an ADR.

Global
auto-fix was withheld because concurrent sessions were editing these files.
Re-run the mechanical repair and verify after those writers finish.

### ty-suppression-retained-in-test-remediation | medium | Test-state construction suppressed an invalid update type

Type: test-policy and typing integrity. A graph worker test replaced one Ty
suppression with another on a generic `TeamState.update` call. The helper had
no callers that supplied overrides. Status: resolved by removing the unused
generic override path and returning the directly typed production state shape.

### stdio-entrypoint-test-can-pass-before-entrypoint-success | low | Stdout-purity coverage omitted successful completion

Type: test adequacy. The MCP stdio subprocess test checked only for absent log
JSON, so an import or startup failure could satisfy it. Status: resolved by
requiring a zero subprocess return code before asserting stdout purity.

### canonical-ci-unit-gate-red | high | The hosted canonical command still fails seventeen non-service tests

Type: release evidence. A real `just ci` run passed Ruff lint, Ruff formatting,
Ty, and Deptry, then selected 2,141 non-service tests. It passed 2,124 and failed
17. The failures include three stale public-contract expectations, six MCP
unavailable-server cases coupled to resident state, one MCP default-preset
failure, five runtime or synchronized-corpus sensitive cases, and two provider
isolation/configuration cases. Status: open and queued across the existing
`stale-contract-assertions`, `mcp-unavailable-tests-nonhermetic`,
`test-policy-regression-after-closeout`, and provider reliability work. Hosted
automation now invokes the correct canonical command, but the product gate is
not green and no failure is suppressed.

A focused follow-up repaired four failing nodes. Logger assertions now target
the production services that own permission and terminal-event logging. The
live preset test accepts the bundled Kimi profile and derives Z.ai readiness
from the real production probe instead of assuming the host has no credential.
All four nodes pass. The full canonical suite has not been rerun, so this
finding remains open until the remaining failure classes are resolved and the
whole gate passes.

### lifecycle-authority-curation-review | high | Initial curation retained conflicting host-process authority

Type: architecture-decision curation. The first `W01.P01.S01` review found that
the desktop decision still retained the foreground shim and that two statements
assigned development-boundary refinement to repository tooling. The corrected
records assign named host-process lifecycle exclusively to the dev-process
registry, limit repository tooling to the delegating `just` surface, and retain
service-lifecycle authority for Compose and product topology. Status: resolved.
The second independent review passed with no findings.

### per-principal-quotas-have-no-principal-to-key-on | medium | the edge authenticates one shared bearer, so a per-principal quota equals the global one

Plan Step `W02.P06.S25` asks for per-principal stream and subscription quotas after
authentication. The step cannot be implemented as written, and implementing something that
resembled it would be worse than leaving it open.

The engine-facing authentication validates a single per-process service token and returns
nothing. There is no principal: every authenticated caller presents the same bearer, so a
quota keyed on principal identity would admit exactly the same traffic as the global
connection limit added under `W02.P06.S24`. Shipping it would create a second bound that
looks like defence in depth and is a duplicate of the first.

The prerequisite is an identity on this edge - a per-consumer credential, or a claim the
gateway can attribute a connection to. That is an architectural decision about the
a2a/dashboard boundary rather than a quota implementation, and it belongs in a decision
record before any quota work.

Left open deliberately. Closing it against the global limit would record a per-principal
bound this service does not have, and a later reader would reasonably assume one exists.

## User-documentation health review

The repository README, contributor and security policies, issue and pull-request
intake, Sphinx guides, API module index, and major package docstrings received a
combined editorial and warning-fatal Sphinx review. The following findings were
classified and resolved in this pass.

### docs-policy-navigation-gap | medium | Contributor and security policy links were absent from the Sphinx path

Type: documentation navigation. Status: resolved by linking both repository
policies from the documentation home, development guide, glossary, and README.

### docs-terminology-and-acronym-drift | medium | First-use terms and provider ownership language were inconsistent

Type: documentation clarity. Status: resolved by expanding CI, CLI, MCP, RAG,
HTTP, and Vaultspec Core on first use, standardizing managed output on
``provider projection``, and defining the terms in the glossary.

### docs-validation-mutation-ambiguity | medium | Validation was called read-only despite ignored output

Type: documentation accuracy. Status: resolved by describing validation as
tracked-source-safe and stating that tests and documentation may create ignored
caches or build output.

### docs-ownership-policy-duplication | medium | Three ownership tables could drift independently

Type: documentation architecture. Status: resolved by making the Sphinx
architecture guide canonical and replacing duplicate README and contributor
tables with concise links to that owner map.

### docs-ci-migration-claim | medium | Guides incorrectly said the unit gate excluded migrations

Type: documentation accuracy. Status: resolved after live collection confirmed
that non-service SQLite and Alembic migration tests run under ``just ci``. The
guides now distinguish those tests from the separate hosted PostgreSQL round
trip.

### docs-ci-environment-claim | medium | Guides named the wrong dependency profile for the canonical gate

Type: documentation accuracy. Status: resolved after a live ``just ci`` run
confirmed that the gate first synchronizes the locked ``server`` extra and
composed ``all`` group. The README and development guide now name that exact
selection and reserve ``tooling`` for hooks and narrower checks. The same live
run was blocked before static checks by a Windows dynamic-library file held by
an active Python process; it isn't passing evidence for the canonical gate.

### docs-sphinx-module-navigation-gap | medium | Operator boundaries lacked module cross-references

Type: API documentation navigation. Status: resolved by linking the CLI, API,
MCP, lifecycle, worker, thread, provisioning, and harness modules with Sphinx
``:mod:`` roles. The desktop contract, manifest, artifact-input, archive
projection, and evidence-publication modules are registered in the API module
index. Workflow-internal assembly modules are explicitly distinguished from
the package-root public component-manifest API.

### docs-navigation-and-intake-copy | low | Navigation labels and intake wording were inconsistent

Type: documentation usability. Status: resolved by aligning the README link
label with its destination, pluralizing the pull-request audit prompt, using
``not run`` consistently, and adding structured bug, feature, and private
vulnerability-reporting routes.

### docs-sync-glossary-ambiguity | low | Sync and reconciliation were treated as exact synonyms

Type: documentation terminology. Status: resolved by defining Vaultspec sync as
an explicit Core mutation and reconciliation as the underlying state comparison
that may be diagnostic or mutating.

### authorization-guard-chain-still-long | low | Permission authorization stage remains a 330-line flat guard chain

Type: maintainability. Status: deferred. Splitting the permission-response state
machine into authorization, transition, and dispatch stages
(`_authorize_permission_response`, `_record_permission_transition`,
`_dispatch_permission_resume`) reduced the orchestrator to 62 lines, but the
authorization stage is still a 330-line sequence of independent early-return
guards (resolution, idempotency dedup, permission-status, terminal, active
interrupt, option validation). Each guard is flat and independently testable
through the real endpoint seam, so this is readability debt rather than a defect;
a follow-on could lift each guard into a named predicate returning an optional
rejection. No behaviour change is implied.

### complexity-recalculation-w04-p15 | info | Post-decomposition cyclomatic recalculation for the hotspot split wave

Type: verification. Status: resolved. Step `S72` recalculated cyclomatic
complexity (ruff C901, mccabe, threshold 10) across every function the `W04.P15`
wave decomposed, and proved behaviour preservation by running the full
touched-area suites green: streaming, providers, control, and thread
(797 passed), plus the api permission characterization suite (103 passed) and the
streaming suite after the final split (73 passed).

Every former hotspot orchestrator now measures at or below the threshold:
`respond_to_permission`, `process_langgraph_event`, `compose_harness_mcp_servers`,
`normalize_tool_input_schema`, `project_checkpoint_tuple`, and - after the recalc
surfaced it - `sync_worker_event` (cyclomatic 23 -> 3). The recalculation also
corrected a plan-scope error: step `S70` named `sync_worker_event` but scoped it
to `control/event_handlers.py`, whereas the function lives in
`streaming/emitters.py`; both the event-handler permission stage and the emitter
dispatch were decomposed.

Residual functions still above 10 are flat branch fans, not nested monoliths, and
each is independently tested: `_authorize_permission_response` (15, the guard
chain queued above), `create` (14, provider-family admission in `factory.py`),
`_translate_chat_model_stream` and `_translate_tool_end` (12 each, per-field event
translators), `emit_interrupt_events` (13, an untouched neighbour), and
`_fold_pending_writes` (11, the pending-writes fold). No threshold was loosened
and no `C901` suppression was added - the project configures no mccabe gate, so
these are recorded as low-severity readability follow-ons rather than defects.

### deletion-saga-schema-blocked-by-capsule-head-coupling | medium | The deletion-saga schema (S08) cannot land while the desktop capsule session is active

Type: sequencing. Status: open (external dependency). The cross-store deletion
saga (`W01.P03` S08-S14) needs a new Alembic migration to add its saga-header and
cleanup-manifest tables. Any new migration bumps the packaged Alembic head, and
`desktop/contract.py` computes `PRIMARY_SCHEMA_VERSION` dynamically from that head
and *enforces* that a capsule manifest's `compatibility.migration_range.head`
equals it. So a deletion-saga migration changes the desktop capsule's declared
schema compatibility, its manifest content, and the golden manifest/tree digests
(`desktop/tests/test_manifest.py`, `test_capsule_archives.py`), and would break
the concurrent desktop capsule session's work in flight. S08's schema (two tables,
migration `0010`, models, and the `test_migrations.py` head/`_APP_TABLES` bumps)
was drafted and reverted TWICE rather than landed. The blocker is now pinned
precisely and is CROSS-REPO, not merely the concurrent desktop session: bumping
the packaged Alembic head to `0010` bumps `desktop/contract.py`'s dynamically
computed `PRIMARY_SCHEMA_VERSION`, and `ComponentManifest` validation enforces
`migration_range.head == packaged head`. The second attempt (with the tree clean)
passed the migration/compatibility suites (29) and the `test_manifest.py` head
assertions, but failed `test_canonical_json_v1_matches_cross_language_golden_vector`:
the manifest golden is a **cross-language canonical vector**
(`component-manifest-canonical-v1.b64` / `.sha256`) that pins `head "0009"` and is
the shared reference the DASHBOARD/Rust side also validates against. Landing `0010`
requires regenerating that cross-language vector in lockstep in BOTH repos, so the
deletion-saga migration is blocked on dashboard-repo access, not just desktop
coordination. This is a real cross-repo ordering constraint, not a code defect.

### wave-w03-review | info | Formal safety/security/resource-bound/quality review of Wave W03

Type: verification (S44). Status: resolved. Wave `W03` (provider MCP-config
validation `P09` and provider resource-failure containment `P10`) was reviewed
against its real-subprocess evidence. The teardown work is sound: a single shared
`run_independent_cleanups` runs each named release regardless of an earlier
failure, aggregates failures, and never swallows `BaseException`/cancellation, so
a killed-process failure can no longer strand a credential home; both the Codex
(`aclose` + `_astream` finally) and ACP (`_astream` finally + `_cleanup_session`)
paths route through it, preserving prior ordering (session-cancel before kill).
The four containment proofs are genuine and non-tautological, exercised against
real subprocesses rather than a full LLM session: stderr backpressure relief
(`S43`, ~960 KB flood), cleanup continuation after a failure (`S124`), request
deadline expiry (`S123`), and a failing handler answering `-32603` over a real
session pipe (`S122`, agent exits 42 to confirm). The MCP-config proofs drive the
real `codex mcp list` (`S114`) and `claude mcp list` (`S115`) entrypoints.

Findings appended to the queue by `S45`:

- `cleanup-runner-imposes-no-per-step-deadline` | low. `run_independent_cleanups`
  awaits each step with no per-step timeout, so teardown boundedness relies on
  each wired step being self-bounded. Every current step is (process-tree kill via
  taskkill/sigterm-sigkill, session-cancel's own 3 s `wait_for`, task-cancel's
  `CLEANUP_TIMEOUT_SECONDS`, local `rmtree`), but a future unbounded step would
  hang teardown silently. Consider an optional per-step deadline in the runner.
- `mcp-config-live-proofs-are-environment-gated` | low. `S114`/`S115` skip when the
  `codex`/`claude` binaries are absent (an honest prerequisite gate, not a green
  shortcut), so the live config validation does not run in an environment without
  them; the certification job must guarantee both binaries are present, or that
  coverage is environment-dependent.
- `cleanup-step-failures-are-logged-unredacted` | info. Cleanup-step exceptions are
  logged with `exc_info` without the stderr path's credential redaction. Low risk
  (cleanup errors carry filesystem paths, not secrets), recorded for symmetry with
  the redacted diagnostic tail.

### skip-monkeypatch-xfail-sweep | info | Codebase-wide sweep confirms no prohibited skip/xfail/monkeypatch shortcuts

Type: verification (S102/S103). Status: resolved. A whole-tree sweep of every
`test_*.py` and `conftest.py` under `src/vaultspec_a2a` found: zero
`@pytest.mark.skip` (unconditional) markers, zero `@pytest.mark.xfail` /
`pytest.xfail(`, and zero real `monkeypatch` usage (the only textual hits are
docstrings declaring "no monkeypatch"). The 20 runtime `pytest.skip(...)` calls are
all conditional environment gates - `if shutil.which("claude") is None`, `if
resolve_engine() is None`, `except (OSError, NotImplementedError)` on symlink
creation, a reclaimed-port guard - which is the executable-environment-gate pattern
`S102` endorses, not a green shortcut. Test environment access uses owned APIs
(e.g. the discovery override reads the official `SERVICE_JSON_ENV` directly), not
interpreter mutation. `S101` (prohibited fakes/stubs) is NOT covered by this sweep:
`_StubProviderFactory`, `_FakeSubmitter`, `_StubProposalSubmitter`, and
`FakeChatModel` remain and need an owner ruling on recording-double-at-a-real-seam
vs. prohibited fake before that step closes.

### tautological-shadow-test-sweep | info | The two named tautological/shadow tests are replaced; a sweep finds no others

Type: verification (S104). Status: resolved. The two offenders were replaced with
assertions against imported production behavior: the compile-only ``FINISH`` test
(which asserted only that a graph compiled) now exercises the real ``_loop_route``
across all arms, and ``test_star_missing_next_field`` (which reimplemented the edge
as a ``state.get("next", "")`` lambda) now imports and drives the real
``_route_from_supervisor``. A whole-tree sweep for the remaining prohibited shapes
found none: zero trivially-true assertions (``assert True`` / ``assert x == x``);
the eleven ``= lambda`` assignments are all legitimate dependency injection,
stream stop-conditions, or sort keys (e.g. ``make_researcher`` invokes the real
``create_researcher_node``, ``endpoint_provider`` injects a real ``EngineEndpoint``),
not reimplementations of production logic. An AST scan flagged 77 tests whose only
assertions are ``is None`` / ``is not None`` / bare-name, but the sampled ones
assert the real outcome of a production call (``_decision("FINISH").routing_error
is None``, ``compute_reconciliation_actions(...).new_thread_status is None``,
``resolve_venv(...) is None``), where ``None`` is the behaviour under test - not a
compile-only proxy. No further tautological or shadow-logic test was identified.

### s101-fake-doubles-adjudication-input | medium | The four named doubles are recording-doubles-at-real-seams; ruling needed

Type: adjudication input (S101 owner decision). Status: RESOLVED (2026-07-22) -
owner affirmed the four doubles as sanctioned recording-doubles-at-real-seams;
S101 has no prohibited fake to replace and is closed on that ruling. Original
analysis retained below for the record.
The four flagged doubles all inject a deterministic or recording collaborator at a
REAL dependency-injection seam while the unit under test runs for real:

- ``_StubProviderFactory`` (``graph/tests/conftest.py``) implements the real
  ``ProviderFactoryProtocol.create`` seam and returns LangChain's own
  ``FakeChatModel`` (a real deterministic model with preset responses). The graph
  compilation and execution paths are exercised for real; only the leaf LLM -
  which needs a live provider and credentials - is deterministic.
- ``FakeChatModel`` is LangChain's shipped deterministic chat model, not a
  hand-rolled shadow of business logic.
- ``_FakeSubmitter`` (``graph/tests/test_research_adr.py``) and
  ``_StubProposalSubmitter`` (``service_tests/test_receipt_role_rules.py``) record
  the phases / proposals the real node hands the submit seam, so the graph's
  routing and the receipt rules are asserted against real behaviour; the real
  submitter target is a live engine, out of scope and credential-gated for a unit.

Per this project's own ``reference_graph_boundary_test_pattern`` (recording model
via the provider_factory seam is the sanctioned pattern), none of these shadow or
reimplement business logic; they are injected collaborators at a real seam.
Recommendation: affirm them as sanctioned recording-doubles-at-real-seams, in which
case ``S101`` has no prohibited fake to replace and closes on that ruling. The
alternative - replacing them with live LLM / engine calls - would require
credentials and turn deterministic unit tests into flaky live tests, contradicting
the unit-test intent. This audit records the analysis; it does not make the ruling.

### await-listener-confirms-port-not-process | low | Readiness checks the port is bound, not that OUR spawn bound it

Type: correctness (surfaced during W01.P02). Status: RESOLVED (2026-07-22) - the
tighter fix landed: `_await_listener` now confirms the listening pid is the
spawned process or a descendant via the dependency-free `listener_belongs_to`
(netstat on Windows, `/proc` then `lsof` on POSIX, with a cross-platform parent-map
ancestry walk), so a foreign holder of the port no longer reads as our child being
ready. It fails safe - an unresolved owner degrades to the bare bound-port signal,
never falsely failing a legitimate boot - and is proven by real multi-process
tests (a foreign listener is positively rejected; the owning tree is accepted;
150 lifecycle tests still green). Original analysis retained below.
``_await_listener`` returns ready as soon as ``_port_is_bound(port)`` is true,
without confirming the process WE spawned is the one holding the port. If a foreign
process holds the record's port when resume/rerun respawns, the respawn crashes on
its own bind while the listener check sees the foreign holder and reports ready, so
a record could be published pointing at a crashed pid. The common case - an orphan
child of the felled old generation still holding the port - is now mitigated by the
S96/S151 confirm-terminated reap-before-spawn (the orphan is felled with the old
tree, freeing the port before the respawn), so only a genuinely foreign racer on a
fixed resume/rerun port remains. The tighter fix landed (2026-07-22): the listening
pid is now confirmed to be the spawned pid or a descendant. This also UNBLOCKED the
clean proof of S97/S152 (the kill-failure atomicity proofs): with the port-vs-process
ambiguity closed, a port-contention stand-in is a valid injection - a real foreign
process holds the record's port (a surviving old-tree member / failed kill), the
respawn stays alive but never OWNS the listener, so the ownership-aware readiness gate
fails and resume/rerun refuse atomically (prior generation unchanged, respawn felled,
no overlapping child). S97 and S152 are proven and closed on that injection with real
multi-process tests; no unkillable process is needed.

### authenticated-pairing-verdict-not-enforced | high | The S93/S94 lifetime+generation classifier is dead code

Type: correctness / dead-code (surfaced 2026-07-22 while grounding S153-156).
Status: RESOLVED (2026-07-24). The 2026-07-24 codebase-health decision record
made the owed policy call - profile-split enforcement: under the armed
profile the pairing verdict is the adoption authority (adopt only OWNED,
evict only authorized PRIOR_GENERATION, refuse FOREIGN/UNIDENTIFIED without
eviction), while unarmed profiles keep the legacy signal. The classifier and
eviction authorization are wired into every adoption seam (readiness gate,
armed pre-spawn occupancy gate, non-auto-spawn attach, post-spawn fallback,
watchdog external-worker fallback) with the spawner generation threaded
through, and the plan's real-process proofs S95/S153/S154/S155 are closed
against the enforced behavior. S156 (eviction-failure conflict proof) and
S157 (Compose regression proof) remain open. Original finding text follows. `lifecycle/pairing.py` implements the fail-closed authenticated
pairing verdict - `classify_worker_pairing` (blank evidence -> ``UNIDENTIFIED``,
lifetime mismatch -> ``FOREIGN``, only the current generation -> ``OWNED``) and
`eviction_is_authorized` (armed + ``PRIOR_GENERATION`` only) - with thorough unit
coverage in `test_worker_pairing_verdict.py`. But neither function has ANY
production caller (verified by grep across `src/` excluding tests): the worker
advertises its `paired_gateway_lifetime` on ``/health`` (`worker/app.py`), yet no
gateway-side code reads or classifies it. The real adoption path
(`control/worker_management.py`) instead gates on the weaker `gateway_url` signal
via `_worker_ready_and_ours` (the 2026-07-22 dev/compose fix above), which by
design treats BLANK evidence as a same-gateway match for legacy no-regression -
the exact opposite of the classifier's fail-closed ``UNIDENTIFIED``. Consequence:
the stricter authenticated pairing S93/S94 built is not the policy actually
enforced, and a plain-health worker with no pairing evidence would be adopted by
the gateway_url path where the classifier would refuse it. This is why the plan's
real-process pairing proofs (S95/S153-156) cannot be honestly closed: the behavior
they assert is unwired. Fix requires a policy decision - wire
`classify_worker_pairing` into the readiness/adoption gate (and
`eviction_is_authorized` into the eviction path), deciding per profile whether the
armed desktop gate is strict fail-closed while dev/compose stays legacy-lenient,
or the classifier supersedes the gateway_url check everywhere. A design decision
owed to the owner, not a mechanical rewrite; recorded here rather than rushed.

## Recommendations

1. Draft and approve a hardening ADR before implementation. The ADR must decide:

   - worker-to-gateway provenance;
   - cross-store deletion;
   - process ownership;
   - public attach authentication; and
   - the progress-event allowlist.

   This audit records the problems. It does not make those decisions.

2. Execute an integrity and process-ownership wave. This wave covers:

   - `foreign-worker-adoption-after-failed-eviction`;
   - `hard-delete-cross-store-nonatomic`;
   - `restart-registers-before-readiness`;
   - `serve-up-commit-failure-leaks-child`;
   - `worker-startup-timeout-orphans-process-tree`; and
   - `resident-discovery-is-not-a-singleton`.

   Closure requires real multi-process tests. They must cover two gateways,
   distinct owners, injected commit and checkpoint failures, and descendant
   cleanup on supported operating systems.

3. Execute a dashboard contract and security wave. This wave covers:

   - `stale-acceptance-gate-disables-dashboard-profiles`;
   - `unauthenticated-public-control-plane`; and
   - `sse-content-exclusion-regression`.

   Closure requires an audited route inventory and authentication tests for
   every public route and client stream. A cross-repository allowlist test must
   prove that excluded content never reaches the dashboard store.

4. Execute a provider reliability wave. This wave covers:

   - `duplicate-harness-server-invalid-codex-toml`;
   - `codex-stderr-backpressure-deadlock`; and
   - `acp-background-rpc-errors-only-log-and-hang`.

   Closure requires real Codex and ACP subprocess tests. They must cover
   duplicate configuration, sustained stderr, handler failure, timeout,
   cancellation, and complete resource cleanup.

5. Execute an evidence-integrity wave for
   `test-policy-regression-after-closeout` and the medium test and
   static-analysis findings. Closure requires:

   - a clean default suite;
   - live certification jobs that fail when prerequisites are unavailable;
   - no prohibited test doubles or mutation shortcuts;
   - a clean Ty run; and
   - a configured dependency gate with only actionable findings.

6. Execute duplication, dead-code, and complexity work after the blocker waves
   stabilize shared seams. Remove or assign owners to every orphaned API.
   Consolidate the three dispatch transitions and duplicate fanout behavior.

   Reduce every listed Radon hot spot to a score of 20 or below. Preserve the
   deliberate separation between wire and domain schemas.

7. Coordinate active desktop-product, Kimi, tool-core, and A2A-edge plan owners
   before touching their files. Concurrent changes to `pyproject.toml`, the
   lockfile, desktop tests, presets, and execution records were not authored or
   modified by this audit.

8. Run a fresh formal code-review audit after every implementation wave.
   Classify every new finding. Append each one to this queue before closing the
   wave.

## Reconciliation (2026-07-24)

Verify-and-classify pass against `main` after the dashboard-bundled-runtime
pivot landed. Each finding is dispositioned with evidence so the plan reflects
reality.

### Resolved — closed this campaign (evidence commit)

- `repair-policy-shadow-map` — `dcd67ea8` (dispatch-failed repair state sourced
  from the pure policy; parity test added).
- `dispatch-failure-policy-duplication` — `b69acbc2` (centralized
  `evaluate_dispatch_failure` + `apply_dispatch_failure`).
- `dead-public-api-cluster-after-dead-code-sweep` — the five named symbols were
  already removed; the residual per-field checkpoint readers removed in
  `fbf10b7a`.

### Resolved — verified fixed by prior/concurrent work (evidence)

- `foreign-worker-adoption-after-failed-eviction` — `658615ab` (same-gateway
  provenance on every adoption path).
- `authenticated-pairing-verdict-not-enforced` — `122b1e06` (the
  lifetime+generation classifier is now enforced at worker adoption).
- `heartbeat-parser-accepts-malformed-as-fresh` — `678934f8` (strict i64/ISO
  parse; `test_heartbeat_freshness`).
- `run-status-triple-checkpoint-read` — single `read_run_snapshot` + pure
  `derive_*` in `api/routes/gateway.py`.
- `run-id-replay-does-not-bind-request` — `gateway.py` compares the full
  `request_digest`, 409 on mismatch.
- `git-manager-orphaned-subsystem` — `_git_mutex` relocated to
  `workspace/concurrency.py`.
- `resident-discovery-is-not-a-singleton` — OS runtime singleton acquired before
  bind/publish (`lifecycle/singleton.py`).
- `restart-registers-before-readiness` and `serve-up-commit-failure-leaks-child`
  — `lifecycle/manager.py` routes restart through reserve → readiness → commit
  with commit-failure-after-readiness handling.
- `worker-startup-timeout-orphans-process-tree` — containment whole-tree reap in
  `worker_management.py` (implementation; the `W01.P02.S06` verify Step remains
  open).
- `duplicate-harness-server-invalid-codex-toml` — `_acp_mcp.py` reject-duplicate
  + order-preserving dedup.
- `codex-stderr-backpressure-deadlock` — continuous `_drain_stderr` task.
- `stale-acceptance-gate-disables-dashboard-profiles` — both summary and launch
  drive off the shared `evaluate_profile_eligibility`; gate reported honestly.
- `cleanup-failure-cascades-artifact-leaks` — aggregated `finally` cleanup in the
  codex/acp models.
- `thread-list-sequential-checkpoint-n-plus-one` — `_bulk_read_checkpoints` with
  bounded concurrency + request-wide deadline.
- `unused-trace-helper`, `timestamp-utility-module-is-export-only` — modules
  already deleted.
- `canonical-ci-unit-gate-red` — does not reproduce; the canonical unit gate is
  green on `main`.
- The self-declared `Status: resolved` findings above (`stale-contract-assertions`,
  the `docs-*` set, `ty-suppression-retained-in-test-remediation`,
  `stdio-entrypoint-test-can-pass-before-entrypoint-success`,
  `lifecycle-authority-curation-review`, `dead-code-refresh-*-review`,
  `a2a-adr-grounding-drift-resolved`, `duplicate-backpressure-fanout`,
  `s101-fake-doubles-adjudication-input`, `await-listener-confirms-port-not-process`,
  and the `info` verification sweeps) stand.

### Open — a2a-local

- `acp-background-rpc-errors-only-log-and-hang` (high) — `_acp_auth` still
  log-only; the ACP prompt loop has no turn deadline.
- `unbounded-stream-subscriber-cardinality` (medium) — connections bounded
  (`fffd645e`); the subscription-count cap is still owed.
- `authorization-guard-chain-still-long` (low) — deferred by the original
  finding.
- `default-otel-import` (high), `torch-source-portability` (medium),
  `probe-gate-durability` (medium) — from the desktop-product-profile audit;
  survive the strip, need separate triage.

### Owner decision (tracked as tasks)

- `authenticated-pairing` design authority and the deletion-saga /
  `hard-delete-cross-store-nonatomic` + workspace-delete-safety findings
  (`containment-is-positional-not-provenance-based`, `silent-partial-deletion`,
  `deletion-scope-derives-from-a-duplicated-source-of-truth`) are owner-scoped
  feature/architecture decisions, not solo-drivable here.

### Cross-repo — dashboard lane

- `sse-content-exclusion-regression` (high), `unauthenticated-public-control-plane`
  (high), `per-principal-quotas-have-no-principal-to-key-on` (medium),
  `dashboard-up-path-has-no-joint-certification` (medium) — versioned wire
  contracts owned by the dashboard project, not this repository.

### Closed after reconciliation (2026-07-24, same day)

Three of the four `Open - a2a-local` items above were driven to closure
immediately after the reconciliation pass. Each landed with a real-behaviour
test carrying a negative control, so a passing run cannot be satisfied by the
pre-fix code.

- `default-otel-import` (high) - RESOLVED `4202a68b`. Root cause was narrower
  and more dangerous than "unhandled missing parent": `importlib.util.find_spec`
  returns `None` only for a missing leaf under an importable parent, and
  *raises* when a parent cannot be imported. The ordered `_OTLP_EXPORTER_MODULES`
  walk already covered the fully-absent exporter, so the surviving hazard was a
  partial install - exporter package present, its `grpc` distribution absent -
  where walking into `opentelemetry.exporter.otlp.proto.grpc` aborts gateway and
  worker startup. Both probes now route through `_spec_exists`, which treats any
  import-time failure as unavailable and degrades to the no-op tracer. Note the
  pre-existing `probe_clean_base.py` can never reach this path: it rejects any
  environment containing `opentelemetry.exporter`.
- `acp-background-rpc-errors-only-log-and-hang` (high) - RESOLVED `222731d5`.
  The finding's first clause was already closed before this pass:
  `handle_server_rpc` converts a raising handler into a `-32603` reply, proven
  over a real session pipe in `test_acp_handler_failure.py`. The outstanding
  clause was bounded turn lifetimes. `_yield_chunks` left its poll only on a
  queue sentinel or `prompt_done`, both of which require the subprocess to
  speak, so an agent that stayed alive while going silent parked the caller
  indefinitely. Bounded by silence rather than total turn length
  (`VAULTSPEC_ACP_TURN_IDLE_TIMEOUT_SECONDS`, default 600s, 0 disables) so a
  legitimately long run is never truncated.
- `unbounded-stream-subscriber-cardinality` (medium) - RESOLVED `ceb37221`.
  Completes the half `fffd645e` left open. `subscribe()` did an unbounded
  `set.update`, so one authenticated caller could demand arbitrary per-event
  fan-out from a single connection. Capped at the domain seam rather than one
  route, refused all-or-nothing, and idempotent for a reconnecting client
  replaying the set it already holds.

Still open and unchanged: `authorization-guard-chain-still-long` (low, deferred
by the original finding), `torch-source-portability` (medium) and
`probe-gate-durability` (medium) - both still needing separate triage.

New debt raised by this pass, carried forward rather than silently absorbed:

- `acp-turn-deadline-default-unproven` (low, open) - the 600s default idle
  deadline is a reasoned choice, not a measured one. No evidence yet on the
  longest legitimate silent gap a production ACP agent produces, so the default
  could in principle cut a real turn. The disable switch and the per-deployment
  override bound the blast radius; a measured default is owed.
- `subscription-refusal-counter-unasserted` (low, open) - the refusal path
  increments `aggregator.subscriptions_refused`, but no test asserts the counter
  is emitted; the finding's "expose operational counters" clause is implemented
  and unverified.
- `deletion-saga-and-workspace-delete-safety` remain owner-scoped as recorded
  above; nothing in this pass changed their status.

### Consolidation sweep (2026-07-25) - divergent-mandate findings, all open

Raised by a duplication and canonical-consolidation sweep over the tree, not by
a feature Step. Each is a contradiction between two places that encode the same
rule differently, which is a correctness class rather than a style one. Line
references are as reported by the sweep and are to be re-verified by whoever
takes the fix.

- `codex-idle-timeout-inversion` (high, open) - every ACP-family provider
  (Claude, Z.ai, Gemini, Kimi) bounds a silent turn with
  `acp_turn_idle_timeout_seconds` (600.0). Codex does not: `factory.py:663`
  takes `settings.provider_timeout_seconds` (120.0) and `factory.py:706` passes
  it into `CodexChatModel`, overriding that class's own 300.0 default
  (`codex_chat_model.py:336`); the one value then serves both the startup and
  RPC waits and the per-notification idle wait in `_consume_turn`
  (`codex_chat_model.py:542-545`). The defect is a category mismatch, not a
  smaller number: `provider_timeout_seconds` is documented as a global timeout
  for provider API calls and is correctly reused for single-shot HTTP
  (`factory.py:924`, `factory.py:950`), but a single-shot call budget is the
  wrong quantity for a streaming idle backstop. A Codex turn that is alive but
  quiet beyond 120s - a long tool call, a thinking gap - aborts as hung, while
  the same workload on the other lanes completes. No decision record pins the
  current wiring, so it reads as unintentional drift. Compounds
  `acp-turn-deadline-default-unproven`: that finding asks whether 600s is the
  right silence budget, and this one shows the budget is not even applied
  uniformly.
- `mcp-api-base-url-scope-mismatch` (medium, open) - `.env.example:103-105`
  documents `VAULTSPEC_MCP_API_BASE_URL` as overriding the MCP server's gateway
  URL alone, but `control/config.py:267-278` wires it as a `validation_alias`
  on the single global `gateway_url` field. That field also supplies the
  spawned worker's heartbeat target (`control/worker_management.py:565`,
  `worker/app.py:115-144`). An operator pointing MCP at a proxy therefore
  redirects worker-to-gateway pairing without being told, which puts a
  documentation-level assumption in direct conflict with the pairing-identity
  work.
- `aget-state-timeout-hardcoded-in-sibling` (low, open) - `worker/executor.py`
  honours `domain_config.aget_state_timeout_seconds`
  (`VAULTSPEC_AGET_STATE_TIMEOUT_SECONDS`); the sibling
  `worker/state_projection.py:239` hardcodes the same 10.0 and never imports
  `domain_config`, though its docstring records that it was extracted from
  `executor.py`. Numerically equal today, so the defect is latent: raising the
  environment knob fixes one path and silently leaves the other, which is worse
  than having no knob because the knob appears to work.

Recorded as non-findings by the same sweep, kept so they are not re-litigated:
compatibility re-export shims are absent (all facade re-exports are the
mandated pattern); the declared port policy is internally consistent; the two
product home directories differ deliberately; the `0.0.0.0` default in
`.env.example` is reconciled by loopback special-casing in
`_derive_service_urls`; `default_owner` in `lifecycle/manager.py` and
`lifecycle/singleton.py` are distinct concepts and must not be merged; and the
MCP tool layer delegates over HTTP rather than duplicating control services.

The same sweep's parallel-implementation and architecture axes add the
following. The two correctness findings were re-verified against the source
before being queued.

- `worker-health-probe-split-brain` (high, closed by `3dae643a`) - `control/worker_management.py`
  carries two implementations of "GET the worker's `/health` and decode it".
  `_probe_worker_health` treats an undecodable 200 as healthy-with-no-body by
  design, so reporting can never turn a healthy worker unhealthy.
  `_fetch_worker_health` evaluates `resp.json()` inside the `try` whose
  `except Exception` returns `None`, so the same malformed 200 is indistinguishable
  from a dead worker. One live worker therefore reads as up to the watchdog and
  `/api/health` and as absent to `_classify_worker_body` and the adopt and evict
  paths, which duplicates or evicts it - striking the authenticated-pairing
  verdict this audit's own 2026-07-24 pass hardened. Aggravating detail: the
  surviving primitive's docstring already claims to be the single worker-health
  primitive for every caller and that its callers "can never drift apart", so
  the module asserts an invariant it does not hold.
- `codex-config-home-escapes-desktop-state` (medium, closed by `5e97dafc`) - the Claude ACP
  isolated home is created with `mkdtemp(..., dir=_temp_home_root())` and sweeps
  orphans on each creation, so an armed desktop install keeps per-run homes
  inside its own accounted state directory and a system-wide temp sweep cannot
  delete a live run's home. The Codex equivalent calls `mkdtemp` with no `dir=`
  at all and has no sweep anywhere in the tree. On an armed desktop install
  Codex runs therefore drop per-run config homes outside the app's state
  directory and nothing ever reclaims them: a leak plus an uninstall-completeness
  gap. Easy to miss because the module's own docstring claims to be the
  structural analog of the Claude home. The correct repair is narrow - share
  root-resolution and sweep only. Merging the two modules would be wrong:
  file-based `auth.json` versus env token, and TOML versus JSON, are correctly
  divergent because the CLIs differ. Note the existing tests glob the system
  temp directory and so encode the defect as an expectation; they must be
  rewritten to cover both the desktop-armed and non-desktop roots.
- `control-package-is-not-a-facade` (medium, open, needs a decision record) -
  `control/__init__.py` declares an `__all__` of 20 submodule names with no
  imports and documents "Import implementations from direct child modules",
  contradicting the facade mandate. Nothing is broken: `from ... import *`
  resolves all 20 names through the documented CPython behaviour. The finding
  is queued rather than fixed because the obvious repair - eagerly importing 20
  control submodules that reach into `thread`, `database`, `streaming`,
  `authoring`, and `worker` - carries real cycle and import-cost risk in a
  repository that has already been bitten twice by exactly that, each time
  resolved with a lazy PEP-562 facade. Eager facade, lazy facade, or a recorded
  local exception is an architecture decision. Until it is decided, the 39
  one-level-deep imports of `control` submodules are structurally forced and are
  not violations. The parallel case in `thread` is NOT forced - that package has
  a proper facade - and is being repaired.
- `module-size-cap-exceeded` (low, open) - three production modules exceed the
  1000-line cap: `api/routes/gateway.py` (1572), `control/worker_management.py`
  (1211), and `graph/compiler.py` (1337). Deliberately not taken during a
  multi-lane campaign. `worker_management.py` specifically should NOT be split:
  it is the module the 2026-07-24 pass hardened, it has the highest fan-in of
  the three, and cutting freshly-proven adoption logic for a file-size target is
  a bad trade. `graph/compiler.py` is the tractable one - the `research_adr` and
  `pipeline_loop` topology clusters are self-contained and extracting both
  leaves roughly 770 lines. Nine test modules also exceed the cap, worst at
  2934; any split there must re-verify the marker-count merge gates that other
  decision records depend on.
- `acp-chat-model-size-drift` (low, open) - `providers/acp_chat_model.py` stands
  at 899 lines against the sub-600 target its own decision record prescribed
  after an earlier split. Under the cap and so not a violation, but it has
  consumed half the margin it was given, which is the evidence that size
  discipline erodes silently here rather than loudly.
- `pairing-identity-disclosed-unauthenticated` (medium, fixed pre-landing) - the
  in-progress pairing echo placed the gateway lifetime identity and the worker's
  reported pairing evidence into the shared payload that `api/routes/health.py`
  serves verbatim on the ungated `/health` under the Compose and development
  profiles. The value's entire security property is that it is unguessable - the
  armed adoption check trusts reported pairing evidence precisely because an
  attacker cannot supply it - so publishing it anonymously destroys the property
  the pairing work exists to create. Not exploitable as shipped, since the armed
  profile serves only a liveness response on that route and unarmed profiles do
  not enforce pairing, but the disclosure and the enforcement were one edit apart.
  Caught in the authoring lane's own work before it landed and closed by making
  the echo opt-in and default-closed, requested only by the attach-authenticated
  service-state verb, with a boundary test asserting both halves in one
  application so neither can pass vacuously.
- `boot-harness-orphans-a-live-gateway-tree` (medium, fixed in both homes) - both
  real-process boot harnesses handed the spawned process to the caller only on
  success, so an attempt that produced a live-but-never-ready gateway had no
  owner and no reaper: the caller's cleanup never received a handle. Each failed
  attempt therefore stranded a gateway and the worker it had already spawned,
  still holding the port the next attempt was about to request. The two homes -
  the acceptance harness and the desktop test harness - carried the identical
  defect and were fixed independently by different agents within hours, together
  accounting for roughly twenty-six orphaned processes measured live on the
  development host. The cascade is self-reinforcing: the orphans hold ports and
  CPU, which times out later boots, which strands more orphans. Recorded because
  the machine contention that obstructed this campaign's verification was in
  significant part produced by the campaign's own test harnesses.
- `boot-harness-protocol-duplicated` (medium, open, analysis requested) - the
  same-defect-in-both-homes finding above has a structural cause worth its own
  entry. The two harnesses are parallel implementations of one boot-and-retry
  protocol - spawn, poll for readiness, retry the bind race, reap on failure,
  tail the log - written twice in different code, which is why they drifted into
  the same bug independently and had to be repaired twice. A byte-identical log
  helper shared between them is the visible tip of that duplication rather than
  its extent. Explicitly NOT a merge instruction: their failure idioms are
  correctly divergent, since the acceptance harness raises a typed error its own
  retry loop catches in order to reap before retrying, and a naive merge would
  break that reap. What is owed is the analysis of which parts are genuinely one
  protocol and what a shared core would have to preserve. Also names a sweep
  blind spot: duplicated multi-step protocols are invisible to an axis that
  looks only for duplicated symbols.
- `lost-ack-proof-outside-the-default-gate` (low, open) - the durable-replay and
  lost-acknowledgement proof demanded by the desktop plan's final step lives in a
  package whose conftest marks every test `service`, while the project's default
  pytest options exclude that marker. The proof therefore never executes in the
  unit tier, so the step cannot be closed honestly on a default gate run and
  requires the service tier to be requested explicitly. Related to
  `service-gate-structurally-unpassable`: the same suite both excludes this proof
  by default and cannot pass at all from this repository alone.
- `service-gate-structurally-unpassable` (medium, open) - the canonical service
  gate cannot pass from this repository alone, and the cause is the gate rather
  than the code it guards. `test_engine_broker_lost_ack_live` hard-asserts that
  `VAULTSPEC_ENGINE_SERVE_CMD` names the dashboard serve command, while every
  sibling in the same suite - `test_pw7_acceptance`,
  `test_s20_solo_coder_bridge_live`, `test_tool_cores_floor_live` - skips
  honestly with a runbook message when the cross-repo engine is absent. One test
  therefore fails hard on any machine without the dashboard repository wired, so
  the gate reports red for a reason unrelated to this repository's health and a
  real regression would be indistinguishable from the standing failure. The
  repair is to make it skip like its siblings. Observed alongside two causes
  that are NOT repository defects and must not be conflated with it: sixteen
  fixture errors from a host Docker credential helper that aborts even anonymous
  public-image pulls, and one third-party provider quota exhaustion.
- `armed-desktop-may-not-fail-loud-on-unready-provider` (UNCONFIRMED LEAD, not a
  finding) - a single unreproduced run of the interactive mock preset through the
  armed-desktop stack reached `completed` with an empty assistant message and no
  interactive pause, while the start response carried `"provider_ready": false`.
  If real, the armed-desktop profile silently no-ops an unready provider instead
  of failing loud, which would be a fail-open on the exact profile this campaign
  hardened. Recorded as a lead and deliberately not as a finding: the single
  observation could not be reproduced because host CPU saturation caused
  subsequent gateway boots to time out. Needs an uncontended machine to confirm
  or dismiss; it must not be closed by assumption in either direction.
- `shim-sweep-analysed-at-the-wrong-granularity` (medium, methodology, closed by
  re-run) - the sweep's first pass returned a clean negative on forbidden
  re-export shims after inspecting `__init__.py` files and whole-module
  candidates. That negative was wrong. It inspected `api/schemas/enums.py`,
  quoted that module's own docstring stating five domain enums are
  "re-exported here for backwards compatibility", and cleared it anyway on the
  reasoning that a module also defining original symbols is not a shim. The
  inference is the defect: a legitimate module can still carry forbidden
  symbol-level shims, so module granularity was the wrong unit of analysis for a
  rule written about symbols, and an explicit backwards-compatibility statement
  should have settled it outright. Recorded because a clean negative from a
  mis-scoped sweep is more dangerous than no sweep - it closes the question. A
  symbol-granularity re-run (symbol imported into a module, listed in its
  `__all__`, never referenced in its body) produced nine raw hits and five
  genuine findings, below. The same question - is the unit of analysis the unit
  the rule is written in - is owed to this campaign's other clean negatives.
- `schemas-enums-symbol-shim` (medium, being actioned) - `api/schemas/enums.py`
  re-exports five domain enums from `graph/enums.py`, lists them in `__all__`,
  and uses none of them, creating a second import path that
  `api/schemas/rest.py` and `api/tests/test_websocket.py` still take. The
  canonical path already dominates. The same five lines are also absolute
  intra-package imports, so closing the shim closes five architecture-mandate
  violations with it.
- `aggregator-classify-tool-kind-shim` (medium, open) - `streaming/aggregator.py`
  re-exports `classify_tool_kind` from `streaming/types.py` without using it.
  The live harm is present rather than hypothetical: `control/snapshot.py` takes
  the shim path while `control/projection.py` takes the canonical one, so one
  symbol has two import paths in the same subsystem.
- `require-attach-alias-shim` (medium, DEFERRED - do not action during the
  campaign) - `api/dependencies.py` aliases `authenticate_request` as
  `require_attach`, exporting one function under two names. Mechanical in shape,
  but it is authentication surface, `require_attach` is the credential gate on
  the `/api` surface that is mid-deprecation, and its consumers include a route
  module under active rewrite. Deferred deliberately: renaming an auth symbol
  across an in-flight file is a poor trade for a naming cleanup.
- `heartbeat-stale-ms-dead-re-export` (low, being actioned) - `lifecycle/discovery.py`
  re-exports `HEARTBEAT_STALE_MS` from `authoring/discovery.py` with no consumer
  on that path, so it is surplus surface rather than a live second path. The
  surrounding delegation in the same module is deliberate and documented - the
  freshness contract is centralised on purpose - and must not be disturbed by
  removing the constant.
- `compiler-vault-index-re-export` (low, open, low confidence) -
  `graph/compiler.py` exports `build_initial_vault_index` from
  `graph/nodes/vault_reader.py` without using it. Recorded rather than actioned:
  `compiler.py` is the graph package's public entry point, so this may be
  intentional package surface rather than a shim, and it entangles with the
  deferred split in `module-size-cap-exceeded`.
- `claim-new-directory-orphaned` (low, being actioned) - `claim_new_directory`
  in `desktop/_filesystem_authority.py` has exactly one reference in the tree:
  its own definition. Its only consumer was the capsule subsystem removed in
  `e9ef823a`, and that commit shows no diff against this file because the
  module's sibling functions are still live, so the leaf was missed. Confirmed
  not registry-dispatched, not a facade re-export (the module is underscore
  private and never named by `desktop/__init__.py`), not a fixture, and not an
  entry point; the sibling importers in `lifecycle/discovery.py` and the module's
  own tests each import a subset that pointedly excludes it. Being deleted on
  the consolidation pass.
- `mock-only-graph-topologies` (medium, OWNER DECISION - do not action) -
  `_compile_star` and `_compile_pipeline_loop` in `graph/compiler.py` have no
  non-mock preset consumer; only the two mock preset files select those
  topologies, while the real presets are single-agent pipeline and `research_adr`.
  This is re-discovery of a question this project already heard and deliberately
  set aside: the earlier dead-code campaign audit records removal as a
  contract-adjacent architecture decision left to the architect successor
  ledger, and the topologies are preserved under a dashboard contract clause. A
  new preset file would exercise them with no code change. Recorded here so the
  re-discovery is not mistaken for new information; it must not be actioned on a
  consolidation pass. Sequencing note: if the topologies were ever removed,
  `graph/compiler.py` falls under the module-size cap with no split at all, so
  this decision precedes the split proposed in `module-size-cap-exceeded`.
- `legacy-api-deprecation-has-no-expiry` (low, open) - the `/api` surface is in
  a sanctioned bounded deprecation behind an attach credential while `/v1` is
  canonical, and the live gating is correct. Its removal is tracked by plan
  Steps S106 and S163, but no expiry date exists, and the pre- and post-removal
  certification runs that once gated those Steps were retired with the
  other-project work, so neither now has an automated proof that no consumer
  depends on the surface. Whoever executes them must establish that another way.

### `W01.P02.S06` scoping analysis (2026-07-24) - not closed

S06 asks to "verify the landed desktop owned-tree implementation reaps the
complete worker tree on startup readiness timeout". Investigated but
deliberately NOT closed, because the Step as worded cannot be honestly proven
and the reason is worth the owner's attention rather than a contrived test.

What the implementation does: the readiness loop in
`control/worker_management.py` distinguishes two failure exits. A worker that
dies on its own is detected by `process.poll()` and releases the containment
handle; a worker that stays alive but never verifies runs to the deadline and is
reaped with `await containment.terminate(term_timeout=5.0, kill_timeout=5.0)` -
the whole-tree primitive - rather than `process.terminate()`. That branch
selection is the actual safety property.

Why the Step's premise is partly vacuous: at the startup-readiness-timeout
instant the worker has no descendants to reap. The worker package spawns no
subprocesses at all (no `Popen`, `spawn_acp_process`, or `create_subprocess`
anywhere under `src/vaultspec_a2a/worker/`); provider trees are spawned from
`providers/` while executing a run, which by definition has not happened yet
because the worker never became ready. So "the complete worker tree" at that
boundary is the worker process alone.

Why this was not tested anyway: a test that reached the branch with a real
worker (held un-ready via a deliberate generation mismatch, so it stays alive
and healthy but never classifies as ours) would assert only that the worker pid
dies - which `process.terminate()` would also achieve. The assertion cannot
discriminate the containment path from the per-pid path without a descendant
existing, and no supported seam produces one: `module_command` is a closed
allowlist with no override by design, so substituting a descendant-spawning
stand-in worker would mean adding test-only production surface to a deliberately
sealed execution allowlist.

Recommended re-scope for the owner, rather than a silent close:

- Narrow S06 to the invariant that is real at this boundary - the timeout exit
  reaps through the containment primitive and the premature-exit exit releases
  the handle - and prove it where descendants genuinely exist.
- The descendant-bearing reap is already covered at the boundaries where a tree
  actually exists: `desktop_tests/test_owned_process_tree.py` proves
  contained-before-work and reaped-whole on graceful termination and on forced
  orphaned termination, and the gateway-owned worker leg proves the graceful
  shutdown reap.

Adjacent finding raised while reading this path:

- `worker-readiness-deadline-is-an-unnamed-literal` (low, open) - the 30-second
  readiness deadline is a bare literal at the `deadline` assignment, and the
  same `30.0` is repeated as the base of the `elapsed` progress math in three
  places. Changing the deadline silently falsifies every elapsed figure logged
  during startup. Unlike its neighbours (`worker_poll_initial_interval_seconds`,
  `worker_poll_backoff_factor`, `worker_poll_max_interval_seconds`) it is not a
  setting.

### Second pass (2026-07-24) - S06 driven to completion, remaining queue cleared

Owner direction: reconcile against what the code actually does, not the plan's
wording; functionality over bookkeeping. That inverted the S06 conclusion
recorded in the previous section.

#### `W01.P02.S06` - RESOLVED `140f26a1`, and it was a real defect

The earlier analysis was right that the worker owns no descendants at the
readiness-timeout instant, and wrong to stop there. Reading the branch for
functionality rather than for the Step's wording found that
`worker-startup-timeout-orphans-process-tree` had only ever been half fixed.
The armed-desktop branch reaps through its OS containment; the other branch -
the one Compose and every development run take - still called a bare
`process.terminate()`.

That signals the immediate process only: no descendants, no escalation past a
SIGTERM the worker may be ignoring, and no wait on the handle. `_spawn_worker`
then returns `None` and reports the spawn as failed, so anything still alive is
an orphan holding the worker port - and the next spawn meets its own leftover
there and refuses it as an unidentified occupant. An incomplete reap wedges the
band rather than merely leaking a process. The graceful-shutdown path had used
`kill_pid_tree_async` correctly all along; only the timeout path had not.

Both bands now route through one named seam, `_reap_unready_worker`, with a
bounded wait on the handle so no zombie is left on POSIX. Tests drive real
process trees through it on both bands; the stand-in worker ignores SIGTERM so
the escalation is exercised rather than assumed. Verified discriminating: all
three fail against the pre-fix implementation.

The Step is therefore closed by fixing what it existed to verify. Its wording
still deserves the re-scope noted in the previous section, but the invariant it
protects is now real and proven.

#### Cleared from the open queue

- `worker-readiness-deadline-is-an-unnamed-literal` (low) - RESOLVED
  `140f26a1`. Now `VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS`. The literal appeared
  five times, twice as the base of the elapsed-progress math where a changed
  deadline would have silently falsified every startup timing logged; elapsed is
  measured from a start stamp, so no base remains to keep in sync.
- `subscription-refusal-counter-unasserted` (low) - RESOLVED `3fba5f05`.
  Asserted through the real OTel hook, which registers counters lazily, plus an
  accepted-subscription control proving the registry is otherwise empty.
- `acp-turn-deadline-default-unproven` (low) - MITIGATED `3fba5f05`. The default
  still cannot be measured here - no preserved session transcripts exist - so
  the signal was widened instead of the number defended: the stderr drain stamps
  the same liveness clock, and an agent whose progress goes to its log rather
  than over the protocol no longer trips the deadline. The deliberate trade is
  that a chatty wedged agent survives longer, which is at least visible. The
  default remains unmeasured against production traffic and stays queued as
  such.
- `probe-gate-durability` (medium) - RESOLVED `8a775ddc`. The finding was exact
  on both counts: `probe_clean_base.py` appeared in no Justfile, just module, or
  workflow and had never run, and it has no installed-module form because the
  wheel excludes `**/tests`. Registered as `just dev test clean-base` and run on
  every push, in an isolated default-deps environment - the CI environment syncs
  with `--extra server` and installs the exporter, so no earlier step can
  observe a base-only install. It is now the standing regression gate for
  `default-otel-import`.
- `torch-source-portability` (medium) - RESOLVED `8a775ddc` as documentation,
  which is the only available remedy. `tool.uv.sources` is not emitted into
  wheel `Requires-Dist` and PEP 508 has no index selector, so the override
  cannot be carried in published metadata at all. Stated at the point of
  definition so it stops reading as a property of the published package.

#### Investigated and dispositioned without a change

- `authorization-guard-chain-still-long` (low) - REMAINS DEFERRED, and the
  original remedy does not fit. The finding proposes lifting each guard into a
  named predicate returning an optional rejection, but five of the six guards in
  `_authorize_permission_response` are transactional, not pure: they call
  `create_control_action` and `commit` (lines 346/355, 374/383, 458/467,
  498/507, 540/549). Reshaping them as predicates would either hide commits
  inside predicates - worse than the flat chain - or move the transaction
  boundary, which is a design change on a security-adjacent authorization path
  with no behavioural gain. Recommend re-scoping to a deliberate step that
  decides the transaction boundary first, rather than a mechanical extraction.
- `containment-terminate-returns-true-with-no-pid` - WITHDRAWN, not a defect.
  Raised while reading the reap paths, on the theory that a containment holding
  no pid silently reports success. It is correct: `assign()` records `self._pid`
  as its first statement, before the POSIX branch and before the Windows
  job-object check, so any attempted assignment leaves a reapable handle even
  when it then fails. The only way to reach the no-pid return is never having
  attempted assignment, where "nothing to reap" is the true answer. Recorded so
  the same theory is not re-derived later.

### Third pass (2026-07-25) - parallel execution findings

Findings raised while driving W01.P03, W02.P06, and W01.P01 in parallel. Code
evidence only; step outcomes are recorded separately once their gates pass.

#### `per-principal-stream-quotas-have-no-principal` (high, blocks `W02.P06.S25`)

S25 asks for per-principal stream and subscription quotas "after
 authentication". It cannot be implemented as written, and the reason is
architectural rather than an execution gap.

Authentication on this surface is a single shared attach credential.
`api/app.py:193` `_http_attach_authorized` compares the supplied bearer against
one `app.state.v1_service_token` with `hmac.compare_digest`; the WebSocket check
mirrors it. There is no subject, no claims, and no per-caller identity anywhere
in the chain - `api/routes/thread_stream.py` takes only `get_db` and
`get_aggregator`, with no identity dependency at all. Every authenticated caller
is therefore indistinguishable from every other, so a per-principal quota has
nothing to key on and would be indistinguishable from the global limit already
enforced.

What IS in place and adequate for the global dimension: the connection cap
(`max_stream_connections`, refused before the thread lookup) and the per-client
subscription cap (`max_subscriptions_per_client`, all-or-nothing, with a refusal
counter).

Closing S25 requires first deciding whether callers get distinct identities -
per-caller tokens or a claims-bearing credential - which is an ADR-level change
to the authentication model, not a step. Recommend re-scoping S25 behind that
decision rather than leaving it open as though it were implementable work.

#### `caller-supplied-workspace-root-is-unconstrained` (medium, trust-boundary decision)

`api/routes/gateway.py:746` `_prepare_workspace_root` reads `workspace_root`
from request-body metadata and accepts it on `candidate.is_absolute()` alone;
the same value is also accepted as a query parameter. It flows into
`load_team_config`, which reads `{workspace_root}/.vaultspec/teams/{id}.toml`
(`team/team_config.py:717`). The team identifier is regex-guarded, so there is
no traversal through it, but the root itself is unconstrained: an authenticated
caller directs preset resolution at any absolute path on the gateway host.

Impact bounded honestly: `AgentModelConfig` carries `Provider`/`Model` enums,
not a command string, so a planted preset cannot name an arbitrary executable
directly. It can set `AgentCapabilitiesConfig` and `AgentPermissionsConfig`, and
`terminal` capability does reach command execution - but only for a caller who
can already write a file on the host, which is the precondition that keeps this
from being straightforwardly exploitable.

Deliberately NOT clamped. Under the armed desktop profile the user's workspace
legitimately IS an arbitrary absolute path - their own project directory - and
the authenticated caller is their own dashboard, so containing the root under
`settings.workspace_root` would break the product's core use case in one line.
Routed to the owner with three options; the recommendation is to split by
profile, unconstrained on armed desktop and allowlisted under Compose, since
Compose is the deployment where the value crosses a real trust boundary.

#### `published-openapi-artifact-is-stale-and-malformed` (medium, closed - artifact regenerated by `c0d7d394`, drift gate added by `d07cf251`)

The committed `openapi.json` is broken three independent ways, and nothing
validates it - the one test that touches OpenAPI builds the document live from
`app.openapi()` and never reads the file.

- It documents 18 paths against the live application's 24, missing the entire
  versioned public surface: `/v1/runs`, `/v1/runs/{run_id}`, its `cancel` and
  `stream` members, `/v1/presets`, and `/v1/service`. A consumer generating a
  typed client from it - which is exactly what the open type-safe-client task
  proposes - would produce a client with no gateway verbs at all.
- It is cp1252-encoded, carrying `0xa7` at offsets 41842 and 42327, so it is not
  valid UTF-8 and a strict RFC 8259 parser rejects the file outright.
- It carries five `ADR-013 §6` vault references in description strings. The live
  document carries none, and no source file under `src/` mentions an ADR
  identifier, so the artifact predates the dev-metadata scrub and preserves
  exactly the coupling that scrub removed.

Fix is to regenerate from the live application as UTF-8 and add a gate asserting
the committed artifact matches, so it cannot silently drift again.

#### `shared-index-cross-staging` (low, process)

Three executor agents shared one working tree and one git index. One agent's
formatting commit staged broadly and captured an unrelated file rename staged by
the orchestrator, recording it under a message that does not describe it. No
work was lost and the rename is correct; the cost is a misleading history entry,
recorded rather than rewritten. Parallel agents in a shared tree must stage
explicit paths and verify the staged set before committing.

### W01 deletion-saga review (2026-07-25)

Adversarial read of the saga landed today (`fd764ed9`, `37f2b4c0`, `5ad477f5`,
`d4506894`, `5e90d584`, `f40bf075`). Performed by the orchestrator directly:
three successive review agents went idle without delivering findings, so this is
first-hand reading rather than a delegated report.

The phase does close what it set out to close - scope is captured once in a
durable manifest, cleanup items run independently and never raise, finalize
refuses until every item is DONE, and artifact paths that escape the recorded
workspace root are refused including via symlink. Two liveness defects survive,
both of which end with a thread hidden from product reads forever.

#### `deletion-claim-does-not-exclude-a-second-pass` (high, open)

`claim_deletion_saga` (`control/repositories/deletion_saga.py:254`) stamps
`claimed_at` on first call but returns the hydrated saga to EVERY caller,
including one that finds the row already claimed. Its own docstring states this:
"a repeated claim leaves it unchanged and returns the same saga". So the
ownership marker is recorded and never enforced - it is a get-or-stamp, not a
claim, despite `W01.P03.S108` being worded as "claims one deletion saga", and
`test_claim_stamps_ownership_once` only asserts the timestamp is written once,
never that a second claimant is refused.

This is reachable, not theoretical. `_run_deletion_saga`
(`control/thread_service.py:669`) runs on every delete request including a
replay, which `W01.P03.S13` exists precisely because clients issue. Two
concurrent DELETEs for one thread therefore both claim, both take a snapshot of
`saga.results` at claim time, and both execute the manifest.

Failure scenario: request A claims and begins; request B (a client retry after a
timeout, or a double-click) claims the same saga and receives a results snapshot
that does not include A's progress. Both execute items. Both call
`advance_deletion_cleanup_item` (line 276), which is an unlocked
read-modify-write over the whole `result_json` blob - `session.get`, deserialize,
mutate, serialize, flush - with no `SELECT ... FOR UPDATE` and no per-item
write. B's write, built from a read taken before A's commit, drops A's recorded
item. That item's result is now permanently absent, `manifest_is_complete`
(line 199) can never return True, `finalize_deletion_saga` refuses forever, and
the thread stays hidden from product reads with its rows intact. The user sees
the thread disappear; it is never actually deleted.

SQLite serialises the writes but not the read-modify-write window, and the
schema explicitly supports a Postgres backend where READ COMMITTED makes the
lost update straightforward.

The minimum fix is to make the claim exclusive - a conditional update that
returns `None` when another pass holds it - or to make `advance` a
per-item-keyed write rather than a whole-blob rewrite. Either removes the lost
update; the first also stops the redundant double execution.

#### `a-permanently-failing-cleanup-item-wedges-the-thread-hidden` (high, open)

`manifest_is_complete` requires every item to be `DONE`. There is no terminal
failure state, no attempt ceiling, and no operator escape. An item that can
never succeed - a Windows file held open by another process, a permissions
error, an artifact on a detached volume - keeps the saga unfinalizable for the
lifetime of the deployment.

Failure scenario: a user deletes a thread whose artifact file is locked. The
thread is immediately hidden from lookup and list by `W01.P03.S11`, every retry
re-runs the same item and records the same failure, finalize refuses, and the
rows are never removed. The thread is invisible to the product, undeletable
through the API, and observable only by reading the control store directly.
Nothing surfaces it: the delete endpoint returns `cleanup_incomplete`, which a
client that has already seen the thread vanish has no reason to act on.

This is the direct cost of hiding deleting threads from product reads, which is
otherwise correct. The pairing needs either a terminal `FAILED` disposition that
finalizes with the failure recorded, or a surface that lists wedged sagas so an
operator can see and resolve them.

#### Verified sound in this pass

Manifest-as-single-source-of-scope (captured once at create, first manifest kept
on a repeated create); cleanup-item independence and never-raising; artifact
path containment against absolute escape, parent traversal, and symlink escape;
finalize's refusal-until-complete guard; and the migration's presence under the
repository's Migration Check job, green on the release commit.

Coverage limit stated honestly: this reviewed `W01.P03`, the new work. `W01.P01`
and `W01.P02` were reviewed earlier in the campaign and were not re-read here,
so `W01.P04.S15` is only partly discharged.

### W04 review (2026-07-25)

Performed by the orchestrator directly. Four review agents were dispatched
across this session and every one went idle without delivering findings, so this
is first-hand reading.

#### `S104-VERDICT`: the claim holds

`W04.P12.S104` claimed that tautological and shadow-logic tests were replaced
with assertions against imported production behaviour. Tested adversarially
across `src/vaultspec_a2a/`, it stands:

- `MagicMock`, `@patch`, `pytest.mark.xfail`: zero occurrences.
- `unittest` imports: zero. The two files matching the word contain it only in
  prose.
- `monkeypatch`: zero actual uses. All 42 matches are docstrings and comments
  asserting its ABSENCE - "No mock, monkeypatch, or fake", "never by
  monkeypatching the running interpreter", "real settings, no monkeypatching".
  A file-level count reads as 36 offenders and is entirely false positives; the
  method-call form `monkeypatch.<attr>` does not appear anywhere.
- Suppressions: one `# noqa: SIM115` in `lifecycle/manager.py:295`, on a file
  handle deliberately outliving its block, and no live `ty: ignore` at all - the
  single match is a docstring describing when one would be needed.

Layer discipline is also clean: `streaming/`, `graph/`, `context/`, and
`thread/` contain zero imports of the infrastructure `control.config` settings.

#### `provider-skip-gates-never-run-in-ci` (medium, open)

The one residual from `test-policy-regression-after-closeout`, which named "skip
gates across provider and live suites". They are still there, and the plan's own
acceptance criterion - "Required certification jobs must fail when prerequisites
are unavailable" - is not met, because they silently skip instead.

The gates are `skipif` conditions on external prerequisites: the Codex CLI on
PATH (`test_codex_chat_model.py:186,194,249`), a configured `ZAI_AUTH_TOKEN`
(`test_zai_fidelity.py:41`), an available mcp streamable-http transport
(`test_acp_authoring_bridge.py:136`), plus module-level gates in
`test_harness_gateway.py:39`, `test_acp_project_mcp.py:435`, and
`test_codex_config_home.py:267`.

The workflow installs none of them - no Codex install step, no `ZAI_AUTH_TOKEN`
secret, no mcp transport provisioning appears anywhere in `.github/workflows/`.
So these tests do not merely skip occasionally; they skip on EVERY CI run, and
have never executed there.

Failure scenario: a change breaks Codex session handling or the Z.ai fidelity
contract. Locally the author may have the CLI and see the failure; CI does not,
reports green across all five jobs, and the regression merges. The suite's own
reported totals conceal it, because a skip is not a failure and the count of
skipped tests is not surfaced against a threshold.

Two honest resolutions, and the choice is the owner's: provision the
prerequisites in the certification job so the tests actually run, or keep them
local-only but make their absence explicit - a required job that asserts the
expected set executed, so a silently shrinking suite fails loudly instead of
passing quietly.

#### Not re-examined

`W04.P14`'s orphan removal and `W04.P15`'s hotspot decomposition were verified
by their own Steps and by the post-decomposition complexity recalculation
recorded as `complexity-recalculation-w04-p15`; they were not independently
re-derived here. `W01.P01` and `W01.P02` were likewise not re-read, so
`W01.P04.S15` stays open as partly discharged while `W04.P17` closes.

### `W05.P18` closeout findings (2026-07-25)

#### `W05.P18.S82` - already satisfied, no new work written

S82 asks to certify that a Compose provenance mismatch fails closed without
worker adoption or eviction. That is already proven by
`test_compose_provenance_mismatch_fails_closed_without_eviction` in
`service_tests/test_compose_profile_regression.py:481`, landed under
`W01.P01.S157`, and it covers BOTH halves S82 names rather than only the one
S157's wording mentions:

- no adoption - `assert spawner.spawned is False`;
- no eviction - the worker's request log contains only `GET /health`, never a
  shutdown, and the process survives (`worker.poll() is None`).

It is discriminating in both directions: its docstring records that degrading
the provenance check to a bare health probe flips `spawned` to True, and the
sibling `test_compose_matching_provenance_attaches` proves the refusal is
provenance-specific rather than a harness that always fails. Closed by pointing
at that evidence; writing a second test would have been duplication dressed as
coverage.

#### `permission-response-exists-only-on-a-surface-the-plan-removes` (high, open, blocks `W05.P18.S81`)

S81 asks to certify proposal-review permission resume and terminal settlement
"through the public facade". It cannot be done as worded, and the reason is
structural rather than a gap in test coverage.

The versioned public facade is a fixed six-member whitelist - `/v1/presets`,
`/v1/runs` (get and post), `/v1/runs/{run_id}`, `/v1/runs/{run_id}/cancel`,
`/v1/runs/{run_id}/stream`, `/v1/service`. None of them answers a permission
request. The status member surfaces `approval_status` and
`approval_request_id`, so the facade can report that a run is WAITING on a human
decision, but offers no way to give one.

The only channel that answers is `POST /api/permissions/{request_id}/respond`
(`api/routes/permissions.py:43`), which is a legacy `/api` product route. The
legacy event WebSocket is not a second channel: it explicitly refuses the
command with `PERMISSION_RESPONSE_WS_FORBIDDEN` (`api/websocket.py:444,466`),
deliberately routing callers to REST.

That makes this a blocker for the campaign's own endgame, not just for S81.
`W02.P07.S28` disables the legacy product routes in Compose and `W05.P20.S106`
removes them outright. Executing those Steps as written deletes the sole means
of answering a permission request, and human-in-the-loop approval - a core
product behaviour, with a whole review-and-settlement path behind it - stops
being reachable through any supported surface.

Failure scenario: `S106` lands after the dashboard composite proves no
dependency on the legacy routes. The composite exercises run control, which is
fully served by `/v1`, so it passes. A run then requests permission, the
dashboard reads `approval_status` from `/v1/runs/{run_id}` and displays the
prompt, and there is no endpoint to POST the answer to. Every run needing a
human decision hangs at that point.

The decision this needs is the owner's, because it changes the shape of the
public contract: either the six-member whitelist gains a permission-response
member before `S106` removes the legacy route, or `S106` is re-scoped to retain
that one route, or human-in-the-loop approval is declared out of scope for the
supported surface. S81 should stay open behind whichever is chosen - certifying
resume through a facade that cannot resume is not possible.

### `W05.P20` canonical gate runs (2026-07-25)

- `S87` `just dev code check` - PASS. Ruff lint, Ruff format across 560 files,
  whole-tree `ty`, deptry, and actionlint all clean.
- `S141` `just dev deps check` - PASS. `uv lock --check` consistent across 189
  packages.
- `S143` `just dev test service` - DID NOT PASS here, and the cause is this
  machine rather than the codebase. Left open rather than marked on CI's behalf.

#### `service-gate-blocked-by-local-docker-credential-store` (low, environment)

The service gate reports 2 failed, 54 passed, 39 skipped, 16 errors. Every one
of the 16 errors is the session-scoped `service_stack` fixture failing at
`docker compose ... up -d --build vidaimock jaeger`, and the underlying cause is
not a missing dependency: Docker is present and healthy (29.6.2). The pull fails
with `error getting credentials - err: exit status 1, out: 'A specified logon
session does not exist. It may already have been terminated.'` - the Windows
credential helper cannot read its logon session, so no image can be pulled.

The same surface is certified in CI, where the Compose server profile regression
job passes on every push, so this is a local-environment blocker on running the
gate rather than evidence about the code. Recorded so a later reader does not
re-diagnose it as a product failure.

#### `service-and-provider-suites-disagree-on-missing-prerequisites` (medium, closed by `18bb720a` and `556ed933`)

Worth stating because the two conventions sit in one repository and only one is
right.

When its prerequisite is absent, the service suite ERRORS - loudly, 16 times,
impossible to miss - which is exactly what the plan's acceptance criterion asks:
"Required certification jobs must fail when prerequisites are unavailable." The
provider suite, under the separate finding
`provider-skip-gates-never-run-in-ci`, SKIPS instead, and skips silently on
every CI run because the workflow provisions nothing it needs.

So the repository already contains the correct pattern; the provider gates
simply do not follow it. That makes the fix for the provider finding concrete
rather than open-ended - adopt the convention the service suite already
demonstrates, and let an absent prerequisite fail rather than vanish.

### W01.P01 pairing mutation test (2026-07-25)

A mutation experiment on the pairing boundary, run to completion and reverted.
Worth recording because the result is a positive one and the reasoning is easy
to get backwards.

**The mutation.** The worker health endpoint reports its pairing evidence from
the environment, defaulting to empty strings when it was not spawned by a
gateway (`worker/app.py:286`). The mutation replaced those defaults with a
fabricated lifetime and a generation of `1`, modelling a worker that claims a
pairing identity it was never given.

**The result.** 169 tests passed with the mutation live - the whole pairing,
provenance, and lifecycle set. A surviving mutation normally means the tests are
blind to it, so this looked at first like a hole in exactly the certification
`S156` and `S157` closed.

**Why it is not a hole.** `classify_worker_pairing`
(`lifecycle/pairing.py:163-166`) fails closed on both inputs by different
routes: blank evidence is `UNIDENTIFIED`, and any value that does not equal this
gateway's own lifetime is `FOREIGN`. `_spawn_worker` refuses both identically -
no adoption, no eviction. The mutation therefore moves the verdict LABEL without
moving the behaviour at the security boundary, and the suite is right to stay
green. Asserting on the label rather than the outcome would have been the
weaker test.

The underlying property is stronger than the certification states: a worker
cannot promote itself by inventing pairing evidence, because the only value that
classifies as OWNED is the gateway's own `uuid4` lifetime, which a process that
gateway never spawned has no way to learn. Fabrication and silence are
equivalent to the classifier, and both are refused.

This is the second time in this campaign that a plausible finding dissolved on
inspection - the first was a `monkeypatch` file count that was entirely
docstrings asserting its absence. Both were caught by reading the mechanism
rather than trusting the signal.

#### `dispatched-agents-left-artifacts-in-the-worktree` (low, process)

A review agent dispatched as read-only wrote to the tree twice: a `.probe/`
directory of investigation scripts at the repository root, which is not
git-ignored and would have been captured by any broad `git add`, and the
mutation above left uncommitted in production code. The probes were relocated
outside the repository rather than deleted (their questions were sound), and the
mutation was reverted. Had it been committed, a worker started outside a gateway
spawn would have advertised a fabricated pairing lifetime on its health
endpoint - noise on a security-relevant surface, for no gain.

Parallel agents in a shared worktree need the same discipline already recorded
for staging: verify `git status` before every commit, and treat an unexpected
production diff as a stop condition rather than something to commit around.

### `W01.P01.S02` and `W05.P20.S142` (2026-07-25)

`S142` `just dev test unit` - PASS, 2604 passed, 111 deselected, in 17m15s.

An earlier run of the same gate reported 2602 passed and was DISCARDED rather
than counted. It overlapped the pairing mutation experiment, and the suite
spawns real subprocesses that re-read `worker/app.py` from disk, so a
mid-flight edit could have reached tests collected after it. A certification
gate whose inputs changed under it certifies nothing; it was re-run against a
pristine tree with no agents active. The two extra tests are `S02`'s.

`S02` - closed by `35cfe5a6`. The certification proves the prerequisites hold
and, more importantly, proves the limit the Step's wording insists on: that
holding them is not evidence of pairing identity. It does so with a REAL second
production worker started outside any gateway spawn, holding the very same
gateway-minted IPC credential over the same application home - a genuine worker
rather than an adversary stand-in - and separates three things that are easy to
conflate:

- the credential does not identify: the stranger answers the authenticated probe
  200 and refuses the unauthenticated one 401, exactly as the gateway's own
  worker does;
- the addressing does not identify: both report a byte-identical declared
  `gateway_url`, so the legacy declared-target comparison cannot separate them;
- only reported pairing evidence identifies.

Verified discriminating rather than assumed: with the worker's pairing defaults
mutated to a non-blank value, the test FAILS.

#### `s02-docstring-overstates-the-mutation-consequence` (info)

The test's docstring says that defaulting the pairing evidence to anything
non-blank makes the stranger's verdict "flip to an adoptable verdict". It does
not. `classify_worker_pairing` sends blank evidence to `UNIDENTIFIED` and any
non-matching value to `FOREIGN`, and `_spawn_worker` refuses both identically -
no adoption, no eviction. The mutation degrades the QUALITY of the evidence, not
the security outcome.

The test is still correct and still discriminating; it fails because it asserts
the specific verdict `UNIDENTIFIED`, which is the right thing to assert. Only
the stated rationale overreaches. Recorded because a future reader who trusts
that sentence would conclude the mutation is exploitable, and it is not - the
only value that classifies as `OWNED` remains the gateway's own `uuid4`
lifetime, which a process it never spawned cannot learn.

### W01.P02 lifecycle review (2026-07-25)

First-hand review of the startup-transactionality Phase. The dispatched agent
for this work went idle without delivering, as six before it did.

#### Verified sound

The transactional shape holds and closes what it was meant to. `serve_up`
(`lifecycle/manager.py:623`) reserves a band port behind an `O_EXCL` marker so
two concurrent same-band boots cannot claim one port, spawns, awaits readiness,
and only then commits the claiming record. A commit that fails AFTER readiness
reaps the child before propagating (`manager.py:709-713`), so
`serve-up-commit-failure-leaks-child` is genuinely closed rather than narrowed.
Restart mirrors the same spawn -> await-listener -> commit-or-reap discipline and
verifies readiness BEFORE publishing (`manager.py:814-820`), so a failed resume
never publishes a record pointing at a dead pid and the prior generation remains
the last committed state - `restart-registers-before-readiness` closed.

Readiness is also ownership-aware rather than port-aware: `_await_listener`
refuses a bound port until `listener_belongs_to` confirms the listening pid is
the child or a descendant, so an un-reaped orphan of a felled generation, or a
racer on a fixed resume port, does not read as our process being ready. That is
the substance of `await-listener-confirms-port-not-process`.

#### `ownership-check-degradation-is-silent` (medium, closed - tri-state ownership classifier consumed at the readiness gate)

The ownership check fails open by design, and the design is right - failing a
legitimate boot because a pid could not be resolved would be worse than the risk
it guards. `listener_belongs_to` (`utils/process.py:240-258`) returns `True`
whenever `port_listener_pid` yields `None`, degrading to the bare bound-port
signal, and `port_listener_pid` yields `None` whenever no owner can be read - no
`netstat` on Windows, no `/proc/net` and no `lsof` on POSIX, or an unreadable
parent map.

What is missing is not the fallback but any evidence it happened. Neither
function logs, increments a counter, or returns the distinction to its caller,
and `_await_listener` cannot tell "confirmed ours" from "could not tell". So on
any host where pid resolution routinely fails - a hardened container without
`lsof`, a restricted-permission POSIX environment, a Windows image without
`netstat` - the check is a silent no-op everywhere, permanently, and
`await-listener-confirms-port-not-process` is effectively unfixed there while
reading as closed.

Failure scenario: a deployment ships without `lsof` in the worker image. Every
readiness probe degrades. An un-reaped orphan from a previous generation holds
the band port; the new child binds nothing but the orphan's port reads as bound;
readiness passes on the stranger; a record is committed pointing at a listener
the gateway does not own - exactly the condition the check exists to prevent -
and nothing in the logs distinguishes that boot from a healthy one.

The fix is observability, not behaviour: surface the degraded outcome, so a
deployment that has silently lost the ownership guarantee is discoverable rather
than indistinguishable from one that still has it.

### `W05.P20.S144` real-process suites (2026-07-25)

PASS - 46 passed, 74 deselected, in 9m22s, across the acceptance, desktop, and
service suites.

The Step's command names `tests/acceptance`, which does not exist; the suite
lives at `src/vaultspec_a2a/acceptance` because `pyproject` sets `testpaths` to
`src/vaultspec_a2a` and a tree outside it would never be collected. Same stale
scope path as several sibling Steps.

#### A discarded first run, and why it is worth recording

The first attempt reported one failure -
`test_stale_discovery_quarantined_only_by_owner`. It was not a product defect
and not a regression from the ownership change committed just before it. The
cause was self-inflicted: the utils and lifecycle suites, which spawn real
listeners on real loopback ports, were being run in the foreground while this
suite ran in the background. The same test took 25.06s under contention and
1.49s in isolation, and the clean re-run with nothing else active passed.

That is the third time in this campaign that running real-process suites
concurrently has produced a misleading result - it previously stalled a gate
long enough to look hung, and produced a unit-gate figure that had to be thrown
out because a mid-flight edit could reach subprocesses. Real-process suites here
claim real ports and spawn real gateways; they are not safe to overlap, with
each other or with an edit to the tree under them. Recorded as a working
constraint rather than diagnosed a fourth time.

### Orchestrated fleet pass (2026-07-25)

Five lanes driven in parallel against one shared worktree. Closed with evidence:
the worker-health probe split-brain and the pairing-identity disclosure; the
boot-harness orphan reap; the Codex idle-timeout inversion; both deletion-saga
liveness defects (`92a2532d`, `71d2c8e4`, `47cab371`); the `aget_state` timeout
knob (`ab3a943f`); the tool-kind and heartbeat re-export shims (`970db6e2`); the
domain-enum symbol shim and its five absolute-import violations (`effb2805`);
the OpenAPI artifact gate (`d07cf251`); the MCP alias scope lie (`812c6b01`);
the Codex config-home escape (`5e97dafc`); and the prerequisite rule that gives
an absent external dependency one meaning across the gates (`18bb720a`,
`556ed933`). The canonical service gate moved from two hard failures to one.

#### `cleanup-abandonment-not-surfaced-to-the-caller` (medium, open)

Found by first-hand reading, not by the lane that wrote the fix. The
terminal-disposition repair genuinely closes the wedge: `_abandoned_items`
settles a manifest once every item is `DONE` or `ABANDONED`, and
`finalize_deletion_saga` proceeds over abandoned items deliberately, so a
permanently-failing cleanup item no longer hides a thread forever.
`DeleteResult` carries `cleanup_abandoned` and the abandonment is logged with
per-item detail.

The route does not read it. `api/routes/threads.py:223` branches on
`cleanup_incomplete` alone, so a delete that finalized over abandoned items
returns as an ordinary success. The caller is told the thread is deleted while
artifacts remain on disk, and the only record is a log line. This is the second
finding's "recorded somewhere nobody looks" clause resurfacing one layer up: the
liveness defect is fixed and the observability half is not. Related to the
owner-scoped `silent-partial-deletion`, and worth deciding together with it.

Also unmeasured rather than wrong: `_MAX_CLEANUP_ATTEMPTS = 3` counts recorded
failures across passes, and a later success supersedes an abandonment, so a
transient failure must recur across three separate delete requests to abandon.
That is a defensible margin but a reasoned rather than measured one, and once a
saga finalizes there is no later pass to restore the item.

#### `stale-index-lock-silently-blocks-every-writer` (medium, process)

A crashed git call left a zero-byte `.git/index.lock` with no live git process
behind it. It blocked every writer in the shared tree for at least eleven
minutes. Two lanes had staged sets ready and simply stalled; neither surfaced
the failure, and it was found only because the orchestrator tried to commit.
The multi-writer arrangement has no detection for this, and a blocked lane is
indistinguishable from a slow one. Pathspec commits (`git commit -- <paths>`)
were adopted as the safe primitive afterwards, since they commit named paths
without capturing another lane's staged entries - the direct repair for the
earlier `shared-index-cross-staging` incident.

#### `dispatched-agents-idle-without-reporting` (medium, methodology)

Now chronic rather than incidental. This audit already records three review
agents and then four more going idle without delivering findings, forcing two
review sections to be done first-hand. This pass added three more: two fleet
members and a lane lead, the last of which went idle holding its entire fleet's
verified work uncommitted, and one lane that idled instantly on every resume so
its report had to be reconstructed from the code. The pattern's shape is
consistent: an agent backgrounds an asynchronous wait, stops, and its findings
are never recorded. Foreground verification and reading output files directly
avoid it. The cost is not lost code - it is lost evidence, which is the part
that cannot be recovered by looking at the tree.

#### `audit-consumer-inventory-under-reports` (medium, methodology)

The `schemas-enums-symbol-shim` entry named two consumers of the shim path.
There were six, plus the package facade. Acting on the audit's inventory alone
would have left four files importing a deleted symbol. Generalises the
granularity lesson already recorded in
`shim-sweep-analysed-at-the-wrong-granularity`: an audit entry's evidence list
is a starting point to be re-derived, not a work order to be executed.

#### `orphan-cascade-misattribution` (correction, closed)

A lane reported 198 live Python processes as this repository's boot-harness
orphan cascade and proposed a start-time-bounded sweep. The attribution was
wrong and the sweep would have killed two other projects' live runs. Measured
directly: all 16 processes belonging to this worktree were live-parented, and no
gateway orphan was observable at all. The real leak was 120 orphaned
`multiprocessing.spawn` workers holding 2.3GB, in four cohorts, every one with a
dead parent. Attribution by interpreter path is unsound here - a uv venv's
`python.exe` is a launcher stub over the managed base interpreter, so children
spawned from any project venv surface under the same path. Under investigation
separately as a production defect. Recorded because a confident wrong
attribution nearly caused a destructive action, and because the correction had
to be pushed back to the lane before it reached a report.

### Wave W02 formal review (2026-07-30)

Verdict: REVISE. The closed W02 Steps are safe, bounded, and concurrency-clean - no
crash path, no leaked resource, no deadlock in the reviewed surfaces, and the streaming
quota and allowlist proofs execute for real against authenticated clients. Two closed
Steps nevertheless do not deliver what their rows charter, which is plan drift rather
than style, and each defect is a localized repair inside otherwise sound code. Reviewed
at `5699c3f2`, every claim re-derived from source rather than from this document's
description of it. Live during the pass: the streaming surfaces plus the progress and
stream-limit gates, 125 passed; the OpenAPI artifact gate, 6 passed; the prerequisite
rule, 5 passed.

Status lines reconciled. Five finding entries above still read `open` while the
2026-07-25 fleet pass already recorded their closure with evidence, so the entries
contradicted the narrative in the same document and inflated the open count. Each was
re-derived independently at HEAD before being flipped, because a wrongly-retired
finding does more damage than a stale-open one: the worker-health probe split-brain,
the Codex config-home escape, the service-and-provider prerequisite disagreement, the
silent ownership-check degradation, and the stale published OpenAPI artifact. The
boot-harness orphan reap needed no change, having already been carried as fixed in both
homes.

One evidence correction: the OpenAPI closure is commonly attributed to `d07cf251`, but
that commit added only the drift gate. The artifact itself was regenerated earlier, in
`c0d7d394`. Cite `c0d7d394` for the artifact and `d07cf251` for the gate.

#### `run-replay-unbound-on-integrity-race` (high, closed by `66c5d39b`)

The sequential replay path is correct and complete: it compares the frozen profile,
then the persisted request digest over the whole body, raising a conflict on either
mismatch. The integrity-error branch - two simultaneous requests carrying the same run
id, which the branch's own comment describes - rolls back, re-reads the winner, and
returns it as a successful replay after no comparison whatsoever
(`api/routes/gateway.py:406-422`). A racer whose body differs in prompt, preset,
feature tag, feedback batch, or profile receives a 200 and the winner's run id, is told
its run started, and has its distinct intention silently discarded. The asymmetry is
structural: the staged commit verb serializes per run id through a single-flight and
compares under constant time, while the direct start stage has no single-flight at all,
so the one race window it must defend is the one it leaves open. The owning Step row
requires the conflict on both the normal and the integrity-error path. No test
exercises the branch; the digest conflict is covered only sequentially.

#### `positive-progress-dto-has-no-producer` (high, open)

The versioned positive progress model carries the whole guarantee its Step was written
for - forbidden extras, bounded counters, a single bounded token delta, and no field
capable of holding a prompt, document body, artifact body, or diff - and its docstring
states that a producer smuggling a forbidden field fails validation rather than crossing
the boundary. Nothing on the wire validates through it (`api/schemas/gateway.py:452`).
Its only references outside the schema module are in its own test, so the test proves
the model and the model governs nothing. Actual enforcement is a dict projection at
`streaming/sse_frames.py:195` - a second encoding of the same policy, with the tested
one inert and free to drift.

#### `progress-allowlist-defaults-to-pass-through` (high, open)

The allowlist looks a frame's type up in a five-family map and, on a miss, returns the
payload unchanged on the documented premise that every other frame type is already
body-free by construction (`streaming/sse_frames.py:131-132`). That premise does not
hold for families the same package defines: the permission-request description, the
plan-update entries, the error message, and the agent-status detail are free-text or
structured-content fields on types absent from the map, and they reach the public
versioned stream verbatim. Today's in-process producers fill those fields with
constructed summaries, so the exposure is latent rather than a live leak - but the relay
seam accepts worker-serialized payloads whose type it does not constrain, and any new
content-bearing family is admitted by default. The projection is a positive allowlist
over FIELDS and a default-allow policy over TYPES, which inverts the direction of
safety the Step chose.

#### `allowlist-layers-are-not-independent` (medium, open)

Both enforcement layers delegate to one implementation
(`streaming/transformer.py:68`). That genuinely defends against a route bypassing the
relay seam, and the comment asserting as much is accurate. But two further comments
claim the exclusion holds even if a projection is bypassed OR BUGGY, and the buggy half
is false: a gap in the field map is present identically in both layers. Same class as
the split-brain finding's aggravating detail that this campaign already fixed - a module
asserting an invariant it does not hold.

#### `delete-abandoned-cleanup-not-surfaced` (medium, open)

Supersedes `cleanup-abandonment-not-surfaced-to-the-caller` above with the confirmed
consequence and the correct repair. The delete route branches on incomplete cleanup
alone and never reads the abandoned flag (`api/routes/threads.py:223`), though the flag
is real and deliberately computed, meaning the delete DID finalize while at least one
cleanup item was judged permanently unremovable so external state was left behind. No
production consumer reads it. The endpoint therefore returns the same bare no-content
response for a fully clean deletion and for one that stranded artifact files or
checkpoint data on disk; a client cannot distinguish them by status, body, or header, so
no remediation can be surfaced and any client-side reconciliation reads the thread as
cleanly gone. Evidence is not lost - it is logged server-side per unremovable item -
which is why this stays medium: recoverable by log inspection, invisible through the
API. The repair is NOT a retryable error. The saga is settled and its rows are gone, so
signalling retryable would invite a client to re-drive a completed deletion. Surface it
as a success carrying the flag, against the existing bare success for the clean case.

#### `sse-subscriber-slot-leak-latent` (low, closed by `2b1b3f84`)

Registration succeeds inside one try block while the subscribe call runs unguarded, and
the try/finally that removes the subscriber opens only afterwards
(`api/routes/thread_stream.py:89`). A raise from subscribe would leave the client
registered forever, consuming one global stream slot for the life of the process.
Unreachable today - the call subscribes exactly one thread id, which cannot exceed a
positive per-client limit - so this is latent, worth one try-boundary move rather than
urgency.

### Blocked-proof reconciliation (2026-07-30)

Two independent live proofs failed today for the same root cause, and both are recorded
as owed rather than routed around. The cross-repository lost-acknowledgement proof in
the desktop campaign skipped for want of an engine binary this checkout cannot supply.
The tool-cores Codex floor proof got further and still died before any agent turn: the
only engine binary on this box predates the token-mint route, so actor-token minting
answered method-not-allowed and the run ended at the mint. Codex was never contacted,
which means the metered-quota question that has held that Step since 2026-07-23 remains
unanswered rather than resolved. Rebuilding the engine is another repository's scope,
and that tree carries a non-compiling refactor, so neither proof is expressible here
today. A stale engine binary is now a shared blocker across two campaigns, not an
incident in one.

### Hardening pass (2026-07-30)

Two of the six findings queued by the Wave W02 review are closed with evidence, and
both carry a proof discipline worth recording rather than just a commit id.

`run-replay-unbound-on-integrity-race` closed by `66c5d39b`. The repair did not copy the
sequential path's profile and digest checks into the integrity branch; it lifted them
into one helper both paths call, so there is no second encoding to drift - the failure
mode this campaign exists to remove. The digest comparison is now constant-time on both
paths. The branch is proven to execute rather than assumed: the race is forced with a
real store-level barrier, and the test asserts on a log line that exists only in that
branch, so it cannot pass on the sequential path. A mutation check reverting the fix
reproduces the defect verbatim - the racer carrying a different prompt receives success
and the winner's run id. One knock-on is recorded deliberately: the loser sets its
persisted flag BEFORE the identity check, because releasing on the way out would discard
the winner's drain-gate admission and let a drain quiesce with a live run.

`sse-subscriber-slot-leak-latent` closed by `2b1b3f84`, with an honest limit stated
rather than a manufactured proof. No reachable input, configuration, or schedule makes
the subscribe call raise today - the per-client cap cannot be satisfied by a single
thread id, and the two statements are adjacent with no await between them - so no test
can distinguish the pre-fix code from the post-fix code. Rather than stub the aggregator
to invent a failing path, which would assert only that the stub raises, the author tested
the enclosing invariant: the registered window is fully inside the cleanup guard, and the
released slot is genuinely retakeable by a subsequent client, mutation-checked by
neutering the release. Recorded because the reasoning is the deliverable here, not the
diff.

#### `preset-disclosure-guard-went-stale` (medium, closed by `a809f176`)

Self-inflicted and caught only by a neighbouring lane. Adding two single-provider profile
lanes in `e228b209` left the gateway's preset-disclosure assertion enumerating the old
set, so that test was red on the mainline from the moment the lanes landed - which means
the disclosure surface was unguarded for the window, the guard having become the thing
that was broken. The authoring lane's gate was scoped to the directory it edited and
passed honestly at 144 tests; the assertion lives in the interface suite. The repair
keeps the expectation an explicit hand-written literal rather than deriving it from the
preset loader or the endpoint's own response, which would have converted a real guard
into a tautology, and adds a disclosure assertion that the new lanes resolve all four
worker roles to the intended provider through the profile source. A tree-wide sweep
confirmed no second stale enumeration. The transferable lesson is scope-shaped: a preset
change reaches every surface that discloses presets, so the gate must follow the
disclosure surfaces rather than the edited directory.

### Hardening review (2026-07-30)

Both hardening commits PASS. The reviewer reproduced the original defect AND the
drain-gate hazard by mutation against a throwaway source copy rather than reasoning about
them, ran the race test nine times for nine passes, and independently re-derived the
unreachability argument behind the slot-leak fix's honest limitation. Test integrity is
clean in both: no mocks, stubs, fakes, monkeypatching, skips, or expected-failure markers,
and no tautological assertion - each primary assertion was shown to fail against the
pre-fix shape.

Verifying one of those claims surfaced a serious pre-existing defect that neither author
caused.

#### `drain-gate-no-terminal-release` (high, open)

The drain gate is never released on a run's terminal outcome. The comment at
`api/routes/gateway.py:335-337` states that an admitted run is released on a terminal
outcome by the execution-state settlement path, and no such call exists anywhere in the
tree: the only two releases are the pre-durability `finally` at `:434` and the cancel verb
at `:1300`, and nothing in production calls the gate's quiescence or drain entry points at
all. Every run that starts and completes normally therefore stays in the active set for the
life of the process, so a drain can never quiesce. Found while proving that the insert-race
loser must not release the winner's admission - which means the property that repair
correctly protects is currently protecting a gate that leaks on the happy path. Another
module asserting an invariant it does not hold.

#### `commit-path-second-profile-encoding` (medium, open)

The insert-race repair genuinely collapsed the start path's replay identity onto one
helper, but the claim is slightly wider than the code: the commit stage keeps its own
profile comparison at `api/routes/gateway.py:575-583`, whose conflict detail string is
byte-identical to the helper's. One half of run-start replay identity is still encoded
twice and free to drift.

#### `commit-loser-strands-reservation` (medium, open)

A commit-stage insert-race loser's new conflict lands in the else arm of the durability
classifier (`api/routes/gateway.py:694-700`) and retains its reservation as committing for
the full TTL (`control/admission.py:59,380-389`). Retaining is defensible as written -
the classifier cannot distinguish someone else's durable row from an own row with an
unexpected binding, and the alternative risks duplicate admission authority - but this
loser demonstrably never wrote a run and never can under that id, so the retention strands
real capacity. Bounded, not permanent, and strictly better than the pre-fix behaviour that
returned the winner's run under the loser's lease. Reachable only across two gateway
processes on one store, since commits are serialized per run id in-process.

#### `replay-digest-fingerprints-credentials` (high, open)

The plain-start replay fingerprint still folds credential values in
(`api/run_admission.py:71,76`), which the governing decision now explicitly classifies out.
Not introduced by the race repair - the sequential path already compared the whole digest -
but that repair extended the comparison to a second caller, so a racing loser presenting a
rotated-but-equivalent bundle is now refused where it previously replayed. The persisted
digest also carries no marker recording which rule computed it, and raw tokens are never
stored so an old digest cannot be recomputed. Implementation is in flight against the
landed clause.

#### Lower-severity queue from the same review

`digest-absent-for-server-minted-ids` (low, open) - a run created without a client-supplied
run id persists no digest, so a later same-id request silently degrades to the profile-only
comparison, while the docstring attributes an absent digest solely to predating digest
persistence. `commit-loser-returns-foreign-lease` (low, open, pre-existing) - an
identical-body commit-stage loser answers with its own lease id bound to the winner's run.
`race-test-fixed-sleep-window` (low, open) - the race test's barrier rests on a fixed sleep
inside the store's busy timeout; an overrun fails loudly rather than passing silently, but
it is the test's least robust element. `gateway-module-over-ceiling` (low, open) - the
gateway route module grew past 1600 lines, further beyond the project ceiling already
recorded under the module-size finding above.

### Consumer consumption inventory (2026-07-30)

The consuming product was read directly rather than assumed, to settle two decisions that
were being held on guesswork. It settled both and surfaced a defect nobody was looking
for.

Topology first, because it governs everything else: the consumer's frontend never calls
the versioned progress stream directly. It transits a whitelisted pass-through in the
engine, which opens the upstream stream on loopback and pumps frames VERBATIM, adding only
a sequence field. The engine reads just the type and event-name fields, plus the terminal
event NAME to latch completion. There is exactly one consumer chain, and it sees this
repository's frames essentially unfiltered.

The aggregate progress schema has NO mirror. Searches for the type names, for every field
name in the shape, and for any token-accounting concept at all return nothing across the
consumer tree - no type, no adapter, no fixture, no UI element. The one overlapping field
name is read from the run-status envelope, a different response object. Its withdrawal is
therefore evidence-backed rather than argued, and the paired-amendment requirement that
guarded the token-delta field is satisfied rather than waived.

The closed catalog gained three MUST-KEEP entries it would otherwise have broken, each
surviving today only because its frame type is unmapped and passes through untouched: the
agent status state field, which drives the live activity indicator; the team roster's
per-agent identifier and state, which the roster liveness read consumes and which the
consumer's own tests lock as a deliberate contract; and the error message, without which
the fault banner degrades to a generic literal and the operator loses the real reason.
Two entries were confirmed droppable: no consumer reads plan-entry content, and none reads
the permission-request fields. The frame type NAMES are load-bearing in a way the catalog
work had to be warned about - the consumer classifies by substring on the event name, so
renaming or projecting a type away would silently downgrade the degrade, heartbeat, and
dropped frames into an inert lane, and for the terminal frame would leave the consumer's
upstream socket and pump thread alive indefinitely.

#### `tool-content-stripped-from-a-rendering-consumer` (high, open, cross-repository)

The consumer reads the tool-call content list and RENDERS it as the tool argument and
result panes, branching on frame status to label one as arguments and the other as result,
and handling three content variants. This repository's allowlist already permits only the
identifier, title, kind, status, and locations on those frames - content is excluded as a
forbidden diff or raw-output body under the accepted decision. Unless some path bypasses
the encode boundary, those panes are ALREADY permanently empty on the live edge, and have
been since the allowlist landed. Neither side is individually wrong: the exclusion is the
accepted decision faithfully implemented, and the rendering is a reasonable consumer of a
field the schema still declares. The contradiction is that the schema advertises a field
the edge always removes.

Established by reading both repositories, with no live run, so the "already empty" claim is
source-derived and unconfirmed against a running system - it should be confirmed by
observation before any repair is designed. The repair is a paired decision, not a catalog
edit: either the accepted decision is amended to admit bounded argument and result text
with explicit caps, or the consumer stops rendering panes that structurally cannot fill.
Deliberately NOT fixed in passing by the catalog work, which would have meant re-admitting
a forbidden field without a decision.

### Hardening lane closures and new queue (2026-07-30, second pass)

`replay-digest-fingerprints-credentials` closed by `36713034`, reviewed PASS WITH FINDINGS.
The review found a defect the author's own mutation probe could not see, and it is the most
instructive result of the pass: the test guarding the fail-closed behaviour on an
unrecognised rule marker DID NOT DISCRIMINATE. It asserted that an unknown marker carrying
a current-rule digest does not match - but a fail-OPEN implementation returns the same
answer for that input, because a credential-free digest never equals a credential-sensitive
one. Proven by mutation: swapping the refusal for a silent fallback left the file fully
green while a run written by a newer process would replay on a guess. Closed by `f9612c17`,
which asserts against a digest the fallback rule would actually match and demonstrates the
tightened test failing against that mutation. A guard that cannot be shown failing against
the thing it guards is not a guard.

`delete-abandoned-cleanup-not-surfaced` implemented by `1b47d397`; review in flight.

#### `replay-legacy-rule-not-frozen` (low, open)

The frozen historical fingerprint rule reads its exclusions from the live always-excluded
table rather than from a frozen copy. That rule describes bytes already on disk and is
therefore immutable, so a legitimate future addition to that table - precisely the case the
surrounding comment anticipates - would silently redefine it and refuse every pre-change
replay. Mitigated in the right direction: the test restates the old rule from its
specification, so such a change fails loudly rather than green-washing. The residual is
that the invariant is held by a test rather than structurally.

#### `replay-exclusion-wider-than-adr-wording` (low, open)

The implementation drops the whole credential field, so the SET OF ROLES presented also
leaves the fingerprint, where the decision record names credential VALUES. Judged within
intent - a replay returns the original run and never consults the presented bundle, and
coverage is routed to admission at first start - but a reader reconciling code against the
record should be told the exclusion is one notch wider than the clause's literal words.

#### `engine-bearer-guard-partial` (low, open)

The guard fails loudly if a refactor lifts the engine bearer OUT of the credential bundle,
but not if one ADDS a top-level bearer beside the nested one - a variant that would fold a
credential value back into the fingerprint with every test still green.

#### `replay-constant-time-claim-overstated` (low, open)

A docstring claims a constant-time comparison, but the marker parse and the
unrecognised-marker short-circuit both return before it. Another instance of a module
asserting a property it does not hold.

#### `cancel-release-appears-unreachable` (low, open)

Found while implementing the drain-gate release. The cancel verb's terminal-status release
looks like dead code rather than a live second release site: the cancel service's success
path always returns a cancelling status, never a terminal one, and the already-terminal
case is refused with a failure type that raises before the release line is reached.
Confirmed empirically - cancelling an already-completed run answers with a dispatch failure
rather than success. The implementer left it untouched as instructed and rewrote its test
to assert the reachable truth instead of a path that cannot execute. Either the case the
surrounding comment describes no longer exists, or the failure guard should not pre-empt
the release for that one failure kind.

#### `identity-keys-unbounded-at-the-edge` (low, closed - bounded by admission)

Raised by the catalog work and resolved on inspection rather than left open. With every
catalogued text field now capped, the frame byte cap became reachable only through the nine
always-safe identity keys, which carry no caps of their own - so the drop-sentinel test had
to change vector to an oversized message identifier. Checked at the source: the
caller-supplied run identifier, which is the only one of those keys a client controls, is
bounded to 128 characters at admission. The remaining keys are server-minted or bounded by
the role grammar. The byte cap is therefore a near-unreachable backstop rather than an
exposed hole, and no edge-side truncation is warranted - truncating an identifier would be
actively worse, since the consumer keys stream grouping off the message identifier and a
truncated one could collide.

### Delete-contract review and consumer repairs (2026-07-30)

`delete-abandoned-cleanup-not-surfaced` implemented by `1b47d397`, reviewed PASS WITH
FINDINGS. The review confirmed the five outcomes are exclusively discriminated at the
service rather than merely ordered at the route - an abandoned finalize that also sets an
incomplete flag is unconstructible, being the true and false arms of one branch - and that
the new kinds tuple is provably equivalent to the old boolean, so no outcome changed
silently.

It then looked one layer further out than its brief required and found the repository's own
tool consumer did not honour the contract at all. Both are now repaired by `28466b0d`,
each mutation-proven by reverting the fix and reproducing the exact reported failure.

#### `mcp-delete-tool-crashes-on-clean-204` (high, closed by `28466b0d`)

Pre-existing and unrelated to the contract change. The shared request helper parsed a
response body unconditionally, so the delete tool raised an uncaught decode error on the
no-content success path - the most common outcome crashed the tool. The repair belongs at
the shared seam for a mechanical reason: the parse raises inside the helper before it
returns, so the calling tool has nothing to catch it with short of abandoning the helper.
Gated on the response carrying no bytes rather than on a status-code list, which is the
actual precondition and needs no keeping in sync. A survey of every endpoint reached
through that helper confirmed the delete verb is today the only body-less success.

#### `abandonment-erased-by-the-mcp-consumer` (medium, closed by `28466b0d`)

The tool flattened every success to a clean-deletion sentence, so the new stranded-state
outcome reported as clean - re-creating one layer up exactly the misreport the contract
exists to end. Repairing the edge while its own consumer erased the distinction would have
been a hollow win. The tool now names the stranded item KINDS, never a locator, and its
description states the outcome too, since that description is what the calling model reads.

#### `bare-204-on-the-already-final-race` (medium, open)

A concurrent replay that loses the claim race reports a clean deletion for a finalize that
abandoned items, while both route and schema document that code as every store cleaned.
The disposition turns on whether the abandoned kinds are still readable at that point: if
they are, this is a defect and the repair is to read them; if the saga rows are already
gone, no code can recover them and the bare success is the best available truth - in which
case it is a documented limit of the contract rather than a defect. Held open pending that
determination rather than guessed at.

#### `mcp-503-reads-as-a-server-fault` (medium, open - under design ruling)

The resumable-incomplete outcome surfaces through a generic branch as a server error, which
tells the calling model the server is broken, so it will not retry - defeating the
resumability the saga was built to provide. That the current behaviour is wrong is not in
dispute. WHAT the repair should be is: report the retryable condition and let the calling
model decide, or have the tool retry automatically with its retry state declared. The
second is under an architecture ruling, because the arguments cut both ways - each call
drives real cleanup passes rather than a cheap idempotent poll, and the saga already holds
an internal attempt ceiling that a tool-side loop could consume, silently converting a
resumable outcome into an abandoned one without the caller seeing the intermediate state;
against which automatic retry with backoff on a degraded service is genuinely standard
practice, and this status code exists to carry that signal.

#### `detached-store-premise-unasserted` (low, open)

The abandonment tests infer the checkpoint store's failure from the refusal-refusal-success
progression and never assert the store actually raises, so the premise is proven only
indirectly.

#### `delete-response-absent-from-the-schema-facade` (low, open)

The new response model is exported from its module but not re-exported by the schema
facade, joining a pre-existing gap it shares with two sibling response models.

#### `sse-live-tests-are-load-sensitive` (low, open)

Surfaced by a lane that refused to accept a flaky result as noise. Three live stream tests
failed once during a full gate run, and two deselect experiments APPEARED to implicate the
lane's own new tests. The decisive evidence went the other way: the identical command,
unchanged, then passed twice in a row, and the failing run was also the slowest by a third
on a box another session was loading. Those tests carry fixed five-second frame deadlines,
so they are load-sensitive; the shorter deselect runs passed by luck rather than by
removing a cause. Either the deadline should be generous or the wait should be
signal-driven. Recorded because a lane correctly declining to blame its own change is the
same discipline as declining to claim a green.

### Final adjudication and closure (2026-07-31)

Three implementations were adjudicated together after their individual reviews were
interrupted. All three PASS, one confirming an earlier pass-with-findings.

The drain-gate release PASSES. The liveness-not-bookkeeping argument holds under scrutiny:
the release sits after the terminal-payload validation, so it fires only for validated
terminal events, and a failed status write is bookkeeping - withholding release there would
strand exactly the runs a drain must count. The fourth release site the implementer found
is real; without it the websocket follow-up path leaks an admission, because its failure
broadcast reaches clients without ever passing the relay. The plain set is confirmed
correct over a reference count, which would underflow on the designed
terminal-event-plus-cancel double fire.

The progress catalog PASSES, verified by EXECUTING the projection rather than reading it.
Every consumer-critical field survives, nested list items are rebuilt with unknown keys
dropped, no frame type name changed, the event-name-only terminal emitters still resolve
through the fallback, free-form metadata is stripped on every shape tried, and a typeless
payload projects to identity keys. An emitter census confirmed the catalog covers what the
tree emits, with one documented exception below.

The delete outcomes PASS with the earlier findings confirmed rather than overturned.

#### `bare-204-on-the-already-final-race` (medium, closed - documented limit)

Adjudicated NOT a defect. At the moment the losing caller returns, the information is
genuinely unrecoverable: the winning pass's finalize removes the saga row - the only
durable carrier of the manifest and ledger - in the same committed transaction as the
thread row. The abandoned kinds then exist nowhere but the winner's in-memory outcome and
the server log, and there is no tombstone table. No read can repair the answer. Reporting
abandonment on every concurrent replay would require a durable record outliving the saga,
which this design deliberately does not keep. The window is narrow and no product driver
issues concurrent duplicate deletes; a sequential retry after finalize answers not-found
rather than the bare success. Recorded in the decision record rather than papered over,
because a caller CAN in principle observe it.

#### `gate-acquisition-asymmetry` (low, open)

The follow-up release paths disagree in rationale: one get-or-creates the gate while the
other deliberately reads only, with a comment arguing that seating a gate is wrong.
Harmless today, since discarding from a freshly seated gate is a no-op, but two sites
asserting contradictory reasons for the same operation is the drift this campaign removes.

#### `graph-registered-absent-without-a-note` (low, open)

One emitted frame type is not in the closed catalog and therefore degrades to identity
keys. That loss is intended-equivalent - the aggregator consumes it server-side before
projection and its content resurfaces through catalogued fields, and the consumption
inventory shows no consumer reads it - so there is no product break. But the catalog's own
comment claims closure over every emitted type, so the absence should be documented as
deliberate rather than left looking like an oversight. Another instance of a module
asserting slightly more than it holds.

#### `delete-result-abandoned-property-test-only` (low, open)

The derived boolean retained for compatibility now has no production reader - the route
branches on the kinds tuple, and only a test asserts the property. Either use it or drop
it.

### Ranked closures (2026-07-31)

Three findings closed by `9d1fd49a`, taken in the order adjudication ranked them.

`commit-path-second-profile-encoding` (medium) - CLOSED. The commit stage carried its own
model-profile comparison whose conflict message was byte-identical to the shared replay
helper's, so one half of run-start replay identity was encoded twice on a refusal surface.
Both sites now call one refusal. Only the COMPARISON is shared: the two paths deliberately
fingerprint the rest of the request under different rules, and unifying those would have
been the wrong repair - the instruction was explicitly to stop rather than force it if the
two could not be separated.

`replay-legacy-rule-not-frozen` (low) - CLOSED, and it mattered more than its severity
suggested because it was an conformance gap against a clause landed the same day. Each
replay rule now states its complete exclusion set as a frozen literal instead of composing
one from the shared set that happens to be current. A rule describes bytes already on
disk; composing it meant a later legitimate addition would silently redefine an older rule
and spuriously refuse byte-identical replays of runs stored under it - digests that cannot
be recomputed, since raw credentials are deliberately never persisted. Changing what is
excluded now requires minting a NEW rule rather than editing an existing one. The
verification is the existing test that recomputes the old fingerprint from its
specification rather than from production tables: it still passes, which is what proves
the frozen sets are byte-identical to what they replaced rather than merely plausible.

`delete-response-absent-from-the-schema-facade` (low) - CLOSED, together with the two
sibling response models sharing the same pre-existing gap.

LEFT RECORDED by decision rather than oversight: the commit-stage loser that retains its
reservation for the full expiry, twice adjudicated defensible because the durability
classifier cannot distinguish another party's durable row from an own row with an
unexpected binding, and the alternative risks duplicate admission authority - recording IS
the disposition. Likewise the unreachable cancel release, the partial engine-bearer guard,
the overstated constant-time claim, the indirectly-proven detached-store premise, the
load-sensitive live stream tests, the absent digest for server-minted identifiers, and the
over-ceiling route module, whose repair is refactor-sized and should not be chased for its
own sake.

#### `mcp-503-reads-as-a-server-fault` (medium, closed)

The tool surfaced the resumable-incomplete outcome through a generic branch as a server
error, telling the calling model the service was broken - so it would not retry, defeating
the resumability the saga exists to provide. The repair reports the condition explicitly:
in progress, resumable, not a fault, repeating the same call resumes the same deletion and
makes progress, and persistent incompleteness is eventually reported as abandoned. The
tool's own description carries it too, since that description is what the calling model
reads before deciding. Mutation-checked: disabling the branch fails the new assertion with
the generic fault text.

The shape was settled by an architecture ruling after the owner challenged an earlier
call. The proposition tested was that automatic retry on a degrading service is the
industry norm provided error conditions and retry state are declared loudly. That was
ACCEPTED as a norm and bounded out of this case on evidence: each attempt drives real
cleanup passes rather than a cheap idempotent poll, and the saga's own attempt ceiling
assumes retries arrive as separate, widely spaced requests - so a client looping at
seconds-scale would exhaust that ceiling against an unchanged cause and finalize over
stranded state, converting the resumable outcome into the abandoned one invisibly inside a
blocking call. One sub-case means another pass merely holds a minutes-long claim, making a
fast loop pure spin. The declare-loudly half of the proposition was adopted in full and is
the entire fix. The boundary and what would move it are recorded in the decision record.

Provenance note, recorded because the same hazard was recorded against this session
earlier: this repair was authored here but landed inside a concurrent session's commit,
which swept the working-tree change in. Nothing was lost, and the mirror-image of the
earlier incident is worth keeping visible - on a shared tree, uncommitted work belongs to
whoever commits next, in either direction.

### Closing verification (2026-07-31)

Run at the end of the hardening pass, after the protocol package's dependency migration
landed and the type baseline moved for the third time.

Type gate: whole-tree, CLEAN - zero diagnostics. This is worth recording precisely because
the number moved three times in one working session, from seventeen to twelve to zero, as
an unrelated lane's dependency work resolved the imports that made up the whole of it.
Every lane was told to measure against a figure that was already stale by the time it
checked, which is why the instruction became report-grouped-by-file rather than report-a
total: a bare count could not distinguish someone else's environment moving from a lane
adding a diagnostic of its own.

Lint and formatting: clean across every file touched.

Tests: the whole package reports 2718 passed with 4 failures, ALL of them in the
real-process desktop suite. Every one of the four passes in isolation - the admission file
seven of seven, and the full desktop package forty-three of forty-three with no failures
and no skips. The mechanism is visible in the timings: individual tests there take fifty
seconds apiece when they own the machine, and the combined run took twenty-nine minutes
while a concurrent session drove its own real gateways and workers through the same tree.
That is the load-sensitivity finding already queued, confirmed rather than newly
discovered, and it is also this document's own recorded working constraint - real-process
suites are not safe to overlap, with or without an edit underneath them.

Scoped suites, each run at least twice: interface plus control 595, interface plus
streaming 529, interface plus control plus worker 677, protocol package 98.

The honest reading is therefore: green on every gate that can be measured without
contention, with four known contention artifacts named rather than rounded away, and the
four proven green the moment they are given the machine to themselves. A whole-package run
on a shared box is not the authority here; the isolated runs are.

### Truthfulness tranche (2026-07-31)

Six findings closed by `91967894`, taken together because they are one family: code
asserting slightly more than it holds. That pattern recurred four separate times across
this campaign's reviews and once more in a test, which is reason enough to treat it as a
class rather than as isolated wording slips.

`replay-constant-time-claim-overstated` - CLOSED. The docstring promised a constant-time
comparison while the marker parse and the unrecognised-marker refusal both return before
any digest is compared. It now states which half is constant-time AND why the other need
not be: the marker is a public, non-secret label naming which rule computed a stored value,
carrying nothing an attacker could learn by timing. Stating the guarantee at its true
strength is worth more than stating it at its most impressive.

`digest-absent-for-server-minted-ids` - CLOSED as documentation, deliberately not as
behaviour. The comment blamed only pre-existing runs; the second cause is that a digest is
stored solely for a caller-supplied id, so a client can read a server-minted id off a
response, present it later as its own, and be compared on the frozen profile alone.
Persisting the digest anyway would NOT fix it - the run id is itself a digested field, so
the original request that carried none could never match a later one that does, and every
such replay would be refused instead. The narrower comparison is the deliberate trade, and
the code now says so rather than leaving the next reader to rediscover the trap.

`graph-registered-absent-without-a-note` - CLOSED. The catalog claimed closure over every
emitted type while one frame type travels the relay uncatalogued. Its loss is
intended-equivalent - consumed server-side before projection, resurfacing through
catalogued fields, read by no consumer - so the repair is the record, not an entry. The
comment now names it as a judgement and gives the condition that would reverse it.

`gate-acquisition-asymmetry` - CLOSED. The two follow-up release sites asserted
contradictory rationales for one operation, one seating the gate and one arguing that
seating is wrong. Both now read without seating, which was the correct rationale: a gate
that was never created has admitted nothing, so there is nothing to release from it.

`engine-bearer-guard-partial` - CLOSED from the schema side. The existing guard catches a
credential moving OUT of the bundle but not a second one added BESIDE it - the direction
that would fold a credential value back into the fingerprint with every other assertion
still green. Rather than guess at future field names, the whole top-level field set is now
pinned, so ANY added field fails and must be answered for: describing the work means
joining the fingerprint, identifying or authorizing the request means joining an exclusion
set, and the latter means minting a new rule rather than editing an old one.

`detached-store-premise-unasserted` - CLOSED. The abandonment tests inferred their premise
from the refusal sequence they observed. The helper now asserts the detached store really
refuses, and that it refuses because the connection is gone rather than because the thread
is unknown. If a library change ever made that store usable again, those tests would have
quietly asserted the wrong outcome for a plausible-looking reason; they now fail at the
cause with a message saying so.

#### `delete-result-abandoned-property-test-only` (low, closed by `be72890f`)

The delete result kept a boolean derived from the abandoned-kinds tuple, retained for
compatibility while that widening landed. Nothing in production read it - the route
branches on the kinds - and the sole assertion against it was proving a property no caller
used. Dropped, with the control test retargeted onto the kinds themselves, which is what
the route actually consumes, so the test proves more rather than less. An unread derived
field is one more thing that must stay true for no benefit.

### Queue state after the hardening campaign (2026-07-31)

What remains open remains so by decision, and each entry carries its reason rather than
waiting for one:

`commit-loser-strands-reservation` - twice adjudicated defensible. The durability
classifier cannot distinguish another party's durable row from an own row with an
unexpected binding, and the alternative risks duplicate admission authority. Recording IS
the disposition; the retention is bounded by expiry and strictly better than the behaviour
it replaced.

`cancel-release-appears-unreachable` - dead code rather than a live defect. The cancel
service's success path never returns a terminal status and the already-terminal case raises
before the release line, confirmed empirically. Removing it is a separate judgement about
whether the case its comment describes should be made reachable again.

`sse-live-tests-are-load-sensitive` - a test-infrastructure improvement, not a product
defect. Their fixed frame deadlines should be generous or signal-driven; until then the
known mitigation is not to overlap real-process suites, which this document already records
as a working constraint.

`gateway-module-over-ceiling` - refactor-sized and should not be chased for its own sake.
The shared-refusal extraction took the free progress available without pretending to close
it.

`tool-content-stripped-from-a-rendering-consumer` - cross-repository, and a paired decision
rather than a code change on either side alone. Either the accepted contract is amended to
admit bounded tool argument and result text with explicit caps, or the consumer stops
rendering panes that structurally cannot fill. Source-derived and still unconfirmed against
a running system, which is the first thing any repair should establish.

`bare-204-on-the-already-final-race` - closed as a documented limit, since the information
is genuinely unrecoverable at that point rather than merely unread.

### Legacy surface teardown (2026-07-31)

The owner directed that no legacy or deprecated surface remain in either repository. The
transition product mount and its websocket are DELETED - 6,807 lines in the deletion
commit alone, plus the websocket module, its dispatcher, the connection manager, the
command and legacy response schemas, a diagnostics module, the websocket configuration
knobs, and cross-origin middleware.

The ordering was the whole discipline: every capability was PORTED to the versioned
surface before anything was removed, because deleting first would have destroyed working
function rather than deadweight. Six ports landed - a follow-up turn into an existing run,
the five-outcome deletion, archive, team status, the wide per-run read, and a history
reading of the run listing - followed by a seventh verb for answering a permission, which
four retirement Steps had been blocked behind. The versioned surface could pose that
question as an enumerated stream frame while only the transition surface could accept the
answer; retiring it first would have stranded every paused run.

The surface count moved from five verbs to a closed enumerated catalog, by explicit
amendment rather than drift. The whitelist test that asserts the surface does not grow
caught every addition, which is what it exists for, and each was declared deliberately
rather than loosened.

#### `mcp-start-tool-can-never-start-a-production-run` (high, closed by deletion)

Surfaced, not caused, by the teardown. The protocol server's start tool could not start
ANY production preset: every one is credential-gated, the consuming product's engine is the
sole minter of the per-role credentials, and this service holds no engine bearer and no
minting path. Obtaining one would require calling the engine from here, inverting the
certified edge direction.

It was invisible because the legacy route ACCEPTED the start and the run then died
mid-flight. Only repointing onto the versioned verb - which refuses an ineligible request
before creating durable state - made the failure honest and therefore visible. The tool's
entire reachable input domain was mock acceptance scaffolding, so it is deleted rather
than kept as something that always fails. Restoring the capability legitimately is work
for the consuming product's repository: its engine fronting an externally-initiated start
and minting at its own run-start. Deliberately not stubbed here. The remaining protocol
tools are NOT orphaned - credentials bind at run-start and live worker-side, so they need
only this service's own bearer against engine-started runs.

#### `stored-metadata-fails-its-own-model` (medium, open)

A run started without a workspace root persists metadata that the metadata model rejects
as incomplete, so the now-deleted metadata route answered a server error for exactly those
runs. The writer and the model disagree. The wide read reports unparseable metadata as
absent and logs it rather than failing the whole record for one field, but the underlying
disagreement is untouched.

#### `product-control-calls-endpoints-that-do-not-exist` (medium, open, cross-repository)

The consuming product's lifecycle control client calls readiness, drain, and lifecycle
operations that exist in no router here. Not legacy usage - an unimplemented contract - and
out of the teardown's scope, but a real dangling dependency. Its shutdown call was
separately found pointing at a path matching neither the old nor the new surface, and is
fixed.

#### Consumer inventory correction

The teardown brief assumed the consuming product needed migrating off the legacy surface.
It did not: it was ALREADY fully versioned, its frontend never contacts this service
directly, and the thread vocabulary appears nowhere in its production code. The agent said
so rather than manufacturing churn to satisfy the brief, which was the correct reading. Its
only real defect was the shutdown path above.

A related decision: seven newly-ported verbs were NOT added to that product's brokered
pass-through whitelist. Each entry is authority granted to a browser client, three of them
destructive or authorization-bearing, and adding them with zero callers would create
exactly the deadweight this directive removes.

#### Verification

Whole-tree lint and type gates clean. The full package passes 2,784 tests with no failures
over twenty minutes of real processes and stores, taken while no other writer was touching
the tree - which is what makes the real-process suites trustworthy here rather than
contended. The consuming product passes 376 native and 281 interface tests.
### 2026-09-19 dead-code measurement pass | low | three private constants removed; reachability leads queued

Type: maintenance. Status: three confirmed removals closed; broader scan open for triage. The repository's Vulture scan measured 525 findings over 794 offered Python modules (8 high-confidence heuristic hits). The entry-point reachability scan measured 8 unreachable modules, 52 unused top-level symbols, and 2 orphaned tests over 302 shipped modules. Manual reference checks confirmed `_STALE_MS` in `authoring/discovery.py` and `_JSON_OBJECT` in both `providers/acp_catalog.py` and `providers/codex_catalog.py` had no consumers. After removal, the unused-symbol count is 49. Ruff and ty pass on the touched files.

Follow-up queue: classify the remaining 49 symbols and 8 modules against installed entry points, dynamic registration, tests, and dev harness consumers before deleting any. In particular, `providers/lane_admission.py` exports `lane_admission_reason` and `unproven_lanes_in` with no current in-tree callers; public exports need compatibility review. The 2 catalog-selection orphaned tests need ownership review. Vulture's highest-confidence import hits are type-annotation imports and its two variable hits are protocol/framework parameters, so they are false positives for deletion. The supplied `Scripts/github-audit` tool measures GitHub security settings, workflows, and secrets rather than dead code. The root Node manifest is an ACP dependency host with no application JavaScript source or Knip enrollment; no Node dead-code denominator exists here.

Review result: PASS for the focused three-constant removal. Type: follow-up investigation; severity low; status open for the remaining reachability leads. No behavioral interface changed by this pass.
### 2026-09-19 test-only dead-code burndown review | medium | scan reaches zero after entry-point corrections

Result: PASS for the dead-code removal and signal correction; observed environment and contract test failures remain queued below. Type: implementation review. The entry-point reachability signal began at 8 unreachable modules, 49 unused symbols, and 2 orphaned tests (59 total) over 302 shipped modules. The `just audit-dead-code-burndown` command prints the integer and fails on scan error. The current signal is 0 after removals and corrected root modeling. Vulture's advisory count moved from 525 to 493; its eight high-confidence hits remain annotation imports and required callback/protocol parameters, not removal evidence. The root Node manifest is an ACP dependency host with no application JavaScript to run Knip against. The supplied `Scripts/github-audit` tool measures GitHub settings, workflows, and secrets, not dead code.

#### scanner-missed-public-entry-points | high | type: measurement correctness | closed

`database.admin` is a documented `python -m vaultspec_a2a.database.admin` CLI, referenced from `alembic.ini`; `lifecycle.engine_serve` is imported by `scripts/engine_serve.py`, which `procs.toml` launches. Both were initially reported unreachable. Their modules and behavior tests were preserved. `dev/audit/unreachable_code.py` now treats modules with a main guard and imports from configured Python scripts as runtime roots, with real-tree regression tests. Pytest hooks in the configured root plugin are also recognized as framework calls, while an ordinary unused helper in that plugin remains a finding.

#### test-support-placement | medium | type: packaging | resolved by user direction

Five shared helpers under `testing/` were imported by many live-behavior tests. Deleting them broke 54 type-check imports. The user chose moving them into the excluded test tree; their consumers were repointed and the live behavior tests remain. `acceptance/_harness.py` is moving beside its tests for the same reason. The test-only `artifacts` declaration package and its declaration-only tests were removed; two independent ACP ownership checks were retained under provider tests.

#### artifact-declaration-proposal-drift | medium | type: decision/code conflict | open

The `2026-07-21-ecosystem-artifact-lifecycle-adr` is **proposed**, not accepted. Its proposed requirement for declaration objects beside artifact creators conflicts with their removal under the user's test-only-code rule. Runtime artifact creation and cleanup paths remain. This proposed decision needs reconciliation before acceptance; the removed declarations cannot be cited as implemented evidence.

#### external-api-compatibility | low | type: public surface | open

Some deleted helpers were listed in `__all__` but had no production or development callers found by the scan. An external consumer could have imported them. No external consumer inventory is available in this pass; the change is a deliberate removal under the user's rule, and release review should treat it as an API change.

#### existing-verification-failures | medium | type: test/contract | open

A focused real-install provision test fails because the installed workspace lacks required `exec-step` and `exec-summary` templates, though those templates exist in this checkout. Admin/migration focused tests had one database `pause` check-constraint failure, and WAL tests had two write-authority rejection failures. A graph web-composition test reached an ACP `initialize` response with a missing or malformed `protocolVersion`; its 12 downstream cases failed. A provider live test requiring `vaultspec-rag` found no CUDA/MPS backend. These failures are recorded as observed, not attributed to this dead-code change without a baseline comparison. The focused tests that passed are reported in the execution summary when the integrated pass closes.
#### integrated-verification | low | type: validation | closed

The integrated pass reports 0 scanner findings. Ruff lint and format, ty, reachability, unused-symbol coverage, and 270 governed import-load probes pass. Focused test groups passed across the scanner, testing support, authoring, provider, service, control, API, desktop, and lifecycle scopes. Pytest collected 4,757 of 4,759 tests (two live proofs withheld by configured prerequisites); the collection recipe returned exit 4 despite listing the tree, so its harness exit behavior remains a medium open validation issue. The real-install, database authority, graph ACP, and GPU failures remain open as listed above. The review found no unqueued new issue from the merged cleanup.

### 2026-09-19 relative-import gate review | low | absolute package imports removed

Type: import discipline. Status: RESOLVED. The package-relative import gate
found 85 absolute self-imports, chiefly in test support modules. All were
converted to equivalent relative imports. Ruff, formatting, just check-all,
and pytest collection pass; selected database and test-support tests pass.
The conversion preserves imported symbols and leaves runtime modules unchanged.

### 2026-09-19 strict-type packaging review | medium | LangGraph namespace typing repaired

Type: dependency typing. Status: RESOLVED. Basedpyright reported 19 missing
type-stub diagnostics for langgraph.graph and langgraph.graph.message
despite the installed namespace root carrying py.typed. A local typing
overlay under typings/langgraph/graph declares the same public graph exports,
message reducer, and message-state shape as the locked runtime package.
just check-type-strict now reports zero diagnostics.

### 2026-09-19 shared normalizer export review | low | read seam export made explicit

Type: typing boundary. Status: RESOLVED. The workspace-identity parity test
consumes the exact normalizer object exposed by control/run_discovery_service.py.
An explicit re-export preserves that identity and removes the private-local-
import diagnostic. The targeted database test passes.

### 2026-09-19 strict structural gates | high | complexity and shape debt remains

Type: maintainability. Status: OPEN. The strict aggregate remains red after
typing and import cleanup. The 2026-09-19 health census counts 162 functions
over the cyclomatic limit, 13 modules over the length limit, 27 functions over
the statement limit, 119 callables over the parameter limit, and 9 functions
over the nesting limit. just check-strict also reports cognitive-complexity
and pylint design findings; Ruff reports 324 shape and complexity errors
and 35 nesting errors in the same strict run. Repository-tooling-hardening
plan W07.P13 and
W07.P14 own decomposition; W08 promotion remains blocked until each sentinel
has zero findings. No threshold, exclusion, or suppression was changed.

### 2026-09-19 strict export gate | medium | unconsumed public names remain

Type: API surface. Status: OPEN. just check-exports reports 111 unconsumed
published names across 1,220 names. Each export needs a consumer check before
removal; some may be intentional external API. The strict gate cannot graduate
while the count is nonzero. Follow-up belongs in the repository tooling
hardening queue before W08 closure.

### 2026-09-19 default-suite follow-up behavior | high | dispatch receipt does not settle applied action

Type: behavior. Status: OPEN. A non-service suite run after the import changes
reached api/tests/test_endpoints.py::TestSendMessage::test_followup_dispatch_marks_message_followup_as_applied;
it fails with last_applied_action == "ingest" after a follow-up receipt, where
the test expects message_followup_applied. This is a real state-transition
finding, independent of import spelling. Record it for control-action
investigation and real-behavior regression proof.

### 2026-09-19 accepted-dispatch recovery | high | unauthorized test dispatch leaves run status running

Type: acceptance contract and failure settlement. Status: OPEN. The full
non-service suite stops at
api/tests/test_acceptance_five_verb.py::test_multirole_run_status_recovery_and_zero_vault_writes.
Its direct DispatchRequest omits graph_definition, graph_action_receipt, and
model_assignment, which are now mandatory accepted execution authority. The
worker correctly rejects the missing definition, but the rejection path calls
emit_terminal_status(FAILED) without GraphFailureEvidence because
_failure_evidence returns None for a request without a receipt. The state
projector rejects that terminal, a second exception is logged, and run-status
still reports RUNNING with no checkpoint. The acceptance fixture must exercise
a real accepted dispatch; the receipt-less rejection path also needs an
authority-consistent terminal policy so it does not double-fault. Do not mint
a fake receipt or weaken the state-projector invariant.

### 2026-09-19 startup re-dispatch accepted authority | high | fixed in implementation

Type: production recovery contract. Review found that `redispatch_reconciling_threads` rebuilt an ingest request from thread metadata and omitted the accepted graph definition and receipt. A real production gateway restart stayed RECONCILING because worker admission rejected the request. The dispatch now restores the exact accepted input by durable action receipt ID, verifies its model assignment and workspace against the thread metadata, and binds the committed graph receipt before delivery. Missing or incompatible evidence is classified per thread so one bad row does not abort the sweep. The production restart proof and 12 adjacent re-dispatch cases pass. The accepted-dispatch fixture and terminal-evidence fixtures were also updated to exercise current authority; the separate receipt-less worker double-fault from the earlier high finding remains OPEN and still requires a production fix.
### 2026-09-19 clarification recovery fixture | medium | fixed in implementation

Type: test contract drift. The API sweep found the clarification restart proof created a RUNNING thread without its initial accepted graph action and receipt. After that was seeded, the resume fixture also lacked a valid accepted-input payload, a recovery deadline, an exact write expectation, and a committed lease. The fixture now persists both accepted actions and the test passes against the real checkpointer and worker. Review found no production behavior change in this pass. The full API and repository suites remain in progress, so this closure applies only to the focused regression.
### 2026-09-19 follow-up application receipt correction | medium | fixed in implementation

Type: audit correction and test contract drift. The earlier note near the accepted-dispatch finding classified `test_followup_dispatch_marks_message_followup_as_applied` as a possible production state-transition defect. Review of `_handle_progress_event` showed that production requires both the exact graph-action receipt and a named checkpoint incorporating it before settlement. The test sent neither, so `last_applied_action` correctly remained `ingest`. The test now records the matching checkpoint and relays both evidence fields; its focused run passes. The earlier production-defect inference is superseded by this evidence.

### 2026-09-19 team status liveness fixture | low | fixed in implementation

Type: test contract drift. Team status includes node metadata only for active threads, and an aggregator event by itself does not make a thread active. The node-summary route test now registers and subscribes a live reader before requesting team status. The focused test passes; review found no production defect in this path.

### 2026-09-19 permission rejection deadline | high | fixed in implementation

Type: production journal invariant. Rejected and duplicate permission-response actions used `create_control_action` without the recovery deadline required for that action type by the current database schema. Invalid responses raised `ValueError` instead of returning their typed conflict. Both non-executing journal writes now carry a finite deadline; the malformed-row test fixture does too. All 11 permission-response endpoint tests pass. The deadline is required by the persisted action-type invariant even though these terminal results are not redriven.

### 2026-09-19 terminal deletion fixture authority | medium | fixed in implementation

Type: test contract drift. Two deletion tests created terminal threads with writer receipt columns but no matching control action, so the deletion election correctly refused them. The fixtures now seed matching journal rows and both focused deletion tests pass.

### 2026-09-19 API batch follow-up | high | open

Type: gate burndown. A broader API run stopped after 20 failures at 212 passing tests. Beyond the resolved permission-response and deletion clusters, remaining groups include cancel non-delivery state expectations, terminal checkpoint proof in gateway-drain tests, gateway live stream fixtures, and harness template discovery. These are queued for implementation and review; the repository-wide green gate has not been reached.

### 2026-09-19 live stream queue shape | high | fixed in implementation

Type: production streaming contract. `EventAggregator.relay_payload` queues a positive-projected dictionary for worker events, while `_stream_thread_events` passed every queue item to `sequenced_to_positive_payload`, which requires a `SequencedEvent`. A live stream crashed with `AttributeError` after a relayed progress event. The stream now distinguishes sequenced in-process events from already-projected worker dictionaries and applies the existing SSE encode boundary to both. Three focused live stream tests pass. The live gateway fixture also now seeds accepted graph authority, and the reconnect-cursor test records real completion evidence before asserting the terminal cursor.

### 2026-09-19 cancel and drain recovery expectations | medium | fixed in implementation

Type: test contract drift. The cancellation and drain tests expected an unreachable worker or a capacity refusal to restore pre-dispatch status or fail an accepted run. The current durable recovery contract preserves accepted work for redrive and requires matching terminal evidence before releasing admission. Updated tests assert the live recovery state and seed the required checkpoint/cancellation proof. All 8 gateway-drain and 11 endpoint delete/cancel tests pass.

### 2026-09-19 installed harness template drift | high | fixed in implementation

Type: installed dependency contract. The pinned `vaultspec-core install` provides `exec-ledger.md` but no `exec-step.md` or `exec-summary.md`, so `provision_workspace` always reported a newly provisioned authoring workspace as unready. The verifier now requires the installed ledger template. The bundled coder prompt was also updated from an obsolete per-Step document instruction to Core's `vault exec log` command and ledger template. All 18 gateway and harness tests pass. Review confirms this is a served authoring-path repair, not a test-only relaxation.

### 2026-09-19 missing-transcript proof fixture | medium | fixed in implementation

Type: test contract drift. Two history tests tried to settle COMPLETED without the graph completion checkpoint now required by production. They now complete with exact accepted evidence, delete the checkpoint, and verify that the wide read reports the resulting transcript loss. All 5 history transcript availability tests pass. The test retains its original failure-mode proof while following the current terminal contract.

### 2026-09-19 served degradation vocabulary | medium | fixed in implementation

Type: public contract drift. The snapshot producer emits `invalid_agent_descriptors` and `incompatible_execution_authority`, but neither token was declared in `DegradedReason`. Both members are now declared, the containment sweep passes (21 tests), and the committed OpenAPI artifact was regenerated from the live schema (6 tests pass).

### 2026-09-19 deletion saga endpoint authority | medium | fixed in implementation

Type: test contract drift. Eight endpoint saga tests seeded thread writer receipts without matching control actions. The deletion election correctly refused terminal seeds. A shared helper now seeds a matching journal row; all 8 endpoint saga cases pass.

### 2026-09-19 internal relay evidence backlog | high | open

Type: test and worker contract drift. The second API batch reached 446 passing tests before 20 failures; after resolving OpenAPI, history transcript, vocabulary, and deletion fixtures, the remaining dominant cluster is `api/tests/test_internal.py`. Its terminal tests relay COMPLETED with no checkpoint or FAILED with no exact action evidence, which current production correctly refuses. The worker-rejection case also exposes the previously recorded high receipt-less double-fault. These require current accepted-action fixtures and evidence-aware assertions, plus a production rejection fix.

### 2026-09-19 subscriber queue annotation | medium | open

Type: typing contract. Review of the SSE fix found `SubscriberManager` annotates subscriber queues as containing only `SequencedEvent`, while `relay_payload` inserts projected dictionaries and can pass through other objects for malformed input. The stream reader now decodes both runtime shapes through an explicit `object` boundary and strict typing passes. The queue's producer/consumer type should be reconciled across the aggregator, WebSocket readers, fanout, and tests so the shared annotation itself is truthful; a broad queue-type change currently surfaces many downstream assumptions. This is queued separately from the fixed live stream crash.

### 2026-09-19 internal relay evidence and receipt-less worker review | high | fixed in implementation

Type: production terminal authority and test contract drift. Review traced the internal relay tests through the accepted action, graph receipt, and checkpoint imports. Forty-four relay tests now pass with exact accepted dispatch evidence, including valid failure evidence and completed checkpoint proof. Malformed failure details and unknown provider conditions are refused without changing durable status. A direct receipt-less Executor rejection previously tried to project FAILED without GraphFailureEvidence, then entered a second unhandled-failure path; both paths now skip unproven terminal settlement. The worker still emits a condition for observability and releases its local slot. API suite: 525 passed; strict typing: green. Remaining queue: subscriber queue type mismatch, structural strict gate, export gate, repository-wide tests, and the unraisable Windows transport warning observed during API tests.

### 2026-09-19 full unit gate first failure batch | high | partial fixes, queue open

Type: gate burndown and production concurrency. The resource-aware parallel unit run reached 1,096 passing tests before stopping after 26 failures. Review classified 19 deletion-saga failures as a fixture missing the current ingest recovery deadline (fixed; 19 focused cases pass), five graph-input failures and adjacent cache cases as missing accepted frozen definitions or outdated bound-authority messages (fixed; 48 focused cases pass), and one Core parity assertion as stale after Core changed active-plan rules (fixed; two focused cases pass). Startup reconciliation was spawning a worker before checking whether a reconciling row exists; the worker spawn now follows the empty-row check. The desktop lazy-worker test then exposed a separate high production issue: four concurrent run starts produce three SQLite `database is locked` 500 responses while one succeeds. The first writer holds the database long enough for other request inserts to fail. This remains OPEN for transaction-boundary/concurrency repair; a journal-mode read experiment did not resolve it and was reverted. The failure batch also contains desktop ownership/admission failures that remain OPEN pending focused review. Structural strict and export gates remain OPEN.

### 2026-09-19 desktop gate follow-up review | high | fixed in implementation

Type: production admission and lifecycle harness. The high concurrent SQLite start finding above is closed by retrying a transient SQLite lock on a fresh transaction, resolving a committed same-ID winner as a replay or conflict, and bounding attempts. The real four-request lazy-worker test returns four 201 responses and confirms a single worker spawn. Thirty live gateway tests, including same-ID insert races and different-body conflicts, pass. Review risk: a sustained SQLite lock beyond four attempts still propagates an error and merits a typed busy response in a later pass. The lifecycle owner in the gateway boot helper now binds its Uvicorn server, allowing the receipt-owned shutdown route to perform a real graceful stop; the process-tree shutdown test passes. The terminal child context fixture gained the session closing field; its real process-tree test passes. Focused run-admission desktop suite: nine passed, while two owner-tree tests were subsequently repaired. No open finding remains from these focused desktop failures. The wider unit gate and structural/export gates remain OPEN.

### 2026-09-19 unit control authority review | medium | fixed in implementation

Type: test contract drift. The next non-service run reached 1,255 passes before a control-test cluster stopped the bounded run. Actual review traced each failure to the accepted-action imports and current durable schema: follow-up and permission fixtures needed the initial frozen graph action under `thread-create:<id>`; receipt, event-handler, recovery, and verdict fixtures needed recovery deadlines; discovery needed a frozen graph definition; completed terminal-sequence tests needed the exact graph action and checkpoint completion proof; deletion tests needed a matching journal row before election. These fixtures now use the current contracts, and their focused groups pass. The vanished-workspace expectation was updated to the current dispatch refusal. Remaining queue: full control and non-service reruns, structural strict findings, export findings, and subscriber queue typing. No new production failure was established by these control clusters.

### 2026-09-19 full control-suite review | medium | fixed in implementation

Type: test contract drift. The full control test package now reports 502 passed and six marker-deselected after the receipt, deadline, initial-authority, checkpoint, deletion-journal, and vanished-workspace fixture updates. Review confirmed the tests still exercise their original state transitions and refusal behavior through current durable authority. No new production issue appeared in the full control run. The repository-wide non-service suite and strict structural/export gate remain queued.

### 2026-09-19 database gate review pass

The database package exposed stale fixtures after current write-authority and graph-recovery contracts became mandatory. This pass supplied complete authority columns and matching accepted action receipts, required recovery deadlines, and current execution metadata; it also changed reboot and retention assertions to the current checkpoint recovery behavior. Focused affected tests pass, and the package was reduced from ten immediate failures to three later fixture failures. The final three have been corrected and focused tests pass; a complete package rerun remains in the queue.

Review findings and queue:

- **Medium, test contract:** The full database package and repository suite must be rerun after the last fixture corrections; a focused pass cannot prove the whole gate. Open until both are green.
- **Medium, test maintainability:** Database reconciliation tests import `_seed_accepted_initial_action` from a control test module. Move the shared authority seeding helper into a neutral test support module if this dependency causes fixture drift or import-order issues. Open.
- **High, quality gate:** `just check-strict` still has outstanding Ruff, nesting, Pylint, and export findings. Burn down the complete strict output; open.

### 2026-09-19 graph compiler and compile probe review pass

Review of the implemented fixtures confirms that inline graph teams now carry the required positive step timeout, node assertions include the structural completion recorder, and the cold compile probe supplies the exact frozen graph definition required by the worker. The graph package passed 365 tests (2 deselected); the focused cold compile responsiveness test passed. Ruff and formatting passed. These are medium-severity test contract drift findings, resolved in this pass.

Remaining queue: the full repository suite is not yet green. A broad parallel run exposed more failures and stalled in accelerator-dependent provider harness startup (`service_env_no_gpu`); the first isolated provider compile failure and graph compiler failures are resolved, but the rest of the suite requires separate inventory runs. The strict gate remains high-severity open with 323 Ruff findings, 33 nesting findings, Pylint shape findings, and 110 unconsumed exports. The service harness accelerator requirement is a medium-severity environment/test-portability finding and remains open.

### 2026-09-19 worker authority fixture review pass

Review of the worker changes confirms that dispatch ID concurrency tests now send graph definitions and matching action receipts with model selections for their actual mock role; held-checkpoint tests reuse an accepted ingest fixture; graph-input projection tests supply a frozen program; receiptless rejection tests assert the current warning and do not invent terminal settlement. Focused dispatch ID, held-checkpoint, graph-input, and receiptless tests pass. These were medium-severity test contract drift issues, resolved here.

Open review findings: nine `worker/tests/test_executor.py` tests still fail in settle ordering and pre-run refusal coverage. The settle fixtures use synthetic preset and cache digests without accepted graph definitions, while refusal fixtures still expect terminal evidence from receiptless dispatches. This is high-severity test contract drift because the suite cannot verify terminal behavior until those requests carry valid authority. The full nonservice suite remains open; a timed broad run was interrupted after the worker cluster. The strict gate findings remain open as recorded above.

### 2026-09-19 worker resume and executor review pass

The executor file passed all 59 tests after accepted graph receipts and exact cache digests were supplied to settle and refusal fixtures. Review found a high-severity production bug: a resume with no durable checkpoint could compile a new graph and continue. The worker graph lifecycle now reads checkpoint authority on every resume and returns the existing missing-graph refusal when absent; a normal gated resume and the no-checkpoint refusal both pass. This is a behavior fix, not only a fixture update. The full worker package then reported 139 passing and four failing actor-token lifecycle tests.

Open queue: convert the four actor-token lifecycle tests from synthetic preset/cache digests and receiptless graph dispatches to accepted graph authority, then rerun the worker package and broad nonservice suite. Review risk: the extra checkpoint read on resume may increase read latency; preserve the existing deadline and verify checkpoint lock/capacity tests in the package rerun. The strict gate and accelerator-dependent harness findings remain open.

### 2026-09-19 actor-token lifecycle review pass

The four remaining worker failures were synthetic fixture drift: token tests registered injected graphs under fake preset and definition digests, then sent receiptless ingest/resume requests. This pass froze the current mock graph program, minted exact action receipts, and keyed the injected graphs from those requests. Review confirms the tests still assert token isolation, interrupt retention, terminal disposal, durable checkpoint secrecy, and log secrecy. The focused lifecycle file passed 5 tests; the full worker package passed 143 tests (2 deselected); Ruff and strict typing passed. These medium-severity test contract findings are resolved.

Open queue: rerun the full nonservice inventory without the accelerator-dependent harness, then address any remaining failures. `just check-strict` structural, Pylint, and export findings and the service harness accelerator prerequisite remain open.

### 2026-09-19 TeamState schema review pass

The late thread, utils, and workspace serial inventory found one medium-severity test contract drift: `TestTeamStateStructure` asserted an exact field set without the current agent descriptor, model assignment digest, graph definition digest, and three graph receipt fields. The expectation now includes those six fields; the focused test passes. The earlier late inventory had 403 passing and one failing test, so rerun that inventory and the full nonservice suite to close it. Review found no production change in this pass; the exact schema assertion remains useful for detecting future drift.

Open queue: a broad xdist run still reported one other late failure before active workers stalled, but it yielded no named summary. Run the full nonservice inventory serially to identify it. The service harness and strict structural/export findings remain open.

### 2026-09-19 bound resume compatibility and duplicate test review pass

Review of the resume guard against live clarification tests found a medium-severity compatibility regression: an accepted parked graph can be registered with a real checkpoint that predates the two digest fields. The bound resume path now checks checkpoint presence under the existing deadline and trusts the exact registered cache binding; the cold recompile path still requires and validates both digests. Current clarification fixtures supply both digests when representing current checkpoints, while the older accepted case remains undigested. All four live clarification tests, the no-checkpoint worker refusal, and the normal gated resume pass. The full lifecycle package passed 146 tests under four workers.

The structural-duplication gate found identical interrupt graph helpers in executor and token tests. The token tests now import the existing helper; five token tests and the structural gate pass. These are resolved medium-severity test contract findings. The broad xdist lifecycle failure did not reproduce in the isolated package and remains a medium-severity concurrency/flakiness finding for a complete repository rerun. `just check-all` passed. The strict structural/export gate and accelerator-dependent service harness remain open.

### 2026-09-19 complete nonservice repository run

A four-worker `pytest -m "not service"` run, excluding the accelerator-dependent provider harness file, completed with 4,535 passed, 1 skipped, and 2 Windows Proactor transport warnings in 375.57 seconds. No test failed. This closes the previously open unnamed broad-suite and lifecycle concurrency failures at the four-worker cadence. The skip is the acceptance proof requiring a reachable loopback authoring engine; the two warnings are unclosed transport finalizers on Windows. They remain medium-severity environment/test-cleanup findings rather than being counted as passing quality work. The strict structural, Pylint, and export gate findings and accelerator-dependent harness remain high-priority open queue items.

### 2026-09-19 strict gate baseline after nonservice test recovery

`just check-strict` remains red on the current pushed branch. Its current output reports 323 Ruff complexity/shape errors (137 excessive arguments, 77 complexity, 39 statements, 37 branches, 33 returns), 33 nested-block errors, 60 Pylint shape findings, and 110 unconsumed exports. All are open findings; the passing `just check-all` and 4,535 passing nonservice tests do not close this stricter gate. The queue is to refactor or justify each reported interface and structure, then rerun the complete strict recipe to zero. No thresholds were raised and no diagnostics were suppressed in this pass.

### 2026-09-19 harness CI contract review pass

`just test-harness` found one medium-severity test contract drift in `dev/tests/test_ci_contract.py`: it still looked for `just lint` workflow sentinel commands, treated duplication as a harness-level advisory target, and expected separate Ty platform commands. The current workflow uses `just check-*` sentinels; the duplication runner owns its advisory result, and platform typing is one `dev.quality.types --no-strict --platforms` command. The test now checks those current artifacts. Focused CI contract and the full harness suite pass (119 tests). Review found no workflow or runner behavior change. The service and strict gates remain open.

### 2026-09-19 service gate review pass

`just test-service` completed with 115 passed, 68 skipped, one failed test, and five Compose setup errors. The five errors shared a high-severity image-build defect: the locked Starlette Git dependency requires a Git executable, absent from the production Python base image. The image now installs Git before `uv sync`; the gateway image builds successfully. The single failure was medium-severity test contract drift: a repeated identical permission verdict is accepted and deduplicated by the service, while the test expected rejection. The service test now submits a conflicting verdict after completion and expects the documented conflict response. Focused test verification and the complete service gate rerun remain in the queue until they finish. Existing service skips require live external prerequisites; the strict structural, Pylint, and export findings remain open.

### 2026-09-19 production import closure review pass

The service rerun resolved the permission conflict test but found a second high-severity Compose defect: the worker image crashed at import because `control.worker_management` imports `psutil` while the production dependency set declared it only in the tooling group. `psutil` is now a direct base dependency, the tooling duplicate and its DEP004 exception are removed, and the lockfile is updated. The complete Compose regression module passes all 17 tests, including gateway and worker health. `just check-all` and a full service rerun remain required before closing the gate. The strict structural, Pylint, and export queue remains open.

### 2026-09-19 cancellation lock collision review pass

The next full service run passed the Compose and permission cases but surfaced one medium-severity concurrency defect: a running thread's cancel request returned HTTP 500 when its SQLite control-action insert collided with a concurrent event write (`sqlite3.OperationalError: database is locked`). The cancel service now rolls back and retries only this specific SQLite lock error at the pre-dispatch claim boundary, with four bounded retries and a fresh durable authority read each time. A direct control lease test injects the collision once and proves one worker dispatch; the focused live cancel test and the direct lease package pass. Review found the retry boundary precedes the accepted action and external dispatch, so the failed attempt cannot duplicate worker work. It also found low-severity module documentation drift: the header denied commits although this service commits durable transitions; the header now states the actual contract. The complete service rerun and strict findings remain open until their gates finish.

### 2026-09-19 complete service gate result

The full `just test-service` gate now exits successfully: 121 passed, 68 skipped, 4,574 deselected, and one warning in 182.76 seconds. The declared skips require live engine/provider credentials or a separately served mock backend; none is a failing test. The production Compose image, worker startup, permission conflict, and cancellation cases all pass in this run. This closes the high-severity image/import defects and the medium-severity cancellation lock collision at the service-gate cadence. The strict complexity, nested-block, Pylint shape, and unconsumed-export findings remain open and prevent completion of the requested zero-issue quality pass.

### 2026-09-19 private export review pass

The strict unconsumed-export audit reported 110 published names with no consumers. Review of private desktop and provider modules found 15 low-severity API-surface findings: 14 internal symbols were unnecessarily listed in `__all__`, and the `thaw_json` helper had no consumer at all. The internal symbols remain available to their owning modules, while their unused exports are removed; `thaw_json` is deleted along with its stale module description. No wildcard import of these private modules exists in the repository. The export audit now reports 95 findings across 1,205 published names. These 95 findings, the 323 Ruff structure errors, 33 nested-block errors, and Pylint shape findings remain open; the strict gate is not yet green.

### 2026-09-19 unconsumed export zero review pass

The remaining 95 unconsumed published names were reviewed against repository imports. They were symbols retained for their owning modules or directly importable by name, but had no repository consumer of their `__all__` publication; no wildcard import of these modules exists. Their unused `__all__` entries were removed without changing the symbol definitions or direct imports. The former sole `database.admin.main` list was removed because the command entry point is invoked directly. The export audit now reports zero findings across 1,110 published names, and `just check-all` passes. This closes the low-severity export-surface queue. A downstream wildcard importer would see a narrower set; explicit imports remain available. The 323 Ruff structure errors, 33 nested-block errors, and Pylint shape findings remain open; `just check-strict` is still red.

### 2026-09-19 strict argument shape review pass

The strict Ruff pass found a low-severity excessive-argument issue in the deterministic completion review-bundle helper: six pieces of one run-bound evidence record crossed its call boundary separately. They now travel as a frozen typed `_ReviewBundleInput`, with the same fields and one unchanged call site. The focused Ruff shape and format checks and Ty pass; the acceptance test itself still requires its declared live engine and durable evidence directory. The strict Ruff structure count falls from 323 to 322. The remaining 322 structure errors, 33 nested-block errors, and Pylint shape findings remain open.

### 2026-09-19 gateway auth case-shape review pass

Two low-severity strict argument-shape findings came from gateway auth tests unpacking one parameterized route case into four pytest arguments alongside fixtures. The route case now crosses each test boundary as one typed tuple and is unpacked inside the test; all 25 gateway auth cases pass, and focused Ruff and format checks pass. The strict Ruff structure count falls from 322 to 320. The remaining 320 structure errors, 33 nested-block errors, and 60 Pylint shape findings remain open.

### 2026-09-19 harness and authoring seed shape review pass

Two low-severity strict argument-shape findings in test helpers were resolved. Harness corpus provisioning now uses one explicit agent-state choice (`complete`, `empty`, or `missing`) and a separate MCP-corpus step; this removes conflicting boolean combinations. The authoring completion tests now pass one typed thread seed holding the run identity, preset, authoring IDs, and status. All 11 harness and four authoring completion tests pass, and focused Ruff checks pass. The strict Ruff structure count falls from 320 to 318. The remaining 318 structure errors, 33 nested-block errors, and 60 Pylint shape findings remain open. A full four-worker nonservice run on the combined branch is in progress.

### 2026-09-19 parameterized compiler and permission audit review pass

Two low-severity strict argument-shape findings were resolved in tests. The compiler structure test now receives its preset/topology/worker expectation as one parameterized case; the permission audit seed helper receives an explicit pause specification instead of three loosely related fields. The focused compiler test and all five durable permission-audit tests pass; Ruff's focused argument rule passes for both files. The strict Ruff structure count falls from 318 to 316. The remaining 316 structure errors, 33 nested-block errors, and 60 Pylint shape findings remain open.

### 2026-09-20 complete combined-branch nonservice result

The four-worker nonservice repository suite completed after the resource-aware test changes and strict test-shape edits: 4,536 passed, one declared live-engine skip, and two Windows Proactor transport warnings in 402.43 seconds. No test failed. This closes the prior need for a combined-branch nonservice rerun. The warnings and live-engine prerequisite remain recorded environment/test-cleanup items; the strict structure, nesting, and Pylint findings remain open.

### 2026-09-20 startup redispatch structure review pass

The strict gate found three medium-severity structure findings and one nested-block finding in the startup reconciliation sweep. The sweep now delegates metadata parsing, incompatible-authority refusal, missing-project refusal, accepted-action restoration, and batch failure summarization to focused helpers. Review checked that each refusal still commits before continuing, malformed metadata remains local to its thread, accepted dispatch remains bound to the stored authority, and each failure ladder category retains all thread IDs. Thirteen real redispatch tests pass, including fresh-worker restart, stale authority, missing project, and repeated circuit-open behavior. `just check-all`, `just check-type-strict`, and complexipy for the module pass. Strict Ruff structure falls from 316 to 313 and nested-block findings fall from 33 to 32.

Strict typing also exposed one low-severity test import-boundary finding from the earlier cancellation retry proof: it read a non-exported claim helper through `cancel_service`. The test now imports that helper from its owning `action_lease` module; its focused test and the full strict type gate pass. The remaining 313 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 Codex catalog structure review pass

The Codex catalog discovery module had five medium-severity strict Ruff structure findings and one complexipy finding across its control construction, RPC exchange, pagination, and normalization paths. Native-control fields now travel as a typed specification; process, timeout, and output budget are bound in one RPC session; pagination returns ordered pages with the next request id; and a typed catalog builder owns model/control accumulation. Review checked that page and control ceilings, duplicate-model and cursor rejection, request-id order, shared output budget, and process cleanup retain their prior behavior. All 13 catalog tests pass, including the service-marked real process and failure cases. `just check-all`, `just check-type-strict`, and the module complexipy check pass. Strict Ruff structure falls from 313 to 308. The public discovery function still has one excessive-argument finding; changing its published call contract needs a separate decision. The remaining 308 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 streaming transformer structure review pass

The streaming transformer had seven medium-severity Ruff structure findings in tool-event projection and its event entry point: five excessive-argument signatures, one complex tool completion path, and one excessive-return path. Tool-event identity and emitters now travel as one typed emission context; stable stream services travel as one typed dependency context; file artifact projection has a focused helper; and the redundant node-boundary return is removed. Review checked that tool start, end, error, completed-action, and artifact updates preserve their IDs, ordering, status, payload limits, and node filtering. The 81 focused streaming and aggregator tests pass; `just check-all`, `just check-type-strict`, and focused Ruff pass. Strict Ruff structure falls from 308 to 301. No new review findings were surfaced. The remaining 301 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 event adapter structure review pass

The domain-to-wire adapter had three medium-severity strict structure findings from an eleven-case conversion function. The message, tool-start, tool-update, control, and state mappings now live in focused functions, with one dispatcher preserving the same event classes, field conversion, sequence, and timestamp. Review found no dropped event case or changed fallback error. Five focused API tests, `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 301 to 298. No new review findings were surfaced. The remaining 298 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 MCP schema normalization structure review pass

Four medium-severity strict structure findings in recursive injected-field removal and older-engine oneOf translation were resolved by extracting property, child, discriminator, and branch-guidance operations. Review checked that nested property/required removal, oneOf/anyOf/allOf traversal, discriminator order and deduplication, opaque payload/alias handling, and required-set intersection retain their behavior. All 20 schema-normalization tests pass, including the real MCP serving case; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 298 to 294. No new review findings were surfaced. The remaining 294 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 write-authority SQL parser structure review pass

Four medium-severity strict structure findings in the named-CHECK parser were resolved by extracting SQL token advancement, named-CHECK header parsing, and balanced predicate scanning. Review checked that comments and quoted content remain ignored, malformed quotes/comments/parentheses still reject the whole parse, duplicate names still reject, and the original predicate slice is preserved. All 16 schema parser tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 294 to 290. No new review findings were surfaced. The remaining 290 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 internal event relay shape review pass

The internal worker-event relay had one low-severity strict argument-count finding: the aggregator, durable store, checkpointer, drain gate, and transport traveled separately through three ingress paths. They now travel as one frozen relay context. Review checked that WebSocket transport attribution, HTTP relay readiness, batch ordering, projection bypass for dispatch receipts, and durable relay arguments retain their values. All 44 focused internal API tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 290 to 289. No new review findings were surfaced. The remaining 289 Ruff structure, 32 nested-block, and 60 Pylint shape findings remain open.

### 2026-09-20 anchoring context structure review pass

One medium-severity cyclomatic finding in contextual anchoring came from rendering vault-index entries within the same function as feature-state summary fields. A focused helper now renders document labels, capped paths, and remainder counts. Review checked that field ordering, empty-index omission, path cap, and validation-error placement stay the same. All 14 anchoring tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 289 to 288. No new review findings were surfaced.

The latest complete `just check-strict` run remains red and confirms the broader open gate: 155 radon cyclomatic findings, 13 module-length findings, 24 function-length findings, 109 parameter-count findings, six code-health nesting findings, plus strict Ruff, nested-block, and Pylint shape findings. These are still in the audit queue; passing the regular gate and strict type checker does not close them.

### 2026-09-20 stream ingest structure review pass

The graph ingest path had four medium-severity strict Ruff findings: excessive argument count, cyclomatic complexity, branch count, and statement count. The internal ingest request now carries its run inputs as one typed value; graph-stream failure classification delegates bounded graph failures and provider failures to focused reporters. Review checked the original precedence of provider cancellation, graph interrupt, recursion limit, ingest stall, step timeout, and provider condition; the durable failure reason/condition writes and emitted codes remain tied to those branches. The 81 focused aggregator and transformer tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 288 to 284. The pre-existing overlong `ingest` function remains one medium-severity code-health finding; the extraction did not add another overlong function. No new review findings were surfaced. The remaining 284 Ruff structure, 32 nested-block, and Pylint/health findings remain open.

### 2026-09-20 ACP protocol dispatch structure review pass

Four medium-severity strict Ruff structure findings in ACP stdout dispatch, server-RPC argument shape, and session-update branching were resolved. One parsed stdout line now has a focused dispatch helper; server-RPC method/id/params travel as a typed request; native-command advertisement and streamed tool-argument chunks have focused handlers. Review checked that activity is still stamped before parsing, malformed frames and queue overflow remain local, batch packet order remains intact, capability refusals still answer the agent, and command advertisements still validate session identity before replacing the catalog. Fifty-seven focused protocol and process-lifetime tests pass; `just check-all`, `just check-type-strict`, and focused Ruff pass. Strict Ruff structure falls from 284 to 280. The pre-existing medium-severity cognitive-complexity finding in `handle_client_response` remains open; this pass did not change that function. No new review findings were surfaced. The remaining 280 Ruff structure, 32 nested-block, and Pylint/health findings remain open.

### 2026-09-20 ACP response complexity review pass

The ACP response handler had one medium-severity cognitive-complexity finding after the dispatch cleanup. Future settlement and terminal prompt-result validation now have focused helpers, preserving duplicate-terminal refusal, late-future handling, error sentinel behavior, and stop-reason validation order. Thirty-four focused response and process-lifetime tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. No new review findings were surfaced. The module has no remaining complexipy offender; the repository-wide strict backlog remains open.

### 2026-09-20 discovery credential and desktop parsing review pass

Six medium-severity strict Ruff structure findings in lifecycle discovery were resolved. The desktop record parser combines equivalent invalidity checks; credential reading and private publication now use focused helpers for leased reads, source claims, existing-file refusal, POSIX identity verification, and platform publication. Review checked that the credential remains owner-restricted, link-like paths and changed identities remain refused, source cleanup still runs after publication failure, Windows ACL hardening still follows publication, and malformed desktop records still fail closed. Twenty-five lifecycle and desktop ownership tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 280 to 274. The two public discovery writer signatures still have low-severity excessive-argument findings; their call contracts remain in the open queue. No new review findings were surfaced. The remaining 274 Ruff structure, 32 nested-block, and Pylint/health findings remain open.

### 2026-09-20 worker management structure review pass

Twelve medium-severity strict Ruff findings across worker spawn admission, readiness polling, exact-tree reaping, shutdown, and watchdog reconciliation were resolved. Desktop and shared-port pairing decisions now have separate predicates; retained process signaling is shared by exact-tree and descendant cleanup; cooperative shutdown and live-descendant capture are focused helpers; readiness inputs travel as one typed specification; and the watchdog separates probe reconciliation from restart. Review checked that only an owned worker is adopted or restarted, an unauthorized or unidentifiable occupant is never evicted, a failed eviction refuses spawn, containment cleanup still runs in nested finally blocks, and restart cooldown still stamps failed attempts. Forty-one focused spawn, provenance, and watchdog tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 274 to 262; worker-management has no remaining Ruff or complexipy findings. The latest code-health gate reports 23 function-length, 104 parameter-count, and four nesting findings (from 24, 109, and six at the prior complete strict run), while the module-length finding for this 1,746-line file remains open. Radon complexity is 145 over the threshold across the repository, down from 155 at the prior complete strict run. No new review findings were surfaced. The remaining 262 Ruff structure, 31 nested-block, and Pylint/health findings remain open.

### 2026-09-20 terminal and application event structure review pass

Seven medium-severity strict Ruff complexity, branch, return, and statement findings in terminal and dispatch-application handling were resolved. Completion, cancellation, and failure terminals now have separate proof checks; the terminal handler releases the drain gate and prunes aggregator state only after one proof accepts. Dispatch application now validates the private receipt, proves checkpoint incorporation, then reloads the current action under row locks before settlement. Review checked that sequence capture still precedes pruning, mismatched or stale evidence still refuses settlement, the intermediate database commit still precedes checkpoint inspection, and permission response resolution still returns its request id to the aggregator. Sixty-four focused control and API tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 262 to 255; code-health function-length findings fall from 23 to 21 and radon findings from 145 to 144. No new review findings were surfaced. Three excessive-argument signatures and the module-length finding remain open in this module; the remaining 255 Ruff structure, 31 nested-block, and Pylint/health findings remain open.

### 2026-09-20 clarification dispatch structure review pass

Three low-severity strict argument-count and medium-severity cyclomatic findings were resolved. The response and restart recovery paths now pass their worker dependencies in one typed runtime; dispatch after a successful claim is a focused helper. Review checked that the claim is finalized before dispatch, the graph receipt is bound before sending, definite non-delivery still records a repair reason, ambiguous delivery retains the lease, and only a matching checkpoint receipt proves application. Ten focused clarification and dispatch-failure tests pass, as do the regular Ruff gate and diff check. Strict Ruff structure falls from 255 to 252. Four pre-existing medium-severity structure findings remain in this service: the main responder has excessive complexity, returns, and branches, and the result builder has excessive parameters. These and the repository-wide strict backlog remain in the audit queue. No new review findings were surfaced.

### 2026-09-20 clarification replay and claim structure review pass

Four medium-severity strict Ruff findings remaining in the clarification service were resolved. Existing-action replay, claim preparation, post-claim state decisions, and worker dispatch now have bounded functions; error details travel as one typed value. Review checked that an existing matching receipt settles before any new claim, conflicting accepted input still returns 409, expired ORM state is not read after a losing claim rollback, non-active and no-longer-parked paths roll back, and only a checkpoint receipt marks application. Ten focused clarification and dispatch-failure tests pass; `just check-all`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 252 to 248, and the clarification service has no remaining strict Ruff or complexipy findings. No new review findings were surfaced. The remaining 248 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 permission response structure review pass

Seven medium-severity strict Ruff findings in the permission-response service were resolved. A typed response and worker runtime now carry the service inputs; rejection journaling, idempotency replay, pending-state authorization, option validation, and failed dispatch have focused helpers. The unused aggregator argument was removed because application is proved by the exact receipt path. Review checked rejection-journal durability, retry replay before pending-status rejection, accepted-body conflict handling, claim election, audit-log placement before dispatch, and definite versus ambiguous dispatch failure compensation. Review surfaced one medium-severity behavior-drift risk: an extracted helper initially used the permission row's thread id, which could differ from the resolved fallback id. It was fixed before commit by using the loaded thread record's id in all three extracted helpers. Fifty-one focused control, database, and live gateway tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 248 to 241; code-health function-length findings fall from 21 to 19 and parameter-count findings from 104 to 97. The permission service has no remaining strict Ruff or complexipy findings. The remaining 241 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 verdict subscriber structure review pass

Six medium-severity strict Ruff findings in verdict subscriber setup, parked-run reconciliation, verdict resume, and recovery-proposal parsing were resolved. The subscriber now receives one typed configuration; candidate selection, decided-verdict mapping, current-gate dispatch setup, and proposal parsing have focused functions. Review checked that INPUT_REQUIRED and mis-statused RUNNING candidates are still deduplicated in order, the current gate alone authorizes a resume, the accepted graph and write expectation are read before claim election, a fresh claim is finalized before worker dispatch, and HTTP acknowledgement still does not mark the action applied. Twenty-two focused tests pass; the six service-marked cases were deselected by the default profile and explicitly run with `-m service`, where all six skipped because a healthy loopback engine plus gateway and worker were unavailable. `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 241 to 235; code-health function-length findings fall from 19 to 18 and parameter-count findings from 97 to 96. No new review findings were surfaced. The remaining 235 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 cancellation control structure review pass

Five medium-severity strict Ruff findings in the cancel workflow were resolved. Worker dependencies now travel as one typed runtime; preflight deadline and eligibility checks, existing-claim replay, thread-authority election, and dispatch settlement are separate functions. Review checked that a caller retry label is still echoed while the thread owns one durable cancellation key, the accepted recovery deadline is captured before claim rollback can expire ORM state, the SQLite busy retry retains its bounded backoff, and ambiguous delivery preserves the lease and CANCELLING projection while definite non-delivery records the repair reason. Thirty-nine focused control and live gateway tests pass; `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 235 to 230; code-health function-length findings fall from 18 to 17 and parameter-count findings from 96 to 95. No new review findings were surfaced. The remaining 230 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 ACP session and chunk structure review pass

Five medium-severity strict Ruff complexity, branch, and statement findings in the ACP chat model were resolved. Environment preparation and harness contract probing now have a focused method; native-command advertisement and prompt construction have a focused method; early subprocess exit and completed prompt-error checks have focused helpers. Review checked that the environment is still prepared before spawn, all session and reader cleanup remains in the same finally path, native commands are refused before prompting when not advertised, interrupt errors retain precedence over prompt errors on early exit, and timeout polling still enforces the turn deadline. One extracted helper initially lost the session-id type narrowing; the review fixed it by passing the exact initialized session id. One hundred nine focused provider tests pass. Two service-marked strict-MCP tests were run separately and skipped because no current live provider lane was selected. `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 230 to 225; code-health function-length findings fall from 17 to 16. No unresolved new review findings were surfaced. The remaining 225 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 Codex provider turn structure review pass

Five medium-severity strict Ruff return, complexity, branch, and statement findings in Codex app-server response routing, native-control admission, and turn streaming were resolved. The turn now keeps deferred retry evidence, cumulative token usage, and side-effect evidence in one state object; notification wait, item projection, retry errors, and terminal settlement have focused functions. Review checked that only the exact thread's item, usage, and terminal frames are honored, retry errors remain deferred until final failure/EOF/idle timeout, a supervised permission interrupt still escapes before frame projection, cumulative usage is emitted once, and terminal status is stamped before a failed-turn exception. Review surfaced one low-severity malformed-frame risk: set membership on an untrusted JSON method could raise for a list or object. It was fixed before commit by using safe tuple comparisons. Eighty-three focused provider tests pass. The one service-marked live Codex turn was attempted and skipped because no current provider lane was selected. `just check-all`, `just check-type-strict`, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 225 to 220; code-health function-length findings fall from 16 to 15 and worst nesting depth from eight to seven. No unresolved new review findings were surfaced. The remaining 220 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 thread admission and archive structure review pass

Four medium-severity strict Ruff argument, complexity, and return findings in thread creation and archive election were resolved. Initial worker dependencies now travel as one typed runtime; failed dispatch settlement and archive-election rechecks have focused helpers. Review checked that the thread and graph action remain durable before worker dispatch, the recovery deadline and receipt authority are preserved, a concurrent terminal writer can still win while dispatch is in flight, missing rows still report their typed outcome, and archive election failure rolls back before re-reading current state. Sixty-three focused creation, deletion-saga, drain, and live gateway tests pass; `just check-all`, `just check-type-strict`, and focused Ruff pass. Strict Ruff structure falls from 220 to 216; code-health parameter-count findings fall from 95 to 94. No new review findings were surfaced. The pre-existing medium-severity cognitive-complexity finding in `list_threads_service` remains open in this module. The remaining 216 Ruff structure, 31 nested-block, and Pylint/health findings stay open in the audit queue.

### 2026-09-20 thread-list summary complexity review pass

One medium-severity cognitive-complexity finding in `list_threads_service` was resolved by extracting checkpoint state, live plan approval, and summary projection. Review checked that missing and uncertain checkpoint probes still degrade readiness and hide approvals, recovery-epoch and checkpoint-id mismatches still degrade stale execution state, terminal threads still hide approvals, and only the latest pending plan permission with valid options is exposed. Eighty-three focused control and API tests pass; `just check-all`, `just check-type-strict`, focused Ruff and Ty, and module complexipy pass. The module now has no cognitive-complexity finding. No new review findings were surfaced. Strict Ruff structure remains at 216; code health remains at 13 module-length, 15 function-length, 94 parameter-count, and four nesting findings. These and the remaining nested-block and Pylint findings stay open in the audit queue.

### 2026-09-20 graph receipt predicate review pass

One low-severity Pylint R0916 boolean-expression finding in graph receipt persistence was resolved by separating exact action identity from original dispatch evidence. Review checked that all seven original comparisons remain, including the upper bound on stored revision after a state-only election; invalid or mismatched receipts still return no persisted witness. Eleven focused receipt and dispatch tests pass; focused Ruff, Ty, and Pylint pass, as does `just check-all`. No new review findings were surfaced. The remaining strict Ruff, nested-block, cyclomatic, module/function/parameter/nesting, and Pylint findings stay open in the audit queue.

### 2026-09-20 dispatch and selection predicate review pass

Three low-severity Pylint R0916 boolean-expression findings were resolved in supervisor plan-approval routing, IPC graph receipt admission, and persisted team-selection validation. Review checked that execution routing still requires a plan and active feature without existing approval, ingest and resume retain their exact allowed action types while cancel remains refused, and role/fallback validation still rejects empty, duplicate, invalid, or excessive inputs. Fifty-six focused graph, provider, and receipt tests pass; focused Ruff, Ty, and Pylint pass. The first `just check-all` run exposed only an IPC formatting change, which was applied before rerunning the gate. No new review findings were surfaced. All remaining strict findings stay open in the audit queue.

### 2026-09-20 team selection normalization review pass

One medium-severity strict Ruff C901 finding and two medium-severity cognitive-complexity findings in team selection normalization were resolved. Catalog selectability, native-control defaulting and freezing, and persisted replay-control decoding now have focused functions. Review checked that provider lane lookup, catalog revision/expiry, model entry, attached controls, option ids, exact replay identity, and stored default controls retain the same validation order and errors. Twenty-two focused selection and persisted-authority tests pass; `just check-all`, focused strict Ruff and Ty, and module complexipy pass. Radon cyclomatic findings fall from 139 to 138. No new review findings were surfaced. The remaining strict Ruff, cyclomatic, nesting, shape, and Pylint findings stay open in the audit queue.

### 2026-09-20 provider factory admission decomposition review pass

The high-severity maintainability cluster in `ProviderFactory.create` remains open while its admission logic is decomposed. Frozen execution-mode validation, native-control validation, and option extraction now have focused helpers; the factory cyclomatic score falls from 53 to 41 without changing the repository-wide 138-offender count. Review checked that timeout, execution mode, and native controls are popped from the same mutable kwargs before model admission, frozen ACP backend conflicts still refuse construction, native control types and provider support still fail before construction, and the existing provider-specific paths receive the same values. Eighty-seven focused factory, in-process catalog, and Z.ai tests pass; `just check-all`, focused Ty, and diff check pass. No new review findings were surfaced. The remaining five strict Ruff findings and cognitive-complexity finding in this module stay open alongside the repository-wide strict backlog.

### 2026-09-20 provider factory construction review pass

Five medium-severity strict Ruff complexity, branch, statement, return, and parameter findings in provider construction were resolved. Codex, Claude, Z.ai, Kimi, in-process, and OpenAI-compatible constructors now have focused functions; Kimi's independent home variable is composed after temporary-model validation. Review checked the frozen model and backend authority, exact native controls, lazy model imports, ambient Claude auth, Z.ai token injection, Kimi command and temporary-provider values, and OpenAI/Zhipu credential precedence. Review surfaced two low-severity private-helper risks: permissive fallback to another provider, fixed by exact provider refusals; the first full check also caught an unused import, removed before the final run. One hundred thirty-five focused provider tests pass, with three deselected by the project marker policy; 46 focused factory tests pass after the review fix. `just check-all`, `just check-type-strict`, strict Ruff for the module, complexipy, and diff check pass. Repository strict Ruff structure falls from 215 after the prior team-selection pass to 210; radon findings fall from 138 to 136; code-health function-length falls from 15 to 14 and parameter-count from 94 to 93. No unresolved new review findings were surfaced. The factory still has a medium-severity module-length finding; the remaining 210 Ruff structure and other strict backlog stay open in the audit queue.

### 2026-09-20 snapshot projection structure review pass

Three medium-severity strict Ruff complexity, branch, and statement findings and one medium-severity cognitive-complexity finding in snapshot enrichment were resolved. Message projection, checkpoint-owned agent descriptors, checkpoint and live tool-call projection now have focused functions. Review checked that checkpoint descriptors retain priority over aggregator state, invalid descriptors still degrade the snapshot, provider action status and ToolMessage correlation remain distinct, and live tool calls do not duplicate checkpoint calls. Review surfaced one low-severity malformed tool-args risk in the extracted projector; an absent args mapping now safely takes the pending/completed correlation path. Strict basedpyright also exposed an imprecise extracted `ToolCall` type, corrected before final verification. One hundred one focused snapshot and API tests pass, followed by 26 focused snapshot and thread-state tests after the final type correction. `just check-all`, `just check-type-strict`, focused strict Ruff and Ty, module complexipy, and diff check pass. Repository strict Ruff structure falls from 210 to 207; radon findings from 136 to 135; code-health function-length findings from 14 to 13. No unresolved new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 checkpoint evidence classification review pass

Three medium-severity strict Ruff complexity, return, and branch findings and one cognitive-complexity finding in durable checkpoint evidence interpretation were resolved. Checkpoint schema, active action, completion receipt, and pending write classification now have focused functions. Review checked that unavailable and absent reads remain distinct, requested checkpoint ids are exact, malformed durable values and receipts remain incompatible, an older writer generation is reported as prior action only after incorporated evidence is verified, a valid completion still outranks pending writes, and error/interrupt channels retain their precedence and incorporation flag. Twenty-three focused recovery-authority and event-handler tests pass; `just check-all`, `just check-type-strict`, focused Ruff/Ty/basedpyright, module complexipy, and diff check pass. Repository strict Ruff structure falls from 207 to 204; radon findings from 135 to 134; code-health function-length findings from 13 to 12. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 direct-control recovery redrive review pass

Three medium-severity strict Ruff complexity, branch, and statement findings and one cognitive-complexity finding in direct-control redrive were resolved. One due recovery claim now passes through focused missing-row quarantine, durable action claim, dispatch preparation, refusal settlement, delivery-failure settlement, and delivery-success functions; an outcome enum counts the same dispatched, deferred, conflicted, and refused cases while applied actions remain uncounted. Review checked that each early branch commits or rolls back before returning, an authority loss defers only after its deadline, payload mismatch and reconstruction refusal quarantine exact authority, definite non-delivery releases the action lease, ambiguous delivery retains it, and successful delivery schedules an application receipt without minting a new dispatch id. During extraction, a generated patch briefly left a literal plus and an invalid trace-header keyword; both were fixed before verification. Ten focused accepted-input and current-redrive tests pass; `just check-all`, `just check-type-strict`, focused Ruff/Ty/basedpyright, module complexipy, and diff check pass. Repository strict Ruff structure falls from 204 to 201; radon findings from 134 to 133; code-health function-length findings from 12 to 11. No unresolved new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 gateway run admission and commit review pass

Ten medium-severity strict Ruff argument-count, complexity, branch, and statement findings in the gateway run-start and commit path were resolved. Private dispatch dependencies now travel as one typed runtime; replay-safe metadata admission, SQLite creation retries, nickname/integrity-race resolution, exact commit replay, execution eligibility, and failed-commit durability classification have focused functions. Review checked that the request replay digest is stamped before drain admission, a durable insert winner keeps its gate admission even when the losing body conflicts, nickname and winnerless errors release unused admission, a terminal dispatch failure releases it, a commit replay verifies the persisted reservation and digest before repairing the broker, and a failed commit aborts only when an authoritative read proves the run absent. Seventy-seven focused gateway, digest, catalog, drain, and desktop admission tests pass; `just check-all`, `just check-type-strict`, focused Ruff/Ty/basedpyright, module complexipy, and diff check pass. Repository strict Ruff structure falls from 201 to 191; radon findings from 133 to 132; code-health function-length findings from 11 to nine and parameter-count findings from 93 to 89. No new review findings were surfaced. The gateway module-length finding remains open and its measured length rose from 2,578 to 2,619 lines during extraction; the remaining strict backlog stays open in the audit queue.

### 2026-09-20 frozen catalog preference parser review pass

Two medium-severity strict Ruff complexity and branch findings in frozen catalog preference parsing were resolved. Assignment shape, one native-control entry, and the bounded native-control list now have focused validators. Review checked that primary and fallback field sets remain exact, schema version and provider errors retain their order, model and execution-mode strings remain required, native-control records still refuse unknown keys, blank ids/values, duplicates, and lists over 32, and provenance remains checked after controls. Eighty-nine focused compiler and persisted-selection tests pass; `just check-all`, `just check-type-strict`, focused strict Ruff/Ty, and diff check pass. Repository strict Ruff structure falls from 191 to 189 and radon findings from 132 to 131. No new review findings were surfaced. The compiler still has two cognitive-complexity and nine strict Ruff findings, plus its module-length finding; these and the remaining repository strict backlog stay open in the audit queue.

### 2026-09-20 graph topology complexity review pass

Two medium-severity cognitive-complexity findings in star and pipeline graph compilation were resolved. Supervisor prompt and metadata construction, and pipeline order validation now have focused helpers. Review checked the configured and fallback supervisor presentations, assignment metadata, worker resolution, and the existing empty-order and duplicate-order errors before node wiring. Sixty-seven focused compiler tests, routine quality gates, strict Ty, module complexipy, and diff review pass. The cyclomatic gate now reports 130 findings, down from 131. No new review findings were surfaced. Nine strict Ruff findings and the compiler module-length finding remain open; the remaining repository strict backlog stays open in the audit queue.

### 2026-09-20 durable snapshot projection complexity review pass

Two medium-severity strict Ruff cyclomatic-complexity findings in durable snapshot enrichment were resolved. Permission projection and execution-projection failure marking now have focused helpers. Review checked terminal permission clearing still takes precedence, valid siblings survive malformed permission rows, unreadable plan approval still clears its request id and demands repair, absent execution rows only degrade when a checkpoint exists, and unreadable execution rows still require operator intervention. Seventeen focused projection tests, focused strict Ruff and Ty, and module complexipy pass. The cyclomatic health gate falls from 130 to 129 findings. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 authoring SSE and IPC event serialization review pass

Three medium-severity strict Ruff complexity findings in authoring SSE line reassembly and IPC event-type selection were resolved. Buffered SSE dispatch now has one helper shared by blank-line and end-of-stream flushing; the closed IPC domain-event mapping is a typed ordered registry. Review checked that empty/comment lines do not emit, undecodable frames still drop, each supported event maps to its prior wire type, unknown events still have no type, and the existing IPC coverage test continues to detect unlisted event subclasses. A new test proves blank-line and EOF flushing. Thirty-four focused authoring and IPC tests, focused strict Ruff and Ty, and module complexipy pass. Repository strict Ruff structure falls from 187 to 184 and cyclomatic findings from 129 to 127. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 desktop gateway credential review pass

Two medium-severity strict Ruff complexity and return-count findings in desktop attach credential selection were resolved. The discovery-origin and credential-reference checks now have focused helpers. Review checked that fresh discovery, supported protocol, live process, exact HTTP host/port, matching resolved credential reference, and credential loading still occur in the same order; malformed ports and path resolution errors still fail closed. Four focused operator credential tests, routine gates, strict Ty, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 184 to 182 and cyclomatic findings from 127 to 126. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 provider readiness and OpenAI catalog review pass

Four medium-severity strict Ruff complexity and return-count findings were resolved. Provider readiness now delegates API-key, Z.ai, and Kimi checks; OpenAI-compatible model-list validation and bounded HTTP response handling have focused helpers. Review checked Claude/Codex command-only readiness, exact OpenAI/Zhipu/Z.ai missing-credential reasons, Kimi's partial temporary-definition refusal, 401/403 authentication mapping, pagination refusal, one-MiB response bound, model-field and duplicate validation, and stream cleanup under cancellation. Strict basedpyright exposed an imprecise extracted JSON value type; the helper now takes the exact recursive JsonValue shape. Sixty-seven focused OpenAI catalog tests, three installed Kimi middleware readiness tests, and one Codex readiness test pass. Routine gates, strict Ty/basedpyright, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 182 to 178 and cyclomatic findings from 126 to 125. No unresolved new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 IPC assignment schema review pass

One medium-severity strict Ruff complexity finding in dispatch model-assignment validation was resolved. Fallback and selected-control field validation now use focused helpers with the same closed required/optional field sets. Review checked that primary lanes and provenance remain exact, malformed fallback lists and records retain their refusal messages, fallback display fields remain optional, and selected controls still reject missing or unknown fields. Nine focused IPC schema tests, routine gates, strict Ty/basedpyright, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 178 to 177 and cyclomatic findings from 125 to 124. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 worker IPC flush review pass

One medium-severity strict Ruff cyclomatic finding and one cognitive-complexity finding in buffered worker event relay were resolved. One batch POST, cancellation requeue, bounded retry wait, and exhausted-batch requeue now have focused methods. Review checked successful HTTP 200 acknowledgement, non-200 and network-error warning details, deadline-limited request timeout and backoff, cancellation requeue before a POST or during backoff, exhausted error logging, and buffer-cap preservation. Twenty-four focused worker IPC tests, routine gates, strict Ty/basedpyright, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 177 to 176 and cyclomatic findings from 124 to 123. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 worker startup and dispatch review pass

Three medium-severity strict Ruff statement and cyclomatic findings in worker startup and dispatch admission were resolved. Startup gateway probing and dispatch receipt, duplicate-response, and scheduling logic now have focused functions. Review checked non-fatal gateway probe logs, invalid graph-receipt refusal before admission, exact duplicate replay before and after capacity wait, 429 for a different request on a busy thread, capacity release when synchronous admission or scheduling fails, and the no-await boundary between admitting a dispatch ID and scheduling its task. Seventeen focused worker app and dispatch-id tests, routine gates, strict Ty/basedpyright, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 176 to 173; the cyclomatic health count remains 123. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 worker terminal evidence review pass

Two medium-severity strict Ruff argument-count and cyclomatic findings in terminal event emission were resolved. One typed evidence value now carries either cancellation or graph-failure proof, and a focused validator checks outcome compatibility and the failure's exact thread, detail fingerprint, and provider condition. Review checked that nonterminal outcomes still emit nothing, failed outcomes retain the UNKNOWN floor, completed terminals carry no failure condition, cancelled outcomes require cancellation proof, and the executor keeps the same evidence for each settlement path. A first executor expression selected evidence by truthiness; review replaced it with an explicit None check so even a false-valued evidence object would be retained. Eleven focused state-projection tests, 21 focused executor settlement tests, routine gates, strict Ty/basedpyright, focused Ruff, and module complexipy pass. Three new test cases verify mismatched thread, detail, and condition refusal. Strict Ruff structure falls from 173 to 171; cyclomatic health stays at 123. No unresolved new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 completed checkpoint preflight review pass

One medium-severity strict Ruff statement-count finding in executor ingest admission was resolved. Completed-checkpoint settlement now has a focused method. Review checked that the checkpoint result is inspected before graph compilation, the span and log identify preflight completion, the terminal event is emitted before graph and metadata release, and any held dispatch capacity is released before returning without rerunning the graph. Thirteen focused executor checkpoint and terminal tests, routine gates, strict Ty/basedpyright, focused Ruff, and module complexipy pass. Strict Ruff structure falls from 171 to 170; cyclomatic health remains at 123. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 desktop readiness ladder review pass

Two medium-severity strict Ruff complexity and branch findings in desktop readiness assembly were resolved. Worker lifecycle selection, pending-worker evidence, and run-admission classification now have focused helpers. Review checked that an unspawned worker needs both a successful live probe and adoption provenance before promotion, a pending worker accepts a heartbeat only when the live probe has no verdict, an explicit failed probe takes precedence, down/restarting workers stay unavailable, and database or recovery-owner failure blocks admission. The first extraction introduced a second radon offender; focused pending-worker and admission helpers resolved it before commit. Eleven desktop readiness/admission and health tests passed during implementation; five focused worker-state and database-health tests pass after the final extraction. Routine gates, strict Ty/basedpyright, focused Ruff, and diff check pass. Strict Ruff structure falls from 170 to 168 and cyclomatic findings from 123 to 122. The existing cognitive-complexity findings in assemble_health_status and build_full_health remain open, alongside the remaining strict backlog. No unresolved new review findings were surfaced.

### 2026-09-20 shared and full health projection review pass

One medium-severity strict Ruff parameter-count finding, two cognitive-complexity findings, and two cyclomatic findings in shared and full health assembly were resolved. Worker status/restart projection and database, checkpointer, and worker probes now have focused helpers. A typed FullHealthRuntime carries the three live probe dependencies into both authenticated service-state and unarmed health callers. Review checked worker observation order, default restart fields, live database and informational journal verdicts, checkpoint timeout/failure details, exact worker HTTP 200 authority, pairing identity only when explicitly requested by the authenticated caller, and the existing overall readiness predicate. Thirty live gateway tests and five focused health/readiness tests pass; routine gates, strict Ty/basedpyright, module complexipy, focused Ruff, and diff check pass. Focused Pylint reports only two existing gateway-module findings. Strict Ruff structure falls from 168 to 167 and cyclomatic findings from 122 to 120. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue. A mistyped audit body-file command briefly displaced the earlier corpus; the committed body was restored through the vault CLI and the final diff checked before commit.

### 2026-09-20 persisted run lease binding shape review pass

One medium-severity Pylint boolean-expression finding in durable staged-commit lease binding validation was resolved. The binding now reuses the existing typed string-field reader for lease id, reservation id, and commit digest, then rejects any blank or absent value before constructing a binding. Review checked that non-string, blank, and missing fields still refuse replay; no durable metadata or digest authority changed. Thirty live gateway tests, routine gates, strict Ty/basedpyright, focused Ruff/Pylint, and diff check pass. Pylint now reports 58 findings, including the gateway module-length finding and six remaining boolean-expression findings. No new review findings were surfaced. The remaining strict backlog stays open in the audit queue.

### 2026-09-20 receipt authority predicate review pass

- Implementation: extracted the persisted graph receipt's writer identity and authority comparisons into a focused predicate. The comparisons and rejection behavior are unchanged.
- Review: inspected the actual diff and checked the receipt tests (5 passed), routine gate, strict type gate, focused Pylint, and focused strict Ruff. No new correctness issue surfaced. Severity: none for this change; type: no contract drift.
- Queue: the pre-existing `prepare_graph_action_receipt` return-count finding remains open in the strict Ruff queue. The repository still has other strict Ruff, Pylint, and code-health findings; this pass does not close them.

### 2026-09-20 native command name validation review pass

- Implementation: extracted the exact native command name predicate and preserved validation order and the existing error path.
- Review: inspected the diff; 8 focused native command tests, routine quality gate, strict type gate, and focused strict Ruff passed. Pylint's boolean-expression finding in this function is cleared. Severity: none for the change; type: no contract drift found.
- Queue: pre-existing Pylint `too-many-lines` and `too-many-instance-attributes` findings in `acp_chat_model.py` remain open. The remaining repository-wide strict gate findings remain open.

### 2026-09-20 thread summary checkpoint review pass

- Implementation: removed redundant checkpointer and tuple conditions from the stale execution-state comparison. `checkpoint_id` is assigned only when both conditions hold, so the comparison's behavior is unchanged.
- Review: inspected the diff; 9 focused thread listing/checkpoint tests, routine quality gate, strict type gate, focused Pylint, and focused strict Ruff passed. Severity: none for this change; type: no contract drift found.
- Queue: pre-existing Pylint instance-attribute findings in `thread_service.py` remain open. A trial split of the discovery record guard exposed a new strict Ruff return-count finding, so that trial was reverted; the existing discovery boolean-expression finding remains open.

### 2026-09-20 cancellation evidence guard review pass

- Implementation: split missing-record rejection from the exact cancellation authority comparison; both paths still roll back and return false.
- Review: inspected the diff; 31 event/cancellation tests, routine quality gate, strict type gate, focused Pylint, and focused strict Ruff passed. Severity: none for this change; type: no contract drift found.
- Queue: pre-existing `event_handlers.py` module-length and three strict Ruff parameter-count findings remain open. Other repository strict findings remain open.

### 2026-09-20 checkpoint permission-clear predicate review pass

- Implementation: extracted the permission-clear decision into a focused predicate, retaining the existing checkpoint and snapshot conditions.
- Review: inspected the diff; 14 snapshot tests and 21 capture/authoring tests passed, as did routine checks and strict type checking. Focused Pylint is clear. Severity: none for this change; type: no contract drift found.
- Queue: `capture_thread_state` still has strict Ruff C901 (13 > 10) and PLR0915 (69 > 50). Its checkpoint projection block requires a larger extraction. Other repository strict findings remain open.

### 2026-09-20 checkpoint projection extraction review pass

- Implementation: moved the existing checkpoint tuple read, history projection, and failure handling into `_read_projected_checkpoint`. A typed result carries the snapshot, checkpoint flags, and captured tuple back to the orchestration function. The statements and exception behavior are unchanged.
- Review: inspected the moved block and return wiring; 35 focused snapshot/capture tests, routine checks, strict type checking, focused Ruff/Pylint, and complexipy passed. The module has no radon functions above 10. Severity: none for this change; type: no contract drift found.
- Queue: the prior C901 and PLR0915 findings for `capture_thread_state` are closed. Repository-wide cyclomatic complexity still has 117 offenders, and other strict Ruff/Pylint findings remain open.

### 2026-09-20 graph receipt preparation review pass

- Implementation: extracted accepted action parsing and dispatch/receipt matching from the receipt orchestration. The same validation and exception paths remain in place.
- Review: inspected the diff; 35 receipt and live gateway tests, routine checks, strict type checking, focused Ruff/Pylint passed. The receipt module has no radon function above 10. Severity: none for this change; type: no contract drift found.
- Queue: the prior PLR0911 finding for `prepare_graph_action_receipt` and two radon offenders in this module are closed. The repository-wide cyclomatic gate still has 115 offenders, with other strict Ruff/Pylint findings open.

### 2026-09-20 team selection authority review pass

- Implementation: extracted focused helpers for control defaults, replay identity and defaults, persisted control records, and role validation. These preserve the existing error conditions and keep the execution-lane import at its original local boundary.
- Review: inspected the diff and corrected new helper annotations to the repository `JsonObject`/`JsonValue` contract. Thirty-one provider tests, routine checks, strict type checks, focused Ruff/Pylint passed. This module has no radon function above 10. Severity: none for the final change; type: no contract drift found. The transient type diagnostics from overbroad `object` annotations were fixed before commit.
- Queue: four prior radon offenders in `team_selection.py` are closed. The repository-wide cyclomatic gate still has 111 offenders; other strict findings remain open.

### 2026-09-20 gateway projection and failure review pass

- Implementation: extracted request-metadata copying, legacy lease-id validation, follow-up dispatch failure mapping, and service degradation reasons into focused helpers. Existing admission, lease, error-status, and health behavior remains in the same order.
- Review: inspected the diff; 65 gateway/digest/drain tests, routine checks, strict type checking, focused Ruff/Pylint passed. The gateway module has no radon function above 10. Severity: none for this change; type: no contract drift found.
- Queue: four prior radon offenders in `api/routes/gateway.py` are closed. Existing Pylint module-length and five strict Ruff endpoint parameter-count findings remain open. Repository-wide cyclomatic gate still has 107 offenders.

### 2026-09-20 ACP MCP composition review pass

- Implementation: extracted per-entry registry validation, attached desktop capability resolution, Codex/ACP composition projections, and native tool declaration. Grouped resolved projection inputs for the private projection function. Existing validation order, lane propagation, allowlist union, and local import conventions remain intact.
- Review: inspected the moved branches; 81 ACP MCP composition tests, 31 pinning tests without real-service startup, 12 contract/surface tests, routine checks, strict type checking, focused Ruff/Pylint passed. The module has no radon function above 10. Severity: none for the code change; type: no contract drift found.
- Verification finding (environment dependency, severity medium): four real-service pinning tests failed because the installed service interpreter reports `service_env_no_gpu` (CUDA and MPS unavailable). They remain queued for execution on a supported accelerator host or a supported service configuration; 112 other tests in that run passed. This is not evidence that the four tests are green.
- Queue: four prior radon offenders and one private PLR0913 finding in `_acp_mcp.py` are closed. Its public composition parameter-count finding and Pylint module-length finding remain open. Repository-wide cyclomatic gate still has 103 offenders, with other strict findings open.

### 2026-09-20 authoring submitter review pass

- Implementation: extracted locator URL, body-link, web-disclosure, and recovery-snapshot parsing helpers. Grouped the run's document proposal fields in an immutable context while keeping bearer and actor token as separate transient arguments. The operation's deterministic IDs and body are unchanged.
- Review: inspected the diff; 56 submitter tests, routine checks, strict type checking, focused Ruff/Pylint passed. The module has no radon function above 10. Severity: none for the final change; type: no contract drift found. An initial pass found two unused locals introduced by the grouping; both were removed and the gates rerun green.
- Verification limitation (environment dependency, severity medium): four service-marked live submitter tests were deselected because this run has no live engine endpoint; engine-backed proposal replay remains unverified here.
- Queue: three prior radon offenders and three strict Ruff findings in `authoring/submitter.py` are closed. The repository-wide cyclomatic gate still has 100 offenders; other strict findings remain open.

### 2026-09-20 OpenAI-compatible catalog review pass

- Implementation: extracted URL-origin validation, complete model-list shape checks, and timeout validation into focused helpers. The same fail-closed checks run in their previous order before model normalization or the HTTP request.
- Review: inspected the diff; 26 catalog tests including real HTTP contract cases, routine checks, strict type checking, focused Ruff/Pylint passed. The module has no radon function above 10. Severity: none for this change; type: no contract drift found.
- Queue: three prior radon offenders in `providers/openai_catalog.py` are closed. Repository-wide cyclomatic gate still has 97 offenders and other strict findings remain open.
