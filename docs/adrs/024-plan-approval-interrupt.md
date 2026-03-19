---
adr_id: 024
title: Plan Approval Interrupt
date: 2026-03-03
status: Revised
related:
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/022-contextual-anchoring-graph-lifecycle.md
  - docs/adrs/023-phase-artifact-gates.md
  - docs/adrs/025-mandatory-review-gate.md
---

## ADR-024: Plan Approval Interrupt

**Date:** 2026-03-03
**Status:** Revised (supersedes supervisor-inline interrupt — see §2.2, §4)

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
a dedicated graph node triggered by the supervisor's conditional edge when exec
routing with an unapproved plan is detected.

**Revision note:** The original design placed the `interrupt()` call inside
`supervisor_node` conditionally. This violates LangGraph's index-based resume
contract: on replay, the supervisor LLM is re-invoked and may produce a
different `next_route`, causing the conditional guard to evaluate differently
and the `interrupt()` call to be skipped entirely. The corrected design places
the interrupt in a dedicated `plan_approval_node` that calls `interrupt()`
unconditionally when entered — matching the documented LangGraph approval node
pattern (<https://docs.langchain.com/oss/python/langgraph/interrupts>).

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
```text

Uses last-write-wins (default LangGraph semantics — no reducer). `NotRequired`
because existing checkpoint rows without this field must default to `False` at
read time — the gate fires on the first exec routing attempt in any thread
where the plan has not yet been approved.

Once set to `True`, `plan_approved` persists for the thread's lifetime in the
checkpointer. This is a per-session, one-time gate.

### 2.2 Trigger Location — Dedicated `plan_approval_node`

The plan approval interrupt fires inside a **dedicated `plan_approval_node`**,
not inside `supervisor_node`. The supervisor's conditional edge routes to this
node when the approval gate conditions are met. Once entered, the node calls
`interrupt()` unconditionally.

This matches the documented LangGraph pattern for human-in-the-loop approval:

```python
# src/vaultspec_a2a/core/nodes/supervisor.py (or a new src/vaultspec_a2a/core/nodes/plan_approval.py)
from langgraph.types import interrupt, Command
from typing import Literal

def create_plan_approval_node(workers: list[str], autonomous: bool = False):
    """Factory: returns a plan_approval_node that unconditionally interrupts.

    Called only when the supervisor routes to an exec worker with an unapproved
    plan. Once entered, always calls interrupt() — no conditional guard inside
    the node.

    In autonomous mode returns a passthrough Command routing directly to the
    exec worker without interrupting.
    """
    async def plan_approval_node(
        state: TeamState,
    ) -> Command[Literal[*workers, "supervisor"]]:  # type: ignore[valid-type]
        if autonomous:
            # No human present — proceed without approval prompt.
            return Command(
                update={"plan_approved": True},
                goto=state["next"],
            )

        vault_index: dict[str, list[str]] = state.get("vault_index") or {}
        decision = interrupt({
            "type": "plan_approval_request",
            "feature": state.get("active_feature"),
            "plan_paths": vault_index.get("plan", []),
            "exec_worker": state["next"],
        })

        if decision.get("approved"):
            _logger.info(
                "plan approved by user — routing to exec_worker=%r",
                state["next"],
            )
            return Command(
                update={"plan_approved": True},
                goto=state["next"],
            )

        _logger.info("plan rejected by user — rerouting to supervisor for revision")
        return Command(
            update={
                "routing_error": (
                    "Plan rejected by user — revise before proceeding to execution."
                ),
            },
            goto="supervisor",
        )

    plan_approval_node.__name__ = "plan_approval_node"
    return plan_approval_node
```text

The supervisor node itself **never calls `interrupt()`**. It sets `state["next"]`
to the intended exec worker and returns. The conditional edge in `graph.py`
intercepts the route and redirects to `plan_approval_node` when the gate
conditions are met:

```python
# src/vaultspec_a2a/core/graph.py — supervisor conditional edge router

def _make_supervisor_router(
    workers: list[str],
    worker_phase_map: dict[str, str] | None,
    autonomous: bool,
) -> Callable[[TeamState], str]:
    def _router(state: TeamState) -> str:
        next_node = state["next"]
        vault_index = state.get("vault_index") or {}
        if (
            not autonomous
            and worker_phase_map
            and worker_phase_map.get(next_node) == "exec"
            and state.get("active_feature")
            and vault_index.get("plan")
            and not state.get("plan_approved")
        ):
            return "plan_approval"
        return next_node
    return _router

builder.add_node("plan_approval", create_plan_approval_node(workers, autonomous))
builder.add_conditional_edges("supervisor", _make_supervisor_router(...))
# plan_approval_node uses Command(goto=...) — no static edges needed from it
```text

### 2.3 Interrupt Payload

```python
interrupt({
    "type": "plan_approval_request",
    "feature": state.get("active_feature"),
    "plan_paths": vault_index.get("plan", []),
    "exec_worker": state["next"],
})
```text

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
3. `plan_approval_node` replays; `interrupt()` returns `{"approved": True}`.
4. Node returns `Command(update={"plan_approved": True}, goto=exec_worker)`.
5. LangGraph applies `plan_approved: True` to state and routes to the exec
   worker. `plan_approved: True` persists in the checkpointer — subsequent
   exec routing decisions in this thread do not enter `plan_approval_node`
   again (the supervisor router condition is false).

**Rejection path:**

1. User clicks "Reject — Revise Plan" → `POST /api/permissions/{request_id}/respond`
   with `option_id: "reject"`.
2. Endpoint dispatches `Command(resume={"approved": False})`.
3. `plan_approval_node` replays; `interrupt()` returns `{"approved": False}`.
4. Node returns `Command(update={"routing_error": "..."}, goto="supervisor")`.
5. Supervisor receives control with `routing_error` set. On its next pass it
   routes to a planning worker for revision.
6. `plan_approved` remains absent or `False` — the next exec routing attempt
   will re-enter `plan_approval_node`.

### 2.5 `autonomous=True` Behaviour

The plan approval interrupt is **skipped** when `autonomous=True`. No human is
present in autonomous mode (headless MCP-launched execution); the interrupt
would block indefinitely with no user to respond.

`create_plan_approval_node` captures `autonomous` at factory call time. When
`autonomous=True`, the node returns a passthrough `Command(update={"plan_approved":
True}, goto=state["next"])` without calling `interrupt()`. The gate conditions
in the supervisor router (`not autonomous and ...`) additionally prevent the
router from ever directing to `plan_approval_node` in autonomous mode — the
node is unreachable in that configuration.

This follows the same pattern as ACP permission approvals: `autonomous=True`
bypasses human-in-the-loop gates, not quality artifact gates.

### 2.6 No `active_feature` Behaviour

The supervisor router gate condition includes `state.get("active_feature")`.
When `active_feature` is `None`, the router never routes to `plan_approval_node`.
The thread is not SDD-bound; the plan approval mandate does not apply. This is
consistent with ADR-023 and ADR-025.

### 2.7 Execution Order at the Exec Boundary

The full gate chain, in order of evaluation:

1. **ADR-022** (in `supervisor_node`): `validation_errors` → block FINISH if
   validation errors are present. Supervisor returns `next=workers[0]`.
2. **ADR-025** (in `supervisor_node`): `vault_index["audit"]` → block FINISH
   if no review artifact exists. Supervisor returns `next=workers[0]`.
3. **ADR-023** (in `supervisor_node`): Phase prerequisites → if hard gate
   fires, supervisor returns `next=workers[0]` (safe fallback, not the blocked
   destination). Soft gate sets `routing_warning`, proceeds.
4. **Supervisor conditional edge router**: checks plan approval conditions. If
   all hold, routes to `plan_approval_node`. Otherwise routes to `state["next"]`
   directly.
5. **ADR-024** (in `plan_approval_node`): interrupts for human approval. On
   resume, routes to exec worker (approved) or `supervisor` (rejected).

ADR-023 and ADR-024 are complementary at the exec boundary: if ADR-023 fires
(no plan artifact), the supervisor routes to a safe fallback and the router
condition `vault_index.get("plan")` is false — `plan_approval_node` is never
entered. If ADR-023 passes (plan exists), the router condition may route to
`plan_approval_node` for approval.

### 2.8 `_emit_interrupt_events` Extension

`aggregator.py`'s `_emit_interrupt_events()` detects payloads with
`type == "permission_request"` to emit `PermissionRequestEvent` to WebSocket
clients. It must be extended to handle `type == "plan_approval_request"`:

```python
if payload.get("type") in ("permission_request", "plan_approval_request"):
    # build and emit PermissionRequestEvent with appropriate options
```text

For `plan_approval_request` payloads, the emitted `PermissionRequestEvent`
carries approve and reject options. The UI permission modal is extended to
render plan context (feature name, plan document paths) when the interrupt type
is `plan_approval_request`.

**Note:** Once the `aggregator.py` interrupt detection is refactored to use
stream-based `"__interrupt__"` key detection (per audit finding A-1) rather
than `BaseException` catching, `_emit_interrupt_events` will receive the
interrupt payload directly from the stream event — the `aget_state` call is
eliminated. This ADR is compatible with both the current and future
implementations.

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
- `plan_approval_node` calls `interrupt()` unconditionally — no conditional
  guard inside the node. This is the documented LangGraph approval pattern and
  is safe for replay: the node is only entered when approval is needed, but
  once entered, the `interrupt()` call always executes. No index mismatch risk.
- Reuses the existing `interrupt()` / resume machinery and `PermissionRequestEvent`
  schema — no new IPC mechanisms required.
- Supervisor node is freed from interrupt responsibility — it only sets routing
  state. All interrupt logic is concentrated in `plan_approval_node`.
- Autonomous mode correctly bypasses the interrupt (no human present to approve)
  while non-autonomous threads are always gated.
- One-time per-session semantics prevent repeated approval prompts for the same
  plan.

### Negative / Trade-offs

- Adds a new `plan_approval` graph node to every compiled team graph that has
  exec-phase workers and a `worker_phase_map`. Graph topology is slightly more
  complex. The node is unreachable in autonomous mode.
- `plan_approval_node` uses `Command(goto=...)` for its return value. Unlike
  `worker_node` and `supervisor_node` which return plain dicts, this node
  participates in LangGraph's `Command`-based routing. The graph compiler must
  not add static edges out of `plan_approval_node` — routing is entirely via
  `Command.goto`.
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

### Supervisor-inline `interrupt()` (original §2.2)

The original design placed the `interrupt()` call inside `supervisor_node`
behind a five-condition guard. Rejected because:

1. **Index mismatch on replay.** On resume, LangGraph replays `supervisor_node`
   from scratch. The LLM is re-invoked and may produce a different `next_route`.
   If any of the five conditions is then false, `interrupt()` is skipped. LangGraph
   finds a stored resume value with no matching `interrupt()` call — undefined
   behaviour.
2. **Violates documented pattern.** Official LangGraph docs show `interrupt()`
   in dedicated nodes that call it unconditionally
   (<https://docs.langchain.com/oss/python/langgraph/interrupts> — "Approval Node
   with Interrupt"). Placing it conditionally inside a routing node is not a
   documented pattern.
3. **Mixed responsibilities.** `supervisor_node` is a routing node (LLM call →
   `state["next"]`). Adding interrupt logic couples routing and HIL gating in
   one function, making both harder to test.

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

- `plan_approved: NotRequired[bool]` added to `TeamState` (`src/vaultspec_a2a/core/state.py`).
  Last-write-wins, no reducer. Consuming code uses `.get("plan_approved")` to
  handle absent field on legacy threads.
- `interrupt()` fires inside `plan_approval_node`, never inside
  `supervisor_node`. The supervisor only sets `state["next"]` and returns.
- `plan_approval_node` must **not** have static outgoing edges added in
  `graph.py`. All routing from this node is via `Command(goto=...)`.
- The supervisor conditional edge router checks plan approval conditions and
  redirects to `"plan_approval"` when all hold; otherwise passes through to
  `state["next"]`.
- `autonomous=True` → `plan_approval_node` returns passthrough `Command`
  without calling `interrupt()`. Additionally, the router condition includes
  `not autonomous` preventing the node from being entered at all.
- `_emit_interrupt_events` (`src/vaultspec_a2a/core/aggregator.py`) extended to handle
  `type == "plan_approval_request"` payloads, emitting `PermissionRequestEvent`
  with approve (`ALLOW_ONCE`) and reject (`DENY_ONCE`) options.
- Resume payload is `{"approved": True}` or `{"approved": False}` — the
  interrupt consumer checks `decision.get("approved")`.

## 6. Module Hierarchy Impact

```text
src/vaultspec_a2a/core/
  state.py              AMENDED: plan_approved: NotRequired[bool] added to TeamState

  nodes/supervisor.py   AMENDED: plan approval interrupt REMOVED from supervisor_node;
                        supervisor_node only sets state["next"] and returns;
                        no interrupt() call in supervisor

  nodes/plan_approval.py  NEW (or added to supervisor.py):
                          create_plan_approval_node(workers, autonomous) factory;
                          unconditional interrupt() + Command(goto=...) routing;
                          __all__ = ["create_plan_approval_node"]

  graph.py              AMENDED: add "plan_approval" node to graph;
                        supervisor conditional edge uses _make_supervisor_router()
                        which redirects to "plan_approval" when gate conditions hold;
                        no static edges from plan_approval_node

  aggregator.py         AMENDED: _emit_interrupt_events() handles
                        type == "plan_approval_request" payloads;
                        emits PermissionRequestEvent with approve/reject options

  tests/test_graph.py   AMENDED: test cases for plan approval gate —
                        interrupt fires on first exec routing with plan present,
                        approve path sets plan_approved and routes to exec,
                        reject path reroutes to supervisor with routing_error,
                        gate skipped in autonomous mode,
                        gate skipped when active_feature is None,
                        gate not re-triggered when plan_approved is True

src/vaultspec_a2a/api/
  schemas/rest.py       AMENDED (if needed): PermissionRequestEvent options
                        for plan approval (approve/reject option_id values)
```text

## 7. References

- [LangGraph docs — Approval Node with Interrupt](https://docs.langchain.com/oss/python/langgraph/interrupts)
  — dedicated node calling `interrupt()` unconditionally; `Command(goto=...)` routing
- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — D-02
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md` — "The user must approve plans before execution proceeds"
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) — TeamState field patterns; `NotRequired` precedent
- [ADR-022](022-contextual-anchoring-graph-lifecycle.md) — `validation_errors` FINISH gate; gate ordering reference
- [ADR-023](023-phase-artifact-gates.md) — phase prerequisite gate at plan→exec boundary (complementary)
- [ADR-025](025-mandatory-review-gate.md) — review artifact FINISH gate; gate ordering reference
- [docs/research/2026-03-03-plan-approval-interrupt-research.md](../research/2026-03-03-plan-approval-interrupt-research.md) — interrupt mechanism analysis, option comparison, resume flow, autonomous interaction
- `src/vaultspec_a2a/core/nodes/worker.py` — `_interrupt_permission_callback`, existing interrupt pattern
- `src/vaultspec_a2a/core/aggregator.py` — `_emit_interrupt_events`, interrupt payload detection
- `src/vaultspec_a2a/api/endpoints.py` — `respond_to_permission_endpoint`, resume via REST
