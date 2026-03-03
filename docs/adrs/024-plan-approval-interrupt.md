---
adr_id: 024
title: Plan Approval Interrupt
date: 2026-03-03
status: Proposed
related:
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/022-contextual-anchoring-graph-lifecycle.md
  - docs/adrs/023-phase-artifact-gates.md
  - docs/adrs/025-mandatory-review-gate.md
---

# ADR-024: Plan Approval Interrupt

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

D-02 from the vaultspec rule drift audit: no human-in-the-loop approval gate
exists before the plan→exec phase transition. The `framework.md` mandate is
explicit: "The user must approve plans before execution proceeds."

ADR-023 ensures a plan artifact exists before exec routing (HARD gate:
`vault_index["plan"]` must be non-empty). ADR-024 is the complementary gate:
it ensures the plan has been **approved by the user** before execution
proceeds. The two gates are sequential at the exec boundary:

- ADR-023: blocks exec routing when there is no plan (can't approve what
  doesn't exist).
- ADR-024: pauses exec routing when a plan exists but has not yet been
  approved.

The existing `interrupt()` mechanism handles ACP tool call permissions inside
worker nodes. This ADR extends the interrupt pattern to handle plan approval —
a supervisor-level interrupt triggered by graph state (exec routing detected),
not by ACP tool output.

## 2. Decision

### 2.1 New TeamState Field: `plan_approved`

```python
class TeamState(TypedDict):
    # ... existing fields ...

    # Set to True once the user approves the plan for execution.
    # Prevents the plan approval interrupt from re-triggering on subsequent
    # exec routing decisions within the same thread.
    # NotRequired: legacy threads without this field default to False (unapproved).
    plan_approved: NotRequired[bool]
```

Uses last-write-wins (default LangGraph semantics — no reducer). `NotRequired`
because existing checkpoint rows without this field must default to `False` at
read time — the gate fires on the first exec routing attempt in any thread
where the plan has not yet been approved.

Once set to `True`, `plan_approved` persists for the thread's lifetime in the
checkpointer. This is a per-session, one-time gate.

### 2.2 Trigger Location

The plan approval interrupt fires inside `supervisor_node`
(`lib/core/nodes/supervisor.py`). When the supervisor routes to an exec
worker, a plan artifact exists, and `plan_approved` is not yet `True`, the
supervisor calls `interrupt()` before returning the routing decision:

```python
if (next_route in exec_workers
        and vault_index.get("plan")
        and not state.get("plan_approved")):
    resume_value = interrupt({
        "type": "plan_approval_request",
        "feature": state.get("active_feature"),
        "plan_paths": vault_index.get("plan", []),
        "exec_worker": next_route,
    })
    if resume_value.get("approved"):
        return {"next": next_route, "plan_approved": True,
                "pipeline_phase": inferred_phase}
    else:
        return {"next": workers[0], "pipeline_phase": inferred_phase,
                "routing_error": "Plan rejected by user — revise before proceeding to execution."}
```

This is consistent with the `interrupt_before=[]` architectural constraint
(CLAUDE.md): all interrupts must be triggered from inside nodes, not as
graph-level pre-node pauses.

### 2.3 Interrupt Payload

```python
interrupt({
    "type": "plan_approval_request",
    "feature": state.get("active_feature"),
    "plan_paths": vault_index.get("plan", []),
    "exec_worker": next_route,
})
```

The payload carries enough context for the UI to render a useful approval
modal: the active feature name, the list of plan document paths for the user
to review, and which exec worker will be invoked on approval.

The `PermissionRequestEvent` schema already supports arbitrary `options` with
`option_id`, `name`, and `kind` fields. Plan approval uses:

- `option_id: "approve"`, `name: "Approve Plan"`, `kind: ALLOW_ONCE`
- `option_id: "reject"`, `name: "Reject — Revise Plan"`, `kind: DENY_ONCE`

### 2.4 Resume Flow

**Approval path:**

1. User clicks "Approve Plan" → `POST /api/permissions/{request_id}/respond`
   with `option_id: "approve"`.
2. Endpoint dispatches `Command(resume={"approved": True})` to the interrupted
   graph.
3. Supervisor node replays; `interrupt()` returns `{"approved": True}`.
4. Supervisor sets `plan_approved: True` in state and routes to the exec
   worker.
5. `plan_approved: True` persists in the checkpointer — subsequent exec
   routing decisions in this thread proceed without re-triggering the
   interrupt.

**Rejection path:**

1. User clicks "Reject — Revise Plan" → `POST /api/permissions/{request_id}/respond`
   with `option_id: "reject"`.
2. Endpoint dispatches `Command(resume={"approved": False})`.
3. Supervisor node replays; `interrupt()` returns `{"approved": False}`.
4. Supervisor reroutes to `workers[0]` with a `routing_error` stating the plan
   was rejected and requires revision. The supervisor LLM determines which plan
   worker to invoke on the next pass.
5. `plan_approved` remains absent or `False` — the next exec routing attempt
   will re-trigger the interrupt.

### 2.5 `autonomous=True` Behaviour

The plan approval interrupt is **skipped** when `autonomous=True`. No human is
present in autonomous mode (headless MCP-launched execution); the interrupt
would block indefinitely with no user to respond.

The supervisor checks `autonomous` (captured in the node closure at
compilation time) before calling `interrupt()`. When `autonomous=True`,
`plan_approved` is implicitly treated as `True` and routing proceeds to the
exec worker without interruption.

This follows the same pattern as ACP permission approvals: `autonomous=True`
leaves `permission_callback` unwired, causing ACP tool calls to auto-approve.
Plan approval follows the same design — autonomous bypasses human-in-the-loop
gates, not quality artifact gates.

### 2.6 No `active_feature` Behaviour

The gate is skipped when `active_feature` is `None`. The thread is not
SDD-bound; the plan approval mandate does not apply. This is consistent with
ADR-023 and ADR-025.

### 2.7 Execution Order in `supervisor_node`

The full gate chain in `supervisor_node`, in order of execution:

1. **ADR-022:** `validation_errors` → block FINISH if validation errors are present.
2. **ADR-025:** `vault_index["audit"]` → block FINISH if no review artifact exists.
3. **ADR-023:** Phase prerequisites → block out-of-order routing (e.g., exec without plan).
4. **ADR-024:** Plan approval → interrupt before exec routing when plan exists but is unapproved.

ADR-023 and ADR-024 are complementary at the exec boundary: if ADR-023 fires
(no plan artifact), ADR-024 is irrelevant. If ADR-023 passes (plan exists),
ADR-024 checks for approval.

### 2.8 `_emit_interrupt_events` Extension

`aggregator.py`'s `_emit_interrupt_events()` currently detects payloads with
`type == "permission_request"` to emit `PermissionRequestEvent` to WebSocket
clients. It must be extended to handle `type == "plan_approval_request"`:

```python
if payload.get("type") in ("permission_request", "plan_approval_request"):
    # build and emit PermissionRequestEvent with appropriate options
```

For `plan_approval_request` payloads, the emitted `PermissionRequestEvent`
carries approve and reject options. The UI permission modal is extended to
render plan context (feature name, plan document paths) when the interrupt type
is `plan_approval_request`.

### 2.9 Per-Session One-Time Semantics

`plan_approved = True` persists for the thread's lifetime once set. Future v2
can clear it when new plan artifacts are written (worker returns
`{"plan_approved": False}`) to re-trigger approval after a plan revision. This
requires plan-writing workers to explicitly clear the flag — a node
implementation contract not enforced structurally in v1.

In v1, the simpler once-only semantics are acceptable: plan revisions within a
thread are uncommon, and the user can always trigger re-approval by rejecting
on the next exec routing attempt.

## 3. Consequences

### Positive

- Human-in-the-loop approval at the plan→exec boundary, fulfilling the
  `framework.md` mandate.
- Reuses the existing `interrupt()` / resume machinery and `PermissionRequestEvent`
  schema — no new IPC mechanisms required.
- Autonomous mode correctly bypasses the interrupt (no human present to approve)
  while non-autonomous threads are always gated.
- One-time per-session semantics prevent repeated approval prompts for the same
  plan.

### Negative / Trade-offs

- Supervisor node replay on resume means the LLM is re-invoked. The routing
  decision must be re-parsed on every resume. The `plan_approved` flag in state
  prevents re-triggering the interrupt, but the LLM call cost is paid on replay.
- `_emit_interrupt_events` must be extended to handle the new
  `"plan_approval_request"` interrupt type — a second detection branch alongside
  the existing `"permission_request"` branch.
- Adds `plan_approved: NotRequired[bool]` to `TeamState` — a new field with
  `NotRequired` semantics that consuming code must read defensively with
  `.get("plan_approved")`.
- v1 does not re-trigger the interrupt when the plan is revised after approval.
  Workers that revise plans must explicitly clear `plan_approved` to enforce
  re-approval — this is a convention, not structural enforcement.

## 4. Rejected Alternatives

### Dedicated `plan_approval_node` Between Supervisor and Exec Workers

A new `plan_approval_node` sits between the supervisor's conditional edge and
each exec worker, triggering the interrupt unconditionally on first invocation.
Rejected: adds another node per exec worker on top of ADR-020 mount nodes,
increasing graph compilation complexity. Rejection routing requires the Command
API (`Command(goto="supervisor")`), changing the node's return type and
introducing a non-standard pattern. The supervisor-inline approach keeps all
routing logic in one location.

### Pre-Node `interrupt_before` Pause

Use LangGraph's `interrupt_before` at graph compilation to pause before exec
worker nodes. Rejected: violates the `interrupt_before=[]` architectural
constraint established in CLAUDE.md (overriding ADR-013 §2.7). All interrupts
must originate from inside nodes using `interrupt()`.

### Per-Plan-Revision Re-Approval

Clear `plan_approved` automatically whenever a new plan artifact is written to
`vault_index["plan"]`, forcing re-approval after every plan revision. Deferred
to v2: requires the `_merge_vault_index` reducer or a new plan-write detection
mechanism to trigger the clear. The node implementation contract (workers
explicitly returning `{"plan_approved": False}`) is fragile and not
structurally enforced. Per-session once-only semantics are sufficient for v1.

## 5. Implementation Constraints

- `plan_approved: NotRequired[bool]` added to `TeamState` (`lib/core/state.py`).
  Last-write-wins, no reducer. Consuming code uses `.get("plan_approved")` to
  handle absent field on legacy threads.
- Interrupt triggers inside `supervisor_node`, not in a separate node.
- `autonomous=True` → skip interrupt, proceed as if `plan_approved: True`. The
  `autonomous` flag is captured in the supervisor node closure at compilation.
- `_emit_interrupt_events` (`lib/core/aggregator.py`) extended to handle
  `type == "plan_approval_request"` payloads, emitting `PermissionRequestEvent`
  with approve (`ALLOW_ONCE`) and reject (`DENY_ONCE`) options.
- Resume payload is `{"approved": True}` or `{"approved": False}` — the
  interrupt consumer checks `resume_value.get("approved")`.
- The interrupt fires only when all three conditions hold: routing to exec
  worker, `vault_index["plan"]` non-empty, `not state.get("plan_approved")`.

## 6. Module Hierarchy Impact

```text
lib/core/
  state.py              AMENDED: plan_approved: NotRequired[bool] added to TeamState

  nodes/supervisor.py   AMENDED: plan approval interrupt in supervisor_node,
                        after ADR-023 phase prerequisite checks, before
                        returning exec routing decision; autonomous closure
                        captured at create_supervisor_node() compilation

  aggregator.py         AMENDED: _emit_interrupt_events() handles
                        type == "plan_approval_request" payloads;
                        emits PermissionRequestEvent with approve/reject options

  tests/test_graph.py   AMENDED: test cases for plan approval gate —
                        interrupt fires on first exec routing with plan present,
                        approve path sets plan_approved and routes to exec,
                        reject path reroutes with routing_error,
                        gate skipped in autonomous mode,
                        gate skipped when active_feature is None,
                        gate not re-triggered when plan_approved is True

lib/api/
  schemas/rest.py       AMENDED (if needed): PermissionRequestEvent options
                        for plan approval (approve/reject option_id values)
```

## 7. References

- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — D-02
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md` — "The user must approve plans before execution proceeds"
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) — TeamState field patterns; `NotRequired` precedent
- [ADR-022](022-contextual-anchoring-graph-lifecycle.md) — `validation_errors` FINISH gate; gate ordering reference
- [ADR-023](023-phase-artifact-gates.md) — phase prerequisite gate at plan→exec boundary (complementary)
- [ADR-025](025-mandatory-review-gate.md) — review artifact FINISH gate; gate ordering reference
- [docs/research/2026-03-03-plan-approval-interrupt-research.md](../research/2026-03-03-plan-approval-interrupt-research.md) — interrupt mechanism analysis, option comparison, resume flow, autonomous interaction
- `lib/core/nodes/worker.py` — `_interrupt_permission_callback`, existing interrupt pattern
- `lib/core/aggregator.py:1023` — `_emit_interrupt_events`, interrupt payload detection
- `lib/api/endpoints.py:722` — `respond_to_permission_endpoint`, resume via REST
