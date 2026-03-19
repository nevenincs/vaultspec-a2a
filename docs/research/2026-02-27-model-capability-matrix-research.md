---
date: 2026-02-27
type: research
feature: model-capability-matrix
description: 'Matrix of LLM provider capabilities relevant to A2A agent orchestration.'
---

# Model Capability Matrix — A2A Coding Teams

**Date:** 2026-02-27
**Type:** Research Fact Sheet
**Purpose:** Reference for agent role assignment, team composition, and model
selection in the a2a orchestration system.

---

## 1. Benchmark Rankings (February 2026)

### SWE-bench Verified — Real-World Code Fix Tasks

| Rank | Model              | Score   | Notes                                        |
| ---- | ------------------ | ------- | -------------------------------------------- |
| 1    | Claude Opus 4.5    | 80.9%   | Self-reported; 79.2% third-party (vals.ai)   |
| 2    | Claude Opus 4.6    | 80.8%   | Self-reported; 79.2–79.4% third-party        |
| 3    | MiniMax M2.5       | 80.2%   | Open-weight; not in our provider matrix      |
| 4    | GPT-5.2            | 80.0%   | Fewer tokens per problem than Claude         |
| 5    | GLM-5              | 77.8%   | $0.11/MTok; competitive frontier performance |
| 6    | Claude Sonnet 4.5  | 77.2%   | —                                            |
| 6†   | **Gemini 3 Flash** | **78%** | **Beats Gemini 3 Pro** on coding tasks       |
| 7    | Kimi K2.5          | 76.8%   | Not in our provider matrix                   |
| 8    | Gemini 3 Pro       | 76.2%   | Beaten by its own Flash variant              |
| 9    | Claude Haiku 4.5   | 73.3%   | "World-class" at price tier                  |

> **Critical finding:** Gemini 3 Flash outperforms Gemini 3 Pro on SWE-bench
> Verified (78% vs 76.2%). Flash was specifically optimised for the high-frequency
> iteration pattern that characterises agentic coding. This inverts the naive
> "bigger = better for coding" assumption.

### SWE-bench Pro — Harder, Closer to Real Work

| Model                                               | Score |
| --------------------------------------------------- | ----- |
| GPT-5.3-Codex                                       | 56.8% |
| GPT-5.2-Codex                                       | 56.4% |
| GPT-5.2                                             | 55.6% |
| (All others drop dramatically from Verified scores) |       |

> All models score 20–30 points lower on Pro vs Verified. Pro more closely
> reflects actual software engineering difficulty. GPT-5.3-Codex leads here.

### Terminal-Bench 2.0 — Agentic Shell Workflows

| Model                     | Score |
| ------------------------- | ----- |
| GPT-5.3-Codex (Codex CLI) | 77.3% |
| GPT-5.3-Codex             | 75.1% |
| Claude Opus 4.6 (Droid)   | 69.9% |

---

## 2. Context Windows, Speed, and Pricing

| Model             | Provider  | Context   | Speed (tok/s) | Input ($/MTok) | Output ($/MTok) |
| ----------------- | --------- | --------- | ------------- | -------------- | --------------- |
| Claude Opus 4.6   | Anthropic | 1M (beta) | —             | $5.00          | $25.00          |
| Claude Sonnet 4.6 | Anthropic | 1M        | —             | $3.00          | $15.00          |
| Claude Haiku 4.5  | Anthropic | —         | —             | $1.00          | $5.00           |
| Gemini 3 Pro      | Google    | **2M**    | baseline      | $2–4           | —               |
| Gemini 3 Flash    | Google    | 1M        | **209**       | **$0.50**      | $3.00           |
| GPT-5.2           | OpenAI    | 400K      | —             | ~$3.00         | ~$15.00         |
| GPT-5.3-Codex     | OpenAI    | 400K      | —             | ~$1.75         | $14.00          |
| GLM-5             | ZhipuAI   | 200K      | —             | **$0.11**      | ~$0.11          |

### Key Context Observations

- **Gemini 3 Pro** holds the largest context window (2M tokens). Best for
  supervision of very large codebases where the entire context must be held
  simultaneously.
- **Claude Opus 4.6** has 1M token context in beta with native multi-agent
  coordination. Best for multi-agent supervision tasks.
- **GPT-5.2/Codex** is capped at 400K but compensates with context compaction —
  a unique feature that allows very long-horizon tasks to continue past the
  context limit by summarising previous work.
- **GLM-5** is limited to 200K context, which constrains it for supervisory
  roles but is adequate for focused tasks (review, research).

### Cost Efficiency Comparisons

- Gemini Flash is **6x cheaper** than Claude Sonnet for equivalent tasks
- Gemini Flash is **10–30x cheaper** for batch/high-volume operations ($0.01 vs
  $0.30 per request estimate)
- GLM-5 is the cheapest frontier model at $0.11/MTok with MIT license
- Claude Haiku batch processing offers up to **90% savings** with prompt
  caching, **50%** with batch API
- A 70/20/10 workload split (Haiku/Sonnet/Opus) cuts costs by ~60% vs all-Sonnet

---

## 3. Qualitative Capability Profiles

### Claude (Anthropic)

**Tier position:** Dominant in code quality, architecture, and extended
reasoning.

### Strengths

- Architecture-level thinking, system design, refactoring
- Sustained performance over extended autonomous sessions — "does not accumulate
  errors" over long reasoning chains
- Multi-agent coordination native (Opus 4.6 supports parallel sub-agents)
- Code review quality — "reviews logic, questions assumptions, highlights
  issues" rather than accepting premises
- Security audits, large-scale migrations, cross-file consistency analysis
- Developer consensus: preferred for "thoughtful, architecture-level work" over
  GPT
- Sonnet 4.6 within 1.2% of Opus 4.6 on SWE-bench — the practical gap is narrow

### Weaknesses

- Most expensive provider per token
- No context compaction (GPT's advantage for very long autonomous runs)

**Role fit:** Supervisor (Opus), Planner (Sonnet), Coder (Sonnet/Haiku),
Reviewer (Haiku)

---

### Gemini (Google)

**Tier position:** Strongest for speed-intensive iterative coding; Flash beats
Pro on benchmarks.

### Flash strengths

- Optimised for agentic/iterative coding loops: write → test → fix → repeat
- Fastest generation at 209 tok/s (3x faster than Pro)
- Surprisingly beats Gemini Pro on SWE-bench Verified (78% vs 76.2%)
- Ideal for rapid prototyping, UI tweaks, repetitive changes
- Most cost-effective for high-frequency coding iteration

### Flash weaknesses

- Developer reports describe it as "less thorough than prior Gemini versions"
  for multi-step reasoning
- Reports of unexpectedly large token usage in some workflows
- Approaches code as something "to be produced quickly" — less suited for
  design-heavy reasoning
- Requires "repeated prompting for multi-step reasoning or careful retrieval"

### Pro strengths

- Largest context window available (2M tokens)
- Deeper reasoning for the ~5% of tasks needing maximum depth
- Better for complex architectural thinking and planning
- Strong multimodal (relevant when analysing screenshots, diagrams, etc.)

### Pro weaknesses

- Beaten by its own Flash variant on coding benchmarks — counterintuitive
- Higher cost than Flash with weaker coding performance

**Decision (confirmed):** Flash = default Gemini for coding roles (LOW/MID). Pro
= supervision/planning roles requiring large context.

**Role fit:** Coder (Flash/LOW), Supervisor (Pro/HIGH), Planner (Pro/MID)

---

### OpenAI (GPT-5 / Codex)

**Tier position:** Strongest for long-horizon terminal-intensive tasks; leads
SWE-bench Pro.

### Strengths: (2)

- Context compaction — unique ability to continue very long tasks by summarising
  past context
- Strongest on SWE-bench Pro (most realistic benchmark) and Terminal-Bench
- "Improved performance in Windows environments" — relevant for our stack
- GPT-5.2 uses "significantly fewer tokens per problem" than Claude (efficiency)
- Preferred for "quick, one-off coding tasks where speed of response matters
  most"
- Codex variant is specialised for software engineering with enhanced agentic
  tooling

### Weaknesses: (2)

- 400K context cap — smallest among top-tier models
- GPT-5 "generally seen as more intelligent for complex reasoning but can be
  slower and use more tokens" in some comparisons
- Less preferred for architecture-level reasoning vs Claude

**Role fit:** Coder (HIGH — especially for complex refactors/migrations),
Supervisor (not ideal due to context cap)

---

### ZhipuAI (GLM-5)

**Tier position:** Budget frontier model; competitive on benchmarks but
operationally sequential.

### Strengths: (3)

- 77.8% SWE-bench Verified — competitive with Gemini Flash
- BrowseComp leader (62.0 vs Claude Opus 4.5's 37.0) — excellent for
  research/retrieval tasks
- Cheapest frontier-class model: $0.11/MTok, MIT license
- Confirmed capable of: lint fixes, merge conflict resolution, code audits,
  release notes
- Strong at knowledge retrieval and research synthesis

### Critical operational weakness

- **Sequential tool use** — does tasks one at a time rather than firing parallel
  operations simultaneously
- Developer comparison: "Opus fires off parallel file reads and runs lint and
  typecheck simultaneously; GLM-5 did everything one at a time"
- This makes it unsuitable for the implementation coder role (where parallel
  read+test+fix matters)
- For sequential review tasks (read file A → assess → read file B → assess),
  sequential operation is **not a problem**

**Role fit (confirmed):** Reviewer (code audit, lint enforcement), Researcher
(knowledge retrieval, documentation lookup, gap analysis). NOT suitable as
primary coder due to sequential tool use.

---

## 4. Coordination & Team Size Research Findings

From Google's February 2026 multi-agent scaling research:

- **Optimal team size:** 3–7 agents per workflow
- Beyond 7 agents: communication overhead grows **exponentially**
- Tasks where solo performance already exceeds 45% accuracy see **negative
  returns** from adding agents
- In some test scenarios, every multi-agent variant tested **degraded
  performance 39–70%** vs solo agent
- Critical saturation point: **0.39 messages/turn** — beyond this, additional
  coordination yields diminishing returns

### Validated Architecture (Cursor's Production System)

3 roles: **Planners → Workers → Judge**

- Equal-status agents with locking (20 agents) → throughput of 2–3
- Role-based hierarchy (3 roles) → solved coordination, scaled to large projects
  without tunnel vision

**Implication for our presets:** Maximum 4 active agents per team. The 3-role
structure (Supervisor/Planner → Coder → Reviewer) is empirically validated.

---

## 5. Recommended Role-to-Model Matrix

### Decision Framework

| Role                   | Priority                     | Primary Model      | Rationale                                                        |
| ---------------------- | ---------------------------- | ------------------ | ---------------------------------------------------------------- |
| **Supervisor**         | Context + reasoning          | Claude Opus MAX    | 1M context, multi-agent native, deep routing logic               |
| **Planner**            | Reasoning + codebase reading | Claude Sonnet HIGH | Near-Opus reasoning, 5x cheaper, excellent for specs             |
| **Coder (standard)**   | Implementation quality       | Claude Sonnet MID  | Default choice; near-Opus quality, same-provider trust           |
| **Coder (fast)**       | Speed + cost                 | Gemini Flash LOW   | 3x faster, 6x cheaper, beats Pro on SWE-bench                    |
| **Coder (complex)**    | Architecture + long-horizon  | Claude Sonnet HIGH | For refactors, migrations, complex feature work                  |
| **Coder (budget)**     | Cost minimisation            | Claude Haiku MID   | 73.3% SWE-bench, $1/MTok, 1/3 cost of Sonnet                     |
| **Reviewer**           | Lint + safety                | GLM-5 MID          | Sequential tool use fits review; $0.11/MTok; BrowseComp strength |
| **Reviewer (quality)** | Deep architecture review     | Claude Haiku MID   | When GLM-5 context limit (200K) is a constraint                  |
| **Researcher**         | Knowledge retrieval          | GLM-5 MID          | BrowseComp leader; research/synthesis natural fit                |
| **Researcher (deep)**  | ADR/technical research       | Claude Sonnet HIGH | Complex multi-source synthesis requiring deep reasoning          |

### Provider-Topology Combinations

| Preset Name       | Topology      | Supervisor   | Coder               | Reviewer     |
| ----------------- | ------------- | ------------ | ------------------- | ------------ |
| `coding-star`     | star          | Claude Opus  | Claude Sonnet (MID) | GLM-5        |
| `coding-pipeline` | pipeline      | —            | Claude Sonnet (MID) | GLM-5        |
| `coding-loop`     | pipeline_loop | —            | Gemini Flash        | GLM-5        |
| `gemini-star`     | star          | Gemini Pro   | Gemini Flash        | GLM-5        |
| `solo-coder`      | pipeline      | —            | Claude Sonnet (MID) | —            |
| `budget-star`     | star          | Gemini Flash | GLM-5               | Gemini Flash |

---

## 6. Validated Hypotheses

| Original Hypothesis                              | Verdict                   | Evidence                                                                                               |
| ------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------ |
| Claude excellent at planning/architecture        | **Confirmed**             | Developer consensus across multiple sources; Claude preferred for "architecture-level work"            |
| Gemini Flash better/cheaper for implementation   | **Confirmed**             | Flash beats Pro on SWE-bench (78% vs 76.2%); 6x cheaper; 209 tok/s                                     |
| Large context → better supervision of long tasks | **Confirmed**             | Gemini Pro 2M and Claude Opus 1M are the viable supervisors for large codebases                        |
| Fast/cheap models for menial cleanup             | **Confirmed**             | Haiku 4.5 (73.3%, $1/MTok) and Gemini Flash ($0.50/MTok) are validated                                 |
| GLM-5 for review/lint/research                   | **Confirmed with caveat** | BrowseComp leader; confirmed for audit/lint. Cannot parallelise tool calls — unsuitable for coder role |
| More agents = better results                     | **Refuted**               | Google research: 39–70% degradation in some multi-agent scenarios. 3-role teams validated.             |

---

## Sources

- [SWE-bench Leaderboard](https://www.swebench.com/)
- [SWE-bench February 2026 — marc0.dev](https://www.marc0.dev/en/leaderboard)
- [Claude Sonnet 4.6 vs Gemini 3 Flash —
  NxCode](https://www.nxcode.io/resources/news/claude-sonnet-4-6-vs-gemini-3-flash-ai-model-comparison-2026)
- [Best AI for Developers —
  Cosmic](https://www.cosmicjs.com/blog/best-ai-for-developers-claude-vs-gpt-vs-gemini-technical-comparison-2026)
- [Gemini 3 Flash vs Pro —
  aifreeapi.com](https://www.aifreeapi.com/en/posts/gemini-3-flash-vs-pro-capabilities)
- [Gemini 3 Flash Review — Serenities
  AI](https://serenitiesai.com/articles/gemini-3-flash-pro-review-2026)
- [Claude Sonnet 4.6 vs Opus 4.6 —
  NxCode](https://www.nxcode.io/resources/news/claude-sonnet-4-6-vs-opus-4-6-which-model-to-choose-2026)
- [GPT-5.3-Codex — OpenAI](https://openai.com/index/introducing-gpt-5-3-codex/)
- [GLM-5 Complete Guide —
  NxCode](https://www.nxcode.io/resources/news/glm-5-open-source-744b-model-complete-guide-2026)
- [GLM-5: From Vibe Coding to Agentic Engineering —
  arXiv](https://arxiv.org/html/2602.15763v1)
- [AI Coding Agents 2026 — Faros
  AI](https://www.faros.ai/blog/best-ai-model-for-coding-2026)
- [Towards a Science of Scaling Agent Systems —
  arXiv](https://arxiv.org/html/2512.08296v1)
- [Google Agent Scaling Principles —
  InfoQ](https://www.infoq.com/news/2026/02/google-agent-scaling-principles/)
- [Scaling Long-Running Autonomous Coding —
  Cursor](https://cursor.com/blog/scaling-agents)
- [2026 Agentic Coding Trends Report —
  Anthropic](https://resources.anthropic.com/2026-agentic-coding-trends-report)
- [Claude Haiku 4.5 — Anthropic](https://www.anthropic.com/claude/haiku)
- [LogRocket AI Dev Tool Power Rankings Feb
  2026](https://blog.logrocket.com/ai-dev-tool-power-rankings/)
