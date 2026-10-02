"""The export gate reads consumers at the repository root."""

from pathlib import Path

from dev.quality.unconsumed_export_coverage import run_gate


def test_root_conftest_consumes_a_package_export(tmp_path: Path) -> None:
    package = tmp_path / "src" / "vaultspec_a2a"
    package.mkdir(parents=True)
    (package / "settings.py").write_text(
        '__all__ = ["build_now"]\ndef build_now():\n    return None\n',
        encoding="utf-8",
    )
    (tmp_path / "conftest.py").write_text(
        "from vaultspec_a2a.settings import build_now\nbuild_now()\n",
        encoding="utf-8",
    )

    verdict = run_gate(repo_root=tmp_path, package_root=package)

    assert verdict.exports_scanned == 1
    assert verdict.is_clean, verdict.report()
