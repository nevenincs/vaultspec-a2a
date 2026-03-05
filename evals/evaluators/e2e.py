"""Dimension 6 -- E2E Task Completion (trajectory + LLM judge).

Thresholds: trajectory_match >= 0.90 AND completion_score >= 0.70

Uses ``agentevals`` trajectory matching in ``superset`` mode and an
LLM completion judge for final artifact assessment.
"""

from __future__ import annotations

# agentevals import deferred to runtime -- requires [eval] extra.
# from agentevals import create_trajectory_match_evaluator
# trajectory_eval = create_trajectory_match_evaluator(mode="superset")
