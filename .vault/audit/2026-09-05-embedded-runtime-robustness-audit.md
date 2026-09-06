---
tags:
  - '#audit'
  - '#embedded-runtime-robustness'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:02e1d033fa388814804ad5ea6e40210cb6515c6975d05fedd06d8ea0b2ac7461'
related:
  - "[[2026-09-05-embedded-runtime-robustness-research]]"
  - "[[2026-08-02-control-action-leases-implementation-review-audit]]"
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
  - "[[2026-08-02-provider-capability-evidence-plan]]"
  - "[[2026-08-05-served-capability-contract-gateway-contract-audit]]"
  - '[[2026-09-05-embedded-runtime-remediation-plan]]'
---
# `embedded-runtime-robustness` audit: `pass two implementation measurements`

## Scope

**REVISION REQUIRED.** The Dashboard binary component does not meet the frozen pass-one robustness criteria. The audit records 28 open findings (16 high, 11 medium, one low), including current Dashboard lifecycle/discovery contract drift, lost or stranded state transitions, cancellation failures, incomplete context budgeting, broken compaction associations, ACP outcome loss and untyped storage contention. A fresh source-built binary completes deterministic orchestration; nine source-process gateway acceptance tests also pass. External provider work and complete Dashboard release integration are not certified.

Baseline: `9438cf0bc1465a13892cb7fad197c44bd72c0360`, source version 0.3.0, clean tracked worktree before this audit, Windows/Python 3.13.11, 2026-09-05. Installed versions match `uv.lock` for Core 0.1.73, LangGraph 1.2.11, HTTPX 0.28.1, pytest 9.1.1, PyInstaller 6.22.2, and Uvicorn 0.52.4. Only audit documents are intentionally changed. Findings are revision requests for a subsequent implementation pass; this audit changes no runtime code.

Pass one was frozen before measurement. Its 34 criteria are normative for this audit; numeric budgets are proposals, not adopted product SLOs. Accepted ADR obligations and proposed hardening targets retain their distinct authority. Source review covered both provider adapters and the standard graph/control paths, with independent reviewers for provider/context, messaging/recovery, and binary lifecycle. RAG search refused a client 0.4.23/service 0.4.21 mismatch; discovery used Core and narrow source inspection without restarting shared infrastructure.

Unless a locator starts with `scripts/`, `.github/`, `tmp/`, `dist/`, or another explicit repository root, abbreviated source locators such as `api/app.py` resolve under `src/vaultspec_a2a/`. Uvicorn locators refer to the installed locked package.

Evidence levels: S = inspected source/schema; L = actual local production functions, SQLite, LangGraph, processes or sockets; P = external provider work; D = dashboard with packaged binary. Synthetic inputs to real production functions are labelled L seam evidence and never promoted to P. No shared process was killed, paid quota exhausted, credentials revoked, or user workspace used as a fault target.

### Measurement ledger

- M01: `uv run --no-sync pytest src/vaultspec_a2a/acceptance/tests/test_dashboard_contract.py src/vaultspec_a2a/acceptance/tests/test_dashboard_deletion.py src/vaultspec_a2a/acceptance/tests/test_dashboard_stream.py -q --tb=short --no-showlocals -o log_cli=false --junitxml=tmp/embedded-runtime-audit-acceptance.xml`. **9 passed in 111.08 seconds**, exit 0. Real source gateway/worker/SQLite processes; provider-independent admission, status, auth, cancellation routing, deletion and reconnect cases. Does not certify external providers or a release binary. Raw local log: `tmp/embedded-runtime-audit-acceptance.log`.
- M02: Broad regression run covers `control/tests`, `thread/tests`, `database/tests`, `streaming/tests`, `api/tests`, `worker/tests`, `context/tests`, `providers/tests`, and `desktop/tests`, under `src/vaultspec_a2a/`, with `uv run --no-sync pytest` and the same flags as M01. Report destination `tmp/embedded-runtime-audit-tests.xml`, local log `tmp/embedded-runtime-audit-tests.log`. Exact command: `uv run --no-sync pytest src/vaultspec_a2a/control/tests src/vaultspec_a2a/thread/tests src/vaultspec_a2a/database/tests src/vaultspec_a2a/streaming/tests src/vaultspec_a2a/api/tests src/vaultspec_a2a/worker/tests src/vaultspec_a2a/context/tests src/vaultspec_a2a/providers/tests src/vaultspec_a2a/desktop/tests -q --tb=short --no-showlocals -o log_cli=false --junitxml=tmp/embedded-runtime-audit-tests.xml`. **3039 passed, 11 failed, 46 deselected, zero skipped, one warning; exit 1; 1343.40 seconds wall summary**. JUnit records 3050 executed cases and 1315.105 seconds of suite time; these are different timing scopes. ER18–ER22 classify every failure group and warning. Default `not service` selection and repository prerequisite withholding remain active; none of the 46 deselections is a pass.
- M03: Real EventAggregator + compiled LangGraph + disposable file-backed AsyncSqliteSaver. One trial: `checkpoint_exists_at_application_receipt=false`, then normal outcome `completed` with final marker `accepted-message`. No crash injected; the crash-loss consequence in ER01 is derived from the inspected settlement/recovery path.
- M04: Real repository functions over disposable SQLite, two retained ORM sessions. One controlled interleaving: first commits `completed`, second commits stale `cancelling`; both succeed and final state is `cancelling`.
- M05: Production context functions with bounded synthetic input. Limit 120000, mounted text length 600000, history `task`: `should_compact=false`, final assembled estimate 150002. Empty-content tool call with 1000-character argument estimates 0 tokens.
- M06: Production compactor at budget 150 removes seeded fact `REQUIRED_FACT_1=amber`; a 400-character AI tool-call message followed by a 360-character ToolMessage leaves types `human,human,tool`, zero call IDs and result ID `t1`. Prompt context loss, not demonstrated deletion of durable history.
- M07: Production ACP response handler receives five terminal stop reasons. All five futures resolve; only `end_turn` sets `prompt_done`. `max_tokens`, `max_turn_requests`, `refusal`, and `cancelled` leave it false and emit no queued completion.
- M08: Production `AcpSessionError(code=-32000)` yields `unknown`; production mapper for that same code yields `unauthenticated`.
- M09: Disposable child calls actual `admin._stop_this_process` inside try/finally. Windows exit code 2, stdout only `entered\n`, no `finally-ran`. Demonstrates skipped Python cleanup, not independently counted orphan descendants.
- M10: Existing local binary `dist/binary/vaultspec-a2a/vaultspec-a2a.exe`, SHA256 `A17FE358C3FC56DDA780BE79085887971A13948103A9E3C245868AF3C5365E34`, reports **0.2.0**, unlike source 0.3.0. Version/help exit 0; `run-module os` refuses with exit 1 and names the allowlist. This artifact is not evidence for current-source runtime behavior.
- M11: Production provider registration/admission inventory below. No discovery prompt or model completion. Production gateway resolver reported unavailable; explicit live-provider selector incomplete. Thus no P or D completed-work proof was obtained.
- M12: Fresh source binary build **passed**, including version/help and disallowed-module smoke. Invoked with `uv run --no-sync python scripts/build_binary.py --dist tmp/embedded-runtime-audit-binary`; local log `tmp/embedded-runtime-audit-build.log`. Fresh executable SHA256 `EDE9B961F7D52952FD1522DB23295AE810490D01C029ADEF869C37EB6354E688`, version **0.3.0**. Positive dispatch `run-module vaultspec_core -- --help` reached the bundled Core CLI, exit 0. The separator is required to pass help through the outer Click command.
- M14: Fresh binary migrated disposable stores successfully (primary head `0016`, checkpoint schema `1.0.0`) and served `/health` plus authenticated `/v1/service`, both HTTP 200. Ran `serve` from an external temporary working directory with PATH restricted to Windows System32 and PYTHONHOME/PYTHONPATH/VIRTUAL_ENV/UV_PROJECT_ENVIRONMENT removed. Service reported version 0.3.0, database/checkpoint ready. Worker was `pending`, connected=false, ready=false: **no frozen worker execution proof**. The probe used production credential/port-allocation/reaping helpers and reaped its own tree. Temporary script `tmp/embedded_runtime_binary_probe.py`; outputs `tmp/embedded-runtime-audit-binary-probe.log` and `tmp/embedded-runtime-audit-binary-probe-worker.log`. This is a direct binary L probe, not a dashboard D test.
- M15: Focused recheck: `uv run --no-sync pytest src/vaultspec_a2a/providers/tests/test_model_stack_warmup.py::test_compiling_a_graph_keeps_the_loop_serving src/vaultspec_a2a/api/tests/test_provider_catalog_route.py::test_authenticated_route_serves_all_registered_lanes_in_order -q --tb=short --no-showlocals -o log_cli=false --junitxml=tmp/embedded-runtime-audit-recheck.xml`. **1 passed, 1 failed in 65.98 seconds**, exit 1. Compile responsiveness passed without changes; catalog's unavailable-versus-available assertion failed again. ER21 remains an intermittent measured failure pending cause/representative-load analysis. Raw local log: `tmp/embedded-runtime-audit-recheck.log`.
- M13: `uv run --no-sync vaultspec-core vault check all --feature embedded-runtime-robustness --json --limit 20` completed **19 checks, zero diagnostics**. Independent document review corrected the criterion count and narrowed A12's verdict; scaffold residue was removed through Core set-body. No runtime source changed, no unrelated documents were repaired, and no implementation plan was marked complete.

Raw XML/log/build outputs are local temporary evidence and are not committed. The measurements, commands, identities and reproductions in this record are the durable audit trail. Source test counts do not become full-criterion passes.

### Regression inventory

| Source test area | Passed | Failed |
| --- | ---: | ---: |
| control | 419 | 8 |
| thread | 226 | 0 |
| database | 329 | 0 |
| streaming | 203 | 0 |
| api | 526 | 1 |
| worker | 121 | 0 |
| context | 167 | 0 |
| providers | 919 | 2 |
| desktop | 129 | 0 |

The separate acceptance selection adds 9 passes, giving **3048 passing executions across the two original commands**, not 3048 independently certified behaviors. There are no skipped executed tests; 46 cases were deselected. The 11 failed executions belong to four root-cause/evidence groups ER18–ER21. The sole warning is ER22. M02 was not a full-repository run and excluded service certification.

### Provider-by-mode inventory

This is current registration and static exact-mode admission, not a live catalog availability claim. Observed using `ProviderFactory().catalog_registrations(Path.cwd(), serve_in_process_lanes=False)` and `is_catalog_lane_admissible`.

| Provider / execution mode | Exact-mode turn admission | Current real-work measurement |
| --- | --- | --- |
| antigravity / antigravity-cli | denied, no exact-mode proof | BLOCKED |
| claude / claude-agent-acp:node | denied, no exact-mode proof | BLOCKED |
| codex / codex-app-server | admitted by historical declaration | BLOCKED |
| gemini / gemini-cli-acp | denied, no exact-mode proof | BLOCKED |
| kimi / kimi-code-acp | denied, no exact-mode proof | BLOCKED |
| openai / openai-api | denied, no exact-mode proof | BLOCKED |
| zai / zai-claude-agent-acp:node | denied, no exact-mode proof | BLOCKED |
| zhipu / zhipu-openai-compatible-api | denied, no exact-mode proof | BLOCKED |

Legacy provider-level proof declares Claude, Codex and Z.ai. That is a different authority from catalog execution-mode admission and cannot be pooled into three currently certified lanes. Denial of unproven lanes is correct fail-closed behavior, not an availability defect. Deterministic and mock in-process lanes are explicitly separate and supply no external proof. No conclusion about present credential validity follows from this inventory.

### Criterion results

FAIL means at least one specified requirement is contradicted; it does not imply every scenario in that row was run. PARTIAL records actual supporting evidence with missing coverage. Every row is assessed, but assessment is not full runtime measurement.

| ID | Result | Evidence and missing measurement |
| --- | --- | --- |
| A01 | FAIL | M18 current consumer route/header and discovery drift, ER23/ER24; pinned release not tested |
| A02 | PARTIAL | M01 real deletion/status behavior; exhaustive state/CRUD combinations and D unmeasured |
| A03 | PARTIAL | M01 prepare/start; inspected reservation/singleflight/replay; M16 twenty concurrent identical requests agree; durable execution count and crash matrix unmeasured |
| A04 | PARTIAL | M01 auth negatives and source attach/IPC controls; all workspace/process fault-isolation cases unmeasured |
| A05 | PARTIAL | M11 eight-mode deny-default inventory; exact live proofs not rerun |
| A06 | FAIL | ER13 capability matrix has no production integration |
| A07 | BLOCKED | No complete live lane selector/running gateway/dashboard certification; zero real provider turns |
| A08 | FAIL | ER01 premature receipt; ER03 busy follow-up disposition |
| A09 | FAIL | ER03 no steady-state delivery queue; 100-message ordering drill not run |
| A10 | FAIL | ER03 accepted backlog has no declared bounded delivery queue/drain; Q+1 drill unmeasured |
| A11 | PARTIAL | Typed checkpoint-bound clarification/resume code; full injected P+D loop unmeasured |
| A12 | PARTIAL | Request/option/lease controls exist; complete scope/stale/cleanup/opposing-decision matrix and P unmeasured. ER01 affects permission durability, but alone does not disprove these narrower A12 assertions |
| A13 | FAIL | ER02 stale writer, ER04 capacity refusal, ER05 delayed cancellation |
| A14 | FAIL | ER01/ER03 recovery boundary gaps; ten-repeat kill drills not run |
| A15 | FAIL | ER14 native command advertisements not integrated into served discovery/control |
| A16 | FAIL | M05 / ER08 full prompt exceeds configured limit after budget decision |
| A17 | FAIL | M06 / ER07 required facts and tool associations lost in prompt compaction; native P behavior unproven |
| A18 | NOT MEASURED | No native compaction queue/cancel/crash drill |
| A19 | FAIL | M08 / ER12 known setup condition discarded; full P fault matrix unmeasured |
| A20 | PARTIAL | ER26/ER27 are related breaker findings; frozen retry/delay/failover assertions are not fully measured or directly disproved |
| A21 | PARTIAL | M01 status behavior and source readiness ownership; five-boundary failure/recovery timing unmeasured |
| A22 | FAIL | M01 terminal reconnect works; ER06 attachment race and missing overflow-gap signal remain |
| A23 | FAIL | M03/M04 and ER01/ER02 violate settlement and terminal consistency |
| A24 | PARTIAL | Derived ingest watchdog and adapter idle guards inspected; long-tool timing proof absent |
| A25 | FAIL | M03/M04 violate durability/concurrency assertions; disk-full/read-only/crash matrix unmeasured |
| A26 | FAIL | M09 / ER15 Windows cleanup bypass; ER16 unbounded graceful stream wait; M20/ER25 task-group cancellation settlement failure |
| A27 | FAIL | M16 frozen deterministic worker completes; ER23/ER24 current Dashboard contract drift; full D/upgrade unmeasured |
| A28 | PARTIAL | M19 completed 1914.98s burst probe: 910 starts, nine accepted runs exceeded settlement deadline; sampled RSS +18.39MiB; quiescence and separate sustained C proof absent |
| A29 | PARTIAL | M16 100 warm terminal-status GETs: p95 15.41ms, p99 16.84ms; other controls and loaded/D distributions unmeasured |
| A30 | PARTIAL | Auth/refusal controls and byte bounds inspected; M21 literal credentials absent from two log snapshots; full secret-canary/tracing matrix unmeasured |
| A31 | FAIL | ER09 target unvalidated and absent from standard graph input; background/subagent P unproven |
| A32 | PASS | Criteria, baseline, exact commands, observations, exclusions, executable reproduction appendix, independent review and classified queue recorded |
| A33 | FAIL | ER11 missing ACP response-version validation |
| A34 | FAIL | M07 / ER10 four valid stop outcomes do not settle stream |

**34/34 assessed: 19 FAIL, 12 PARTIAL, 1 BLOCKED, 1 NOT MEASURED, 1 PASS. Passed/applicable = 1/34; the sole full pass is audit reproducibility A32, not product readiness. Full-scenario measured/applicable = 1/34.** Targeted partial runtime evidence from M01 and M03–M10/M12/M14 and M16–M21 addresses 20 product criteria (A01, A02, A03, A04, A08, A13, A14, A16, A17, A19, A20, A22, A23, A25, A26, A27, A28, A29, A30, A34); with A32 this is partial-or-full targeted runtime evidence for 21/34. The remaining assessment uses source/inventory evidence or an explicit gap. This conservative count does not assign every broad regression test to an unmeasured scenario. A failing seam can disprove a criterion without completing its full fault matrix. Product criteria deliberately span boundaries beyond a basic passing test. Complete rollout certification remains withheld.

## Findings

### ER01-early-application-receipt | high | Application is acknowledged before durable graph input exists

**OPEN; durability; A08/A12/A14/A23/A25; measured local seam plus static consequence.** M03 observes no checkpoint at the application callback. `streaming/ingest.py:320` invokes it on the first raw event; `worker/executor.py:250` sends application acknowledgement; `control/event_handlers.py:633` settles message application and `:639` permission application. Recovery at `control/direct_control_recovery.py:224` selects unapplied actions. A crash between journal settlement and checkpoint persistence can therefore remove accepted input from recovery eligibility. No crash-induced loss was directly measured. **Owner:** control/worker persistence. **Close when:** application uses durable request-scoped checkpoint evidence and kill-between-receipt/write drills preserve every accepted action.

### ER02-stale-terminal-writer | high | A stale cancellation can overwrite a completed run

**OPEN; concurrency; A13/A23/A25; measured M04.** `database/thread_repository.py:469` validates cached ORM state, then writes at `:494` without conditional prior-state election. Two real sessions successfully commit completed then cancelling. `control/cancel_service.py:326` writes after a network await, providing an ordinary stale-writer trigger. **Owner:** database lifecycle/control. **Close when:** competing transitions use atomic state/version conditions, stale cancellation cannot reopen terminal work, and all competing terminal/control pairs are tested.

### ER03-busy-message-delivery | high | Accepted follow-ups can remain unapplied with no steady-state delivery owner

**OPEN; correctness/concurrency; A08/A09/A10/A14; static path.** `thread/message_policy.py:30` permits active states, `control/message_service.py:129` journals acceptance, and `worker/app.py:325` schedules before the executor acquires its active slot. `worker/executor.py:768` returns when that slot is held without queueing application or reporting rejection. Stable dispatch suppression survives that return. Direct recovery at `api/app.py:399` and `:427` runs at startup with one conditional retry, not as a continuous delivery owner. A journal is not sufficient evidence of a drained message queue. **Owner:** message service/worker recovery. **Close when:** every accepted busy-time message has ordered, bounded, restart-safe disposition and stable retries cannot strand it.

### ER04-cancel-at-capacity | high | Capacity admission can refuse the control action needed to free capacity

**OPEN; correctness; A13; static path.** `worker/app.py:312` checks `executor.at_capacity()` before selecting the dispatch action, including cancel. At the concurrent-run cap, cancellation receives 429 before it can stop work. **Owner:** worker dispatch. **Close when:** cancellation/control delivery remains available at C and overload, with one terminal result and bounded resource use.

### ER05-cancel-awaits-output | medium | Cancellation is observed only after the next graph event arrives

**OPEN; correctness/performance; A13; static path.** `streaming/ingest.py:302` awaits the next graph event before checking the cancellation flag at `:323`. Silent provider/tool work may continue for the configured stall/step allowance after an acknowledgement. **Owner:** ingest/executor cancellation. **Close when:** an independent cancellation signal can interrupt the await and provider cessation or an explicit unresolved outcome is measured separately from ACK.

### ER06-stream-attachment-gap | medium | Stream attachment can miss completion and overflow has no explicit client gap

**OPEN; contract/observability; A22; static path.** `api/thread_stream.py:220` reads status before subscriber registration at `:69`. Completion between those operations belongs to neither the captured status nor the new queue; the heartbeat loop at `:151` does not re-read authoritative state. `streaming/fanout.py:126` evicts/logs overflow without explicit client gap notification. M01 proves reconnect after already-visible terminal status, not this attachment interleaving. **Owner:** streaming/API. **Close when:** snapshot/subscription boundary reconciles completion and queue loss is disclosed under the declared stream contract.

### ER07-compaction-context-loss | high | Compaction can drop required facts and retain tool results without their calls

**OPEN; correctness; A17; measured M06.** `context/token_budget.py:108` trims individual messages and `:123` inserts a generic removal notice, not a summary of removed meaning. Production callers include `graph/nodes/worker.py:115`, `:743`, and `graph/nodes/supervisor.py:310`. The probe loses its seeded fact and retains result t1 without any associated AI tool call. This is model-prompt loss, not measured durable history deletion. **Owner:** context/graph. **Close when:** compaction preserves required state and tool-call/result groups, and exact-lane post-compaction continuation recovers seeded facts.

### ER08-incomplete-prompt-budget | high | Context admission excludes text added later and tool-call arguments

**OPEN; correctness; A16; measured M05.** `graph/nodes/worker.py:115` through `:141` checks history before adding system prompt, rules, anchoring and mounted context. `context/token_budget.py:30` counts content text but omits tool-call arguments. Probe assembled estimate 150002 exceeds configured 120000 despite a false compaction decision. The 80% trigger also calls a function that returns unchanged until above 100% at `:45` through `:70`. **Owner:** prompt assembly/context. **Close when:** complete provider-relevant input and output reserve are budgeted with declared approximation/unknown semantics, including large tool payloads and mounted context.

### ER09-message-recipient-unbound | high | The served recipient is unvalidated and absent from standard graph input

**OPEN; contract; A31; static standard path.** `api/schemas/gateway.py:775` accepts bounded arbitrary agent_id; `api/routes/gateway.py:2090` forwards it; `worker/executor.py:786` uses it for event attribution. `worker/graph_lifecycle.py:719` constructs an ordinary shared HumanMessage without recipient identity/routing. Unknown/stopped recipients are not rejected along this path. This establishes missing standard recipient binding, not every custom graph's eventual behavior. **Owner:** message contract/graph routing. **Close when:** targeted semantics are defined and verified end to end, with explicit invalid-recipient refusal and cross-agent isolation.

### ER10-acp-stop-outcomes | high | Four supplied terminal outcomes leave the ACP stream waiting

**OPEN; correctness; A34; measured M07 plus inspected wait loop.** `providers/_acp_protocol.py:165` signals completion only for end_turn; `providers/acp_chat_model.py:617` through `:650` only checks resolved response errors. max_tokens, max_turn_requests, refusal and cancelled resolve their futures but do not terminate chunk waiting. With an open subprocess they can become idle failures; disabled timeout allows continued waiting. **Owner:** ACP transport. **Close when:** every negotiated stop reason settles promptly and preserves the provider's actual outcome through authoritative run status.

### ER11-acp-negotiation | high | Returned ACP protocol version is not validated

**OPEN; contract; A33; source-established missing guard.** `providers/_acp_session.py:332` requests version 1; `:394` through `:405` reads capabilities/auth methods without validating the returned version before session setup. Missing, malformed or incompatible negotiated versions can proceed. **Owner:** ACP session. **Close when:** the pinned negotiation contract rejects incompatible responses and optional operations follow negotiated support. This is not a fabricated-provider live proof.

### ER12-setup-condition-loss | medium | Known session authentication conditions collapse to unknown

**OPEN; contract/observability; A19; measured M08.** `providers/_acp_session.py:390`, `:524`, and `:540` construct AcpSessionError without the available condition mapping; `providers/acp_exceptions.py:50` defaults UNKNOWN. Prompt errors alone invoke the mapper at `providers/acp_chat_model.py:194`. **Owner:** provider conditions/session setup. **Close when:** known setup, auth, model/config and initialization discriminators survive to durable run status with truthful coarse fallback for unknown wire information.

### ER13-unserved-capability-matrix | high | Capability evidence contracts have no production composition or consumer

**OPEN; contract; A06; source-established integration gap, overlaps unfinished capability-evidence plan.** `providers/provider_capabilities.py:101` and `:146` define evidence/matrix types; exact-symbol search excluding tests finds no outside production constructor or consumer. Accepted exact-capability requirements are not satisfied by those types or their contract tests. **Owner:** provider catalog/capability-evidence campaign. **Close when:** each external mode has complete independently evidenced records consumed by served claims and required-role admission; no proof transfers across sibling capability/mode.

### ER14-command-integration | medium | Native command advertisements do not reach a served control contract

**OPEN; contract; A15; source-established component gap.** `providers/_acp_protocol.py:296` stores availableCommands in session-local agent_modes. No production reader or gateway command-discovery/control integration was found, nor native compaction completion/status integration. ACP commands can legitimately travel as prompt content; the missing proof is discovery, disposition and actual effect, not a mandatory separate transport. **Owner:** provider control/gateway. **Close when:** every claimed command is discoverable and its busy/unsupported/success/failure outcomes are measurable per lane. Optional provider non-support must remain distinct from this component gap.

### ER15-windows-shutdown | high | Administrative shutdown terminates Windows Python before cleanup

**OPEN; correctness/portability; A26; measured M09.** `api/routes/admin.py:22` uses os.kill with SIGINT. Windows uses TerminateProcess for this value, confirmed by the production-function sentinel probe and Python 3.13 documentation. Lifespan work at `api/app.py:590`, `:610`, and `:627` is bypassed. Existing drain test discards the deferred callback at `api/tests/test_gateway_drain.py:118`, so it does not certify this path. **Owner:** API lifecycle. **Close when:** actual Windows HTTP shutdown performs bounded drain and cleanup with an owned-child census. Source: https://docs.python.org/3.13/library/os.html#os.kill

### ER16-unbounded-graceful-stream-wait | high | An open stream can block entry into the application's bounded drain

**OPEN; lifecycle/boundedness; A26; static dependency path, no socket drill.** `api/app.py:651` starts Uvicorn without timeout_graceful_shutdown. Locked Uvicorn 0.52.4 defaults it to None and waits for connection tasks before lifespan shutdown (`uvicorn/config.py:231`, `uvicorn/server.py:289`). `api/thread_stream.py:151` heartbeats until terminal, so an indefinitely parked run can delay entry to the five-second application drain. This concerns the graceful-signal path; ER15 dominates current Windows admin shutdown. **Owner:** server lifecycle/streaming. **Close when:** paused-run SSE cannot make shutdown exceed the declared total bound, tested over a real socket.

### ER17-frozen-execution-evidence | medium | Release smoke does not certify the embedded execution lifecycle

**OPEN; evidence gap; A27.** `.github/workflows/release.yml:266` calls `scripts/prove_artifact_lifecycle.sh`, which runs setup, standalone start, health and stop; `:87` explicitly notes no worker has spawned. `scripts/build_binary.py:199` smoke checks version, help and negative module dispatch. These are useful gates but do not prove dashboard-armed launch, frozen worker execution, positive MCP/module dispatch, migrations across supported versions or source/PATH independence. **Owner:** packaging/dashboard integration. **Close when:** identified current binary completes those execution/recovery scenarios under its actual consumer; do not reinterpret smoke success as that evidence.

### ER18-optional-server-test-profile | medium | Eight PostgreSQL checks cannot import the optional server driver

**OPEN; evidence/environment; M02; outside the embedded SQLite runtime claim.** Eight cases in `control/tests/test_sync_url_derivation.py` fail at `:54` while SQLAlchemy imports psycopg. The URL assertions passed before engine construction; no PostgreSQL connection was attempted. `pyproject.toml` declares psycopg in optional `server`, and the frozen desktop spec deliberately excludes it. This is an incomplete server-test prerequisite/profile, not evidence that desktop SQLite or URL derivation is broken. **Owner:** test/profile maintenance. **Close when:** server checks run under the locked server dependency profile and its requirement is explicit; retain this run's eight failures in the evidence history.

**Resolution (W01.P02.S04 correction, 2026-09-05): RESOLVED; formal re-review pending.** The project names a supported task-environment flow for the `server` optional extra: set `UV_PROJECT_ENVIRONMENT` to a bounded task path, run exact locked sync, then run tests with `uv run --no-sync`. Separate `server-env`, `freeze-env`, and `build-env` paths preserve the shared `.venv`. The server profile passed all 15 URL/configuration/SQLAlchemy engine-construction checks. The freeze-only record proves all three PostgreSQL distributions and imports absent (digest `F4EAE3C1...`); the server-equipped build record proves the drivers present before PyInstaller (digest `C3378273...`), while the post-build scan proves zero blocked modules among 5,720 PYZ names and zero blocked paths among 2,746 artifact files (digest `A0D70509...`). Exact commands, full canonical JSON, match grammar, roots, hashes, and the source-boundary digest are retained in the corrected S04 Step Record. The original eight M02 failures remain historical evidence of using the wrong dependency posture.

### ER19-catalog-test-stale-assumption | medium | A route test hard-codes provider unavailability despite real enumeration

**OPEN; test contract drift; M02.** `api/tests/test_provider_catalog_route.py:150` expects the OpenAI catalog to be unavailable; the actual route returns available after its preceding HTTP/status/order/schema assertions pass. The production OpenAI registration in `providers/factory.py:1180` calls real prompt-free discovery, and `providers/openai_catalog.py` owns GET/models enumeration. An available catalog is not execution admission or completed-work proof. **Owner:** provider catalog tests. **Close when:** the test distinguishes declared catalog behavior from environment-dependent availability without weakening admission assertions or hiding a real discovery failure.
**Resolution evidence (provider-model-catalog P01.S11, 2026-09-05): ER19 CORRECTED; owning step pending.** The route test now parses the v1 response, keys records by provider identity, and validates OpenAI and Z.AI against their observed available or unavailable state. Available results require entries, revision, expiry, and authenticated evidence; unavailable results require no entries and a bounded reason. Health catalog state must equal the catalog state in either case. Exact-mode admission remains independently `not_admitted` and `selectable=false`, so successful prompt-free discovery is not promoted to completed-turn evidence. The former failing test and assembled 49-test catalog behavior set pass on the credentialed host. Formal review `16066b83983a90a6a7dc067f98510e3fc5c040fc` reopened P01.S11 because P01.S10 remains open and the battery does not yet drive a real persisted legacy assignment through fresh gateway/worker startup redispatch. Those blockers prevent S11 and remediation S05 closure without invalidating the ER19 route correction.

### ER20-rag-version-mismatch | medium | RESOLVED pending W01.P02.S06 formal review

**HISTORICAL FINDING; evidence/environment; A04/A32; M02.** `providers/tests/test_harness_mcp_pinning.py:408` invokes the real server; its failure is `service_version_mismatch`: client 0.4.23 versus service 0.4.21, raised by the RAG service-port check. The expected pinned workspace never appears in the diagnosis. This proves a dependency mismatch, not that the server ignored the workspace pin. It is the same mismatch that blocked semantic discovery at audit orientation. **Owner:** RAG/test environment. **Close when:** the intended locked runtime/service identities agree and the real pin proof reaches and verifies its discriminator. Shared service lifecycle was left untouched.


**Resolution evidence (W01.P02.S06):** the discriminator now reads the single
locked RAG version from `uv.lock`, runs both the production stdio MCP entry point
and a real local-only service from that exact distribution, and gives the
service an owned loopback port plus isolated status, data and Qdrant-storage
roots. The service record proves the version/port match before the real tool
call. The pinned non-workspace path appeared in the refusal while the valid
launch workspace did not; the isolated case passed in 46.46 seconds and all 33
pinning tests passed in 47.93 seconds. Owned cleanup stopped only the isolated
service. Shared PID 56028, port 8766 and service token stayed unchanged. Formal
S06 review remains required.

### ER21-compile-loop-budget | medium | Graph compilation exceeded its existing loop responsiveness ceiling

**OPEN; performance; M02; separate from A29's unmeasured HTTP percentiles.** `providers/tests/test_model_stack_warmup.py:114` measures a cold production graph-compilation subprocess. Observed work 25.312691 seconds, max loop gap **0.6182457 seconds**, 1557 ticks, versus its existing **0.5-second** ceiling. This is a measured threshold failure, not proof of the test message's asserted import-causality diagnosis. M15 passed on the targeted recheck without code or threshold changes. Host contention and repeatability require separation; this is retained as an intermittent observation, not declared fixed. **Owner:** worker warmup/performance tests. **Close when:** the gap is explained and the fixed budget holds on the named representative host/load; retain both failed and successful rechecks.

### ER22-upstream-testclient-deprecation | low | Starlette's test client uses a deprecated AnyIO alias

**OPEN; upstream maintenance; M02 warning.** Locked `starlette/testclient.py:53` emits DeprecationWarning for `anyio.abc.BlockingPortal`; replacement is `anyio.from_thread.BlockingPortal`. No behavior failure was observed from this warning. **Owner:** dependency maintenance. **Close when:** a deliberately reviewed locked dependency update removes the deprecated use; do not suppress the warning as an audit fix.

### Reproduction appendix

Run each Python block from this checkout with `uv run --no-sync python -` (PowerShell: a literal single-quoted here-string piped to that command). Blocks import production behavior; temporary storage/processes belong exclusively to the probe. M03 and M04 are one trial each. M05-M08 are bounded synthetic inputs, not provider simulations or external service proof.

M03:

```python
import asyncio, json, tempfile
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from vaultspec_a2a.streaming.aggregator import EventAggregator

class State(TypedDict):
    marker: str

async def work(state):
    return state

async def main():
    with tempfile.TemporaryDirectory(prefix="a2a-audit-receipt-") as d:
        async with AsyncSqliteSaver.from_conn_string(str(Path(d) / "checkpoint.sqlite")) as saver:
            builder = StateGraph(State)
            builder.add_node("work", work)
            builder.add_edge(START, "work")
            builder.add_edge("work", END)
            graph = builder.compile(checkpointer=saver)
            config = {"configurable": {"thread_id": "audit-receipt"}}
            observations = []
            async def receipt():
                checkpoint = await saver.aget_tuple(config)
                observations.append({"checkpoint_exists_at_application_receipt": checkpoint is not None,
                                     "values": checkpoint.checkpoint["channel_values"] if checkpoint else None})
            agg = EventAggregator()
            outcome = await agg.ingest("audit-receipt", "supervisor", graph,
                                      {"marker": "accepted-message"}, config, on_graph_started=receipt)
            final = await saver.aget_tuple(config)
            print(json.dumps({"observations": observations, "outcome": outcome,
                              "final_marker": final.checkpoint["channel_values"].get("marker")}))
            await agg.shutdown()

asyncio.run(main())
```

M04:

```python
import asyncio, json, tempfile
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.database.thread_repository import create_thread, get_thread, update_thread_status

async def main():
    with tempfile.TemporaryDirectory(prefix="a2a-audit-terminal-") as d:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(Path(d) / "db.sqlite"))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            await create_thread(session, thread_id="audit-terminal", status="running")
            await session.commit()
        async with sessions() as first, sessions() as second:
            one = await get_thread(first, "audit-terminal")
            two = await get_thread(second, "audit-terminal")
            await update_thread_status(first, "audit-terminal", "completed")
            await first.commit()
            await update_thread_status(second, "audit-terminal", "cancelling")
            await second.commit()
        async with sessions() as session:
            final = await get_thread(session, "audit-terminal")
            print(json.dumps({"first_committed": "completed", "second_stale_source": "running",
                              "second_committed": final.status, "both_commits_succeeded": True}))
        await engine.dispose()

asyncio.run(main())
```

M05/M06/M08 (combines independently executed bounded inputs):

```python
import json
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from vaultspec_a2a.context.token_budget import compact_context, estimate_tokens, should_compact
from vaultspec_a2a.graph.nodes.worker import _build_worker_messages
from vaultspec_a2a.domain_config import domain_config
from vaultspec_a2a.providers.acp_exceptions import AcpSessionError
from vaultspec_a2a.providers.conditions import condition_from_acp_error

budget = domain_config.context_limit_tokens
small = {"messages": [HumanMessage(content="task")], "mounted_context": "z" * (budget * 5)}
built = _build_worker_messages(state=small, system_prompt="system", workspace_root=None)
print(json.dumps({"configured_limit": budget, "compaction_requested": should_compact(small, budget),
                  "actual_built_estimate": estimate_tokens(built)}))
call = AIMessage(content="", tool_calls=[{"id": "t1", "name": "read", "args": {"query": "x" * 1000}}])
print(json.dumps({"tool_args_estimated_tokens": estimate_tokens([call])}))
messages = [HumanMessage(content="task"),
            HumanMessage(content="REQUIRED_FACT_1=amber\n" + "x" * 1000),
            AIMessage(content="x" * 400, tool_calls=[{"id": "t1", "name": "read", "args": {}}]),
            ToolMessage(content="y" * 360, tool_call_id="t1")]
compacted = compact_context({"messages": messages}, 150)["messages"]
print(json.dumps({"types": [m.type for m in compacted],
                  "fact_preserved": any("REQUIRED_FACT_1" in str(m.content) for m in compacted),
                  "tool_calls": [t["id"] for m in compacted if isinstance(m, AIMessage) for t in m.tool_calls],
                  "tool_results": [m.tool_call_id for m in compacted if isinstance(m, ToolMessage)]}))
error = AcpSessionError("authentication required", code=-32000)
print(json.dumps({"session_error_condition": error.condition,
                  "mapping_for_same_code": condition_from_acp_error({"code": -32000})}))
```

M07:

```python
import asyncio, json, sys
from vaultspec_a2a.providers._acp_types import AcpSessionContext
from vaultspec_a2a.providers._acp_protocol import handle_client_response

async def main():
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    results = []
    for reason in ["end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"]:
        future = asyncio.get_running_loop().create_future()
        context = AcpSessionContext(process=process, stdin=process.stdin, stdout=process.stdout,
            response_futures={3: future}, chunk_queue=asyncio.Queue(),
            prompt_done=asyncio.Event(), prompt_id_ref=[3], interrupt_exc=[])
        await handle_client_response({"id": 3, "result": {"stopReason": reason}}, context)
        results.append({"stopReason": reason, "response_done": future.done(),
                        "prompt_done": context.prompt_done.is_set(), "queued_events": context.chunk_queue.qsize()})
    await process.wait()
    print(json.dumps(results))

asyncio.run(main())
```

M09 (the production stop executes only in the new child):

```python
import subprocess, sys
code = '''from vaultspec_a2a.api.routes.admin import _stop_this_process
print("entered", flush=True)
try:
    _stop_this_process()
finally:
    print("finally-ran", flush=True)
'''
result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=45)
print({"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
```

M14 (requires the M12 build; save this block as a local temporary Python file and run with `uv run --no-sync python PATH`; it writes disposable credentials/stores and starts/reaps only its own gateway tree):

```python
import json
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from vaultspec_a2a.tests.gateway_boot import (
    armed_gateway_env,
    clean_subprocess_environment,
    reap_gateway,
    seed_credentials,
    spawn_until_ready,
)

binary = (Path.cwd() / 'tmp/embedded-runtime-audit-binary/vaultspec-a2a/vaultspec-a2a.exe').resolve()
with tempfile.TemporaryDirectory(prefix='a2a-audit-frozen-') as temporary:
    root = Path(temporary)
    app_home = root / 'home'
    seed_credentials(app_home, attach='audit-disposable-attach', ownership='audit-disposable-owner')
    environment = clean_subprocess_environment()
    environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    migration = subprocess.run(
        [str(binary), 'migrate', '--app-home', str(app_home)],
        cwd=root, env=environment, capture_output=True, text=True, timeout=180,
    )
    print(json.dumps({'migration_exit': migration.returncode, 'migration_output': migration.stdout.strip()}), flush=True)
    if migration.returncode:
        print(migration.stderr[-2000:], flush=True)
        raise SystemExit(migration.returncode)
    log_path = root / 'gateway.log'
    with log_path.open('wb') as output:
        def spawn(gateway_port, worker_port):
            env = armed_gateway_env(app_home, gateway_port=gateway_port, worker_port=worker_port)
            for name in ('PYTHONHOME', 'PYTHONPATH', 'UV_PROJECT_ENVIRONMENT', 'VIRTUAL_ENV'):
                env.pop(name, None)
            env['PATH'] = environment['PATH']
            env['OTEL_TRACES_EXPORTER'] = 'none'
            env['OTEL_METRICS_EXPORTER'] = 'none'
            return subprocess.Popen([str(binary), 'serve'], cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        proc = None
        try:
            proc, _, _, base = spawn_until_ready(spawn, log_path=log_path, timeout=90)
            with httpx.Client(base_url=base, timeout=30, headers={'Authorization':'Bearer audit-disposable-attach'}) as client:
                health = client.get('/health')
                state = client.get('/v1/service')
                body = state.json()
                print(json.dumps({'health_http':health.status_code,'service_http':state.status_code, **{key:body.get(key) for key in ('service_version','worker_connected','worker_ready','worker_status','worker_generation','database_ready','checkpoint_ready')}}), flush=True)
        finally:
            if proc is not None:
                reap_gateway(proc)
```

## Recommendations

For the intended Dashboard deployment, resolve ER23/ER24 as integration gates and establish ER17's exact release certificate. Prioritize ER01/ER02/ER03 as the durable action/state campaign, then ER04/ER05/ER15/ER16/ER25 for interrupt and lifecycle bounds, ER07/ER08/ER10/ER11/ER12 for provider/context correctness, and ER06/ER09/ER13/ER14 for served contract completeness. ER26/ER27/ER28 cover overload, recovery admission and storage contention. The original queue contained 22 findings: 12 high, 9 medium and 1 low; the continuation below adds ER23–ER28, bringing the current queue to 28 findings: 16 high, 11 medium and 1 low, including explicit environmental/test-evidence items. Each entry above is an open queue item with an owner and objective closure condition; no issue is closed merely because an existing suite passes.

The control-action-leases implementation review's first-event receipt and busy-slot conclusions must be revisited: M03 proves the first event is not a durable application receipt, and ER03 shows dispatch suppression is not a delivery queue. This audit records the changed understanding without rewriting historical entries. The completed provider-error-taxonomy plan does not close setup-condition loss at ER12. The unfinished capability-evidence plan already owns ER13; link remediation there rather than creating a competing implementation plan.

Architecturally significant follow-up decisions must settle durable application acknowledgement, queued-message disposition/order/capacity, recipient routing semantics, and native command/compaction disclosure under the dashboard contract. This report does not authorize new wire shapes or change provider admission declarations.

Current gaps requiring additional measurement: exact external lane selection and provider fault controls; current dashboard with current binary; compaction races; exhaustive crash/disk-failure matrix; sustained C loading and proven quiescence; remaining control latency distributions; complete secret canaries. Run those against disposable audit-owned state. Preserve typed blocked/not-measured outcomes until the required evidence exists.

## Continuing measurement: packaged execution and current consumer

- M16: `uv run --no-sync python tmp/embedded_runtime_execution_probe.py`, exit 0, with observed completed outcomes (exit alone is not a success assertion). Same M12 binary and independent identity, external temporary cwd, PATH System32, no Python environment overrides, in-process lanes explicitly armed. Frozen deterministic selection was obtained from the production catalog helper and asserted exact; a bundled test preset completed through the real gateway/worker/graph/stores. Service reported worker connected=true and ready=true, generation 1. Raw watchdog status pending is distinct from live readiness and is not classified as a defect. One hundred warm GETs for a terminal run all returned 200: p95 0.0154101s, p99 0.0168358s, max 0.019773s. Twenty concurrent identical start requests all returned 201 with the same run ID, which eventually completed. No start barrier, durable application/side-effect count, external provider, or Dashboard execution was measured; exactly-once execution is not established. Printed `failure_condition=null` is ignored because the actual served field is `provider_condition`. Raw log: `tmp/embedded-runtime-audit-execution.log`.
- M17: Actual worker app and Executor, five real checkpointed LangGraphs held at gates, disposable SQLite, production cancel service and WorkerBridge relay over loopback HTTP. All five ingests returned 200. Cancellation at capacity returned accepted=false, applied=false, failure_type=at_capacity after worker 429. The durable cancellation remained accepted_not_applied with its claim released. After gates were released, the run completed naturally and active count reached zero; the cancel action remained unapplied. This promotes ER04 from static to measured L evidence. An initial failed setup reused graph cache keys and timed out; excluded. A hand-built malformed cancel returned 422; excluded in favor of the correctly constructed production-service request. Neither error is capacity evidence.
- M18: Dashboard clean revision `330b2efe294c8ab134fff2142f9fae98afd14fec` compared with the A2A baseline. Dashboard's component lock pins A2A `d59b41b6c1ac8b6e498326ea74ab32898ac9c08b`, version 0.1.0; these findings concern current-source compatibility and do not claim the pinned release was tested. Actual A2A create_app/ASGI with valid synthetic attach/ownership values and the Dashboard header produced GET /readiness=404, POST /drain=404, POST /admin/shutdown=403 with lifecycle ownership required. No shutdown callback or application lifespan was invoked. Consumer callers are inspected source, not a complete D boot.

### ER23-dashboard-lifecycle-wire | high | Current Dashboard lifecycle client cannot use A2A lifecycle routes and ownership header

**OPEN; integration/contract; A01/A26/A27; S plus M18 L route/header measurement.** Dashboard `engine/crates/vaultspec-product/src/control.rs:176` calls /readiness, :184 calls /drain, and :272 sends X-Ownership-Capability. A2A has neither route and requires X-Vaultspec-Lifecycle-Capability at `api/dependencies.py:30`. Reachable Dashboard boot and stop callers are `engine/crates/vaultspec-api/src/boot.rs:385`, :501 and `engine/crates/vaultspec-api/src/routes/a2a_lifecycle.rs:653`, :692. **Owner:** Dashboard/A2A lifecycle contract. **Close when:** one versioned wire contract drives both implementations and the intended locked binary passes actual seated boot, readiness, drain and owned shutdown from Dashboard.

### ER24-dashboard-discovery-wire | high | Current A2A discovery output does not satisfy either Dashboard reader

**OPEN; integration/contract; A01/A27; source/schema evidence.** Dashboard `engine/crates/vaultspec-product/src/a2a_contract.rs:43` and `engine/crates/vaultspec-api/src/routes/a2a_lifecycle.rs:157` use gateway-discovery.json. Its `engine/crates/vaultspec-product/src/discovery.rs:53` schema requires string endpoint, root pid, heartbeat_ms, install_identity, release_set, state_schema and handoff_reference. A2A `api/app.py:452`, :473 and `lifecycle/discovery.py:593`, :738 publish service.json with object endpoint, nested process.pid, last_heartbeat and credential_reference. Dashboard's resident fallback at `engine/crates/vaultspec-api/src/routes/ops/a2a/discovery.rs:30`, :126 expects root port, also absent from armed output. Real operation resolution calls this reader from `engine/crates/vaultspec-api/src/routes/ops/a2a.rs:982`. **Owner:** product discovery/packaging. **Close when:** actual binary-generated discovery is read and authenticated by the intended Dashboard generation, with identity, liveness and stale-record cases exercised.

Dashboard broker coverage also limits ER14/A15: its seven advertised verbs cover run start/status/cancel/list, presets, catalog and clarification response; that broker does not expose follow-up messages, permission responses or native command/compact controls. This is a consumer coverage gap, not proof that the corresponding A2A message/permission routes are absent. Production launch uses the verified binary's serve command; the legacy standalone_mcp capsule field is not treated as a production incompatibility.

The ongoing M19 burst probe is not yet a 30-minute pass. It submits 2C concurrent HTTP starts, then settles each batch, without proving sustained active occupancy at C/2C. Post-batch RSS misses active peaks; a fixed five-second final delay does not establish quiescence if runs remain unsettled. Harness tree reaping does not certify graceful application cleanup. Results will retain these scope limits.

Automatic approval review rejected removal of a failed probe's own temporary directory `C:/Users/hello/AppData/Local/Temp/a2a-audit-capacity-zdhmox3p`, citing “blocked by policy.” It was left untouched; deletion was not retried.

### ER02 continuation: completion rejected before running is committed

**HIGH; concurrency/durability/observability; M19 actual frozen binary observation, independently reviewed.** This differs from M04's stale terminal overwrite. Creation persists submitted at `control/thread_service.py:603`, dispatches, then commits running at :632. A sufficiently fast worker completes in that gap. `thread/transitions.py:13` forbids submitted→completed, but `control/event_handlers.py:370` catches all InvalidTransitionError as “already terminal” and discards the event; :390–398 release admission and relay state. Creation then commits running with no further terminal event. Read-only SQLite and logs establish this for audit-soak-9-8 and audit-soak-10-0: skipped completion local times 17:17:37.707 / 17:19:38.206 preceded final row updates UTC 15:17:37.739368 / 15:19:38.311712. Both remained running/healthy with last_sequence NULL while execution state showed task_count=0, interrupt_count=0, next_nodes=[] and no degradation reasons. This is not evidence that a committed terminal row was overwritten in these particular runs. ER02 closure must cover early terminal arrival as well as stale writers.

### ER25-worker-taskgroup-cancellation | high | Cancellation masks itself with an uninitialized outcome and leaves execution unsettled

**OPEN; correctness/lifecycle; A23/A26; M20 local production boundary measured.** `uv run --no-sync python tmp/embedded_runtime_executor_cancellation_probe.py`, exit 0. After an actual checkpointed LangGraph node entered, AnyIO task-group cancellation produced observed UnboundLocalError: outcome, active_ingest_count=1 after task-group exit, and durable status running. Production Executor.handle_dispatch, SQLite, WorkerBridge and loopback relay_event were used; a logging observer captured the exception without replacing behavior. `worker/executor.py:794` assigns outcome after an await, except Exception excludes cancellation, and finally at :820 uses the unassigned variable. The resume structure at :889/:915 has the same source hazard, not independently measured. Actual worker lifespan uses task-group cancellation at `worker/app.py:248`. Measurements precede explicit executor.shutdown; eventual process exit and restart recovery are not established. **Owner:** worker lifecycle. **Close when:** shutdown cancellation cannot mask itself, active ownership is released and durable disposition/recovery remains truthful for ingest and resume.

### ER26-overload-opens-worker-breaker | medium | Ordinary capacity rejection becomes a shared worker failure cooldown

**OPEN; availability/performance; A20/A28; M19 frozen binary observation plus source.** `control/dispatch.py:239–249` records capacity 429 as breaker failure. The third refusal opens the breaker (`control/circuit_breaker.py:80–90`). At local 17:16:38.283 the third 429 opened it; a run completed at .456, but the next dispatch at .532 was refused by the shared circuit. More completions at .770/.842/.878/.994 freed work while the 30-second cooldown remained. Logs show actual overload amplification, not an external-provider outage. **Owner:** worker admission/breaker policy. **Close when:** healthy saturation has bounded backpressure independent of failure isolation and recovery resumes admission promptly after capacity becomes available.

### ER27-half-open-probe-concurrency | medium | Half-open breaker does not enforce its documented single probe

**OPEN; concurrency/availability; A20; source-only evidence.** `control/circuit_breaker.py:51–59` pre_dispatch returns state != open without reserving the documented single half-open probe. Concurrent callers can all pass after the recovery window. No controlled runtime fan-out measurement was performed. **Owner:** circuit breaker. **Close when:** concurrent recovery admits only the specified probe count, with other requests receiving a stable disposition, and success/failure settles the gate atomically.

M17 exact reproduction is retained locally at `tmp/embedded_runtime_capacity_probe.py`; M20 at `tmp/embedded_runtime_executor_cancellation_probe.py`. They use only disposable local state and no external provider. Independent review excluded malformed probe requests and initial setup errors before promoting observations into this queue. M19's final duration/resource results remain pending; an intermediate observation is not a soak pass.

### M19 measurement identity and intermediate result

Command: `uv run --no-sync python tmp/embedded_runtime_soak.py`, redirected to `tmp/embedded-runtime-audit-soak.log`. M12 executable identity applies. Duration requested: 1800 seconds; source configured C=5, ten concurrent submitted starts per batch, deterministic catalog selection, five sequential warmup runs completed. Worker effective capacity was not independently queried. External temporary state: `C:/Users/hello/AppData/Local/Temp/a2a-audit-soak-7lo6qehj`. Diagnostic reads used SQLite URI mode=ro against home/state/vaultspec.db; logs are gateway.log and home/runtime/worker.log. Intermediate log snapshots retained in `tmp/embedded-runtime-audit-soak-gateway-snapshot.log` and `tmp/embedded-runtime-audit-soak-worker-snapshot.log`.

At elapsed 673.6654 seconds: 24 batches, 240 submitted HTTP requests, 100 responses 201, 138 responses 503, two responses 409; accepted-run settlement observations: 96 completed and four exceeding the nominal 120-second polling deadline. That label is not a hard upper bound because individual HTTP timeouts can exceed remaining poll time. Non-201 response bodies were not captured, so status alone is not attributed to one cause; the separate gateway logs establish the particular 429/breaker sequence above. Baseline: three observed processes, 335.1484 MiB summed RSS, 622 handles. That sample: three processes, 347.4844 MiB RSS, 635 handles. No final memory verdict follows from this intermediate sample. Pending runs preclude an assertion of quiescence. Probe process identities recovered after a truncated launch response: PID 31036 / creation timestamp 1788621351.3919969 and PID 43500 / 1788621351.3744895; both verified still the same processes. They are audit-owned; the measurement was not restarted.

Exact M17 execution command: `uv run --no-sync python tmp/embedded_runtime_capacity_probe.py`. Local reproduction file SHA256 identities: M16 FE7366CDE3431D0CB7E889438D58CDAA3EAFCE3ECAC6E4AFB7402C2A91DC58F8; M17 EE2C07FCA8C3A2C8AF15A67C73D81C811AD9EEA5A82083AE0C9029F01CD7FDA7; M19 9E53A6A5911AA6FC809FD5BE5A0458712E212636AA37299B5AF8E8458B9EB186; M20 53C31E6094F95DE06C3ABA07A06D7F2EDA36AB1770C75313F8C09DB75062CDFC.

Independent continuation review corrected A20 from FAIL to PARTIAL: the breaker findings stand, but they do not directly contradict the narrower frozen retry/fallback assertions. A28 remains PARTIAL, with incomplete duration, separate C load and quiescence. M13 is historical validation; Core check after ER23–ER27 also ran all 19 checks with zero errors or warnings, before this identity/review append. Final measurement and final document checks remain outstanding.

### M18 exact route reproduction

`uv run --no-sync python tmp/embedded_runtime_dashboard_contract_probe.py` was rerun, exit 0: readiness 404, drain 404, shutdown 403 lifecycle ownership required. No lifespan, live server or shutdown callback was executed.

```python
"""Measure current Dashboard lifecycle requests against the real A2A ASGI app.

No application lifespan or live server is started. Dashboard's mismatched
ownership header fails authorization before the shutdown callback is scheduled.
Only synthetic credentials are used.
"""

import asyncio
import json

import httpx

from vaultspec_a2a.api.app import create_app


async def main() -> None:
    app = create_app()
    app.state.v1_service_token = "audit-attach-canary"
    app.state.lifecycle_capability = "audit-ownership-canary"
    headers = {
        "Authorization": "Bearer audit-attach-canary",
        "X-Ownership-Capability": "audit-ownership-canary",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://audit.invalid",
        timeout=10,
    ) as client:
        for method, path in (
            ("GET", "/readiness"),
            ("POST", "/drain"),
            ("POST", "/admin/shutdown"),
        ):
            response = await client.request(method, path, headers=headers)
            print(
                json.dumps(
                    {
                        "method": method,
                        "path": path,
                        "http": response.status_code,
                        "body": response.json(),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=20))
```

### ER28-sqlite-contention-untyped-start-failure | high | Concurrent run creation exposes SQLite contention as an untyped HTTP 500

**OPEN; concurrency/contract/observability; A25/A28; M19 packaged runtime plus independent read-only review.** At elapsed 813.5269s the probe recorded six HTTP 500 responses. Six initial INSERT INTO threads failures in burst 24 raise OperationalError: database is locked. Log lines 1675/1784/1893/2003/2112/2221 correspond to run suffixes 24-3/24-1/24-2/24-8/24-9/24-7. Common production trace: `api/routes/gateway.py:376` → :623 → :517 → `control/thread_service.py:479` → `database/thread_repository.py:176` → `database/_helpers.py:56` (flush). Gateway :539/:545 handles nickname and integrity errors, not this operational contention. Read-only DB review found only four burst-24 rows, all completed (0/4/5/6); the six failed inserts have no durable row. This demonstrates failed admission, not lost acknowledged work, duplicate dispatch or corruption. Gateway :606–608 releases unsuccessful start admission.

Observed journal mode is WAL. Production connections set WAL and configured busy timeout (`database/session.py:119`, :128); default timeout is 5000ms (`control/config.py:251`), but the running connection's effective timeout was not queried. The locking connection, extended SQLite error code and transaction responsible are unmeasured. A long transaction or lock-upgrade explanation remains a hypothesis; increasing timeout is not an established remedy. **Owner:** storage/run admission. **Close when:** bounded write contention yields a documented retryable refusal with truthful admission state, and C/2C concurrent starts cannot expose unclassified storage failures.

### M21 bounded log credential check

Read-only literal-byte scan of the audit-owned live gateway and worker logs (764860 and 178090 bytes at the snapshot) found zero occurrences of each complete disposable attach, ownership and worker-IPC credential. Credential contents were read only into the scanner and never printed. This strengthens A30 narrowly: these log snapshots did not contain the literal values. It does not certify transformed/partial values, exception locals, distributed traces, other routes or external provider credentials. The ongoing run was not changed.

### Audit deliverable coverage and certification boundary

| Requested scope | Assessment delivered | Evidence still required for a passing product gate |
| --- | --- | --- |
| Provider gates and degradation | A05–A07/A19–A21/A33–A34; exact-mode inventory, production adapter seams and classified findings | Current external lane work, injected real provider faults and capability-specific proof |
| Messaging, queues and interruption | A08–A15/A23/A31; journal/source review, checkpoint and cancellation reproductions | Full ordered backlog/restart matrix and intended Dashboard control flow |
| Context and compaction | A16–A18; measurable budgets and production budget/association failures | Native compaction effects and race matrix on an available supported lane |
| Binary as Dashboard component | A01/A26/A27; rebuilt artifact identity, source-independent execution, actual consumer contract comparison | Intended locked Dashboard release boot/attach/drain/upgrade and MCP completed work |
| Persistence, resources and responsiveness | A03/A14/A22–A30; real storage/concurrency probes, warm status distribution, completed M19 burst measurement | Full sustained C workload, proven quiescence, remaining fault/control distributions |

Every criterion has an explicit verdict and evidence boundary. A failing criterion needs a valid counterexample to reject sign-off; it does not need every possible failing scenario repeated. Conversely, passing regression tests cannot certify the missing boundary cases. The unexecuted certification matrix remains listed in the criterion rows and closure conditions. This audit requests remediation and subsequent certification; it does not change provider admission, define new wire contracts or implement fixes.

## Final measurement closeout

M19 finished its 1800-second submission window and final batch/settlement work in **1914.9809 seconds (31m54.98s)**. It submitted **910 requests in 91 batches**: 284 HTTP 201, 609 HTTP 503, six HTTP 409, six HTTP 500 and five HTTP 422. Among 201 responses, 275 runs were observed completed and nine exceeded the nominal settlement polling deadline. These are per-batch observations, not proof that every timed-out run remained active forever. Earlier snapshot/log evidence independently establishes persistent false-running state for the ER02 examples. Response bodies for non-201 statuses were not captured; only the separately traced 429/breaker and SQLite errors are causally classified. Remaining 409/422/503 counts are unclassified status measurements, not additional asserted root causes.

Final summed RSS was **353.5391 MiB**, versus baseline 335.1484 MiB: **+18.3906 MiB**. Maximum sampled post-batch RSS was 359.5859 MiB. Observed process count stayed three; handles were 622 at baseline and 588 at the last sample. The script's rss_growth_pass=true is the arithmetic comparison against 50 MiB only. Its field named quiescent follows a fixed five-second delay and does not establish actual quiescence; nine settlement timeouts preclude promoting this to an A28 pass. Forty-one successful post-batch status samples had p95 0.0233948s and p99 0.0439430s. That is fewer than 100 and is not a complete loaded control distribution; M16's separate 100 warm terminal-status samples remain the narrower A29 evidence.

Harness cleanup initially reported one surviving observed PID, 61256. Immediate process inspection found it absent. The original probe PID 31036 was absent; PID 43500 had been reused by conhost.exe with a different creation time (1788623305.7607005 versus 1788621351.3744895). That unrelated replacement was left untouched. Final/cleanup records plus missing original process identities prove this measurement is terminal; no restart was attempted and no shell exit code is inferred from the unavailable original session handle. Cleanup evidence concerns the harness's observed process set, not a graceful product shutdown guarantee or detached processes missed between samples.

The temporary soak directory was removed by the probe's normal cleanup. Earlier gateway/worker log snapshots and `tmp/embedded-runtime-audit-soak-db-snapshot.json` preserve selected diagnostic evidence; they are not final full-store snapshots. The final aggregate record remains in `tmp/embedded-runtime-audit-soak.log`. This section supersedes earlier “ongoing” and “pending final measurement” statements while preserving their historical intermediate readings.

### Result of the two audit passes

Pass one supplies 34 criteria, their measurable success conditions and evidence-level requirements. Pass two assesses all 34 against the recorded implementation: **19 FAIL, 12 PARTIAL, one BLOCKED, one NOT MEASURED and one PASS**. The full pass is audit reproducibility, not an operational readiness gate. All 28 findings are classified and queued with owners and closure conditions. The assessment is **revision required / production sign-off withheld**. The outstanding product certification cases remain explicit gaps; no external-provider work or complete Dashboard release integration is claimed. No runtime source was changed. Source revision and M12 binary SHA256 were reverified unchanged before closeout.

### Final independent review and reproducibility supplement

Independent closeout review reconciled all 28 finding severities, all 34 criterion verdicts, the 910 HTTP responses and 284 accepted-run outcomes. It found the two-pass assessment deliverable complete with production certification withheld. The final Core validation after this supplement is the closeout check; historical validation entries retain their original scope.

M21 exact scanner logic, run while the disposable M19 directory existed, is reproduced below. Run with `uv run --no-sync python` against the same audit-owned live directory during a reproduction. It prints counts, never credential values. Paths must identify that reproduction's own disposable state.

```python
from pathlib import Path
import json
root = Path('C:/Users/hello/AppData/Local/Temp/a2a-audit-soak-7lo6qehj')
logs = [root / 'gateway.log', root / 'home/runtime/worker.log']
data = [path.read_bytes() for path in logs]
print(json.dumps({
    'scope': 'audit-owned live log snapshots',
    'log_bytes': [len(blob) for blob in data],
    'literal_credential_occurrences': {
        name: sum(blob.count((root / 'home/credentials' / name).read_bytes().strip()) for blob in data)
        for name in ['attach.cred', 'ownership.cap', 'worker-ipc.cred']
    },
}))
```

## Remediation planning handoff

The owner requested research, approved remediation ADRs and an implementation plan on 2026-09-05, with an explicit stop at the plan boundary. Tracking is in `2026-09-05-embedded-runtime-remediation-plan`; grounding is `2026-09-05-embedded-runtime-remediation-research`; qualification is decided in `2026-09-05-embedded-runtime-remediation-adr`. Runtime semantics were refined in their existing ADR homes. No ER finding is closed by these document changes and no runtime implementation has begun.

Planning review classified and resolved three document issues: PR01 medium/contract, a universal checkpoint requirement incorrectly included cancellation no-ops; PR02 low/document consistency, research described an ADR's historical proposed status as current; PR03 low/decision consistency, an open question duplicated the newly decided durable writer identity. The saved decisions now distinguish graph incorporation from cancellation evidence, place status authority in the ADR and retain legacy-state migration as implementation work. These are resolved planning-document findings, separate from the 28 open runtime/evidence findings. Existing active plan owners retain their Step identities and completion states; the remediation plan tracks dependencies rather than silently reopening historical Steps.

Planning review also resolved PR04 medium/implementation completeness by adding explicit ownership-schema migration and checkpoint-receipt declarations, PR05 medium/contract completeness by adding typed storage-admission HTTP projection, and PR06 medium/dependency ordering by moving final external qualification behind local corrections. Core's PLAN022 identifier-order notice is an intentional consequence of canonical insertions, not an untracked renumbering. These changes remain plan-only; runtime findings remain open.

Final plan review resolved PR07 medium/provider correctness by adding explicit ACP stream-consumer outcome propagation; PR08 medium/dependency ordering by qualifying new command effects after implementation and before claim activation; PR09 medium/scheduling by permitting independent local work while optional environment proofs remain open; and PR10 medium/provider coverage by adding the distinct admitted Codex native-control mapping. The saved plan has 81 open Steps in six Waves, with all ER01-ER28 mapped to implementation/dependency and closing-evidence Steps. No operational finding was closed and no implementation Step was executed.

### ER19 W01.P02.S05 owner verification | medium | corrected pending formal review

The now-closed P01.S11 owner result was rerun at A2A `c1da77cd` without changing
runtime or tests. The authenticated real route observed OpenAI available with
129 models and complete authenticated revision/expiry evidence, and Z.AI
unavailable with no models and a bounded reason. Each provider's health catalog
axis matched its catalog status while exact-mode admission stayed
`not_admitted` and selectability stayed false. The exact route test passed, the
11-test route file passed, 34 surrounding selection/catalog tests passed, and 10
current-lane/no-retired guards passed. Static checks passed. This removes ER19's
stale host-state assumption without turning discovery into execution proof. No
new finding surfaced; W01.P02.S05 remains open for formal review and later
Dashboard/external qualification remains with W05.P12.S57.

### ER19 W01.P02.S05 lifecycle closure | low | closed

Formal evidence review `3ed2ccdc0342f34e623cb507b914b68dba5f2f8c`
passed the exact ER19 owner verification recorded at `1daa2ea9`: observed catalog
availability is host-relative, health agrees with catalog state, and both exact
OpenAI/Z.AI modes remain not admitted and nonselectable. Core closed only
W01.P02.S05 and created its evidence Step Record. S06-S08 and later assembled
Dashboard/external qualification remain open. This lifecycle entry adds no
runtime, test, legacy or deprecated behavior; closure-record review is pending.
