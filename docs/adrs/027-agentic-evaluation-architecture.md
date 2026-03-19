---
adr_id: 027
title: Agentic Evaluation Architecture
date: 2026-03-04
status: Proposed
related:
  - docs/adrs/010-observability-telemetry-integration.md
  - docs/adrs/013-team-composition-topology.md
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/023-phase-artifact-gates.md
  - docs/adrs/024-plan-approval-interrupt.md
  - docs/adrs/025-mandatory-review-gate.md
---

# ADR-027: Agentic Evaluation Architecture

**Date:** 2026-03-04
**Status:** Proposed

## 1. Context & Problem Statement

### 1.1 Two Distinct Testing Layers

The test suite (942 tests as of 2026-03-03) exercises code correctness: unit
reducers, schema validation, API contract adherence, graph compilation, and
LangGraph API conformance. These tests are deterministic, fast, and do not
require LLM calls. They constitute the first testing layer.

A second layer is entirely absent: evaluation of agent behaviour quality. This
layer asks different questions:

- Does the supervisor route to the correct worker given a realistic task
  description?
- Does the plan agent produce a plan that complies with ADRs and is actionable?
- Does the coder agent produce code that passes tests?
- Does the reviewer agent produce a complete review that catches planted
  defects?
- Does a full pipeline run for a representative feature request complete with
  all required artifacts?

These questions cannot be answered by pytest assertions on Python objects.
They require running the actual agents against realistic inputs and judging
outputs — either by exact match (deterministic checks), by structured rubric
(LLM-as-judge), or by trajectory comparison (did the right agents fire in
the right order?).

### 1.2 Non-Determinism

LLM outputs are non-deterministic. A single run cannot characterise agent
behaviour. Three mitigation strategies apply:

1. **`temperature=0`** for all models under evaluation — maximises
   reproducibility for a given model version. Not a guarantee of
   determinism but the standard practice.
2. **Aggregate over N runs** — `aevaluate()` supports `num_repetitions`; the
   evaluator computes mean and variance over multiple runs, surfacing
   instability as a measurable signal.
3. **Thresholds, not exact scores** — CI gates trigger on score falling below a
   threshold (e.g., `routing_accuracy < 0.9`), not on exact value, tolerating
   natural run-to-run variance.

### 1.3 Why Traditional pytest Is Insufficient

| Concern | pytest | Agent eval layer |
|---|---|---|
| Code correctness | Excellent | Out of scope |
| LLM routing quality | Cannot test (non-deterministic) | Exact match evaluator |
| Plan quality | Cannot test (open-ended text) | LLM-as-judge rubric |
| Multi-step trajectory | Cannot test (requires full graph run) | Trajectory evaluator |
| Regression across model upgrades | Cannot test | Dataset-based comparison |
| Aggregate stability over N runs | Impractical | Built-in `num_repetitions` |

pytest remains the sole mechanism for code-layer correctness. The evaluation
layer adds a second, complementary layer — it replaces nothing.

### 1.4 LangGraph Is Tracing-First

LangGraph's own guidance treats tracing as the primary integration observation
mechanism, not pytest assertions. Every live graph run produces a LangSmith
trace when `LANGSMITH_TRACING=true` is set (canonical current name; legacy alias
`LANGCHAIN_TRACING_V2` also accepted). Traces capture the full
execution graph: which nodes fired, in what order, what each LLM received and
returned, how long each step took, and where errors occurred.

This design choice has a direct implication for how we test integration
behaviour: **integration observation belongs in LangSmith traces, not in
pytest assertions.** Writing pytest tests that make live LLM calls and assert
on their outputs fights the tool — it conflates the code-correctness layer with
the behaviour-observation layer, produces flaky tests (non-deterministic LLM
outputs), and provides no regression tracking across model upgrades.

ADR-010 established OpenTelemetry (OTel) tracing. LangSmith accepts OTel
traces when `LANGSMITH_TRACING=true` is set. This means all existing
tracing infrastructure wires into LangSmith automatically — evaluation runs
are traced without any additional instrumentation code.

## 2. Decision

### 2.0 Three-Layer Mandate

The architecture draws a hard boundary between three layers. Each layer has
a single, non-overlapping responsibility:

**Layer 1 — pytest: code correctness only.**
pytest is the authoritative gate for unit-level code correctness: reducers,
node logic, schema validation, API contract adherence, LangGraph API
conformance, and graph compilation. pytest scope ends here. No new `@pytest`
tests should be written to observe agent behaviour, routing quality, plan
content, or any output that requires a live LLM call to judge.

**Layer 2 — LangSmith tracing: integration observation.**
`LANGSMITH_TRACING=true` causes every live graph run to emit a trace to
LangSmith automatically via the existing OTel infrastructure (ADR-010). Traces
are the primary signal for integration-layer observation. Live agent behaviour
— which nodes executed, what the supervisor decided, what the LLM produced,
how long each step took — is observed by reading LangSmith traces post-run,
not by asserting on pytest return values.

The mechanism for producing traceable runs is **direct Python scripts**, not
pytest test cases. A script sources `.env` (activating `LANGSMITH_API_KEY` and
`LANGSMITH_TRACING=true`), constructs a graph input, invokes the graph, and
exits. The resulting trace appears in LangSmith automatically and is the
primary observation artefact for integration behaviour.

The existing `@pytest.mark.live` tests in `test_e2e_live.py` are
**deprecated**. They assert superficial things (e.g., "at least 1 AI message
was produced") that provide no useful signal about agent behaviour. They are
retained temporarily as compilation smoke tests — confirming the graph
initialises and executes without crashing — but must not be extended with new
behavioural assertions. They will be removed once the tracing-script pattern
is established as the team norm.

**Layer 3 — LangSmith `aevaluate()` + agentevals: behavioural evaluation.**
Structured evaluation of agent behaviour quality runs offline against LangSmith
datasets. This layer produces quantitative scores (routing accuracy, plan
quality, trajectory match) that are tracked over time and gated in CI.

These three layers are additive. Layer 3 does not replace Layer 1 or Layer 2.
Layer 2 does not replace Layer 1. No layer's tooling crosses into another
layer's responsibility.

### 2.1 Evaluation Stack

| Component | Package | Role |
|---|---|---|
| Harness | `langsmith` (`aevaluate()`) | Orchestrates runs, stores results |
| Trajectory evaluator | `agentevals` | Multi-step routing correctness |
| LLM-as-judge | `openevals` | Open-ended quality rubrics |
| Exact match | Custom (trivial) | Deterministic gate checks |
| Datasets | LangSmith cloud | Versioned, immutable labeled examples |

### 2.2 Evaluation Dimensions

Six evaluation dimensions are defined, each bound to a specific pipeline stage
and evaluated by the most appropriate evaluator type.

#### Dimension 1 — Supervisor Routing Accuracy

**Stage:** Supervisor node
**Evaluator type:** Exact match
**What it measures:** Given a task description and pipeline state, does the
supervisor route to the correct next worker?

A LangSmith dataset contains labeled `(state_snapshot, expected_next)` pairs
covering common routing decisions: initial dispatch, phase transitions, FINISH
triggering, phase gate blocks. The target function invokes
`create_supervisor_node()` in isolation (no full graph run) and compares
`result["next"]` to the label.

```python
# Evaluator
def routing_evaluator(run, example):
    return {
        "key": "routing_correct",
        "score": int(run.outputs["next"] == example.outputs["expected_next"]),
    }
```

**Threshold:** `routing_accuracy >= 0.90` required for CI pass.

#### Dimension 2 — Phase Gate Compliance

**Stage:** Supervisor phase gating (ADR-023)
**Evaluator type:** Deterministic — presence/absence of `routing_error`
**What it measures:** Does the phase gate correctly block routing when a
prerequisite artifact is absent, and correctly pass when it is present?

This dimension is deterministic (no LLM call required for the check itself —
the gate logic is pure Python). It is included in the evaluation suite rather
than pytest solely because the gate fires within a full `supervisor_node` call
(which does invoke the LLM for routing), making it impractical to test in
isolation without the evaluation harness.

```python
def gate_compliance_evaluator(run, example):
    expect_blocked = example.outputs["expect_blocked"]
    has_error = bool(run.outputs.get("routing_error"))
    return {
        "key": "gate_compliant",
        "score": int(has_error == expect_blocked),
    }
```

**Threshold:** `gate_compliance == 1.0` (deterministic — zero tolerance for
gate failures).

#### Dimension 3 — Plan Quality

**Stage:** Plan agent output
**Evaluator type:** LLM-as-judge (rubric)
**What it measures:** Is the plan complete, actionable, and compliant with
vaultspec ADRs?

The `openevals` LLM-as-judge evaluator is used with a custom rubric:

```
Given a feature request and a plan document, score the plan 0-1 on:
- COMPLETENESS: all pipeline stages (research→adr→plan→exec→audit) addressed
- ACTIONABILITY: each step has a concrete, executable description
- ADR_COMPLIANCE: plan references relevant ADRs; no contradictions
- TASK_GRANULARITY: tasks are appropriately sized (not too coarse, not too fine)

Respond with JSON: {"score": <float 0-1>, "reasoning": "<string>"}
```

**Threshold:** `plan_quality >= 0.75` required for CI pass.

#### Dimension 4 — Code Correctness Rate

**Stage:** Coder agent output
**Evaluator type:** Subprocess pytest execution
**What it measures:** Does the code produced by the coder agent pass the
test suite associated with the task?

The target function invokes the coder agent against a labeled task. The
evaluator runs `pytest` in a subprocess against the output directory and
returns `test_pass_rate = passed / total`.

```python
def code_correctness_evaluator(run, example):
    result = subprocess.run(
        ["python", "-m", "pytest", run.outputs["output_dir"], "--tb=no", "-q"],
        capture_output=True, text=True
    )
    # Parse "X passed, Y failed" from stdout
    passed, total = _parse_pytest_output(result.stdout)
    return {
        "key": "test_pass_rate",
        "score": passed / total if total > 0 else 0.0,
    }
```

**Threshold:** `test_pass_rate >= 0.85` required for CI pass.

#### Dimension 5 — Reviewer Completeness

**Stage:** Reviewer (audit) agent output
**Evaluator type:** LLM recall judge
**What it measures:** Does the reviewer's audit report identify all planted
defects in the code under review?

Each dataset example includes a code file with N known defects (annotated in
the example metadata). The LLM judge checks whether each defect appears in the
review report.

```
Given a list of defects and a review report, for each defect output 1 if the
defect is mentioned in the report (recall), 0 if not.
Return: {"defect_recall": <float 0-1>}
```

**Threshold:** `defect_recall >= 0.80` required for CI pass.

#### Dimension 6 — E2E Task Completion

**Stage:** Full pipeline run
**Evaluator type:** Superset trajectory match + LLM completion judge
**What it measures:** (a) Did the right agents fire in the correct order? (b)
Is the final state of the task complete?

The trajectory evaluator uses `agentevals.create_trajectory_match_evaluator`
in `superset` mode. In superset mode the expected trajectory is a subset of
the actual trajectory — the graph may invoke additional agents for error
recovery or replanning without failing the evaluation.

```python
from agentevals import create_trajectory_match_evaluator

trajectory_eval = create_trajectory_match_evaluator(mode="superset")
```

The LLM completion judge evaluates whether the final vault artifacts (plan,
exec, audit docs) constitute a completed feature implementation.

**Threshold:** `trajectory_match >= 0.90` AND `completion_score >= 0.70`.

### 2.3 Trajectory Matching Mode Selection

`agentevals` supports four trajectory matching modes:

| Mode | Semantics | Used for |
|---|---|---|
| `strict` | Exact order, exact agents | Not used — too brittle |
| `unordered` | Same set, any order | Not used — order matters |
| `subset` | Actual ⊆ expected | Not used — would penalise extra steps |
| `superset` | Expected ⊆ actual | E2E dimension 6 — allows adaptive replanning |

For the supervisor routing dimension (1), exact match on `next` value is used
directly rather than trajectory matching, since only a single routing decision
is evaluated.

### 2.4 Dataset Storage Policy

All evaluation datasets are stored in LangSmith, not as local files. Rationale:

- **Versioned and immutable:** LangSmith datasets are versioned; a CI run
  always pins to a specific dataset version, preventing silent dataset drift.
- **Shareable:** Team members can inspect, annotate, and extend datasets via
  the LangSmith UI without touching the codebase.
- **Traceable:** Each evaluation run is linked to the dataset version that
  produced it, enabling regression tracking over time.

Dataset naming convention: `vaultspec-{dimension}-v{N}` (e.g.,
`vaultspec-routing-v1`, `vaultspec-e2e-v1`).

### 2.5 OTel / LangSmith Integration

ADR-010 established OTel tracing. No additional instrumentation is required.
Setting `LANGSMITH_TRACING=true` in the evaluation environment causes
LangChain/LangGraph to emit traces to LangSmith automatically. Evaluation runs
are therefore fully traced at no extra cost.

Required environment variables for evaluation runs:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<langsmith api key>
LANGSMITH_PROJECT=vaultspec-eval
```

### 2.6 Package Dependencies

`agentevals` and `openevals` are to be added to `pyproject.toml` under an
`[eval]` optional dependency group:

```toml
[project.optional-dependencies]
eval = [
    "agentevals>=0.0.4",
    "openevals>=0.0.4",
    "langsmith>=0.2",
]
```

These packages are NOT added to the main dependency group — evaluation is a
development/CI concern, not a production runtime concern. Production deployments
do not require the eval stack.

### 2.7 `temperature=0` Mandate

All models invoked during evaluation runs MUST be configured with
`temperature=0`. This applies to:

- The model under evaluation (the agent being tested).
- LLM-as-judge models (openevals judge calls).

`temperature=0` is not a guarantee of determinism but is the industry-standard
mitigation. Results MUST be interpreted as aggregate scores over `num_repetitions`
runs, not single-run point measurements.

## 3. What Is NOT in Scope

- **Replacing pytest for code correctness.** The pytest suite is the
  authoritative gate for code-layer correctness. Nothing in this ADR modifies
  or replaces it. pytest scope is strictly: unit tests, reducers, node logic,
  schema validation, graph compilation, LangGraph API conformance.
- **Writing new pytest tests for agent behaviour.** No new `@pytest` tests
  should be written to observe routing decisions, plan content, trajectory
  ordering, or any output requiring a live LLM call to judge. The existing
  `@pytest.mark.live` tests in `test_e2e_live.py` are deprecated — they assert
  superficial things ("at least 1 AI message produced") that provide no useful
  signal. They are retained temporarily as compilation smoke tests only. All
  behavioural observation happens via LangSmith traces (Layer 2) and
  `aevaluate()` datasets (Layer 3).
- **Inline evaluation during graph execution.** Evaluators run offline against
  completed runs, not as graph nodes or hooks inside the production graph.
- **Replacing human review.** LLM-as-judge rubrics are proxies, not
  replacements. Human review of sampled evaluation outputs is recommended
  quarterly.
- **Coverage of all possible agent behaviours.** Initial datasets will be small
  (10–30 examples per dimension). Coverage grows iteratively as failure modes
  are discovered.

## 4. Consequences

### Positive

- Provides a quantitative signal for agent behaviour quality — currently
  entirely absent.
- Catches regressions introduced by model upgrades (e.g., switching from
  `claude-sonnet-4-6` to a new model version) that leave pytest passing but
  degrade routing accuracy or plan quality.
- LangSmith datasets are versioned and shareable — evaluation becomes a team
  artefact, not a one-off script.
- OTel integration means evaluation runs are fully traced with zero additional
  instrumentation.
- `superset` trajectory matching is tolerant of adaptive replanning — the
  evaluation does not break when the graph adds extra steps for error recovery.

### Negative / Trade-offs

- Evaluation runs require live LLM calls — they are slow (minutes per
  dimension) and incur API cost. Evaluation is NOT run on every commit; it
  runs on schedule (nightly) or on explicit trigger.
- LangSmith API dependency introduces an external service requirement for
  evaluation CI. Offline evaluation is not supported by this architecture.
- LLM-as-judge rubrics are proxies; their scores may not correlate perfectly
  with human judgement. Rubric calibration requires human-annotated ground
  truth for validation.
- `temperature=0` reduces but does not eliminate non-determinism. CI thresholds
  must be set conservatively enough to tolerate natural variance.

### Edge Cases

| Scenario | Behaviour |
|---|---|
| LangSmith API unavailable | Evaluation CI step fails with explicit error; pytest suite unaffected |
| Model under evaluation changed (version bump) | All 6 dimensions re-run; score deltas surfaced in LangSmith comparison view |
| New pipeline stage added (e.g., security audit) | New evaluation dimension added; existing dimensions unaffected |
| Dataset contains ambiguous examples | Excluded via human review of dataset; not handled automatically |
| `num_repetitions=1` (cost-saving mode) | Allowed for development; CI must use `num_repetitions >= 3` |

## 5. Rejected Alternatives

### DeepEval / Ragas

Both provide LLM-as-judge and RAG-specific evaluators. Neither provides
trajectory evaluation for multi-agent graphs. Both require hosting their own
evaluation infrastructure (DeepEval Confident AI, Ragas dashboards). Rejected
in favour of LangSmith, which is already the tracing backend (ADR-010) and
integrates natively with LangGraph via `LANGSMITH_TRACING`.

### Phoenix / Arize

Strongest RAG and hallucination evaluators. No trajectory evaluation support.
Appropriate if the system evolves to include retrieval-augmented generation;
not appropriate for routing and planning evaluation in the current architecture.
May be adopted alongside LangSmith in a future ADR if RAG is introduced.

### Local Dataset Files (JSON/YAML in repo)

Simpler to version-control but loses LangSmith's annotation UI, run-linking,
and versioned comparison features. Rejected because dataset management
complexity grows quickly: annotating new examples, tracking which dataset
version a CI run used, and comparing scores across model versions all require
tooling that LangSmith provides out of the box.

### Strict Trajectory Matching

Rejected for E2E evaluation (dimension 6). Strict matching requires the graph
to fire exactly the same agents in exactly the same order on every run. Any
adaptive replanning step (a legitimate and desirable behaviour) would fail the
evaluation. `superset` mode is the correct choice: the expected trajectory
defines the minimum required steps; additional steps are tolerated.

## 6. Module Hierarchy Impact

```text
pyproject.toml
  [project.optional-dependencies]
    eval = ["agentevals>=0.0.4", "openevals>=0.0.4", "langsmith>=0.2"]

evals/                            NEW top-level directory
  __init__.py
  conftest.py                     Shared fixtures: langsmith client, dataset refs
  datasets/                       Dataset IDs / version pins (not the data itself)
    routing.py                    vaultspec-routing-v1 dataset reference
    e2e.py                        vaultspec-e2e-v1 dataset reference
  evaluators/
    routing.py                    Exact match evaluator (dimension 1)
    gate_compliance.py            Deterministic gate evaluator (dimension 2)
    plan_quality.py               LLM rubric evaluator (dimension 3)
    code_correctness.py           pytest subprocess evaluator (dimension 4)
    reviewer_completeness.py      LLM recall judge (dimension 5)
    e2e.py                        Trajectory + completion evaluators (dimension 6)
  suites/
    nightly.py                    Full 6-dimension suite (scheduled CI)
    smoke.py                      Dimensions 1+2 only (fast, on PR)
```

No changes to `lib/` production code. No changes to existing `lib/*/tests/`
directories.

## 7. References

- [docs/research/2026-03-03-agentic-evaluation-frameworks-research.md](../research/2026-03-03-agentic-evaluation-frameworks-research.md) — full research underpinning this ADR
- [ADR-010](010-observability-telemetry-integration.md) — OTel tracing infrastructure; LANGSMITH_TRACING integration
- [ADR-013](013-team-composition-topology.md) — multi-agent topology this evaluation covers
- [ADR-023](023-phase-artifact-gates.md) — phase gate compliance (dimension 2)
- [ADR-025](025-mandatory-review-gate.md) — review gate (informs reviewer completeness dimension 5)
- LangSmith `aevaluate()` API: <https://docs.smith.langchain.com/evaluation>
- `agentevals` package: <https://github.com/langchain-ai/agentevals>
- `openevals` package: <https://github.com/langchain-ai/openevals>
- LangGraph v1 release notes: <https://docs.langchain.com/oss/python/releases/langgraph-v1>
