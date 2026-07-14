---
tags:
  - '#reference'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - '[[2026-07-14-a2a-edge-conformance-reference]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
---

# `a2a-edge-conformance` reference: `engine authoring wire shapes`

Exact wire shapes of the dashboard engine's authoring plane, extracted
read-only from the Rust source at
`Y:/code/vaultspec-dashboard-worktrees/main` (rag-led, then
source-confirmed, 2026-07-14). This is ground truth over the prose brief:
where the companion reference and this document disagree, this document
wins. Implementation of the authoring client (W03), the five-verb gateway
(W04), and the discovery contract (W05) codes against these shapes.

## Summary

### Mount and transport basics

- Router assembly in `engine/crates/vaultspec-api/src/lib.rs:105`
  `build_router()`; authoring subtree mounted via `authoring_router()`
  (`authoring/http/mod.rs:467`) nested under `/authoring`, so every path
  below is `/authoring/v1/...`.
- Two-layer auth, distinct headers, transport first: machine bearer
  (`Authorization: Bearer <token>`, `bearer_gate`, `app.rs:1402-1441`,
  constant-time compare, gates everything except `/health` and the SPA
  shell) THEN per-actor principal via the `x-authoring-actor-token` header
  (`AUTHORING_ACTOR_TOKEN_HEADER`, `authoring/principal.rs:26`).
- Shared envelope on success and error: `{data, tiers, next_cursor?}`
  (`routes/mod.rs:109` `envelope()`); error shape
  `{error, error_kind?, tiers}` (same file, lines 130-160). Authoring
  wrappers in `authoring/response.rs`: `snapshot`, `command_receipt` ->
  `{data:{receipt:...}, tiers}`, `typed_error` -> `{error, error_kind,
  tiers}`.
- The idempotency key is a BODY field, not a header. Every mutating command
  route deserializes the whole POST body as `CommandEnvelope<T>`
  (`authoring/api/mod.rs:346-351`, extractor `ResolvedCommand<T>` at
  `authoring/http/mod.rs:239-292`):
  `{"api_version":"v1","command":"<command_kind>","idempotency_key":"...",
  "payload":{...}}`. `api_version` is a snake_case enum with `v1` the only
  variant. No Idempotency-Key header exists anywhere in the domain.
- Exception: `POST /v1/actor-tokens` (`handlers3.rs:954`) takes a bare JSON
  `IssueActorTokenRequest` - not envelope-wrapped, no idempotency key
  (bootstrap seam, machine-bearer-gated only). Payload
  (`api/mod.rs:586`): `{actor: ActorRef, lifetime_ms?: u64}`.
- ID and token validation (one macro, `authoring/model.rs:77-131`, applied
  to ActorId, SessionId, ChangesetId, ProposalId, ApprovalId, RunId,
  ToolCallId, IdempotencyKey, RevisionToken): non-empty after trim, max
  160 bytes, no surrounding whitespace, ASCII alphanumeric plus `_ - : . /`
  only. Plain JSON strings on the wire.
- `ActorRef` (`model.rs:144`): `{id, kind, delegated_by?}`; `ActorKind`
  (`model.rs:135`, snake_case): `human | agent | system | tool_executor`.

### Route-by-route shapes

Sessions and runs:

- `POST /v1/sessions` -> create_session; payload `{scope, title}`
  (`api/mod.rs:385`).
- `GET /v1/sessions`, `GET /v1/sessions/{session_id}` - unauthenticated
  projection reads.
- `POST /v1/sessions/{session_id}/turns` -> start_prompt_turn; payload
  `{prompt, summary?}` (`api/mod.rs:392`).
- `POST /v1/runs/{run_id}/cancel` -> payload `{reason}`.
- `POST /v1/runs/{run_id}/resume` -> payload `{session_id?}`.

Proposals:

- `POST /v1/proposals` -> create_proposal; payload `{session_id,
  changeset_id, summary, operations: [ChangesetChildOperationDraft]}`
  (`api/mod.rs:432`).
- `ChangesetChildOperationDraft` (`api/mod.rs:441`): `{child_key,
  operation, target: TargetRevisionFence, draft: DraftMutation}`.
  `ChangesetOperationKind` (snake_case): `create_document | replace_body |
  append_body | edit_frontmatter | rename | archive | section_edit |
  set_plan_step_state` (partial enum; section/plan-step kinds deferred
  engine-side - whole-document shapes only per the standing deferral).
  `DraftMutation` carries `body?`, `frontmatter?`, `new_stem?`,
  `section_selector?`, `plan_step?` - exactly one populated per operation
  kind; no accepted-but-ignored fields.
- `POST /v1/proposals/{changeset_id}/append` and `/replace` -> payload
  `{changeset_id, expected_revision: RevisionToken, summary, operations}`
  (`proposal/mod.rs:51`); `expected_revision` is the optimistic-concurrency
  fence on every draft mutation.
- `POST /v1/proposals/{changeset_id}/rebase` -> `{changeset_id,
  expected_revision, summary}` (`rebase/mod.rs:89`).
- `POST /v1/replacement-proposals` -> `{source_changeset_id,
  source_expected_revision, replacement_changeset_id, summary}`
  (`rebase/mod.rs:97`).
- `GET .../snapshot` -> `{changeset_id, history, latest,
  latest_validation}`; `GET .../conflicts`, `GET .../provenance` read-only.
- `POST /v1/proposals/{changeset_id}/submit` -> `{expected_revision,
  summary}` (`api/mod.rs:574`); the server composes validation plus
  approval-opening.
- Review and apply (engine/human side, listed for completeness):
  `/v1/review-queue`, `/v1/review-claims` (+ `respond`, `release`),
  `/v1/reviews/{approval_id}/decisions`, `/v1/apply-requests`,
  `/v1/rollback-proposals`, `/v1/direct-writes` (human-only).

Agent-tool plane:

- `GET /v1/agent-tools` -> catalog, unauthenticated snapshot
  (`handlers1.rs:39`).
- `POST /v1/agent-tools/prepare` -> payload `AgentToolCall`
  (`tools.rs:114`): `{tool_call_id, name, idempotency_key?, input}`; the
  payload-level idempotency_key is backfilled from the envelope's when
  absent (`handlers1.rs:51-54`).
- `POST /v1/agent-tools/{tool_call_id}/permission-decision` -> payload
  `{decision: ToolPermissionDecisionKind, comment?}` (`api/mod.rs:951`).
- `POST /v1/runs/{run_id}/agent-tools/execute` -> same `AgentToolCall`
  payload (`handlers3.rs:564`).

Interrupts and events:

- `POST /v1/interrupts/{interrupt_id}/resume` -> payload
  `{decision: Value}` - opaque JSON, replay-safe (`api/mod.rs:961`).
- `GET /v1/events` -> SSE (`stream.rs:62`), query `?last_seq=<i64>`
  (default 0), replays from the durable transactional outbox.
  `GET /v1/recovery` companion snapshot read with
  `?last_seq&session_id&run_id`; malformed id -> typed 400
  `authoring_recovery_request_invalid`.

### Two denial vocabularies (normative for our R2 denial)

In-domain business denials are HTTP 200 VALUES, not HTTP errors. The
`forbidden_actor` shape verbatim (test
`authoring/http/tests/group1.rs:397-434`; producer
`authoring/direct_write/mod.rs:419-442`):

- status 200; `data.status = "denied"`; `data.denial_kind =
  "forbidden_actor"` (machine-readable snake_case discriminator);
  `data.eligibility.reason` human-readable ("...agents must propose
  changesets"); `tiers` block present.
- `ActionEligibility` (`model.rs:394-399`): `{command, allowed, reason?}`.
  `DirectWriteDenialKind` (`direct_write/types.rs:102+`): `path_collision |
  stale_base | scope_mismatch | forbidden_actor | ...`.

Transport and identity failures ARE typed HTTP errors
(`ResolvedCommandRejection`, `http/mod.rs:161-231`): missing actor token ->
401 `authoring_actor_token_missing`; unknown/revoked token -> 401
`authoring_actor_token_unknown`; store unavailable -> 503
`authoring_store_unavailable`; malformed or unknown-field body -> 400
`authoring_request_invalid`; registered but unauthorized actor -> 403
`authoring_authorization_denied`.

The ACP fs-write denial in this repo mirrors the 200-value pattern: a
value-typed result with a snake_case `denial_kind` beside a human-readable
reason, never a bare exception or transport error.

### Pass-through template (informs the five-verb gateway)

From `/ops/rag/{verb}` (`routes/ops/mod.rs`): whitelist-first - an
unrecognized verb 403s BEFORE any I/O; field-by-field 400 validation of
bounded enums/ints before any transport (including a flag-injection guard
rejecting values starting with `-`); sibling envelope passed through
verbatim inside `{data:{envelope: ...}, tiers}` via `brokered_envelope()`;
a down sibling yields `{data:{envelope: null}, tiers: degraded_tiers()}` -
never a hard 5xx; subprocess verbs run under hard caps (8 MiB stdout, 120s
timeout); destructive verbs live behind a separate harsher broker with
dry-run-default. Our gateway endpoints should assume the engine treats us
exactly this way and shape responses accordingly.

### Discovery-file contract (normative for R8)

From the rag precedent (`rag-client/src/client.rs`):

- Candidate resolution order (`service_json_candidates`, line 52): a
  machine-global pointer wins even over a fresher per-scope file; missing
  candidates are skipped silently.
- `ServiceInfo` (line 82): `port: u16` REQUIRED; `service_token?`,
  `pid?: u32`, `last_heartbeat?` accepting i64 ms-epoch OR ISO-8601 string
  (untagged union), plus optional extra ports.
- Freshness: consumer staleness window `HEARTBEAT_STALE_MS = 120_000`;
  the producer refreshes every 15s with a 60s self-stale bound. Stale is
  treated as a crash, not as available.
- Outcome typing (`discover_kind`, line 422): `Fresh | Stale | Malformed |
  Absent` - only Fresh maps to Available, and only Absent licenses
  STARTING a new service; Crashed/Stale means attach-never-own, do not
  start.
- The split to replicate: hot-path reads use the cheap filesystem-only
  discover(); the heavier `/health` probe (`probe_machine_state()`, line
  476; `status == "ready"` case-insensitive is the sole liveness
  predicate) is reserved for lifecycle and ops callers, never per-response.

### Engine service operation runbook (W03 dependency)

Step-ordered operating procedure for a live engine process, kept as its own
subsection because W03 executors need the literal sequence, not prose
scattered across the transport/discovery sections above.

#### 1. Start procedure

Run `vaultspec serve` from a vaultspec-core-managed git worktree (has both
`.vault/` and `.vaultspec/`). Binary name `vaultspec`, built from crate
`engine/crates/vaultspec-cli` (`Cargo.toml:18`, `name = "vaultspec"`).
Default bind is `127.0.0.1:8767` (`DEFAULT_PORT`, `lib.rs:39`). On success
it prints `vaultspec serve: listening on http://127.0.0.1:8767 (bearer
token in service.json)` (`boot.rs:371`). Two dev/test escape hatches exist
for running concurrent instances outside the machine-singleton discipline:
`--port 0` (OS-assigned ephemeral port) and `--no-seat` (bypasses the
"seated" single-app-runtime claim) - both referenced at
`boot.rs:15,55,66,93` and `seat.rs:12`.

#### 2. Bearer semantics

The bearer token is never an env var, never a config value you set. It is
minted fresh at every boot from the OS CSPRNG (`mint_bearer()`,
`app.rs:1549`, 128-bit random via `getrandom::fill`) and published into the
discovery file's `service_token` field (`discovery.rs:75`,
`heartbeat_service_json`). There is no way to pre-set or predict it - a
client must start the service, then read the token back out of whichever
`service.json` it wrote. Two possible file locations depending on run mode:
a default "seated" serve writes the machine-global
`~/.vaultspec/service.json`; a `--no-seat` exempt serve writes
`<workspace>/.vault/<engine_data_dir>/service.json`
(`workspace_discovery_dir`, `discovery.rs:25-27`).

#### 3. No server-side auth relaxation (confirmed)

There is no `--dev`, `--insecure`, or environment flag that relaxes the
bearer or actor-token checks on a running `vaultspec serve` process. The
engine's own HTTP integration tests relax auth only by construction, never
by a runtime flag:

- They build an in-process `AppState` directly via `crate::app::
  build_state(dir)` and mount ONLY `authoring_router(state)`
  (`authoring/http/tests/helpers.rs:53,104`) - the outer `bearer_gate`
  middleware lives in the full `build_router()` assembly in `lib.rs`, so it
  is simply absent from the router under test.
- Per-actor auth still goes through the real production path:
  `register_actor` + `issue_token_in_state` (`authoring/http/tests/
  helpers2.rs:254`) call the actual `ActorTokenRepository::issue()` store
  logic to mint a genuine token, then drive requests through the real axum
  `Router` via `tower::ServiceExt::oneshot` with that token in the
  `x-authoring-actor-token` header.
- Lower-level tests construct `ResolvedCommand::from_principal(principal,
  envelope)` directly, bypassing the HTTP extractor/header entirely - an
  in-process shortcut, not a server mode.

Conclusion: integration testing against a REAL running engine has no
shortcut around the full auth sequence in step 4.

#### 4. The 7-step W03 startup runbook

1. Ensure the target directory is a vaultspec-core-managed git worktree
   (has `.vault/` + `.vaultspec/`).
2. Run `vaultspec serve` from that worktree; wait for the "listening on
   http://127.0.0.1:8767" line, or poll the discovery file's `state` field
   until `"ready"` (mirrors the rag pattern above - don't assume "file
   exists" means "ready").
3. Read the discovery file (`~/.vaultspec/service.json` for a default
   seated serve, or `<workspace>/.vault/<engine_data_dir>/service.json` for
   a `--no-seat`/exempt serve) and extract `port` + `service_token` - do
   not hardcode 8767 or assume default, since a prior `--no-seat` run can
   leave a stale file recording a different port (see the live specimen
   below).
4. **Never trust the file without a liveness check.** Verify freshness
   (heartbeat age against the staleness window) AND confirm the process is
   actually alive - or better, attempt a genuine `GET /health` and require
   a real 200. A stale file with a plausible-looking `state: "ready"` is
   not evidence of a running service (see the specimen below).
5. Use `service_token` as `Authorization: Bearer <token>` for every
   request.
6. `POST /authoring/v1/actor-tokens` (bearer-gated only, no per-actor token
   needed yet) with `{"actor": {"id": "...", "kind": "agent"}}` to mint the
   per-actor token; use it as `x-authoring-actor-token` on every subsequent
   authoring call.
7. If starting fresh (no stale file, or a confirmed-dead one), no manual
   cleanup is required - the engine's own `remove_service_json_if_owned`
   boot-time logic reclaims a stale file itself. Never delete it by hand.

#### 5. Observed live specimen (evidence for attach-never-own)

Recon performed 2026-07-14 against this machine found `~/.vaultspec/
service.json` present but describing a service that was NOT actually
running:

- File contents (token redacted): `state: "ready"`, `port: 8823` (not the
  default 8767 - an earlier `--no-seat` ephemeral-port run), `pid: 20372`,
  `last_heartbeat` roughly 20.5 hours stale.
- `Get-Process -Id 20372` confirmed the PID does not exist on this machine.
- `GET /health` against both the default port 8767 and the file's recorded
  port 8823 refused the connection (curl exit 7) on both.
- By the engine's own discovery-outcome typing (`Fresh | Stale | Malformed
  | Absent`, `rag-client/src/client.rs:422` pattern mirrored here), this is
  a **Crashed** state, not **Absent** - something died without cleaning up
  its own discovery file. Treating a present-and-plausible-looking
  `service.json` as sufficient proof of a running service would have been
  wrong; only step 4's liveness check catches this. This is the concrete
  case the attach-never-own discipline (R8) exists to guard against.

### Live catalog snapshot (2026-07-14)

Read-only W03 pre-flight probe against a live engine instance (GET-only,
no sessions/proposals/tokens created). Discovery: the machine-global
`~/.vaultspec/service.json` was stale (port 8823, pid 20372, confirmed
not running -- the same specimen documented above). The live instance
was found via the workspace-local exempt-serve file instead --
`Y:/code/vaultspec-dashboard-worktrees/main/.vault/data/engine-data/
service.json` -- `port: 8767`, `pid: 29664` (confirmed running via
`Get-Process`), heartbeat 7s old at read time, `state: "ready"`. Bearer
read from this file, never printed; referred to below as `<bearer>`.

- `GET /health` (ungated): `{"data":{"ok":true,"service":"vaultspec",
  "status":"running"},"tiers":{"declared":{"available":true},
  "semantic":{"available":true},"structural":{"available":true},
  "temporal":{"available":true}}}` -- exactly matches the `health()`
  handler documented in `lib.rs`; no `pid`/`schema_version` fields
  appear here (those belong to a DIFFERENT struct -- rag's own
  `HealthInfo`, used by the discovery-file health probe in Discovery
  section above -- not this engine's own liveness ping). No divergence.

- `GET /authoring/v1/agent-tools` (with `<bearer>`) -- the tool catalog
  our R4 bridge must mirror, `schema_version:
  "authoring.semantic_tools.v1"`, 7 tools, verbatim (no token-ish
  fields present):

  ```json
  {
    "data": {
      "schema_version": "authoring.semantic_tools.v1",
      "tools": [
        {
          "name": "read_context",
          "commands": ["read_context"],
          "description": "Read bounded authoring context without side effects.",
          "permission_requirement": "auto_permitted",
          "risk_tier": "read_only",
          "idempotency_required": false,
          "input_schema": {
            "additionalProperties": false,
            "oneOf": [
              {"target": "document", "required": ["document"], "optional": ["revision", "max_bytes"]},
              {"target": "proposal", "required": ["changeset_id"], "optional": ["max_bytes"]},
              {"target": "session", "required": ["session_id"], "optional": ["max_bytes"]},
              {"target": "document_list", "optional": ["cursor", "cap"]}
            ]
          }
        },
        {
          "name": "search_graph",
          "commands": ["search_graph"],
          "description": "Search the bounded project graph for authoring context.",
          "permission_requirement": "auto_permitted",
          "risk_tier": "read_only",
          "idempotency_required": false,
          "input_schema": {
            "additionalProperties": false,
            "required": ["query"],
            "optional": ["scope", "type", "max_results"],
            "bounds": {"max_results": 50, "query_chars_max": 512, "scope_chars_max": 256, "target": ["vault", "code"]}
          }
        },
        {
          "name": "propose_changeset",
          "commands": ["create_proposal", "append_draft", "replace_draft"],
          "description": "Create a proposal changeset through the backend authoring ledger.",
          "permission_requirement": "human_approval_required",
          "risk_tier": "mutating",
          "idempotency_required": true,
          "input_schema": {
            "additionalProperties": false,
            "oneOf": [
              {"operation": "create", "payload": "CreateProposalRequest"},
              {"operation": "append", "alias_of": "append_draft"},
              {"operation": "replace", "alias_of": "replace_draft"}
            ]
          }
        },
        {
          "name": "validate_proposal",
          "commands": ["validate_proposal"],
          "description": "Request backend validation for a proposal without applying it.",
          "permission_requirement": "human_approval_required",
          "risk_tier": "mutating",
          "idempotency_required": true,
          "input_schema": {
            "additionalProperties": false,
            "alias_of": "validate_proposal",
            "required": ["changeset_id", "expected_revision", "summary"],
            "backend_derived": ["current_revisions", "chunk_evidence"]
          }
        },
        {
          "name": "request_approval",
          "commands": ["submit_for_review"],
          "description": "Submit a validated proposal into backend-owned human review.",
          "permission_requirement": "human_approval_required",
          "risk_tier": "mutating",
          "idempotency_required": true,
          "input_schema": {
            "additionalProperties": false,
            "alias_of": "submit_for_review",
            "payload": "RequestApprovalToolInput",
            "required": ["changeset_id", "expected_revision", "summary"],
            "composes": ["validate_proposal", "submit_for_review", "open_approval"]
          }
        },
        {
          "name": "cancel",
          "commands": ["cancel_proposal", "cancel_run"],
          "description": "Cancel a proposal or run through semantic authoring state.",
          "permission_requirement": "human_approval_required",
          "risk_tier": "mutating",
          "idempotency_required": true,
          "input_schema": {
            "additionalProperties": false,
            "oneOf": [
              {"target": "proposal", "required": ["changeset_id", "expected_revision", "summary"]},
              {"target": "run", "required": ["run_id", "reason"]}
            ]
          }
        },
        {
          "name": "request_apply",
          "commands": ["request_apply"],
          "description": "Request application of an approved proposal through the apply boundary.",
          "permission_requirement": "human_approval_required",
          "risk_tier": "dangerous",
          "idempotency_required": true,
          "input_schema": {
            "additionalProperties": false,
            "alias_of": "request_apply",
            "payload": "ApplyRequest"
          }
        }
      ]
    },
    "tiers": { "...": "see envelope note below" }
  }
  ```

  Note the semantic-level tool names (`read_context`, `search_graph`,
  `propose_changeset`, `validate_proposal`, `request_approval`,
  `cancel`, `request_apply`) are a HIGHER-LEVEL vocabulary than the wire
  route names documented above (`create_proposal`, `submit_for_review`,
  etc. appear as `commands`/aliases underneath, not as the top-level
  `name`). Our R4 bridge should mirror `name` + `input_schema` +
  `risk_tier` + `permission_requirement`, not assume a 1:1 mapping to
  route paths.

- `GET /authoring/v1/sessions` (with `<bearer>`) -- ADDITION to the
  route table above (the list envelope shape wasn't captured there):
  `{"data":{"cap":50,"items":[],"truncated":false},"tiers":{...}}`. No
  `next_cursor` present (optional, absent here since `items` is empty).

- `GET /authoring/v1/events?last_seq=0` (with `<bearer>`) -- confirmed
  `200 OK`, `content-type: text/event-stream`, connection established
  and held open (chunked transfer, no immediate frames since there are
  zero active sessions to replay) -- matches the SSE behavior documented
  above verbatim. No divergence.

- **Negative probe 1** -- bogus route WITH bearer,
  `GET /authoring/v1/nonexistent-route-xyz`: **404**,
  `{"error":"unknown API path \`/v1/nonexistent-route-xyz\`",
  "error_kind":"authoring_unknown_route","tiers":{...}}`. **File-worthy
  addition**: `authoring_unknown_route` is a SIXTH `error_kind`, not
  previously documented alongside the five `ResolvedCommandRejection`
  kinds above (`authoring_actor_token_missing`,
  `authoring_actor_token_unknown`, `authoring_store_unavailable`,
  `authoring_request_invalid`, `authoring_authorization_denied`). Note
  the error message reports the path relative to the `/authoring` nest
  point (`/v1/...`, not `/authoring/v1/...`).
- **Negative probe 2** -- `GET /authoring/v1/agent-tools` WITHOUT any
  bearer header: **401**, `{"error":"Unauthorized","tiers":{...}}`.
  **File-worthy confirmation**: no `error_kind` field at all here --
  this is the OUTER machine `bearer_gate` (`app.rs:1402-1441`, which
  returns a bare `StatusCode::UNAUTHORIZED` per its own signature),
  distinct from the INNER actor-token-layer denials
  (`authoring_actor_token_missing`, etc.) which DO carry `error_kind`.
  Confirms the two-layer auth model produces two genuinely different
  error shapes depending on which layer refuses the request -- useful
  for the R4 bridge to distinguish "wrong machine bearer" from "wrong/
  missing actor token" without guessing from status code alone (both
  are 401).

### Scope note

Not covered field-by-field: review/lease/comment/langgraph routes and the
full apply-requests/rollback-proposals bodies. The pattern (CommandEnvelope,
expected_revision fences, denial-kind-as-value) is consistent across the
domain, but unverified structs must be read in the Rust source before
coding against them.
