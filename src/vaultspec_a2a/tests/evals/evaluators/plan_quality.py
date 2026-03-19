"""Dimension 3 -- Plan Quality (LLM-as-judge rubric).

Threshold: plan_quality >= 0.75

Uses ``openevals`` LLM-as-judge with a custom rubric scoring
completeness, actionability, ADR compliance, and task granularity.
"""

from __future__ import annotations

PLAN_QUALITY_RUBRIC = """\
Given a feature request and a plan document, score the plan 0-1 on:
- COMPLETENESS: all pipeline stages (research->adr->plan->exec->audit) addressed
- ACTIONABILITY: each step has a concrete, executable description
- ADR_COMPLIANCE: plan references relevant ADRs; no contradictions
- TASK_GRANULARITY: tasks are appropriately sized (not too coarse, not too fine)

Respond with JSON: {"score": <float 0-1>, "reasoning": "<string>"}
"""

# Implementation will use openevals.llm_as_judge when datasets are populated.
# Placeholder for scaffold -- actual evaluator wiring in suites/nightly.py.
