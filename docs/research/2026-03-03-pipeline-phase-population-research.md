---
title: 'Research: pipeline_phase Population'
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: 'How should a multi-stage agent pipeline track which phase it is in? Analysis of deterministic inference, LLM-driven, and hybrid approaches for setting pipeline_phase in TeamState.'
---

## Research: pipeline_phase Population

**Date:** 2026-03-03

## Summary

ADR-019 added `pipeline_phase: str | None` to `TeamState` with the note "None until the supervisor sets it on the first routing pass." The field is never actually set at runtime — this is DRIFT-11 in the vaultspec rule drift audit. This document researches how `pipeline_phase` should be populated and which of three approaches (deterministic, LLM-driven, or hybrid) is most appropriate.

---

## 1. Framework Analysis

### 1.1 MetaGPT (arXiv 2308.00352)

MetaGPT uses a **deterministic role-sequencing model**. Phases are hard-coded as an ordered list of roles:
`ProductManager → Architect → ProjectManager → Engineer → QAEngineer`. The orchestrator advances phase by exhausting the current role's task list — it never asks the LLM "what phase are we in?" Phase is a property of the orchestrator's execution cursor, not an LLM output.

**Key lesson:** Phase identity is too structurally important to delegate to an LLM. In MetaGPT, a hallucinated phase skip would cascade into the entire downstream role chain producing outputs for the wrong phase. The deterministic cursor prevents this class of error entirely.

**Applicability to vaultspec:** The vaultspec pipeline (`research → reference → adr → plan → exec → audit`) maps directly to the MetaGPT pattern. The key difference: vaultspec phases are not strictly sequential — a feature may skip `reference` or loop back to `adr` after `exec`. The cursor must be inferred from artifact state, not from a hardcoded sequence.

### 1.2 CrewAI

CrewAI offers two process modes:

**Sequential process:** Tasks execute in a fixed order. Phase is implicit in the task index — there is no explicit phase field. When task N completes, phase N+1 begins. No LLM involvement in phase transitions.

**Hierarchical process:** A manager LLM delegates tasks to worker agents. The manager determines _which worker to call_ but not an explicit phase label. CrewAI has no concept of a `pipeline_phase` field in its shared context.

**Key lesson:** CrewAI sidesteps phase tracking entirely by structuring it as task sequencing (sequential) or delegation (hierarchical). Neither approach exposes a named phase to agents. For vaultspec's use case — where agents need to know "I am in the exec phase; read `.vault/exec/` documents" — CrewAI's implicit approach is insufficient. A named, queryable phase field is necessary.

### 1.3 LangGraph Multi-Step Patterns

LangGraph provides the `Command` API for nodes to simultaneously update state and determine the next destination:

```python
from langgraph.types import Command
from typing import Literal

def supervisor_node(state: TeamState) -> Command[Literal["worker_a", "worker_b"]]:
    return Command(
        update={"pipeline_phase": "exec", "next": "worker_a"},
        goto="worker_a"
    )
```yaml

This is the canonical LangGraph pattern for combining routing with state updates. The supervisor can return `{"pipeline_phase": inferred_phase, "next": worker_id}` in a single return dict without requiring the `Command` type if using `add_conditional_edges`.

LangGraph's `with_structured_output` enables LLM-driven phase output:

```python
class RoutingDecision(BaseModel):
    next: str = Field(description="Worker to route to, or FINISH")
    phase: str = Field(description="Current pipeline phase")
```text

However, this requires the LLM to produce a valid phase name on every invocation — a hallucination risk for a field with binding consequences (ADR-022 anchoring, ADR-020 mounting, ADR-021 queue injection all key off `pipeline_phase`).

**Key lesson:** LangGraph makes it easy for either Python logic or the LLM to update state at routing time. The `Command` API supports either approach. The question is which is more reliable — not which is technically possible.

### 1.4 arXiv 2507.01701 — Blackboard Control Unit

The blackboard architecture paper describes a **control unit** (scheduler) that determines which knowledge sources are relevant at each step. The control unit in the paper operates deterministically — it inspects the current blackboard content and applies a priority ordering to select the next knowledge source to activate.

The paper explicitly distinguishes the control unit from the agents themselves:

> "The control unit is not itself a knowledge source. It does not produce blackboard content. Its role is to observe the blackboard and determine activation order."

For phase tracking, this maps directly to: the supervisor (acting as control unit) should _observe_ the vault_index and _infer_ phase — it should not _produce_ a phase as part of its LLM output.

**Key lesson:** Phase determination is a control-unit responsibility, not a knowledge-source responsibility. It should be computed deterministically from observed blackboard state, then injected into the context for agents to read.

---

## 2. Options Analysis

### Option A — Deterministic Inference from vault_index

**Mechanism:** A Python function inspects `state["vault_index"]` to determine the most advanced phase with artifacts. The phase ordering is:

```text
research < reference < adr < plan < exec < audit
```text

The inferred phase is the highest phase that has at least one entry in `vault_index`. If `vault_index["exec"]` has entries, phase = `exec`. If only `vault_index["adr"]` has entries, phase = `adr`.

**First session (no artifacts):** `vault_index` is empty → inferred phase = `"research"` (the starting phase).

**Implementation:** A pure Python function called from the supervisor node before building its context:

```python
_PHASE_ORDER = ["research", "reference", "adr", "plan", "exec", "audit"]

def _infer_phase_from_vault_index(vault_index: dict[str, list[str]]) -> str:
    for phase in reversed(_PHASE_ORDER):
        if vault_index.get(phase):
            return phase
    return "research"
```text

**Pros:**

- Deterministic — no LLM hallucination risk on a structurally binding field
- Zero additional tokens — no extra LLM call
- Self-correcting — if an agent writes a new artifact and updates `vault_index`, the phase automatically advances on the next supervisor call
- Aligns with blackboard control-unit pattern (2507.01701) — phase is observed from blackboard state, not produced by an agent
- Works correctly on first session (empty vault → research)
- Works correctly on session restart (artifacts persist on disk, `vault_index` rebuilt at graph compilation)

**Cons:**

- Cannot distinguish between "in progress at this phase" and "starting this phase" — phase is always the highest phase with any artifacts
- Cannot handle non-linear phase orders (e.g., jumping from `plan` back to `adr` after a major revision) without artifact deletion
- `vault_index` is populated at graph compilation from disk scan — if an artifact is written mid-session but `vault_index` is not updated, the inferred phase may lag

### Option B — LLM Outputs Phase as Part of Routing

**Mechanism:** The supervisor LLM is prompted to return a structured output containing both the next worker and the current phase:

```python
class RoutingDecision(BaseModel):
    next: str
    phase: Literal["research", "reference", "adr", "plan", "exec", "audit", "FINISH"]
```text

**Pros:**

- Flexible — the LLM can read context and declare a phase that does not follow strict artifact presence rules
- Can handle edge cases (e.g., "we have ADR artifacts but user wants to go back to research")

**Cons:**

- Fragile — the LLM may hallucinate a phase value (e.g., `"implementation"` instead of `"exec"`) despite the Literal constraint; structured output reduces but does not eliminate this risk
- `pipeline_phase` is consumed by anchoring (ADR-022), mounting (ADR-020), and queue injection (ADR-021) — a wrong value has cascading effects
- Adds a Pydantic-constrained structured output requirement to the supervisor, increasing model invocation cost and constraining which models can serve as supervisor
- Phase is an observation of artifact state, not a judgment the LLM is better positioned to make than Python logic
- MetaGPT, blackboard paper, and CrewAI sequential all avoid LLM phase determination for exactly this reason

**Verdict:** Rejected. Phase determination is structurally too important to delegate to LLM output.

### Option C — Hybrid (Deterministic Baseline, LLM Can Advance)

**Mechanism:** Python infers a baseline phase from `vault_index` (Option A). The supervisor LLM is given the baseline in its anchoring context. If the LLM's routing output includes a phase hint (e.g., as part of a more detailed structured output), it is accepted only if it is at or ahead of the inferred baseline — never behind.

```python
inferred = _infer_phase_from_vault_index(state["vault_index"])
llm_phase = structured_output.phase if structured_output.phase else None
if llm_phase and _PHASE_ORDER.index(llm_phase) >= _PHASE_ORDER.index(inferred):
    final_phase = llm_phase
else:
    final_phase = inferred
```text

**Pros:**

- Combines determinism with flexibility
- LLM can signal "we're done with plan, starting exec" even before the first exec artifact appears
- Phase cannot regress below the artifact-inferred baseline

**Cons:**

- Requires structured output from the supervisor — adds model constraint and token overhead
- The "LLM can advance phase" path still has hallucination risk (LLM declares `exec` when no exec work has been done)
- Adds implementation complexity: two phase computation paths, tiebreaker logic, structured output schema
- In practice, the LLM advancing phase ahead of artifacts is only useful during the transition moment between phases — a narrow benefit for significant added complexity
- The deterministic baseline is already correct in the vast majority of cases; the hybrid only helps during the exact transition step, and even then the LLM's advance signal is only as reliable as the supervisor's reasoning

**Verdict:** The team lead identifies this as the recommendation, but the benefit over pure Option A is narrow and the cost (structured output constraint, additional complexity) is real. The key insight is whether the transition-moment ambiguity is a real problem in practice.

---

## 3. First Session Behaviour

When a new thread is created with no prior artifacts (`vault_index = {}`):

- **Option A:** `_infer_phase_from_vault_index({})` returns `"research"` — correct starting phase
- **Option C:** Same baseline; LLM could theoretically declare `"adr"` on first invocation — but this would be a hallucination, not a feature

Both options correctly handle first session. Option A is sufficient.

---

## 4. Ambiguity Analysis — Can Phase Be Inferred from vault_index Alone?

**Unambiguous cases (majority):**

- `vault_index = {}` → `research`
- Only research entries → `research`
- research + adr entries, no plan → `adr`
- research + adr + plan, no exec → `plan`
- Any exec entries → `exec`
- Any audit entries → `audit`

**Potentially ambiguous cases:**

- A feature that has ADRs but was deliberately re-opened at research phase — the human has asked the agent to do more research before revising an ADR. The vault_index-inferred phase would be `adr`, but the correct phase is `research`.
- A feature transitioning from `plan` to `exec` — the first exec invocation happens with no exec artifacts yet; `vault_index["exec"]` is empty, so inferred phase is `plan`.

**Assessment of ambiguity:**
The first case (deliberate regression) is a human-directed workflow deviation. The supervisor prompt instructs agents on what to do; the `pipeline_phase` field gates document injection and queue injection, it does not constrain what the supervisor can ask workers to do. Running a research worker with `pipeline_phase = "adr"` injects ADR documents alongside research documents — slightly suboptimal but not incorrect.

The second case (plan → exec transition) is the most relevant. At the moment the first exec artifact is created, the phase will update to `exec` on the next vault_index refresh. Between assignment and first artifact write, `pipeline_phase = "plan"` — workers have plan documents injected, which is appropriate for the planning work they are completing before beginning execution.

**Conclusion:** vault_index-based inference is correct in all structurally important cases. The edge cases produce slightly suboptimal document injection, not incorrect behavior.

---

## 5. When to Set pipeline_phase

Phase should be computed and written to state on **every supervisor invocation** — not once at graph compilation. This ensures it reflects the current vault_index, which may have been updated mid-session by worker nodes writing new artifacts.

The computation is O(1) over the six phase keys — no filesystem I/O needed (vault_index is already in state).

The supervisor node returns `{"next": route, "pipeline_phase": inferred_phase}` in its return dict. The last-write-wins semantics of `pipeline_phase` (ADR-019 §2.1) mean this is safe — whichever supervisor call ran most recently sets the current phase.

---

## 6. Recommendation

**Implement Option A (deterministic inference) as the primary mechanism.**

Rationale:

1. Phase determination is a control-unit responsibility (2507.01701) — it observes blackboard state, it does not produce it
2. MetaGPT and all surveyed frameworks use deterministic phase management, not LLM-driven phase output
3. `pipeline_phase` has cascading downstream effects (anchoring, mounting, queue injection) — hallucination risk is unacceptable
4. Option A correctly handles first session, session restart, and the normal sequential progression
5. The edge cases where Option A produces suboptimal results (deliberate phase regression, transition moments) have low impact — slightly wrong document injection, not wrong routing or data corruption
6. Option C adds implementation complexity and a structured output constraint for marginal benefit

**If Option C (hybrid) is chosen** (team lead recommendation), the implementation should:

- Keep the deterministic inference as the default and the floor
- Use a `phase_hint` field (optional) in structured output, not a required `phase` field
- Only accept LLM phase advances in the forward direction
- Ensure supervisor models that do not support structured output gracefully fall back to Option A

**For the ADR-026 scope**, the minimum binding decision is:

1. `_infer_phase_from_vault_index(vault_index)` is a private function in `src/vaultspec_a2a/core/graph.py` (or `src/vaultspec_a2a/core/phase.py`)
2. Called by `create_supervisor_node()` on every invocation
3. Result written as `pipeline_phase` in the supervisor return dict
4. No LLM involvement in phase computation (Option A) unless team lead explicitly locks in Option C

---

## 7. References

- [MetaGPT arXiv 2308.00352](https://arxiv.org/abs/2308.00352) — deterministic role-sequencing, orchestrator owns phase transitions
- [CrewAI sequential/hierarchical processes](https://docs.crewai.com/) — implicit phase via task order, no named phase field
- [LangGraph Command API](https://langchain-ai.github.io/langgraph/concepts/low_level/#command) — state update + routing in single return
- [LangGraph structured output routing](https://docs.langchain.com/oss/python/langgraph/workflows-agents) — `with_structured_output` for routing decisions
- [arXiv 2507.01701](https://arxiv.org/abs/2507.01701) — control unit as observer of blackboard state, not knowledge source
- [ADR-019](../adrs/019-teamstate-enrichment-sdd-blackboard.md) — `pipeline_phase` field definition, 6-stage taxonomy
- [ADR-022](../adrs/022-contextual-anchoring-graph-lifecycle.md) — `pipeline_phase` consumed in anchoring summary
- [ADR-020](../adrs/020-blackboard-content-mounting.md) — `pipeline_phase` used for phase-scoped document selection
- [ADR-021](../adrs/021-persistent-task-queue-schema.md) — queue injection gated on `pipeline_phase in {"plan", "exec"}`
- [docs/audits/2026-03-03-vaultspec-rule-drift.md](../audits/2026-03-03-vaultspec-rule-drift.md) — DRIFT-11: pipeline_phase never set at runtime
- [docs/research/2026-03-02-sdd-blackboard-architecture-research.md](2026-03-02-sdd-blackboard-architecture-research.md) — original blackboard gap analysis
