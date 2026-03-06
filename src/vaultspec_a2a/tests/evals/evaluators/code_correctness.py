"""Dimension 4 -- Code Correctness Rate (pytest subprocess).

Threshold: test_pass_rate >= 0.85
"""

from __future__ import annotations

import re
import subprocess
import sys

from typing import Any


_PYTEST_SUMMARY_RE = re.compile(r"(\d+) passed")
_PYTEST_FAILED_RE = re.compile(r"(\d+) failed")


def code_correctness_evaluator(run: Any, example: Any) -> dict:
    """Run pytest against the coder agent's output directory."""
    output_dir = run.outputs.get("output_dir", "")
    if not output_dir:
        return {"key": "test_pass_rate", "score": 0.0}

    result = subprocess.run(
        [sys.executable, "-m", "pytest", output_dir, "--tb=no", "-q"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    passed = 0
    failed = 0
    match_passed = _PYTEST_SUMMARY_RE.search(result.stdout)
    match_failed = _PYTEST_FAILED_RE.search(result.stdout)
    if match_passed:
        passed = int(match_passed.group(1))
    if match_failed:
        failed = int(match_failed.group(1))

    total = passed + failed
    score = passed / total if total > 0 else 0.0
    return {"key": "test_pass_rate", "score": score}
