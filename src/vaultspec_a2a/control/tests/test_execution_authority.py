"""One exact current-schema authority governs every execution re-entry."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ...providers.team_selection import model_assignment_digest
from ..execution_authority import (
    ExecutionAuthorityError,
    ExecutionAuthorityFailure,
    resolve_execution_authority,
)
from ._catalog_authority import current_execution_metadata


def test_current_freeze_resolves_to_its_complete_canonical_compiler_map(
    tmp_path: Path,
) -> None:
    authority = resolve_execution_authority(current_execution_metadata(tmp_path))

    assert authority.model_assignment
    assert authority.model_assignment_digest == model_assignment_digest(
        authority.model_assignment
    )
    assert all(
        lane["schema_version"] == 1 for lane in authority.model_assignment.values()
    )


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        (None, ExecutionAuthorityFailure.ABSENT),
        ("{", ExecutionAuthorityFailure.CORRUPT),
        (
            json.dumps({"workspace_root": "C:/project"}),
            ExecutionAuthorityFailure.ABSENT,
        ),
        (
            json.dumps({"model_profile": {"profile_id": "retired"}}),
            ExecutionAuthorityFailure.RETIRED,
        ),
        (
            json.dumps(
                {
                    "provider_catalog_selection": {
                        "schema_version": 0,
                        "profile_id": "retired",
                    }
                }
            ),
            ExecutionAuthorityFailure.CORRUPT,
        ),
    ],
)
def test_absent_corrupt_and_retired_authority_fail_with_one_bounded_reason(
    metadata: str | None,
    reason: ExecutionAuthorityFailure,
) -> None:
    with pytest.raises(ExecutionAuthorityError) as raised:
        resolve_execution_authority(metadata)

    assert raised.value.reason is reason
    assert "profile_id" not in str(raised.value)


def test_every_graph_reentry_constructor_supplies_the_exact_authority() -> None:
    control_root = Path(__file__).resolve().parents[1]
    omissions: list[str] = []
    for path in control_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DispatchRequest"
            ):
                continue
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            action = ast.unparse(keywords.get("action", ast.Constant("")))
            if "CANCEL" not in action and "model_assignment" not in keywords:
                omissions.append(f"{path.name}:{node.lineno}")

    assert omissions == []
