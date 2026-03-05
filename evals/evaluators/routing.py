"""Dimension 1 -- Supervisor Routing Accuracy (exact match).

Threshold: routing_accuracy >= 0.90
"""

from __future__ import annotations

from typing import Any


def routing_evaluator(run: Any, example: Any) -> dict:
    """Compare supervisor's ``next`` output to the expected label."""
    predicted = run.outputs.get("next", "")
    expected = example.outputs.get("expected_next", "")
    return {
        "key": "routing_correct",
        "score": int(predicted == expected),
    }
