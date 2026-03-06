---
title: 'Research: Plan Approval Interrupt'
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: 'How to implement a human-in-the-loop plan approval gate at the plan→exec boundary. Integration with existing interrupt mechanism. Research for ADR-024.'
---

# Research: Plan Approval Interrupt

**Date:** 2026-03-03

## Summary

D-02 in the vaultspec rule drift audit: no human-in-the-loop approval gate before
transitioning from plan to exec. The `framework.md` mandate: "The user must approve
plans before execution proceeds." This document researches how the plan approval
interrupt should integrate with the existing `interrupt()` mechanism and the ADR-023
phase artifact gate.

---

## 1. Existing Interrupt Mechanism

### 1.1 How `interrupt()` Works in This Codebase

The existing interrupt mechanism is implemented in `src/vaultspec_a2a/core/nodes/worker.py` via
`_interrupt_permission_callback`:

```python
async def _interrupt_permission_callback(tool_name, tool_input, options) -> str:
    resume_value = interrupt({
        "type": "permission_request",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "options": options,
    })
    # ... validate and return option_id
```

When `interrupt()` is called inside a LangGraph node:

1. LangGraph raises `GraphInterrupt` (a `GraphBubbleUp` subclass) — the node re-raises it
2. The graph suspends to the checkpointer
3. The `finally` block in `aggregator.ingest()` calls `_emit_interrupt_events()`
4. `_emit_interrupt_events()` inspects `state.tasks[].interrupts[]` for payloads with `type == "permission_request"`
5. A `PermissionRequestEvent` is emitted to WebSocket clients with `request_id = "{thread_id}:{uuid}"`
6. The UI shows the permission modal

**Resume path:**

1. User responds via `POST /api/permissions/{request_id}/respond` with `option_id`
2. Endpoint dispatches a `DispatchRequest(action="resume", option_id=...)` to the worker
3. Worker calls `Command(resume=option_id)` on the interrupted graph
4. LangGraph replays the interrupted node; `interrupt()` returns the stored `option_id` instead of raising
5. `_interrupt_permission_callback` returns the `option_id` to the ACP model

### 1.2 Current Interrupt Scope

The current interrupt is exclusively for **ACP tool call approval** — it fires inside
the worker node when an ACP agent requests permission to use a tool. The interrupt
payload type is `"permission_request"` and the options are ACP-provided (allow_once,
deny_once, allow_always, etc.).

**The plan approval interrupt is different in nature:**

- It fires at the **supervisor level**, not the worker level
- It fires based on **graph state** (exec routing detected), not ACP tool output
- The options are binary: **approve** (proceed to exec) or **reject** (reroute to plan)
- It is a **one-time gate** per session, not per tool call

### 1.3 `interrupt_before=[]` Architectural Constraint

The `interrupt_before=[]` decision (CLAUDE.md, overriding ADR-013 §2.7) means no
pre-node graph pauses. Interrupts must be triggered from **inside** nodes using
`interrupt()`. The plan approval interrupt must therefore be called from within a
node, not as a graph-level pre-node pause.

---

## 2. Where to Trigger the Plan Approval Interrupt

### Option A: Inside `supervisor_node`

The supervisor node detects that it is routing to exec for the first time and calls
`interrupt()` before returning the routing decision.

```python
async def supervisor_node(state: TeamState) -> dict[str, Any]:
    # ... phase inference, anchoring, LLM invocation, route parsing ...

    if next_route in exec_workers and vault_index.get("plan") and not state.get("plan_approved"):
        resume_value = interrupt({
            "type": "plan_approval_request",
            "plan_paths": vault_index.get("plan", []),
            "exec_worker": next_route,
        })
        if resume_value.get("approved"):
            return {"next": next_route, "plan_approved": True, "pipeline_phase": inferred_phase}
        else:
            return {"next": "FINISH", "pipeline_phase": inferred_phase,
                    "routing_error": "Plan rejected by user — returning to FINISH"}
```

**Pros:**

- Single location for approval logic
- Supervisor has all needed context (vault_index, next_route)
- Consistent with `interrupt_before=[]` constraint

**Cons:**

- Supervisor node currently uses `TAG_NOSTREAM` (responses not streamed) — the interrupt payload needs to reach the aggregator's `_emit_interrupt_events` machinery, which looks for `type == "permission_request"` specifically. A new `type == "plan_approval_request"` requires extending `_emit_interrupt_events` to handle it.
- Replaying the supervisor node on resume means the LLM is re-invoked — the routing decision must be re-parsed. The `plan_approved` flag in state prevents re-triggering the interrupt.

### Option B: Dedicated `plan_approval_node` between supervisor and exec workers

A new node `plan_approval_node` sits between the supervisor's conditional edge and
each exec worker. It triggers the interrupt unconditionally on first invocation.

```python
async def plan_approval_node(state: TeamState) -> dict[str, Any]:
    if state.get("plan_approved"):
        return {}  # already approved, pass through
    resume_value = interrupt({
        "type": "plan_approval_request",
        "plan_paths": state.get("vault_index", {}).get("plan", []),
    })
    if resume_value.get("approved"):
        return {"plan_approved": True}
    # Rejected: how to re-route? Cannot change `next` from inside a non-supervisor node
    # without using Command API
    from langgraph.types import Command
    return Command(update={"plan_approved": False}, goto="supervisor")
```

**Pros:**

- Clean separation — plan approval is its own node, not mixed into supervisor logic
- Supervisor replay is avoided — `plan_approval_node` replays on resume, not the supervisor

**Cons:**

- Adds another node per exec worker (on top of ADR-020 mount nodes)
- Rejection requires `Command(goto="supervisor")` — uses the Command API, changing the return type of the node
- Must be wired into graph compilation (ADR-020 style: `supervisor → plan_approval_{worker} → exec_worker`)

### Recommendation: Option A (supervisor-inline interrupt)

Option A is simpler and keeps all routing logic in the supervisor. The key implementation detail:

1. Add `plan_approved: NotRequired[bool]` to `TeamState`
2. Supervisor checks `not state.get("plan_approved")` before triggering the interrupt
3. Extend `_emit_interrupt_events` in `aggregator.py` to handle `type == "plan_approval_request"` payloads
4. On resume with `approved=True`, supervisor sets `{"plan_approved": True}` in state and routes to exec
5. On resume with `approved=False`, supervisor routes back to plan worker or FINISH

---

## 3. What Information to Present to the User

The interrupt payload should include enough for the UI to render a useful approval modal:

```python
interrupt({
    "type": "plan_approval_request",
    "feature": state.get("active_feature"),
    "plan_paths": vault_index.get("plan", []),  # list of plan document paths
    "exec_worker": next_route,                   # which worker will execute
    "task_queue_path": f".vault/plan/{active_feature}-queue.md"  # if exists
})
```

The UI permission modal (already implemented for ACP tool approvals) can be extended
to render:

- Feature name and plan document paths as links
- Task queue summary (if available)
- Two options: "Approve — proceed to execution" and "Reject — revise the plan"

The `PermissionRequestEvent` schema already supports arbitrary `options` with
`option_id`, `name`, and `kind` fields. The plan approval can use:

- `option_id: "approve"`, `name: "Approve Plan"`, `kind: ALLOW_ONCE`
- `option_id: "reject"`, `name: "Reject — Revise Plan"`, `kind: DENY_ONCE`

---

## 4. User Approval/Rejection Flow

**Approval:**

1. User clicks "Approve Plan" → `POST /api/permissions/{request_id}/respond` with `option_id: "approve"`
2. Worker dispatches `Command(resume={"approved": True})` to interrupted graph
3. Supervisor receives resume, sets `plan_approved: True`, routes to exec worker
4. `plan_approved: True` in state prevents re-triggering on subsequent exec routing

**Rejection:**

1. User clicks "Reject — Revise Plan" → `POST /api/permissions/{request_id}/respond` with `option_id: "reject"`
2. Worker dispatches `Command(resume={"approved": False})`
3. Supervisor routes back to the plan worker (or to the worker the LLM selects given the rejection context)
4. `plan_approved` remains `False` (or absent) — next exec routing attempt will re-trigger the interrupt

---

## 5. One-Time vs. Per-Session Gate

**Recommendation: Per-session, one-time gate.**

The `plan_approved: bool` flag in `TeamState` persists in the checkpointer for the
thread's lifetime. Once approved in a session, subsequent exec routing decisions in
the same thread proceed without re-interrupting.

If the plan is substantially revised after approval (new plan artifact written),
the gate should re-trigger. Implementation: clear `plan_approved` when a new plan
artifact is written (worker returns `{"plan_approved": False}`). This requires
workers that write plan artifacts to explicitly clear the flag — a node implementation
contract, not a structural enforcement.

For v1, the simpler approach is: per-session once-only. Once `plan_approved = True`
is set in the thread's state, it persists for the entire thread. This is acceptable
because plan revisions within a thread are relatively rare and the user can always
manually trigger a new approval by rejecting and re-approving.

---

## 6. `autonomous=True` Interaction

When `autonomous=True`, the plan approval interrupt should be **skipped entirely**.
`autonomous=True` is the headless MCP-launched mode — there is no human present to
approve. The graph should proceed to exec without interruption.

Implementation: the supervisor checks `autonomous` (passed at node creation time via
the closure) before calling `interrupt()`. If `autonomous=True`, set
`plan_approved: True` implicitly and route to exec without interrupting.

This is the same pattern as `_interrupt_permission_callback` — `autonomous=True`
leaves the ACP `permission_callback` unwired, so tool calls auto-approve. The plan
approval gate follows the same design.

---

## 7. Integration with ADR-023 Phase Artifact Gate

ADR-023 (phase artifact gates) checks that `vault_index["plan"]` is non-empty before
routing to exec. ADR-024 (plan approval interrupt) fires when routing to exec AND a
plan exists AND approval has not yet been given.

Execution order in `supervisor_node`:

1. Parse LLM routing decision → `next_route`
2. ADR-022: check `validation_errors` → block FINISH if errors
3. ADR-025: check `vault_index["audit"]` → block FINISH if no review artifact
4. ADR-023: check phase prerequisites → block if plan missing before exec routing
5. ADR-024: check plan approval → interrupt if routing to exec without approval

ADR-023 and ADR-024 are complementary at the exec boundary:

- ADR-023 blocks exec routing when there is NO plan (hard gate — can't execute without a plan)
- ADR-024 pauses exec routing when there IS a plan but it hasn't been approved yet

If ADR-023 fires (no plan), ADR-024 is irrelevant — there's nothing to approve.
If ADR-023 passes (plan exists), ADR-024 checks for approval.

---

## 8. New TeamState Field Required

```python
class TeamState(TypedDict):
    # ... existing fields ...

    # Set to True once the user approves the plan for execution.
    # Prevents the plan approval interrupt from re-triggering on subsequent exec routing.
    # Cleared to False (or absent) when a new plan artifact is written.
    plan_approved: NotRequired[bool]
```

Uses last-write-wins (default LangGraph semantics). `NotRequired` because legacy
threads without this field should default to `False` (unapproved) — the gate fires
on first exec routing attempt.

---

## 9. References

- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — D-02
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md` — "The user must approve plans before execution proceeds"
- `src/vaultspec_a2a/core/nodes/worker.py` — `_interrupt_permission_callback`, existing interrupt pattern
- `src/vaultspec_a2a/core/aggregator.py:1023` — `_emit_interrupt_events`, interrupt payload detection
- `src/vaultspec_a2a/api/endpoints.py:722` — `respond_to_permission_endpoint`, resume via REST
- [ADR-023](../adrs/023-phase-artifact-gates.md) — prerequisite gate at plan→exec boundary
- [ADR-022](../adrs/022-contextual-anchoring-graph-lifecycle.md) — validation_errors gate (ordering reference)
- [ADR-025](../adrs/025-mandatory-review-gate.md) — review artifact gate (ordering reference)
- [ADR-019](../adrs/019-teamstate-enrichment-sdd-blackboard.md) — TeamState field pattern
