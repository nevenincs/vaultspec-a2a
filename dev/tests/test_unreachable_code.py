"""Prove the reachability audit over a real tree built for the purpose.

Each fixture writes an actual package to disk, with an actual
``pyproject.toml`` naming an actual console script, and runs the real scan
against it. Nothing is stubbed: the audit's whole job is reading a source
tree, so a test that hands it anything other than a source tree tests the
wrong thing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev.audit.unreachable_code import (
    ModuleReach,
    ShippedTreeSpec,
    UnreachableCodeOutcome,
    scan_unreachable_code,
)

if TYPE_CHECKING:
    from pathlib import Path

PYPROJECT = """
[project]
name = "sample"
version = "0"

[project.scripts]
sample = "sample.cli:main"
"""


def _tree(
    root: Path, modules: dict[str, str], *, manifest: str = PYPROJECT
) -> ShippedTreeSpec:
    """Write a shipped package to disk and return its spec."""
    (root / "pyproject.toml").write_text(manifest, encoding="utf-8")
    package = root / "src" / "sample"
    for name, source in modules.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return ShippedTreeSpec(
        repo_root=root,
        src_root=root / "src",
        package_root=package,
        package="sample",
    )


def test_a_module_no_entry_point_imports_is_unreachable(tmp_path: Path) -> None:
    """The whole point: bytes that ship and nothing loads."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "from .engine import run\n\n\ndef main():\n    return run()\n",
            "engine.py": "def run():\n    return 1\n",
            "orphan.py": "def never_called():\n    return 2\n",
        },
    )
    result = scan_unreachable_code(spec)
    assert result.outcome is UnreachableCodeOutcome.FINDINGS
    assert [f.module for f in result.modules] == ["sample.orphan"]
    assert result.modules[0].reach is ModuleReach.UNREACHABLE


def test_root_conftest_pytest_hooks_are_framework_consumers(tmp_path: Path) -> None:
    """Only registered plugin hooks are exempt from unused-symbol findings."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "def main():\n    return 1\n",
            "plugin.py": (
                "def pytest_report_header(config):\n    return 'ready'\n"
                "def unused_helper():\n    return 2\n"
            ),
        },
    )
    (tmp_path / "conftest.py").write_text(
        "pytest_plugins = ('sample.plugin',)\n", encoding="utf-8"
    )

    result = scan_unreachable_code(spec)
    findings = {(item.module, item.name) for item in result.symbols}
    assert ("sample.plugin", "pytest_report_header") not in findings
    assert ("sample.plugin", "unused_helper") in findings


def test_main_guard_and_configured_script_imports_are_entry_points(
    tmp_path: Path,
) -> None:
    """Direct module commands and configured scripts reach their package code."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "def main():\n    return 1\n",
            "admin.py": (
                "def main():\n    return 0\n"
                "if __name__ == '__main__':\n    raise SystemExit(main())\n"
            ),
            "engine.py": "def run():\n    return 1\n",
        },
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "engine_serve.py").write_text(
        "from sample.engine import run\n", encoding="utf-8"
    )
    (tmp_path / "procs.toml").write_text(
        'serve = ["{python}", "scripts/engine_serve.py"]\n', encoding="utf-8"
    )

    result = scan_unreachable_code(spec)
    unreachable = {item.module for item in result.modules}
    assert "sample.admin" not in unreachable
    assert "sample.engine" not in unreachable


def test_a_type_checking_only_import_does_not_make_a_module_runtime(
    tmp_path: Path,
) -> None:
    """A guarded import never executes, so the module it names never loads."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from .shapes import Shape\n"
                "def main():\n"
                "    return 1\n"
            ),
            "shapes.py": "class Shape:\n    pass\n",
        },
    )
    result = scan_unreachable_code(spec)
    reaches = {f.module: f.reach for f in result.modules}
    assert reaches["sample.shapes"] is ModuleReach.TYPE_ONLY


def test_a_module_named_only_in_a_string_is_reached(tmp_path: Path) -> None:
    """A dotted string is how a factory, a worker target and a plugin are bound."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": (
                'TARGET = "sample.worker:serve"\n\n\ndef main():\n    return TARGET\n'
            ),
            "worker.py": "def serve():\n    return 1\n",
        },
    )
    result = scan_unreachable_code(spec)
    assert [f.module for f in result.modules] == []


def test_a_decorated_function_is_not_reported_unused(tmp_path: Path) -> None:
    """A registration decorator reaches a function without spelling its name."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": (
                "app = object()\n"
                "\n"
                "\n"
                "def route(path):\n"
                "    return lambda fn: fn\n"
                "\n"
                "\n"
                "@route('/health')\n"
                "def health():\n"
                "    return 1\n"
                "\n"
                "\n"
                "def main():\n"
                "    return 1\n"
            ),
        },
    )
    result = scan_unreachable_code(spec)
    assert "health" not in {f.name for f in result.symbols}


def test_a_symbol_only_its_own_test_imports_is_a_labelled_finding(
    tmp_path: Path,
) -> None:
    """Code kept alive by the test written for it is the orphan signal."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            # `helpers` must be a RUNTIME module: the symbol layer only looks
            # inside modules an entry point reaches, because a symbol in a
            # dead module is already covered by that module's own finding.
            "cli.py": "from . import helpers\n\n\ndef main():\n    return helpers\n",
            "helpers.py": "def only_tested():\n    return 7\n",
            "tests/__init__.py": "",
            "tests/test_helpers.py": (
                "from ..helpers import only_tested\n"
                "\n"
                "\n"
                "def test_it():\n"
                "    assert only_tested() == 7\n"
            ),
        },
    )
    result = scan_unreachable_code(spec)
    finding = next(f for f in result.symbols if f.name == "only_tested")
    assert finding.used_by == ("tests",)


def test_an_all_entry_does_not_clear_its_own_symbol(tmp_path: Path) -> None:
    """Publishing a name is not using it; the opposite makes the layer vacuous."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "from . import surface\n\n\ndef main():\n    return surface\n",
            "surface.py": (
                '__all__ = ["published"]\n\n\ndef published():\n    return 1\n'
            ),
        },
    )
    result = scan_unreachable_code(spec)
    assert "published" in {f.name for f in result.symbols}


def test_a_real_self_reference_clears_a_published_symbol(tmp_path: Path) -> None:
    """The exclusion is scoped to the __all__ literal, not to the exported names."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "from . import surface\n\n\ndef main():\n    return surface\n",
            "surface.py": (
                '__all__ = ["scheme", "read"]\n'
                "\n"
                "\n"
                "scheme = object()\n"
                "\n"
                "\n"
                "def read():\n"
                "    return scheme\n"
            ),
        },
    )
    result = scan_unreachable_code(spec)
    assert "scheme" not in {f.name for f in result.symbols}


def test_a_test_whose_every_subject_is_dead_is_an_orphan(tmp_path: Path) -> None:
    """The code and its tests can then be retired together."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "def main():\n    return 1\n",
            "orphan.py": "def gone():\n    return 1\n",
            "tests/__init__.py": "",
            "tests/test_orphan.py": (
                "from ..orphan import gone\n\n\n"
                "def test_it():\n    assert gone() == 1\n"
            ),
        },
    )
    result = scan_unreachable_code(spec)
    assert [f.module for f in result.tests] == ["sample.tests.test_orphan"]


def test_a_tree_with_no_resolvable_entry_point_is_an_error(tmp_path: Path) -> None:
    """Everything would read as unreachable, which is a broken scan, not a finding."""
    spec = _tree(
        tmp_path,
        {"__init__.py": "", "thing.py": "def run():\n    return 1\n"},
        manifest='[project]\nname = "sample"\nversion = "0"\n',
    )
    result = scan_unreachable_code(spec)
    assert result.outcome is UnreachableCodeOutcome.ERROR
    assert "entry point" in result.reason


def test_a_fully_reachable_tree_is_clean(tmp_path: Path) -> None:
    """Green is reachable; a gate that can only be red teaches people to skip it."""
    spec = _tree(
        tmp_path,
        {
            "__init__.py": "",
            "cli.py": "from .engine import run\n\n\ndef main():\n    return run()\n",
            "engine.py": "def run():\n    return 1\n",
        },
    )
    result = scan_unreachable_code(spec)
    assert result.outcome is UnreachableCodeOutcome.CLEAN, result.headline()
    assert result.modules_scanned == 3
