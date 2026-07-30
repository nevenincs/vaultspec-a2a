---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-30'
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
