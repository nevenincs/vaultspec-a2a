---
tags:
  - '#audit'
  - '#production-telemetry-boundary'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:bde660e1cbf911aa9f51c93edd44f3bf6511280a357c5ad980c2e4f047711789'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-07-19-observability-lanes-adr]]"
  - "[[2026-09-24-architecture-review-audit]]"
---
# `production-telemetry-boundary` audit: `Jaeger security remediation`

## Scope

User-authorized remediation on 2026-10-04 of the medium security finding
reported against revision b973403: production Jaeger publishes unauthenticated
collector, query UI, and health ports to all host interfaces. Review covers
`service/docker-compose.prod.yml`, the production section of
`service/README.md`, and the focused Compose profile regression tests.

This bounded change needs no durable implementation plan or new costly
decision. Accepted service-lifecycle and observability-lanes decisions retain
Compose health and OTLP tracing, without requiring public collector access.
The related architecture-review audit's beyond-loopback-hardening entry remains
historical evidence; this pass resolves its production Jaeger portion only.

## Findings

### production-jaeger-publication | medium | production telemetry host exposure fixed

Type: security/network boundary. Status: fixed and verified.
`service/docker-compose.prod.yml:114` publishes only the query UI on explicit
127.0.0.1. Collector ports 4317/4318 and health port 13133 have no host mappings.
Gateway and worker still export to `http://jaeger:4317`; Jaeger health runs
inside the container. Trace URLs, routes, server addresses, and thread IDs in
`src/vaultspec_a2a/telemetry/middleware.py:129` and `:199` remain diagnostic data
behind this boundary. UI port customization remains supported. Remote access
requires an authenticated TLS proxy, access controls, and resource limits.

### integration-jaeger-publication | medium | integration telemetry remains published on all host interfaces

Type: security/network boundary. Status: open follow-up, outside production fix.
`service/docker-compose.integration.yml:135` publishes OTLP and the query UI
without loopback binding. The infrastructure recipes use this file too
(`Justfile:105`). Host-started certification processes use the published OTLP
endpoint (`src/vaultspec_a2a/service_tests/harness.py:457`), so removal would
break that workflow. Follow-up: bind these host publications to loopback and
prove host export and querying in the integration certification lane.

### telemetry-full-url-credential-claim | low | query-string privacy needs a separate investigation

Type: privacy/documentation contract. Status: open investigation; credential
exfiltration is not established. The module promises that span attributes
contain no secrets, but `src/vaultspec_a2a/telemetry/middleware.py:139` records
the complete request URL, including any caller-supplied query string. This
pass does not establish a legitimate credential-bearing query workflow.
Follow-up: trace actual callers and decide on a URL attribute redaction policy
if sensitive query parameters are supported.

### compose-test-prerequisite-comment | low | regression section now states its CLI requirement

Type: documentation/test prerequisites. Status: fixed during review.
The regression section heading now distinguishes configuration checks requiring
the Compose CLI from checks requiring a running Docker daemon.

### production-remediation-review | low | focused security and compatibility checks passed

Type: implementation review. Status: PASS. A fresh read-only reviewer found
no concrete bypass or behavior regression in the candidate production changes.
Resolved SQLite and PostgreSQL configurations publish only the loopback UI,
including custom UI ports; legacy OTLP port overrides cannot restore host
publication. Docker Engine 29.8.1 and Compose v5.5.1 supplied live evidence.

Verification against the final configuration and tests:

- `uv run --no-sync --frozen python -m pytest src/vaultspec_a2a/service_tests/test_compose_profile_regression.py -m service -k 'test_prod or test_dev or test_integration or test_resolved' -q`: 15 passed, seven unrelated full-stack cases deselected.
- `uv run --no-sync --frozen python -m pytest src/vaultspec_a2a/control/tests/test_deployment_names.py -q`: seven passed.
- Locked Ruff lint/format, Ty, and basedpyright checks on the changed regression module: PASS. `git diff --check`: PASS.
- Live isolated production Jaeger project started with `up -d --no-deps --wait jaeger`. Docker inspection showed only 16686/tcp bound to 127.0.0.1, with no collector or health host publication. Jaeger was healthy.
- A real peer container connected to internal gRPC 4317, queried internal health 13133, and submitted a unique OTLP HTTP span on 4318. The host loopback UI returned that trace through its query API. This proves internal ingestion, health, and local diagnostic querying remain functional.
- Compose rejected UI port values containing `0.0.0.0:26686` or `[::]:26686`, rather than allowing host-address injection. The isolated project was removed successfully.

No full gateway/worker rebuild or unchanged live integration suite was required
for this host-publication-only change. Remote-host packet testing was not run;
the exposure result is based on actual Docker publication inventory. Deployment
assumes the default NAT bridge, not administrator-enabled direct routing or
unprotected gateway modes. Docker's port-publishing documentation describes
loopback exposure to same-segment peers before Engine 28.0.0; the service README
states the supported minimum for this boundary.

Semantic discovery returned `index_unverifiable`; server status confirmed
failed indexing. Grounding continued through focused source searches and Core
ADR listing/search. This is a discovery limitation, not a passing search result.

### remediation-commit-concurrent-work | medium | repository hooks block the scoped commit

Type: tooling/integration workflow. Status: open verification/commit blocker.
The scoped five-file commit attempt ran enabled hooks and was rejected. Whole-
repository Ty reported 15 diagnostics in concurrent untracked or temporarily
stashed work, including the POSIX-only MCP probe, authoring state-layout use,
and desktop ACL test import. Global vault gates reported an unresolved ADR
status and annotations in concurrent workspace/worker records. Scoped lint,
format, type, Markdown, and production-telemetry-boundary vault checks pass.
The hooks restored concurrent changes; no hook was bypassed and no unrelated
file was repaired. Retry the scoped commit once the other work is coherent.
The patch remains locally implemented and verified; commit completion is pending.

### remediation-commit-blocker-follow-up | low | prior validation failures repaired

Type: tooling/integration workflow. Status: resolved for the scoped production
patch. The user confirmed the hook was uninstalled and authorized fixing the
failures. Absence of the active pre-commit hook was verified; it was not
reinstalled. Concrete listener typing, context-manager types, payload inference,
formatting, and vault scaffold drift were repaired and reviewed in
`2026-10-04-acp-read-remediation-audit`. Full-tree Ruff lint/format, Ty, and
Basedpyright passed; 74 targeted tests passed. The original failure report is
retained above as history. Concurrent feature source remains in the shared
checkout for its owning commits; this pass commits only the production Jaeger
configuration, regression coverage, documentation, audit, and index.

### final-shared-checkout-verification | medium | new ACP test drift belongs to the active migration

Type: integration/verification. Status: queued under S02 of
`2026-10-04-acp-read-remediation-plan`, which is actively changing the read
contract from offset to line. After the original failures were repaired and
full-tree Ty/Basedpyright passed, the current read helper began requiring
line. Two direct calls in `src/vaultspec_a2a/providers/tests/test_acp_fs_read_limits.py:128`
and `:139` still pass offset; latest Ty reports four diagnostics there. The
migration's tests also retain old offset expectations and need their complete
contract update, not a compatibility shim. No S02 status or implementation was
changed by this review. Its existing sequential plan owns the remaining work.

The reconciling-dispatch workspace helper initially lacked an import during
concurrent editing. It is now imported once, preserving workspace authority;
review found no altered refusal path. Three real redispatch/refusal suites
passed 24 tests. Together with the 74 engine/discovery/replay tests above,
98 targeted tests passed. Latest whole-tree Ruff lint/format, vault conformance,
and annotation checks passed. Full type-check completion for the newest shared
checkout awaits the S02 test migration; earlier passing evidence is retained
as history rather than presented as certification of newer code.

Production commit d4d4084b contains exactly the five scoped Jaeger files. The
active commit hook remains absent as requested. No unrelated work was reverted
or included in that commit.

## Recommendations

Retain the production publication and internal-export regression checks.
Apply the integration follow-up under its own verified scope. Investigate URL
privacy before proposing a costly redaction or telemetry-schema decision.
## Authorized dependency and validation follow-through, 2026-10-04

The user requested committing all current changes, fixing failures, and bumping
ACP. Existing provider-binary and client-wire decisions cover this maintenance.

### acp-current-release | low | resolved: adapter and lockfile updated

Type: dependency maintenance. Status: resolved. The official npm registry latest
stable is 0.85.1. The exact @agentclientprotocol/claude-agent-acp pin and npm
lockfile were updated from 0.84.0 to 0.85.1 using pinned Node 26.8.1/npm 11.19.0.
Seven installed packages changed; npm reports zero vulnerabilities. The lock now
supplies ACP SDK 1.6.0 and Claude SDK 0.3.286. Its installed Windows executable
reports Claude Code 2.1.286. The CI helper's stale 2.1.207 expectation now matches
2.1.286, and the real helper succeeds. This is CI binary identification, without
adding any provider admission or completed-turn proof. Claude and ZAI remain
unproven in the served eligibility declaration. No real model turn is claimed.
The real adapter handshake and installed SDK callback service tests both passed
after the update: two passed, 74 deselected.

### integrated-static-drift | low | resolved: concrete gate failures repaired

Type: verification and maintenance. Status: resolved. The owning ACP migration
fixed its overlong SDK test lines and synchronous-context-manager use under
async with. Windows ACL helpers now reject non-Windows invocation before using
Windows-only ctypes attributes, restoring cross-platform typing. Removed unused
public exports for the engine layout constant and workspace helper. Removed the
obsolete discovery view parser and its three implementation-only tests after
confirming no production consumers. Shared reading/freshness and real rejection
tests remain. Corrected a subsequent real-peer formatting change. Whole-tree
Ty platform checks and Basedpyright pass with zero diagnostics; unused-symbol
and unconsumed-export gates also pass. The engine connection proof validates
that HTTPcore supplies an AsyncNetworkStream before proving it, making the
explicit pinned runtime dependency and its fail-closed contract concrete.

### core-under-concurrent-load | low | resolved: audit write retried after Git timeout

Type: verification environment. Status: recovered. The first guarded audit write
failed with Cannot verify Git protection for local settings. Core's protection
probe has a five-second Git subprocess deadline; full static analysis and tests
were running concurrently. A subsequent vault check completed. No protection
check was disabled, no dependency source modified, and no unverified write used.
Final validation results are appended after their actual completion.
### broad-verification-recovery | medium | resolved: discovered integration failures repaired

Type: testing and environment integration. Status: resolved for the surfaced
failures; the entire unit run is still in progress. A broad provider/authoring/
desktop/workspace cohort initially reported 1514 passed, 21 failed, eight
existing platform skips, 69 service deselections. Three Codex factory failures
correctly rejected ambient Codex 0.160.0 outside its completed-turn range. The
CI-pinned official 0.159.2 executable was provisioned only in temporary tooling
and rerunning those cases passed; no eligibility proof was loosened. The old
uvx command assertion was repaired by its owning probe workstream to assert the
trusted absolute executable. The MCP readiness failure passed when rerun free
of the prior heavy concurrent load. Authoring peers were updated by their owner
to the authenticated connection contract. The combined authoring/retry/MCP
regression run passed 41 tests; the four Codex/path cases passed independently.

The full unit gate exposed armed-desktop acceptance and catalog restart fixtures
placing their project beside app-home rather than in its managed workspaces
tree. Those fixtures now create app-home/workspaces/project. All eleven related
contract, deletion, streaming and restart cases pass, preserving production
workspace refusal. The new release overlay uses Compose's valid !reset tag;
two static deployment checks had a generic YAML reader that could not parse it.
Their safe loader now recognizes that null reset while retaining shutdown and
hostname assertions; all seven checks pass.

### tooling-contract-drift-followup | low | resolved: runtime shapes and storage exceptions checked

Type: verification and maintenance. Status: resolved. Strict typing failures in
new receipt validation, dynamically keyed open MCP metadata, and stdio refresh
roots were repaired with validated object types. Refresh roots remain required,
nonempty, absolute strings before constructing Path objects. Five real stdio
refresh cases pass. Discovered storage-anchor exceptions now document their
actual authorities: private producer fixtures outside repositories, engine-
owned external state, host-controlled executable search, and disposable build,
qualification, promotion and isolation-proof material. No application storage
was redirected into system temp. The gate and 37 tooling regression cases pass.
The previously passing 165 harness cases remain applicable.

The dependency advisory gate passes for 111 Node and 189 Python packages.
npm audit signatures verifies all 106 installed package signatures and fifteen
attestations after the ACP bump. The commit hook remains intentionally absent.
No deployment, registry publication, or Git push was executed by this pass.
### desktop-fixture-root-migration | medium | resolved: real desktop certification uses managed projects

Type: integration verification. Status: resolved. The full unit run finished
with 5436 passed, 21 failed, nine fixture errors, nineteen existing prerequisite
or platform skips, 289 deselections and five warnings. The fixture errors and
remaining desktop failures used the former arbitrary-working-directory contract.
The shared test bootstrap now records each explicitly armed gateway's managed
project path; desktop certification helpers request that project instead of
Path.cwd(). Projects are created under the lifecycle-derived workspaces tree,
and production admission and refusal logic are unchanged. Existing tests continue
to exercise first-demand races, reservations, cleanup, ownership, pairing,
settlement and worker adoption over real processes and sockets.

The seven affected desktop modules passed 23 cases in one run. One introduced
fixture-order regression created app-home before its fresh-home bootstrap. The
conflict case now creates project metadata inside the armed context; its rerun
passes. Together these provide passing evidence for all 24 distinct desktop
cases. Pairing independently passed both cases. The earlier eleven acceptance
and restart checks, seven deployment checks, and one export-declaration check
cover every failed or errored case from the full run after repair. The full run
is retained as failure history; it is not reported as an all-green invocation.

### duplicate-test-export | low | resolved: helper imports retain a single declaration home

Type: introduced architecture/test regression. Status: resolved. The initial
fixture repair republished desktop_workspace from the ordinary desktop catalog
module. The existing export-home guard rejected that extra owner. All callers
now import the helper from tests.gateway_boot, and the catalog module offers
only its own catalog_selection function. The unchanged guard passes. No
exemption or weakened check was added.

### new-retirement-checkpoint-style | low | resolved: private use and nesting checks repaired

Type: concurrent implementation/static verification. Status: resolved. The new
retirement coordinator used a private class method across its class boundary;
its single-journal operation is now public retire. Sequential cursor use moves
the missing-owner-table decision outside the cursor context, retaining behavior
while satisfying the existing nesting limit. Source format and import repairs
were applied using project tools; no gate threshold was increased.

Review of the integrated fixes found no security-boundary relaxation. The
original production Jaeger remedy retains loopback-only UI and internal OTLP.
The workspace, engine-connection and descriptor-open decisions remain enforced.
Open native desktop isolation, native callback reachability, sibling callback
session debt and provider proof prerequisites stay with their existing audit
owners; these fixes do not establish missing authority or fabricated live proof.

Current passing evidence: 168 tooling tests; package sdist/wheel build; six docs
tests and warning-free Sphinx build; configured Ty and strict Basedpyright;
whole-tree Ruff lint/format and unchanged nesting gate; dependency advisory and
registry-signature audits. Final lint/vault/inventory results are checked before
committing all reviewed current changes as explicitly requested.
### final-manual-gates | low | passed for the reviewed integrated candidate

Type: final verification and implementation review. Status: PASS for the
implemented fixes and repaired failures. The final python -m dev lint all
invocation exits zero, including Ruff, format, all configured Ty platforms,
strict Basedpyright, guarded-import checks, nesting, import loadability,
reachability, symbol/export consumption, deptry, TOML, workflow policy,
actionlint and shell checks. The final vault check all reports zero errors and
zero warnings after owning-verb hygiene and index updates. git diff --check
passes. Ten fresh retirement/deletion cases pass, covering compaction, old/new
role fencing and retry of incomplete deletion. The active commit hook is absent.

The user expressly authorized committing all current changes. The final
inventory contains only source, declared lockfiles, configuration, tests and
governed audit/decision/plan records. Temporary Node/Codex tooling, test runtime
state, build outputs and credentials are excluded. Existing open Steps retain
their statuses; no native desktop sandbox or missing completed-turn capability
is reported as implemented. Scope and gate evidence above distinguish the
original failed full invocation from the passing affected reruns. No additional
full run is required to repeat unchanged passing cases under the repository's
proportionate evidence-reuse rule.
### final-concurrent-journal-regularity | low | resolved: reject nonregular existing journals

Type: concurrent validation hardening. Status: resolved and reviewed. After the
84-file integration commit 3f4a8f6a, the owning retirement implementation added
an explicit is_file guard alongside its existing link and link-count checks in
the isolated shared-journal creation branch. The refusal also suppresses the
underlying FileExistsError context. This retains valid regular journal behavior
and narrows invalid objects, with no provider admission change. Focused Ruff,
format and strict Basedpyright pass; all three existing retirement tests pass.
The user-authorized all-changes commit follow-through includes this final edit.
The ACP manifest and lock are both confirmed at 0.85.1 after cede7801.
