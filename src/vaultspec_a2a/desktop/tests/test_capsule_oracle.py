"""End-to-end oracle: the real consumer accepts the first-party wheel.

``open_verified_capsule_inputs`` is the production authority that reconciles a
full capsule input set - both closures, both locks, every archive, and the
retained-session envelope.  These tests drive it against a real on-disk input
cache whose Python installed inventory is built through the production
authority (``build_python_installed_inventory``) with the first-party A2A wheel
as an installed member and no reserved attribution record.  A session that
opens without raising is the proof the consumer accepts that shape; the
assertions then pin the shape itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vaultspec_a2a.desktop.tests._capsule_inputs import open_real_capsule_session

if TYPE_CHECKING:
    from pathlib import Path


def test_consumer_accepts_the_first_party_wheel_in_python_installed(
    tmp_path: Path,
) -> None:
    with open_real_capsule_session(
        tmp_path, project_wheel_in_python_installed=True
    ) as session:
        installed = session.python_installed

        # Deps-only license coverage: the dependency carries an attribution
        # record; the first-party wheel does not.
        licensed = {record.package for record in installed.licenses}
        assert licensed == {"click"}
        assert "vaultspec-a2a" not in licensed

        placed = {file.relative_path for file in installed.files}
        # The A2A wheel's modules are materialized (they back the console
        # scripts), so the launchers can import them.
        assert "vaultspec_a2a/cli/main.py" in placed
        assert "vaultspec_a2a/protocols/mcp/__main__.py" in placed
        # No reserved attribution record was authored for the first-party wheel.
        assert not any(
            path.startswith(".capsule-licenses/vaultspec-a2a/") for path in placed
        )
        # Yet the product's own license still ships as its dist-info member.
        assert "vaultspec_a2a-0.1.0.dist-info/licenses/LICENSE" in placed
