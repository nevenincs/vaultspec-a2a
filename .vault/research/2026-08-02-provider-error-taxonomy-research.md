---
tags:
  - '#research'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c7841e06b035a81994626c66735dd7a66bc6fb3bd45b433b11d20bb562692376'
related: []
---

# `provider-error-taxonomy` research: `surfacing provider failure conditions to a client`

Can a client tell WHY a run failed - specifically, whether the provider was
unreachable, overloaded, unauthenticated, rate-limited, out of credits, past a
spend floor, inside an exhausted usage window, or broken for an unknown reason?
Today it cannot, for any of the eight. The gap matters because the dashboard is
the only consumer, it renders whatever a failed run reports, and every one of
these conditions demands a different user action - wait, re-authenticate, top up,
switch lane, or file a bug - while all of them currently render identically.

The evidence inverts the obvious framing. This is NOT a missing-taxonomy problem
requiring new classification to be invented at the provider boundary. Every
served lane already puts a machine-readable discriminator on the wire, and the
ACP lane's is already parsed into a Python attribute that has zero readers. The
defect is that the classification is destroyed in transit: a worker-node wrapper
replaces the provider exception with one naming only the worker and the model
CLASS, ingest re-stringifies that wrapper without walking `__cause__`, and the
result is a capped string carrying no provider fact at all. A typed
severity/recovery vocabulary for exactly this purpose already exists in-tree and
is also dead. So the work is recovery and plumbing, not design - with one
genuine exception, recorded below, where a condition pair is not separable on the
Claude lane at all.

Three findings exceed the original question in severity and are recorded here
because they make the surfacing work moot if left unfixed: two paths terminate a
run with no reason whatsoever, a reconnecting client cannot recover the reason
even when one was written, and the two canonically retryable conditions never
retry.

## Findings

### The wire carries exactly four error codes, none of which is a provider condition

`streaming/ingest.py:259-311` contains every production `emit_error` call in the
tree, emitting `RECURSION_LIMIT_EXCEEDED`, `INGEST_STALL_TIMEOUT`, `STEP_TIMEOUT`,
and the catch-all `INGEST_ERROR`. `streaming/emitters.py:527-545` and
`streaming/aggregator.py:287-295` are pass-throughs with no other callers. All
eight conditions of interest reach the catch-all.

The frame catalog admits three fields on an `error` frame - `code` (64 chars),
`message` (512), `recoverable` - and three on `thread_terminal`, including
`error_detail` (512) (`streaming/sse_frames.py:329-338`). The durable counterpart
is the single `threads.failure_reason` text column (`database/models.py:140`,
migration `database/migrations/versions/0011_thread_failure_reason.py:30`),
projected to the wire at `api/routes/gateway.py:1430` onto
`RunStatusResponse.failure_reason` (`api/schemas/gateway.py:492-498`).

### The provider exception is destroyed before anything reports it - the largest single loss

`graph/nodes/worker.py:589-597` catches every non-`GraphBubbleUp` exception and
re-raises `_wrap_worker_exception(...)`, which (`graph/nodes/worker.py:138-156`)
logs the original and constructs a `WorkerExecutionError` whose entire message is
`f"worker={worker!r} model={model} messages={message_count}"`
(`thread/errors.py:164-169`). The provider's type, message, ACP numeric code, and
`data` payload are absent from the new exception's string; they survive only on
`__cause__` and in the worker log. `model` is `type(effective_model).__name__`
(`graph/nodes/worker.py:571`) - the class name `AcpChatModel` - so the wrapper
names neither the lane nor the model id.

Ingest's catch-all then computes `f"{type(exc).__name__}: {exc}"` and does not
walk `__cause__` (`streaming/ingest.py:60-75`). The end-to-end product of a real
provider authentication failure is therefore:

```
Graph event stream failed unexpectedly: WorkerExecutionError: worker='vaultspec-researcher' model=AcpChatModel messages=3
```

This is the correction that reframes the whole feature: for a provider fault
raised inside a worker node - which is every fault of interest - the existing
free-text channel does not carry a degraded version of the provider's message. It
carries none of it. Any belief that the frontend currently shows "the error text,
just untyped" is wrong.

### Every served lane already puts a typed discriminator on the wire, and all of them are discarded

Only three external lanes are served. `providers/lane_admission.py:165-192`
declares `PROVEN_TURN_LANES` as CLAUDE, CODEX, ZAI; `:158-163` records `gemini`
and `openai` as deliberately absent for want of completed-turn proof, and
`:199-201` admits MOCK/DETERMINISTIC in-process. Designing typed conditions for
gemini/openai would be speculative work on surfaces no served profile can name.
`gemini_auth.py` is additionally not a chat lane - it is an OAuth refresh helper
whose whole error surface is bare `RuntimeError`/`OSError`
(`gemini_auth.py:229-268`, `:426-428`).

**ACP lane (Claude, and ZAI via the same adapter with a redirected base URL,
`factory.py:88-106`, `:742-761`).** The adapter attaches `data.errorKind` at its
three fail sites (`node_modules/@agentclientprotocol/claude-agent-acp@0.59.0/dist/acp-agent.js:2044`,
`:2080`, `:2090`), documented at `:4103-4115` as "a convention for ACP clients to
dispatch on without having to pattern-match the human-readable message text". The
value is a closed 10-member enum in
`node_modules/@anthropic-ai/claude-agent-sdk@0.3.207/sdk.d.ts:2822`:
`authentication_failed`, `oauth_org_not_allowed`, `billing_error`, `rate_limit`,
`overloaded`, `invalid_request`, `model_not_found`, `server_error`, `unknown`,
`max_output_tokens`. The same enum is compiled into the shipped CLI binary, so it
is what executes rather than a typing artefact. The repo already parses it:
`acp_chat_model.py:125-139` reads `code` and `data` into `AcpPromptError`, stored
as slots at `acp_exceptions.py:34-66`. `AcpPromptError.data` has zero readers in
`graph/`, `worker/`, or `thread/`.

**Codex lane.** Verified against a protocol schema generated from the installed
binary (`codex app-server generate-json-schema`, codex-cli 0.146.0). The `error`
notification carries `ErrorNotification{error: TurnError, threadId, turnId,
willRetry: bool}` where `TurnError{message, codexErrorInfo, additionalDetails}`.
`CodexErrorInfo` maps nearly one-to-one onto the eight conditions:
`usageLimitExceeded`, `serverOverloaded`, `sessionBudgetExceeded`, `unauthorized`,
`badRequest`, `internalServerError`, `contextWindowExceeded`, `cyberPolicy`,
`other`, plus object variants carrying `httpStatusCode` including
`httpConnectionFailed`. Credits and reset times are first-class:
`CreditsSnapshot{hasCredits, unlimited, balance}`,
`RateLimitWindow{usedPercent, resetsAt, windowDurationMins}`,
`SpendControlLimitSnapshot{limit, used, remainingPercent, resetsAt}`, and
`RateLimitReachedType` separating `rate_limit_reached` from
`workspace_owner_credits_depleted` and `workspace_owner_usage_limit_reached`.

The repo keeps the message string and nothing else. `codex_chat_model.py:168-174`
(`_response_error_message`) returns only `error["message"]`, dropping
`codexErrorInfo` and `willRetry`; the `error` branch at `:700-706` consumes only
that. At `:707-717` the `turn/completed` branch reads `turn["status"]` and raises
`f"codex turn ended with status {status!r}"` - discarding `Turn.error`, which per
the schema is populated exactly when `status == "failed"`. No
`account/rateLimits/updated` subscription exists.

### Two of the eight conditions are not separable on the Claude lane, and pretending otherwise would ship a false claim

The CLI's 429 handler returns `errorKind:'rate_limit'` on every sub-branch. It
does branch internally on the `anthropic-ratelimit-unified-overage-disabled-reason`
response header and on `rateLimitType === "seven_day_overage_included"`, but the
distinction survives only in the human-readable message string. So
rate-limited (6) and usage-window-exhausted (8) arrive identically. Codex
separates them cleanly; the ACP lane does not.

An authoritative reset time exists but on a different, earlier channel:
`SDKRateLimitInfo` (`sdk.d.ts:4127-4143`) carries `resetsAt`, `rateLimitType`,
`status: 'allowed' | 'allowed_warning' | 'rejected'`,
`overageDisabledReason:'out_of_credits'` and `errorCode:'credits_required'`,
forwarded by the adapter as a `session/update` with `sessionUpdate:"usage_update"`
and `_meta:{"_claude/rateLimit": ...}` (`acp-agent.js:2500-2512`). The repo's
`handle_session_update` (`_acp_protocol.py:250-311`) has no branch for it and
silently drops it; `src/` contains zero occurrences of `usage_update`,
`_claude/rateLimit`, or `rateLimit`. Two caveats bound its usefulness: the adapter
emits it only when `lastAssistantTotalUsage !== null` (`acp-agent.js:2501`), and
it precedes the failure rather than accompanying it. It is opportunistic, not
guaranteed.

For the API proper (reference only - no served lane speaks it directly), status
maps to `error.type` with credit exhaustion now a first-class `402 billing_error`
rather than the legacy 400-with-message form, and every quantitative signal -
`retry-after`, `anthropic-ratelimit-*-reset` in RFC 3339 - is a response HEADER,
absent from the body. The CLI consumes those headers internally and forwards none.

### `recoverable` classifies which branch caught the exception, not whether the failure is retryable

Producers are the four `emit_error` calls above; consumers are three, all
live-wire (`graph/events.py:154-159`, `streaming/sse_frames.py:332`,
`api/event_adapter.py:265-274` onto `api/schemas/events.py:228-236`). It is
persisted nowhere: no column, no field on `RunStatusResponse`
(`api/schemas/gateway.py:462-516`), and absent from the hand-built
`thread_terminal` payload (`worker/state_projection.py:285-292`).

Because every provider fault lands in the `else` branch, it is hardcoded
`recoverable=False` (`streaming/ingest.py:310`). A transient provider 502 and a
permanent credential revocation are both reported unrecoverable, while a step
timeout is reported recoverable. The flag is structural, not semantic.

### A typed severity and recovery-action vocabulary already exists in-tree and is dead

`thread/errors.py:14-22` defines `ErrorSeverity{TRANSIENT, PERMANENT, UNKNOWN}`
and `:25-36` defines `RecoveryAction{RETRY, RETRY_WITH_BACKOFF, REASSIGN,
ESCALATE_TO_USER, ABORT}`. Every `VaultspecError` subclass declares both
(`thread/errors.py:85-86, 152-153, 161-162, 182-183, 200-201, 214-215, 228-229,
242-243, 256-257, 265-266`). Production readers: zero - a scan for
`\.severity|\.recovery_action` across `src/` returns only the constructor's own
writes (`thread/errors.py:69, 71`) and tests. Both enums are re-exported from
`thread/__init__.py:76, 94` and consumed by nothing. `ProviderSessionError` is
referenced in production only as a member of `_NO_RETRY_EXCEPTIONS`
(`graph/compiler.py:41, 100`) and is never raised anywhere in `src/`.

This is decision-relevant: the ADR can adopt an existing vocabulary rather than
mint one, but must then account for why it lay unused, or it will lie unused
again.

### Overloaded and rate-limited - the two canonically retryable conditions - never retry

A node-level retry policy with exponential backoff does exist and is applied to
every worker and supervisor node: `graph/compiler.py:131`
`RetryPolicy(retry_on=_worker_retry_on)`, with LangGraph 1.2.2 defaults of
`initial_interval=0.5`, `backoff_factor=2.0`, `max_interval=128.0`,
`max_attempts=3`, `jitter=True` (`.venv/Lib/site-packages/langgraph/types.py:406-425`).

It never fires for a provider fault. `_TRANSIENT_EXCEPTIONS`
(`graph/compiler.py:89-95`) is five stdlib types; `AcpError` and its subclasses
appear in neither that tuple nor `_NO_RETRY_EXCEPTIONS` (`:98-101`), so
`_worker_retry_on` (`:104-127`) unwraps `__cause__`, matches nothing, and returns
`False`. A provider 429 or 502 is a one-shot terminal failure by omission rather
than by decision. Codex's `willRetry: bool` would answer the question directly and
is discarded.

The only in-provider retry is `max_retries=2` on `ChatOpenAI`
(`providers/factory.py:911`, `:937`) - both unserved lanes. There is no runtime
failover: `fallback_providers` is consulted at eligibility time only
(`providers/model_profiles.py:555-557`), never at failure time.
`WorkerCircuitBreaker` (`control/circuit_breaker.py:18-58`) holds no provider,
lane, or model key and is driven exclusively by worker `/dispatch` transport
outcomes (`control/dispatch.py:230, 245, 257`); a provider failure inside an
already-dispatched run never touches it.

### Six paths terminate a run with no reason at all; two are critical

No bare `except Exception: pass` exists in production code. The real swallows are
worse because they produce a terminal state.

**Every dispatch-level failure writes `failure_reason` NULL.**
`control/repair_transitions.py:17-28` `apply_dispatch_failure` calls
`update_thread_status(db, thread_id, failed_status)` with no reason argument. All
four callers hold the reason and discard it into an HTTP response body only:
`control/thread_service.py:577-595`, `control/message_service.py:182-201`,
`control/permission_service.py:765-784`, and `api/routes/gateway.py:2000-2008`
(which performs no durable write at all). None broadcasts to the aggregator. A
client reloading after a worker-unreachable or circuit-open failure sees
`status="failed", failure_reason=null`.

**The executor's top-level handler emits no terminal at all.**
`worker/executor.py:470-480` logs `"...worker task group protected - thread may be
stuck in RUNNING"` and returns - no terminal event, no frame, no durable write.
Because `worker/app.py:239-253` acks `/dispatch` immediately and runs the work via
`tg.start_soon`, the gateway believes the dispatch succeeded while the thread sits
`RUNNING` indefinitely.

Four further sites: `_reject_slot_held` is fully silent by explicit design
(`worker/executor.py:360-381`, reachable at `:553-555` and `:614-616`);
`_reject_missing_graph` drives to FAILED with no detail though the cause is known
(`:338-358`, and the same shape at `:511-526`); the ingest/resume `except
Exception` blocks yield FAILED with no reason when an exception escapes
`aggregator.ingest` (`:583-596`, `:668-681`); and `_reject_compile_failure`
(`:313-336`) sets `error_detail` but calls no `emit_error`, so a compile refusal
has a reason and no `code` while an ingest failure has both - a consumer keying on
`code` cannot see it.

### A reconnecting client cannot recover the reason, and error frames are droppable

The terminal replay frame is hand-built as
`{type, event_type, thread_id, status, replay: True}` with no `error_detail` and
no preceding `error` frame (`api/thread_stream.py:89-101`); there is no replay
buffer, each subscriber getting a fresh empty queue
(`streaming/subscribers.py:46, 90-95`). A client attaching to an
already-terminal run learns only `failed`, and must fall back to `run-status`.

Separately, `deliver_bounded` (`streaming/fanout.py:29-64`) is drop-oldest with no
frame-type priority, so an `error` or `thread_terminal` frame is exactly as
droppable as a token chunk under backpressure
(`streaming/subscribers.py:199, 250-251`).

### The consumer is free-text only, and the two repositories disagree on the bound

The dashboard engine models a failed run's reason as
`RunRecord.failure_reason: Option<String>` with no code, class, or retry hint, and
validates it non-empty, unpadded, and at most **500 bytes**
(`engine/crates/vaultspec-api/src/authoring/session/validate.rs:266-276` in the
dashboard repository). A2A caps `error_detail` at **512 chars** on the frame
(`streaming/sse_frames.py:337`) - though the durable column is capped at 500 by
`_MAX_FAILURE_REASON_LEN` (`database/thread_repository.py:377-385`). The frame
bound therefore exceeds the consumer's limit, and 500 chars of multibyte text
exceeds 500 bytes regardless, so a long reason can be rejected outright by the
consumer.

No binding dashboard ADR specifies an error taxonomy - checked
`2026-08-01-a2a-agent-flow-adr`, `2026-07-31-a2a-integration-verification-adr`,
and `2026-08-01-agent-panel-shell-integration-adr` on branch
`origin/feature/agent-panel`. A2A is free to define the vocabulary. The
integration-verification ADR does ask for a scripted scenario preset covering
"tool calls, permission pauses, failure and cancellation", which is the natural
proof surface for this work rather than a bespoke one.

### Pre-launch admission has eight reason channels, none enumerated

`ProviderEligibility` is binary (`api/schemas/gateway.py:139-153`) and computed
from credential presence and command resolvability only -
`providers/model_profiles.py:325` states "Presence/resolvability only (never quota
headroom)". Readiness reasons are presence strings such as `"no Claude OAuth token
configured"` (`providers/model_profiles.py:341`, and `:355`, `:362`, `:377`).

Eight distinct free-form reason channels reach a client before a run starts:
`DesktopReadiness.reasons` (`api/schemas/gateway.py:326-327`, produced at
`control/health.py:352-393`, truncated `[:16]` at `:416`),
`RunStartEligibility.reason` (`control/run_start_policy.py:45-46`, produced
`:153-189`), `ExecutionEligibility.reason` (`:60-61`, produced `:80-87`),
`ProfileSummary.unavailable_reasons` (`api/schemas/gateway.py:770`, composed
`providers/model_profiles.py:577-599`), `RoleAssignmentSummary.resolution_error`
(`api/schemas/gateway.py:753`, produced `providers/model_profiles.py:524-532`,
`:565-575`), lane refusals (`providers/lane_admission.py:315-328`,
`providers/model_profiles.py:469-487`), `ServiceStateResponse.degraded_reasons`
(`api/schemas/gateway.py:856`, produced `api/routes/gateway.py:2296-2304`, with no
`max_length`), and the projection `degraded_reasons`
(`worker/state_projection.py:247, 260`) - the last being the only near-enumerated
set on the surface, at two fixed literals.

`FailureType` (`thread/dispatch_policy.py:21-37`: `CIRCUIT_OPEN`, `AT_CAPACITY`,
`UNREACHABLE`, `REJECTED`, `NOT_FOUND`, `TERMINAL`, `INPUT_REQUIRED`) is the only
existing machine-readable failure vocabulary, and it is dispatch-scoped: it
reaches a client only as an HTTP status via `raise_for_cancel_failure`
(`api/routes/gateway.py:1506`), never persisted, never streamed.

### Existing coverage proves the durable hop and nothing else

Proven: `api/tests/test_internal.py:937-1035` drives the real gateway handler
against a real session factory for three cases - reason lands on `failed`, column
untouched on `completed`, non-string ignored; `streaming/tests/test_aggregator.py:1671-1700`
proves a real stalling graph yields a once-only reason, with the `recoverable`
flag asserted at `:1510-1533`, `:1599`, `:1668`; `streaming/tests/test_progress_allowlist.py:258-290`
proves catalog retention; `control/tests/test_cancel_failure_mapping.py:41-60`
proves `FailureType` to HTTP status.

Unproven: no test asserts `RunStatusResponse.failure_reason` on the wire - the
whole-tree matches are the five DB-level lines in `api/tests/test_internal.py`
(`:958, 975, 980, 1008, 1035`) - even though `api/schemas/snapshots.py:170-177`
records that the field was added because it had been silently dropped at a
`model_validate` seam. No test drives a provider exception end to end to an
`error` frame, so the wrapper loss above is entirely unpinned. No test covers the
terminal replay frame's contents, `_reject_missing_graph`, `_reject_slot_held`, or
the top-level `handle_dispatch` handler.

Two further `model_validate` silent-drop seams sit on this path:
`api/routes/gateway.py:1538-1546` (`snapshot_to_wire`, run-history) and
`control/event_handlers.py:577`. `RunStatusResponse` itself is built with explicit
kwargs (`api/routes/gateway.py:1401-1447`) and so is drop-safe, but requires a
hand edit per field - which is how `failure_reason` was missed originally.
`RunCancelResponse` (`:1522-1530`) carries no failure field at all despite
`CancelResult.error_detail` existing.

### What the ADR must settle

Whether the condition vocabulary is lane-uniform or lane-conditional, given that
Codex can type all eight honestly while the ACP lane can type six and must
collapse (6) and (8) into one throttled condition. Whether to adopt the existing
dead `ErrorSeverity`/`RecoveryAction` pair or mint a purpose-built enum, and what
prevents a second dead vocabulary. Where classification is computed - at the lane
adapter, or centrally from a preserved exception chain. Whether `recoverable`
becomes a genuine retry contract binding `_worker_retry_on`, or stays advisory.
Whether the condition is persisted (new column) or derived on read. Whether a
reset time is carried at all, given it is lane-conditional and opportunistic on
the ACP lane. What the frame bound becomes, given the consumer rejects over 500
bytes. And whether the swallow sites are in scope here or split to a separate
record - they are independent defects that this feature's value depends on.

### Not investigated

No lane was exercised live and no credential was spent; every wire claim derives
from installed adapter and SDK source, generated protocol schema, published docs,
and the repo's own captured evidence. Whether `errorKind` survives on the ZAI lane
is UNVERIFIED and is the most likely way this work ships a false claim: the CLI
derives the kind partly by pattern-matching Anthropic's English error prose
(binary extract shows `.message.includes("OAuth token has been revoked")` and
similar), and Z.ai is an Anthropic-compatible endpoint whose text need not match,
so status-gated branches should hold while message-gated ones likely degrade to
`unknown`. No live ZAI error capture exists in the repo; a live probe is cheap and
should precede any ADR claim binding ZAI to Claude's typing.

Also unverified: whether the `"You've hit your weekly limit"` fixture at
`service_tests/test_claude_web_grounding_live.py:626` (commit `53b5c876`) is a
verbatim wire capture - its SHAPE is confirmed against `acp-agent.js:2044`, its
text is not attested; whether Anthropic still emits the legacy 400 credit-balance
form alongside 402; the Codex `error` field semantics on the wire as opposed to in
the generated schema - the only observed Codex failure evidence is the prose
string recorded at `.vault/exec/2026-07-17-tool-cores/2026-07-17-tool-cores-P04-S20.md:26`
("You've hit your usage limit. ... try again at Jul 23rd, 2026 6:15 AM"), itself a
demonstration of a reset time arriving as prose because the typed `resetsAt`
channel is unconsumed. `anthropic-ratelimit-unified-overage-disabled-reason` is
read by the CLI binary but is undocumented publicly and should not be built on.
Dashboard-side rendering beyond the record and validator cited was not traced, and
`desktop/settlement.py` `emit_run_settlement` was not read.

A live-observed defect outside this feature's question, found while reading the
ACP protocol handler: `_acp_protocol.py:165-166` sets `ctx.prompt_done` only on
`stopReason == "end_turn"`, but the shipped ACP schema
(`node_modules/@agentclientprotocol/sdk@1.2.1/schema/schema.json`, definition
`StopReason`) defines five legal terminal values - `end_turn`, `max_tokens`,
`max_turn_requests`, `refusal`, `cancelled`. The other four leave the turn
hanging until the idle deadline fires and report `turn_idle_deadline_expired`
(`acp_chat_model.py:592-597`), a wrong classification for four of five legal
outcomes. Related: the ACP SDK emits `-32800` requestCancelled and `-32002`
resourceNotFound (`node_modules/@agentclientprotocol/sdk@1.2.1/dist/jsonrpc.js:809-826`)
which `AcpErrorCode` does not map, while defining `UNKNOWN_ERROR = -1`
(`acp_exceptions.py:28`) which the adapter never emits; and
`is_auth_required_error` (`_acp_auth.py:143-155`) matches code `-32000` or four
substrings, none of which match the `authentication_failed` kind the adapter sends
on its `-32603` path.

## Sources

- `src/vaultspec_a2a/streaming/ingest.py:38, 60-75, 141-148, 250-328`
- `src/vaultspec_a2a/streaming/sse_frames.py:101-113, 329-338, 519`
- `src/vaultspec_a2a/streaming/aggregator.py:118-127, 287-295, 329-331`
- `src/vaultspec_a2a/streaming/emitters.py:527-545`
- `src/vaultspec_a2a/streaming/fanout.py:29-64`
- `src/vaultspec_a2a/streaming/subscribers.py:46, 90-95, 199, 250-251`
- `src/vaultspec_a2a/streaming/transformer.py:57-71`
- `src/vaultspec_a2a/graph/nodes/worker.py:138-156, 571, 589-597`
- `src/vaultspec_a2a/graph/compiler.py:41, 89-101, 104-127, 131`
- `src/vaultspec_a2a/graph/events.py:154-159`
- `src/vaultspec_a2a/thread/errors.py:14-36, 69-86, 152-266`
- `src/vaultspec_a2a/thread/dispatch_policy.py:21-37`
- `src/vaultspec_a2a/thread/__init__.py:76, 94`
- `src/vaultspec_a2a/worker/executor.py:303-336, 338-358, 360-381, 414-417, 470-480, 511-526, 553-555, 583-596, 614-616, 668-681`
- `src/vaultspec_a2a/worker/state_projection.py:247, 260, 285-301`
- `src/vaultspec_a2a/worker/app.py:239-253`
- `src/vaultspec_a2a/api/internal.py:103-130`
- `src/vaultspec_a2a/api/thread_stream.py:89-101, 126-135`
- `src/vaultspec_a2a/api/event_adapter.py:265-274, 286-300`
- `src/vaultspec_a2a/api/schemas/events.py:228-236`
- `src/vaultspec_a2a/api/schemas/gateway.py:139-153, 326-327, 462-516, 492-498, 753, 770, 856`
- `src/vaultspec_a2a/api/schemas/snapshots.py:170-177`
- `src/vaultspec_a2a/api/routes/gateway.py:1401-1447, 1430, 1506, 1522-1530, 1538-1546, 2000-2008, 2296-2304`
- `src/vaultspec_a2a/api/tests/test_internal.py:937-1035`
- `src/vaultspec_a2a/control/event_handlers.py:226-235, 577`
- `src/vaultspec_a2a/control/repair_transitions.py:17-28`
- `src/vaultspec_a2a/control/thread_service.py:577-595`
- `src/vaultspec_a2a/control/message_service.py:182-201`
- `src/vaultspec_a2a/control/permission_service.py:765-784`
- `src/vaultspec_a2a/control/run_start_policy.py:45-46, 60-61, 80-87, 153-189`
- `src/vaultspec_a2a/control/health.py:352-417`
- `src/vaultspec_a2a/control/circuit_breaker.py:18-58`
- `src/vaultspec_a2a/control/dispatch.py:230, 245, 257, 271`
- `src/vaultspec_a2a/control/thread_state_service.py:260`
- `src/vaultspec_a2a/control/tests/test_cancel_failure_mapping.py:41-60`
- `src/vaultspec_a2a/database/models.py:140`
- `src/vaultspec_a2a/database/thread_repository.py:377-385, 397-406, 418-429`
- `src/vaultspec_a2a/database/migrations/versions/0011_thread_failure_reason.py:30`
- `src/vaultspec_a2a/ipc/serializers.py:36-41, 50, 69-76`
- `src/vaultspec_a2a/providers/acp_exceptions.py:28, 31, 34-66`
- `src/vaultspec_a2a/providers/acp_chat_model.py:118, 125-139, 592-597, 606, 626`
- `src/vaultspec_a2a/providers/_acp_protocol.py:107, 165-166, 250-311`
- `src/vaultspec_a2a/providers/_acp_auth.py:143-155, 158-183, 196-200`
- `src/vaultspec_a2a/providers/codex_chat_model.py:168-174, 287-291, 694-717`
- `src/vaultspec_a2a/providers/factory.py:88-106, 742-761, 911, 915-939`
- `src/vaultspec_a2a/providers/gemini_auth.py:229-268, 426-428`
- `src/vaultspec_a2a/providers/lane_admission.py:158-192, 199-201, 222-283, 315-328`
- `src/vaultspec_a2a/providers/model_profiles.py:322-385, 469-487, 524-575, 577-599`
- `src/vaultspec_a2a/service_tests/test_claude_web_grounding_live.py:130, 358-361, 626-628`
- `.vault/exec/2026-07-17-tool-cores/2026-07-17-tool-cores-P04-S20.md:26`
- `.venv/Lib/site-packages/langgraph/types.py:406-425` (langgraph 1.2.2)
- `node_modules/@agentclientprotocol/claude-agent-acp/dist/acp-agent.js:2035, 2044, 2080-2093, 2337, 2500-2512, 4103-4115` (`@agentclientprotocol/claude-agent-acp@0.59.0`)
- `node_modules/@anthropic-ai/claude-agent-sdk/sdk.d.ts:2822, 4127-4147, 6714` (`@anthropic-ai/claude-agent-sdk@0.3.207`)
- `node_modules/@agentclientprotocol/sdk/dist/jsonrpc.js:809-826` and `schema/schema.json` (`@agentclientprotocol/sdk@1.2.1`)
- Codex protocol schema, regenerable via `codex app-server generate-json-schema --out <DIR>` (codex-cli 0.146.0); not committed
- `engine/crates/vaultspec-api/src/authoring/session/validate.rs:266-276` (dashboard repository, branch `main`)
- `.vault/adr/2026-08-01-a2a-agent-flow-adr.md`, `.vault/adr/2026-07-31-a2a-integration-verification-adr.md`, `.vault/adr/2026-08-01-agent-panel-shell-integration-adr.md` (dashboard repository, branch `origin/feature/agent-panel`)
- https://agentclientprotocol.com/protocol/prompt-turn#stop-reasons
- https://platform.claude.com/docs/en/api/errors (fetched 2026-08-02)
- https://platform.claude.com/docs/en/api/rate-limits (fetched 2026-08-02)
