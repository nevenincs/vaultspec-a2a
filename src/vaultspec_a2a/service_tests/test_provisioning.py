"""Service-layer proof that the provision fixture yields a harness-ready workspace.

Exercises the ``provisioned_workspace`` fixture (the adoption of the provision
verb in the service fixtures) against the real harness verifier - a genuine
``vaultspec-core install`` under the fixture, no doubles. This is the fixture
adoption called for ("the service fixtures call it"), proven at the
service-test layer independently of the compose stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..context.harness import DEFAULT_REQUIRED_TEMPLATES, verify_harness

if TYPE_CHECKING:
    from pathlib import Path


def test_provisioned_workspace_fixture_is_harness_ready(
    provisioned_workspace: Path,
) -> None:
    """The fixture's provisioned workspace passes the real harness verifier."""
    verdict = verify_harness(provisioned_workspace)
    assert verdict.ready, verdict.reasons
    assert verdict.reasons == []


def test_provisioned_workspace_carries_the_required_surfaces(
    provisioned_workspace: Path,
) -> None:
    """Provisioning materialized the flat rules corpus and every required template."""
    assert any((provisioned_workspace / ".vaultspec" / "rules").glob("*.md"))
    templates = provisioned_workspace / ".vaultspec" / "templates"
    for name in DEFAULT_REQUIRED_TEMPLATES:
        assert (templates / f"{name}.md").is_file(), name
