"""Tests for the storage-anchor gate.

The gate's whole value is discrimination: it must catch a path anchored to the
repository while clearing the package-data and configuration forms that look
similar. Every case below parses real source through the real ``ast`` module and
calls the real gate functions, and the last case runs the gate as a real
subprocess against this repository.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from dev.guards import storage_anchors

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse(source: str) -> ast.Module:
    """Parse a source fragment the way the gate parses a real module."""
    return ast.parse(source)


def test_a_walk_that_escapes_the_package_is_reported() -> None:
    """The defect this gate exists for: a walk up to the source tree."""
    tree = _parse("ROOT = Path(__file__).resolve().parent.parent.parent.parent\n")
    found = storage_anchors._walk_violations(tree, Path("control/config.py"))
    assert len(found) == 1, found
    assert "escapes the package root" in found[0][1]


def test_a_walk_that_stops_at_the_package_root_is_allowed() -> None:
    """Bundled package data is resolved this way and must not be reported."""
    tree = _parse('BIN = Path(__file__).resolve().parent.parent / "bin"\n')
    assert storage_anchors._walk_violations(tree, Path("providers/factory.py")) == []


def test_a_walk_inside_the_package_is_allowed() -> None:
    """The shallow form used for a module's own asset directory."""
    tree = _parse('RULES = Path(__file__).parent / "presets" / "rules"\n')
    assert storage_anchors._walk_violations(tree, Path("context/rules.py")) == []


def test_the_budget_follows_module_depth_rather_than_a_fixed_number() -> None:
    """A deeper module may take more steps before it leaves the package."""
    source = "ROOT = Path(__file__).resolve().parent.parent.parent\n"
    shallow = storage_anchors._walk_violations(_parse(source), Path("a/mod.py"))
    deep = storage_anchors._walk_violations(_parse(source), Path("a/b/c/mod.py"))
    assert len(shallow) == 1, "three steps escape a module two parts deep"
    assert deep == [], "three steps stay inside a module four parts deep"


def test_a_chain_is_reported_once_at_its_full_length() -> None:
    """Inner nodes of a parent chain must not each report a shorter walk."""
    tree = _parse("ROOT = Path(__file__).parent.parent.parent.parent.parent\n")
    found = storage_anchors._walk_violations(tree, Path("control/config.py"))
    assert len(found) == 1, found
    assert "walk of 5 parents" in found[0][1]


def test_working_directory_reads_are_reported() -> None:
    """Both spellings of "wherever the process happened to start"."""
    tree = _parse("a = Path.cwd()\nb = os.getcwd()\n")
    found = storage_anchors._cwd_violations(tree)
    assert [lineno for lineno, _ in found] == [1, 2], found


def test_an_unrelated_cwd_attribute_is_not_reported() -> None:
    """The gate keys on the real call, not on the word."""
    tree = _parse("value = config.cwd\nother = shutil.which('cwd')\n")
    assert storage_anchors._cwd_violations(tree) == []


def test_install_root_reads_are_reported_outside_the_asset_resolver() -> None:
    """Reading the asset anchor elsewhere is how it becomes a storage root."""
    tree = _parse("root = settings.install_root\n")
    found = storage_anchors._install_root_violations(tree, Path("providers/factory.py"))
    assert len(found) == 1, found
    assert (
        storage_anchors._install_root_violations(
            tree, Path("providers/_factory_commands.py")
        )
        == []
    )


def test_user_profile_anchors_are_reported() -> None:
    """Both spellings of "somewhere in the user's home"."""
    tree = _parse("a = Path.home() / 'x'\nb = Path('~/y').expanduser()\n")
    found = storage_anchors._home_violations(tree)
    assert [lineno for lineno, _ in found] == [1, 2], found


def test_system_temp_is_reported_unless_a_directory_is_given() -> None:
    """``dir=`` places a temporary file under a2a's own state; nothing else does."""
    tree = _parse(
        "a = tempfile.mkdtemp()\n"
        "b = tempfile.TemporaryFile(dir=root)\n"
        "c = tempfile.gettempdir()\n"
        "d = tempfile.NamedTemporaryFile(delete=False)\n"
    )
    found = storage_anchors._tempfile_violations(tree)
    assert [lineno for lineno, _ in found] == [1, 3, 4], found


def test_raw_environment_reads_are_reported_outside_the_settings_module() -> None:
    """Every named read; copying the whole environment for a child is not one."""
    tree = _parse(
        "a = os.environ.get('X')\n"
        "b = os.getenv('Y')\n"
        "c = os.environ['Z']\n"
        "d = os.environ.copy()\n"
        "os.environ['W'] = '1'\n"
    )
    found = storage_anchors._env_read_violations(tree, Path("providers/factory.py"))
    assert [lineno for lineno, _ in found] == [1, 2, 3], found
    assert (
        storage_anchors._env_read_violations(tree, Path("control/settings_base.py"))
        == []
    )


def test_spelled_out_setting_names_are_reported_outside_the_settings() -> None:
    """A literal name is a second declaration; sibling tools' names are theirs."""
    tree = _parse(
        "a = {'VAULTSPEC_A2A_PORT': '1'}\n"
        "b = 'VAULTSPEC_RAG_ROOT'\n"
        "c = 'set VAULTSPEC_A2A_PORT to change it'\n"
    )
    found = storage_anchors._name_literal_violations(tree, Path("cli/main.py"))
    assert [lineno for lineno, _ in found] == [1], found
    assert (
        storage_anchors._name_literal_violations(tree, Path("control/infra_config.py"))
        == []
    )


def test_the_spellings_that_slipped_past_the_first_rules_are_reported() -> None:
    """A None directory, an imported name, and a qualified Path all still count."""
    tree = _parse(
        "from tempfile import mkdtemp as make\n"
        "a = tempfile.mkdtemp(dir=None)\n"
        "b = make()\n"
        "c = pathlib.Path.cwd()\n"
        "d = pathlib.Path.home()\n"
    )
    temp = storage_anchors._tempfile_violations(tree)
    assert [lineno for lineno, _ in temp] == [2, 3], temp
    assert [lineno for lineno, _ in storage_anchors._cwd_violations(tree)] == [4]
    assert [lineno for lineno, _ in storage_anchors._home_violations(tree)] == [5]


def test_test_modules_are_out_of_the_production_rules() -> None:
    """Tests legitimately build paths against the checkout they run in."""
    assert storage_anchors._is_test_module(Path("control/tests/test_config.py"))
    assert storage_anchors._is_test_module(Path("testing/plugin.py"))
    assert storage_anchors._is_test_module(Path("conftest.py"))
    assert not storage_anchors._is_test_module(Path("control/config.py"))


def test_tests_and_tooling_are_held_to_the_tempfile_rule_alone(tmp_path: Path) -> None:
    """Test and dev modules may read the checkout, but never write to system temp."""
    tests_dir = tmp_path / storage_anchors.ROOT / "control" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_probe.py").write_text(
        "import tempfile\n"
        "from pathlib import Path\n"
        "here = Path.cwd()\n"
        "scratch = tempfile.mkdtemp()\n",
        encoding="utf-8",
    )
    tooling = tmp_path / storage_anchors.TOOLING_ROOT
    tooling.mkdir()
    (tooling / "tool.py").write_text(
        "import os\n"
        "import tempfile\n"
        "flag = os.environ.get('ANY')\n"
        "with tempfile.TemporaryDirectory() as scratch:\n"
        "    pass\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "dev" / "guards" / "storage_anchors.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    reported = [line.strip() for line in result.stderr.splitlines() if ".py:" in line]
    assert len(reported) == 2, reported
    assert any("test_probe.py:4: tempfile.mkdtemp()" in line for line in reported)
    assert any("tool.py:4: tempfile.TemporaryDirectory()" in line for line in reported)


def test_the_gate_passes_against_this_repository() -> None:
    """The real invariant, run the way the harness runs it.

    Exit 0 means every remaining violation is one of the explicitly deferred
    modules. A new anchor in production code fails this test.
    """
    result = subprocess.run(
        [sys.executable, "dev/guards/storage_anchors.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"the storage-anchor gate failed:\n{result.stderr}\n{result.stdout}"
    )


def test_every_deferred_module_still_exists() -> None:
    """A deferred entry naming a module that is gone is stale debt bookkeeping."""
    package = REPO_ROOT / storage_anchors.ROOT
    missing = [key for key in storage_anchors.DEFERRED if not (package / key).is_file()]
    assert missing == [], (
        f"deferred entries name modules that no longer exist: {missing}"
    )


def test_the_gate_refuses_to_pass_from_the_wrong_directory() -> None:
    """A gate that silently passes when it scanned nothing is worse than none."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "dev" / "guards" / "storage_anchors.py")],
        cwd=REPO_ROOT / "dev",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 2, result.stdout + result.stderr
