---
tags:
  - '#research'
  - '#embedded-runtime-robustness'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:09c73b2f0583ed88f92bd2947f9ef7a910fafe2f66b9aa559c6f556aff193d0c'
related:
  - "[[2026-08-02-control-action-leases-adr]]"
  - "[[2026-08-02-provider-error-taxonomy-adr]]"
  - "[[2026-08-02-provider-capability-evidence-adr]]"
  - "[[2026-08-03-production-boundary-adr]]"
  - "[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
---

# `embedded-runtime-robustness` research: `pass one acceptance criteria`

This audit asks whether the dashboard-embedded A2A binary provides a dependable control and execution boundary under normal work, competing actions, provider degradation, and interrupted processes. Pass one freezes the criteria below before pass two measures the implementation. The user's 2026-09-05 scope is authoritative: this is a binary component of Vaultspec Dashboard. Standalone installation, UI design, and redesign of the consumer are outside scope.

## Findings

### The acceptance unit is a complete observable scenario

Audit baseline: source commit `9438cf0bc1465a13892cb7fad197c44bd72c0360`, clean tracked worktree at orientation, Windows host, 2026-09-05. Capture the measured artifact hash, resolved dependency versions, provider executable/version, execution mode, model, operating system, configuration limits, and prerequisite availability separately in pass two. Source tests never certify an unidentified binary. Historical proof is evidence to rerun, not current availability.

Classify each criterion PASS, FAIL, PARTIAL, BLOCKED, or NOT MEASURED. PASS requires all applicable scenario assertions at the specified evidence boundary. PARTIAL means some assertions have evidence but the full criterion does not. BLOCKED names an unavailable prerequisite; NOT MEASURED names a scenario not run. Neither is a pass. Unsupported optional provider features may pass truthful refusal only; this does not prove positive capability. Record severity and type separately: correctness, concurrency, durability, contract, security, performance, observability, or evidence gap. Critical means demonstrated data loss, isolation breach, or equivalent severe safety defect; high means core execution/recovery/contract failure; medium means bounded degradation or missing certification; low means minor diagnostics/documentation. A finding's severity is distinct from its confidence.

Acceptance requires no unresolved critical/high defects and every applicable criterion passed. Report passed/applicable and measured/applicable counts separately; never average correctness away using test counts. An unknown denominator prevents a readiness percentage. Preserve observed failures even when other checks pass.

### Contracts and proposed audit targets have different authority

Existing accepted grounding includes durable leased actions, exact-lane capability proof, provider condition classification, workspace binding, and dashboard ownership. The August served-capability state-truthfulness record is proposed; its obligations are useful audit targets, not falsely reported as accepted decisions. Earlier bundled-runtime records disagree on capsule distribution; the user's current binary instruction controls this audit. Verify the actual consumer release contract before certifying compatibility.

The numeric targets below are proposed audit acceptance targets, not previously agreed service-level commitments. Existing tighter contractual bounds prevail. Record the configured bound B before running a test; do not tune it after seeing results. A request acknowledgement is not graph application, and local exactly-once dispatch is not exactly-once external tool effects. Where a non-idempotent effect has uncertain delivery, honest reconciliation is acceptable; blind replay is not.

### The scenario matrix freezes coverage and pass conditions

Evidence boundaries: S = source/schema inspection; L = real local production services, database/filesystem or subprocess; P = exact external provider completing work through production transport; D = dashboard plus actual packaged binary. Source-only evidence can establish a concrete missing path but cannot establish end-to-end success.

| ID | Condition and scenario | Measurable pass condition | Required boundary |
| --- | --- | --- | --- |
| A01 | Enumerate dashboard-facing routes, methods, schemas, auth, errors, and version handshake | Every consumer-required operation maps to an implemented verb and bounded request/response; unknown fields/versions/IDs receive documented handling; zero silent incompatible acceptance | S+D |
| A02 | Create, read, history, archive, delete in every lifecycle state | All legal transitions succeed; every illegal transition refuses without mutation; deletion covers owned journal/checkpoint/event references or reports recoverable cleanup; repeat requests follow declared semantics | L+D |
| A03 | Start/prepare/commit/release with duplicate and competing bodies | At 20 simultaneous callers, one durable run and one dispatch identity per accepted intention; same-body replay stable, changed-body conflict; expired/released reservation cannot start work | L |
| A04 | Authentication, IPC provenance, and workspace isolation | Missing/wrong bearer and wrong worker generation refuse; zero cross-workspace reads/writes; real project MCP configuration survives success, refusal, cancellation, and crash cleanup | L+D |
| A05 | Provider inventory and admission | Every configured provider/mode is listed as selectable, blocked, or unsupported with reason; every external selectable lane has exact-mode completed-turn proof; absent credentials do not imply upstream non-support | S+L+P |
| A06 | Capability and model selection truth | Catalog, preset claims, launch gate, and actual execution agree for each lane/model/capability; stale selection refuses or explicitly revalidates; no proof transfer across mode or sibling capability | L+P |
| A07 | Successful real work | Per admitted external lane, 3 consecutive turns reproduce a fresh workspace-only marker; multi-turn continuation retains identity; each advertised required capability has its own completed-work proof | P+D |
| A08 | Message eligibility and durable acceptance | Messages submitted during running, submitted, input-required, cancelling, and terminal states produce specified queue/refusal outcomes; every acknowledged message has durable identity and recoverable payload before delivery | L+D |
| A09 | Message order, deduplication, editing/removal if offered | 100 distinct messages plus 20 identical retries produce no silent loss or duplicate graph application; ordering follows declared policy; conflicting bodies and cancelled queued items cannot silently replace accepted work | L |
| A10 | Queue capacity and backpressure | Fill declared capacity Q and submit Q+1: bounded refusal or documented eviction with disclosure; no accepted item disappears; one overloaded run does not block another; report max backlog and drain time | L |
| A11 | Typed clarification | Real producer drives interrupt → status disclosure → typed response → checkpoint resume; wrong/stale request, invalid option, incomplete answer, duplicate answer, and decline tested; zero follow-up-message bypasses | L+P+D |
| A12 | Tool permission and approval | Allow/deny/always policy only affects matching live request and authorized scope; terminal cleanup leaves no actionable stale permissions; concurrent opposing decisions yield one winner and typed conflict | L+P |
| A13 | Cancel and interrupt races | Cancel before dispatch, during output/tool work, while waiting, and concurrently with completion; acknowledgement distinguished from cessation; one terminal result and no later unauthorized effect; repeat cancel stable | L+P+D |
| A14 | Durable action recovery | Kill gateway/worker before send, after send before ACK, and after apply before receipt; 10 repeats per boundary yield no lost accepted action, duplicate graph application, or permanent active slot; uncertain external effects exposed | L |
| A15 | Native commands and control discovery | Advertised built-in commands execute through intended provider control path; unknown/unsupported commands explicitly refuse; test ordinary command, command arguments, command while busy, and compact command separately; ACP slash commands may use prompt content, but observing the actual command effect is required; echoing text is not proof | L+P+D |
| A16 | Context accounting and limits | Observe fresh turn, follow-up, tool result, and resumed run at 80%, 95%, and above declared context limit; units/source/freshness known or explicitly unknown; budget includes relevant messages, tools, system input, and reserved output; no false precision | L+P |
| A17 | Compaction correctness | On every lane claiming compaction, force real compaction and verify completion/failure visibility plus preservation of pinned instructions, workspace identity, pending actions, tool-result associations, and 10 seeded required facts; unsupported lanes disclose refusal/unknown | P+D |
| A18 | Compaction races and recovery | Queue message, request cancel, encounter pending permission, and terminate process at compaction boundaries; repeat each 10 times; no message duplication, orphaned interrupt, false completion, or silent context replacement | L+P |
| A19 | Provider condition fidelity | Exercise unreachable, DNS/TLS/connect failure, timeout, overload, authentication, throttling, quota/credit/window exhaustion, and unknown errors where representable; typed condition survives cause chain, persistence, reload, and terminal status; coarser mapping disclosed | L+P |
| A20 | Retry, circuit breaking, and failover | Retry only allowed conditions; respect supplied retry delay within configured bound; attempts and elapsed time bounded; permanent auth/policy failures do not loop; fallback only to eligible permitted lanes and disclosed selection; no replay of uncertain effects | L+P |
| A21 | Connectivity and readiness | Separately fail provider, worker, gateway stream, database, and engine discovery; status names affected dependency without claiming observations it did not make; local degradation visible within 5 seconds after detection and recovery visible after a successful probe | L+D |
| A22 | Authoritative snapshots and stream recovery | Disconnect stream, overflow subscriber queue, reconnect with stale cursor, and reload client; authoritative status retains terminal outcome, pending actions, and degradation; gaps explicitly signalled; no requirement that droppable progress frames be exhaustive | L+D |
| A23 | State consistency and terminal writers | Every transitional state has an owner and reconciliation path; every terminal run has no unjustified pending work; failure reason/condition, repair/readiness, transcript availability, artifacts and outcome do not contradict each other | S+L |
| A24 | Watchdog and liveness | Silent-but-valid long tool work does not fail before its configured run budget; actual stall resolves by derived deadline B plus one polling interval; status remains responsive and names the observed signal | L+P |
| A25 | Persistence under crash and contention | Kill during checkpoint/journal/event updates, exercise SQLite locking and disk-full/read-only refusal on disposable stores; zero false durable ACKs or silent corruption; startup classifies partial state and recovery preserves workspace pin | L |
| A26 | Drain, shutdown, and process ownership | Close admission before drain; complete or explicitly cancel admitted work by configured B; no orphan owned child process or foreign process termination; dashboard can restart and identify the replacement binary/worker | L+D |
| A27 | Binary and upgrade integration | Run actual release binary from fresh directory without source Python/PATH assumptions; worker, built-in module dispatch, MCP and migrations function; dashboard-owned snapshot/rollback and schema refusal verified against consumer contract | D |
| A28 | Bounded resources and sustained work | At configured concurrency C and 2C submitted load for 30 minutes, bounded queues/processes/connections and disclosed overload; after quiescence, owned child count returns to baseline and RSS growth stays within max(10% baseline, 50 MiB) | L+D |
| A29 | Local control responsiveness | On named host/load, at least 100 samples per status/message/cancel ACK operation: p95 ≤ 1 second, p99 ≤ 3 seconds; provider latency excluded; slow dependency cannot make unrelated control requests unbounded | L+D |
| A30 | Diagnostics and confidentiality | Every rejected/failed/uncertain action has stable run/action identity, typed safe reason and next-action distinction; synthetic secret canaries never appear in served errors, event payloads, or retained test logs; UTF-8 bounds tested | L+D |
| A31 | Agent messaging and tool/background task lifecycle | Addressed messages route only to intended agent/run; unknown/stopped recipient refuses; task status tracks accepted/running/completed/failed/cancelled truth; interrupted subagent/background work reconciles; each claimed provider capability proven separately | L+P |
| A33 | Protocol negotiation | Initialize before sessions; incompatible versions and absent optional capabilities cannot silently authorize methods/content; test advertised capability changes against pinned schema | L+P |
| A34 | Provider stop outcomes | Distinguish refusal, output/context/request-budget exhaustion, cancellation, failure, and completed work where supplied; partial output or HTTP 200 followed by stream failure cannot imply success | L+P |
| A32 | Audit reproducibility and regression coverage | Every result names criterion, scenario, exact command/test, observed count/timing, commit/artifact, evidence boundary and exclusions; no skip/mock/handshake counted as real-provider success; every finding entered in rolling audit queue | S+L |

### Sampling and limits prevent accidental certification

The 3-turn smoke proves basic operation only, not a reliability rate. The 10-repeat race drills are defect detection, not a statistical concurrency guarantee. For a claimed failure probability below 1% with approximately 95% one-sided confidence, require at least 299 independent representative trials with zero failures, separately for each claimed population; independence must be justified. Do not pool unrelated providers or scenarios.

Do not deliberately exhaust real paid quotas, revoke shared credentials, alter a user's active project, or kill shared processes. Run failure drills in disposable audit-owned services/stores and use legitimate isolated fault controls. An unavailable safe real-provider condition is BLOCKED, never substituted with a fabricated provider response. Existing synthetic tests may support mapping/contract assertions and must be labelled as such.

Pass two must include a provider-by-mode applicability inventory and a criterion-by-result ledger. Lack of a complete live dashboard stack, packaged build, credentials, or fault controls limits certification explicitly. Test collection is inventory; a zero-test or all-skipped run is no measurement of behavior.

### Official protocol sources constrain optional behavior

ACP v1 initialization requires negotiation before session use; slash commands can be advertised dynamically and submitted as prompt content. Judge their actual effect rather than imposing a separate transport. The session-compaction RFD is labelled Draft on 2026-09-05, so its event names are not a universal released-protocol requirement. LangGraph resumes can re-execute pre-interrupt code; recovery evidence must count side effects. These sources establish protocol expectations, never local completed-work proof. The audit targets above retain a 1-second/3-second local responsiveness envelope rather than the researcher's stricter 0.5-second/2-second alternative; neither is an adopted product SLO.

## Sources

- User scope, 2026-09-05; `docs/architecture.rst`; `scripts/build_binary.py:1`.
- Related accepted records: control-action leases, provider-error taxonomy, provider-capability evidence, production boundary, dashboard subordination. The related served state-truthfulness record is proposed.
- `.codex/rules/clarifications-are-typed-interrupts.md`; `.codex/rules/no-unproven-providers-in-served-profiles.md`.
- `src/vaultspec_a2a/api/routes/gateway.py`; `src/vaultspec_a2a/thread/enums.py`; `src/vaultspec_a2a/domain_config.py`: discovery grounding for route, state, and configured-bound inventory, not pass-two proof.
- Numeric targets in this document are audit proposals. The zero-failure sample calculation is `ceil(log(0.05) / log(0.99)) = 299`.

- https://agentclientprotocol.com/protocol/v1/initialization
- https://agentclientprotocol.com/protocol/v1/prompt-turn
- https://agentclientprotocol.com/protocol/v1/slash-commands
- https://agentclientprotocol.com/rfds/session-compaction (Draft; inspected 2026-09-05)
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://platform.claude.com/docs/en/api/errors
