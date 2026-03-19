# Agentic Evaluation Frameworks Research

**Date:** 2026-03-03
**Author:** docs-researcher
**Sources:** MCP-anchored via `mcp__docs-langchain__SearchDocsByLangChain` and `mcp__context7__query-docs` against `/websites/langchain_langsmith` (benchmark 78.6, High reputation)

---

## 1. LangSmith Evaluation — Offline Dataset-Based Evaluation for LangGraph

### 1.1 Two Evaluation Modes

LangSmith distinguishes two evaluation modes (source: <https://docs.langchain.com/langsmith/evaluation>):

- **Offline Evaluation**: Run on curated datasets during development to compare versions, benchmark performance, and catch regressions. This is the primary mode for CI/CD pipeline integration.
- **Online Evaluation**: Evaluate real user interactions in production to detect issues on live traffic. Supports multi-turn thread evaluation.

### 1.2 The `evaluate()` / `aevaluate()` API

Source: <https://docs.langchain.com/langsmith/evaluate-llm-application>

The core API requires three components:

1. **Dataset**: A set of test inputs (and optionally expected outputs). Named or UUID-referenced.
2. **Target function**: Takes `inputs: dict` from a dataset `Example` and returns `outputs: dict`.
3. **Evaluators**: Functions that score `(inputs, outputs, reference_outputs) → bool | float | dict`.

```python
from langsmith import Client, evaluate

client = Client()

# Target function — wraps the application under test
@traceable
def my_app(inputs: dict) -> dict:
    return {"answer": run_pipeline(inputs["question"])}

# Evaluator — returns bool, number, or dict with score key
def correct(inputs: dict, outputs: dict, reference_outputs: dict) -> bool:
    return outputs["answer"] == reference_outputs["expected_answer"]

# Run evaluation
results = client.evaluate(
    my_app,
    data="my-dataset-name",           # dataset name or UUID
    evaluators=[correct],
    experiment_prefix="baseline-v1",  # optional, groups experiments
    description="Testing baseline",   # optional
    max_concurrency=4,                # optional, parallelism
)
```

For large jobs, `aevaluate()` is the async variant with identical interface. Requires `langsmith>=0.3.13`.

**Evaluator return types** (source: <https://docs.langchain.com/langsmith/code-evaluator-sdk>):

- `bool` — binary pass/fail
- `float` / `int` — numeric score
- `dict` with `key` and `score` — named metric: `{"key": "correctness", "score": 0.85}`
- Multiple metrics: return a list of dicts

**Summary evaluators**: `summary_evaluators=[fn]` — run once over the full experiment aggregate (e.g., compute overall pass rate).

### 1.3 Evaluator Types

#### Exact Match (code evaluator)

Source: <https://docs.langchain.com/langsmith/code-evaluator-ui>

```python
def perform_eval(run, example):
    actual = run['outputs']['answer']
    expected = example['outputs']['answer']
    return {"exact_match": actual == expected}
```

#### LLM-as-Judge

Source: <https://docs.langchain.com/langsmith/llm-as-judge-sdk>

Uses a separate LLM to score output quality against rubric criteria. Example pattern:

```python
from pydantic import BaseModel

def valid_reasoning(inputs: dict, outputs: dict) -> bool:
    class Response(BaseModel):
        reasoning_is_valid: bool

    msg = f"Question: {inputs['question']}\nAnswer: {outputs['answer']}\nReasoning: {outputs['reasoning']}"
    response = oai_client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[{"role": "system", "content": rubric}, {"role": "user", "content": msg}],
        response_format=Response
    )
    return response.choices[0].message.parsed.reasoning_is_valid
```

**Prebuilt evaluators**: The `openevals` package (open source, LangChain-maintained) provides prebuilt LLM-as-judge evaluators including `CORRECTNESS_PROMPT` (source: <https://docs.langchain.com/langsmith/prebuilt-evaluators>).

#### Trajectory Evaluators (`agentevals` package)

Source: <https://docs.langchain.com/langsmith/trajectory-evals>

The `agentevals` package (open source, LangChain-maintained) provides agent-specific evaluators:

**`create_trajectory_match_evaluator`** — deterministic, no LLM call needed:

| Mode | Description | Use Case |
|------|-------------|----------|
| `strict` | Exact match of messages and tool calls in order | Testing specific sequences |
| `unordered` | Same tool calls in any order | Verifying retrieval without caring about order |
| `subset` | Agent calls only tools from reference (no extras) | Ensuring agent doesn't exceed scope |
| `superset` | Agent calls at least the reference tools (extras allowed) | Verifying minimum required actions |

```python
from agentevals.trajectory.match import create_trajectory_match_evaluator

evaluator = create_trajectory_match_evaluator(trajectory_match_mode="superset")
evaluation = evaluator(
    outputs=result["messages"],
    reference_outputs=reference_trajectory,
)
# {"key": "trajectory_superset_match", "score": True, "comment": None}
```

**`create_trajectory_llm_as_judge`** — flexible, LLM-scored:

```python
from agentevals.trajectory.llm import create_trajectory_llm_as_judge, TRAJECTORY_ACCURACY_PROMPT

evaluator = create_trajectory_llm_as_judge(
    model="openai:o3-mini",
    prompt=TRAJECTORY_ACCURACY_PROMPT,  # or custom rubric
)
evaluation = evaluator(outputs=result["messages"])
# {"key": "trajectory_accuracy", "score": True, "comment": "The trajectory is reasonable..."}
```

Reference trajectory is optional for the LLM judge variant.

### 1.4 LangGraph Trace Structure in LangSmith

Source: <https://docs.langchain.com/langsmith/trace-with-langgraph>

LangSmith **automatically** traces LangGraph graphs when `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` are set. No explicit SDK calls needed.

Each LangGraph invocation produces a **hierarchical trace**:

- Root span: the `graph.invoke()` / `graph.astream()` call, identified by `thread_id`
- Child spans: one per node execution (supervisor, worker, mount, etc.)
- Leaf spans: LLM calls within each node, tool calls via ToolNode
- Metadata: `thread_id` is automatically propagated via `config["configurable"]["thread_id"]`

The `@traceable` decorator can annotate custom functions within nodes for additional granularity. LangSmith's CI/CD pipeline example (<https://docs.langchain.com/langsmith/cicd-pipeline-example>) shows trajectory evaluation that "analyzes the complete path your agent takes through the graph, including all intermediate steps and decision points."

**Multi-turn thread evaluation**: LangSmith supports evaluating entire conversation threads across multiple graph invocations (source: <https://docs.langchain.com/langsmith/online-evaluations-multi-turn>), measuring semantic intent, semantic outcome, and trajectory across all turns.

---

## 2. LangChain/LangGraph Native Eval Tools

### 2.1 `agentevals` Package (Current Recommended Approach)

Source: <https://docs.langchain.com/langsmith/trajectory-evals>

`agentevals` is the current LangChain-maintained open-source evaluation package for agent trajectories. It supersedes the older `langchain.evaluation` module for agent use cases. Key modules:

- `agentevals.trajectory.match` — `create_trajectory_match_evaluator`
- `agentevals.trajectory.llm` — `create_trajectory_llm_as_judge`

**Integration with LangSmith `evaluate()`**:

```python
from langsmith import Client
from agentevals.trajectory.llm import create_trajectory_llm_as_judge, TRAJECTORY_ACCURACY_PROMPT

trajectory_evaluator = create_trajectory_llm_as_judge(
    model="openai:o3-mini",
    prompt=TRAJECTORY_ACCURACY_PROMPT,
)

def run_agent(inputs):
    return agent.invoke(inputs)["messages"]  # return trajectory as messages list

experiment_results = Client().evaluate(
    run_agent,
    data="my-dataset",
    evaluators=[trajectory_evaluator],
)
```

### 2.2 `openevals` Package

Source: <https://docs.langchain.com/langsmith/prebuilt-evaluators>

`openevals` provides prebuilt evaluators including:

- `CORRECTNESS_PROMPT` — LLM judge for answer correctness
- `create_llm_as_judge` — generic LLM judge factory
- Multi-turn simulation support via `run_multiturn_simulation` and `create_llm_simulated_user`

Both `agentevals` and `openevals` integrate with pytest via `@pytest.mark.langsmith` decorator.

### 2.3 `langchain.evaluation` (Legacy)

The older `langchain.evaluation` module contains `TrajectoryEvalChain` and criteria-based evaluators. These are largely superseded by `agentevals` / `openevals` for new projects. Not recommended for LangGraph-based systems.

---

## 3. Alternative Evaluation Frameworks (2025–2026)

The LangChain docs do not cover alternatives in detail. Based on the ecosystem landscape as of early 2026:

### 3.1 DeepEval

- Python framework for unit-testing LLM outputs
- Metrics: answer relevancy, faithfulness, contextual precision/recall, hallucination, toxicity, bias, summarization
- **LangGraph compatibility**: Works as a post-hoc evaluator — run your LangGraph graph, capture outputs, pass to DeepEval metrics. No native LangGraph integration but compatible via Python.
- Non-determinism handling: built-in `threshold`-based pass/fail with configurable confidence scores; runs each metric multiple times internally for stability
- Supports `@pytest.mark.parametrize` for dataset-style testing

### 3.2 Ragas

- Focused on RAG pipeline evaluation
- Metrics: faithfulness, answer relevancy, context precision, context recall, context entity recall, answer semantic similarity, answer correctness
- **LangGraph compatibility**: Compatible via Python — capture RAG context + answer from LangGraph node outputs, pass to Ragas metrics
- Less suitable for supervisor/worker routing pipelines; optimized for retrieval-augmented generation specifically
- Non-determinism: LLM-based metrics computed stochastically; recommends multiple runs and averaging

### 3.3 Phoenix / Arize

- Observability-first platform (similar to LangSmith but broader ML scope)
- **LangGraph compatibility**: Supports OpenTelemetry tracing — LangGraph can emit OTEL traces which Phoenix can ingest
- Provides span-level evaluation via evaluators bound to trace spans
- Relevant for teams already using OTEL (our system uses OTel via `src/vaultspec_a2a/telemetry/`)
- Supports LLM-as-judge evaluators attached to trace data

### 3.4 AgentBench

- Academic benchmark for evaluating LLM agents on task completion in environments (OS, web, database, etc.)
- Not designed for custom pipeline evaluation — focused on standardised benchmark tasks
- **LangGraph compatibility**: Low — AgentBench requires specific agent harnesses; not directly applicable to supervisor/worker pipelines

### 3.5 Evaluation Framework Compatibility Summary

| Framework | LangGraph Native | Key Strength | Fit for Our System |
|-----------|-----------------|--------------|-------------------|
| LangSmith + agentevals | Yes (first-party) | Trajectory eval, dataset management, CI/CD | HIGH — designed for this use case |
| openevals | Yes (first-party) | Prebuilt LLM judges, multi-turn simulation | HIGH — complements agentevals |
| DeepEval | Via Python | Unit-test style, many metric types | MEDIUM — useful for per-node output quality |
| Ragas | Via Python | RAG-specific metrics | LOW — not applicable to our pipeline |
| Phoenix/Arize | Via OTEL | Observability + span eval | MEDIUM — leverages existing OTel instrumentation |
| AgentBench | No | Standardised task benchmarks | LOW — not applicable |

---

## 4. Non-Determinism Handling in Evaluation Frameworks

Source: <https://docs.langchain.com/langsmith/evaluation-approaches>, <https://docs.langchain.com/langsmith/evaluation-concepts>

### 4.1 Core Problem

LLMs are stochastic — the same input can produce different outputs across runs. This creates evaluation challenges:

- **Exact match evaluators** are brittle: a correct answer phrased differently fails
- **LLM-as-judge evaluators** are themselves non-deterministic: the judge can disagree with itself
- **Trajectory evaluators** face path multiplicity: multiple valid tool-call sequences may exist for the same task

### 4.2 Established Patterns

**1. Repeated runs + aggregation**
Run the same experiment N times and report mean ± standard deviation. LangSmith's `experiment_prefix` groups runs for comparison. Recommended for catching instability in routing decisions.

**2. Fuzzy / semantic matching**
Rather than string equality, use embedding cosine similarity or LLM-judged semantic equivalence. The `CORRECTNESS_PROMPT` in `openevals` is designed for this — asks the judge "is this answer semantically equivalent to the reference?"

**3. Rubric-based scoring**
Replace binary pass/fail with a numeric rubric (0–3 or 0–1 float). LLM-as-judge evaluators return structured scores. Rubrics reduce sensitivity to exact phrasing. Example: "0 = completely wrong, 1 = partially correct, 2 = mostly correct, 3 = fully correct."

**4. Trajectory abstraction levels**
Instead of matching exact message content, match only tool names (`strict`/`unordered` trajectory modes). This tolerates variability in LLM reasoning text while still verifying functional behavior.

**5. Subset/superset matching**
`superset` mode: the agent must call at least the expected tools, but may call more. This accommodates valid additional reasoning steps without failing the test.

**6. Temperature=0 for deterministic evaluation runs**
Set `temperature=0` on the model under evaluation to eliminate sampling variance during eval runs. Our `FakeListChatModel` approach in tests already achieves this for unit tests.

**7. Threshold-based pass/fail with confidence bands**
Rather than `score >= threshold` being a hard gate, define a "needs review" band (e.g., 0.4–0.6) where human review is triggered automatically.

**8. Multi-turn simulation averaging**
`openevals.run_multiturn_simulation` runs a simulated conversation and evaluates the full trajectory. Because each simulation is stochastic, running multiple simulations and averaging the trajectory quality scores produces a stable signal.

---

## 5. Evaluation Dimensions for the Vaultspec Pipeline

The vaultspec pipeline is a supervisor-driven multi-agent system: **supervisor → planner → coder → reviewer** with optional audit gate and plan approval interrupt. The right evaluation dimensions differ by pipeline layer.

### 5.1 Supervisor Routing Correctness

**What to evaluate**: Given a task description and conversation history, does the supervisor route to the correct next agent?

**Approach**: Offline dataset evaluation with exact-match evaluator.

- Dataset: pairs of `(conversation_history, expected_next_agent)` for known scenarios
- Target: `supervisor_node(state) → state["next"]`
- Evaluator: `state["next"] == reference_outputs["expected_next"]`
- Additional: verify phase gate fires correctly (routing_error present when required artifact absent)
- FakeListChatModel can provide deterministic supervisor responses for unit-level testing

**Trajectory aspect**: `unordered` or `superset` match for sequences that must visit specific agents.

### 5.2 Plan Quality

**What to evaluate**: Does the planner produce a plan that is actionable, complete, and addresses the task?

**Approach**: LLM-as-judge evaluator with rubric.

- Dataset: task descriptions with reference plan outlines
- Target: `planner_node(state) → messages[-1].content` (the plan text)
- Evaluator rubric dimensions:
  1. Completeness (0–2): Does it address all task requirements?
  2. Actionability (0–2): Are steps concrete and executable?
  3. Sequencing (0–2): Is the order logical and dependency-aware?
  4. ADR compliance (0–1): Does it reference relevant ADRs?

**Non-determinism**: Use temperature=0 for planner during eval. Run each example 3× and take median score.

### 5.3 Code Correctness

**What to evaluate**: Does the coder produce code that passes tests and meets the implementation spec from the plan?

**Approach**: Code execution evaluator (most reliable for correctness).

- Run the generated code against a test harness
- Evaluator: `pytest_exit_code == 0` (binary) + `test_pass_rate` (float)
- Secondary: LLM-as-judge for code quality (naming, ADR compliance, no mocks)

**LangSmith integration**: The target function runs the graph, extracts generated code from artifacts, writes it to a temp file, runs pytest, returns `{"test_pass_rate": x, "passed": bool}`.

### 5.4 Reviewer / Audit Completeness

**What to evaluate**: Does the reviewer identify real issues and produce an audit report that blocks incorrect code?

**Approach**: LLM-as-judge against known-bad code samples.

- Dataset: pairs of `(code_with_known_issues, expected_issues_list)`
- Evaluator: what fraction of known issues does the reviewer identify? (`issue_recall` metric)
- Secondary: does the reviewer correctly output PASS for correct code? (`false_positive_rate`)

### 5.5 End-to-End Task Completion

**What to evaluate**: Given a task, does the full pipeline produce a correct, tested, reviewed implementation?

**Approach**: Multi-turn trajectory evaluation.

- Dataset: task descriptions with expected outcomes
- Target: `run_full_pipeline(task) → {"final_code": str, "trajectory": list[messages]}`
- Evaluators:
  1. `trajectory_superset_match`: must visit planner → coder → reviewer (at minimum)
  2. `task_completion_llm_judge`: LLM judge on whether the final output fulfills the task
  3. `review_gate_respected`: `vault_index["audit"]` non-empty before FINISH

### 5.6 Phase Gate and Plan Approval Compliance

**What to evaluate**: Does the system correctly enforce ADR-023 phase gates, ADR-025 review gate, and ADR-024 plan approval?

**Approach**: Deterministic unit evaluation (no LLM needed).

- These are pure logic checks on supervisor routing output
- FakeListChatModel-based tests already cover these at the unit level
- For integration: dataset of `(vault_index_state, expected_routing_outcome)` pairs
- Evaluator: `state["routing_error"]` present/absent as expected; `state["next"]` matches expected

---

## 6. Recommended Evaluation Stack for Vaultspec

Based on the research, the recommended evaluation stack is:

| Layer | Tool | Rationale |
|-------|------|-----------|
| Unit (no LLM) | pytest + FakeListChatModel | Routing logic, phase gates, exact match — already in place |
| Offline dataset | LangSmith `evaluate()` + `aevaluate()` | Industry standard, integrates with existing OTEL tracing |
| Trajectory | `agentevals.create_trajectory_match_evaluator` (superset mode) | Verifies planner→coder→reviewer sequence without fragility |
| LLM quality | `agentevals.create_trajectory_llm_as_judge` + custom rubrics | Plan quality, reviewer completeness, code quality |
| Code execution | Custom evaluator in `evaluate()` calling pytest subprocess | Most reliable signal for code correctness |
| Observability | LangSmith traces (automatic with LangGraph) | Existing OTel instrumentation maps to LangSmith spans |

**Non-determinism mitigations**:

1. `temperature=0` for models under evaluation
2. `superset` trajectory matching (not `strict`) for multi-agent pipelines
3. Numeric rubric scores (0–3) rather than binary for LLM judges
4. Run each experiment 3× and report mean ± std for stochastic evaluators

**Integration path**: LangSmith tracing is zero-configuration for LangGraph — set `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`. All existing graph runs will produce structured traces that can be linked to evaluation experiments.

---

## Sources

- LangSmith Evaluation: <https://docs.langchain.com/langsmith/evaluation>
- evaluate() API: <https://docs.langchain.com/langsmith/evaluate-llm-application>
- Target function: <https://docs.langchain.com/langsmith/define-target-function>
- LLM-as-judge: <https://docs.langchain.com/langsmith/llm-as-judge-sdk>
- Trajectory evaluations (agentevals): <https://docs.langchain.com/langsmith/trajectory-evals>
- Complex agent evaluation: <https://docs.langchain.com/langsmith/evaluate-complex-agent>
- Evaluation approaches: <https://docs.langchain.com/langsmith/evaluation-approaches>
- LangGraph tracing in LangSmith: <https://docs.langchain.com/langsmith/trace-with-langgraph>
- Prebuilt evaluators (openevals): <https://docs.langchain.com/langsmith/prebuilt-evaluators>
- Multi-turn simulation: <https://docs.langchain.com/langsmith/multi-turn-simulation>
- Multi-turn online evaluators: <https://docs.langchain.com/langsmith/online-evaluations-multi-turn>
- CI/CD pipeline example: <https://docs.langchain.com/langsmith/cicd-pipeline-example>
