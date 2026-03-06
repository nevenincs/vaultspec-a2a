"""Dimension 2 -- Phase Gate Compliance (deterministic).

Threshold: gate_compliance == 1.0
"""

from __future__ import annotations

from typing import Any


def gate_compliance_evaluator(run: Any, example: Any) -> dict:
    """Check that the gate blocks/passes as expected."""
    expect_blocked = example.outputs.get("expect_blocked", False)
    has_error = bool(run.outputs.get("routing_error"))
    return {
        "key": "gate_compliant",
        "score": int(has_error == expect_blocked),
    }
