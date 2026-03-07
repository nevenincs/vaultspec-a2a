"""Dimension 5 -- Reviewer Completeness (LLM recall judge).

Threshold: defect_recall >= 0.80

Uses an LLM to check whether each planted defect is mentioned in
the reviewer's audit report.
"""

from __future__ import annotations


REVIEWER_RUBRIC = """\
Given a list of defects and a review report, for each defect output 1 if the
defect is mentioned in the report (recall), 0 if not.
Return: {"defect_recall": <float 0-1>}
"""

# Implementation will use openevals.llm_as_judge when datasets are populated.
# Placeholder for scaffold -- actual evaluator wiring in suites/nightly.py.
