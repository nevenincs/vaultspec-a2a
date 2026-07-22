---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-19'
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
