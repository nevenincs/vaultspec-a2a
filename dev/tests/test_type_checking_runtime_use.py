"""Prove the TYPE_CHECKING runtime-use scan fires, and fires only when it should.

Every case here is a real module parsed from real source. The three "safe"
cases are the exact false positives the scan reported against this repository
before each rule was added, so a regression in any of them reproduces a
finding set that was already rejected once.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from dev.quality.source_import_analysis import SourceModule
from dev.quality.type_checking_runtime_use import run_gate, scan_module

if TYPE_CHECKING:
    from pathlib import Path


def _module(tmp_path: Path, source: str) -> SourceModule:
    """Write and parse one module the way the scan's own loader would."""
    path = tmp_path / "subject.py"
    path.write_text(source, encoding="utf-8")
    return SourceModule(
        name="subject",
        path=path,
        tree=ast.parse(source),
        is_test=False,
    )


def test_runtime_expression_is_a_finding(tmp_path: Path) -> None:
    """A guarded name in an executed expression is a NameError waiting."""
    module = _module(
        tmp_path,
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "def convert(value):\n"
        "    return Decimal(value)\n",
    )
    findings, guarded = scan_module(module)
    assert guarded == 1
    assert [f.name for f in findings] == ["Decimal"]
    assert findings[0].line == 5


def test_eager_signature_annotation_is_a_finding(tmp_path: Path) -> None:
    """Without the future import a signature annotation is evaluated at def time."""
    module = _module(
        tmp_path,
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "def convert(value: Decimal) -> Decimal:\n"
        "    return value\n",
    )
    findings, _ = scan_module(module)
    assert {f.name for f in findings} == {"Decimal"}
    assert all("evaluated eagerly" in f.position for f in findings)


def test_deferred_annotations_clear_every_annotation(tmp_path: Path) -> None:
    """With the future import an annotation is a string and never evaluated."""
    module = _module(
        tmp_path,
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "TOTAL: Decimal\n"
        "def convert(value: Decimal) -> Decimal:\n"
        "    return value\n",
    )
    findings, guarded = scan_module(module)
    assert guarded == 1
    assert findings == ()


def test_function_local_annotation_is_never_evaluated(tmp_path: Path) -> None:
    """PEP 526 does not evaluate a local variable's annotation, future import or not."""
    module = _module(
        tmp_path,
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "def convert(raw):\n"
        "    value: Decimal = raw\n"
        "    return value\n",
    )
    findings, _ = scan_module(module)
    assert findings == ()


def test_module_level_annotation_without_future_is_a_finding(tmp_path: Path) -> None:
    """A module-level annotation IS evaluated, and lands in __annotations__."""
    module = _module(
        tmp_path,
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "TOTAL: Decimal = None\n",
    )
    findings, _ = scan_module(module)
    assert [f.name for f in findings] == ["Decimal"]


def test_type_parameter_bound_is_lazy(tmp_path: Path) -> None:
    """A PEP 695 bound is evaluated only when something reads ``__bound__``."""
    module = _module(
        tmp_path,
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Callable\n"
        "def wrap[NodeT: Callable[..., object]](node: NodeT):\n"
        "    return node\n",
    )
    findings, _ = scan_module(module)
    assert findings == ()


def test_local_reimport_clears_the_guarded_name(tmp_path: Path) -> None:
    """Re-importing inside the function is the idiomatic fix, not a finding."""
    module = _module(
        tmp_path,
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "def convert(value):\n"
        "    from decimal import Decimal\n"
        "    return Decimal(value)\n",
    )
    findings, _ = scan_module(module)
    assert findings == ()


def test_unparseable_source_refuses_to_report_clean(tmp_path: Path) -> None:
    """A tree that cannot be read is unavailable, never green."""
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("def broken(\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unavailable"):
        run_gate(repo_root=tmp_path, package_root=package)


def test_the_real_package_is_clean() -> None:
    """The live tree holds the line this gate was written to hold."""
    verdict = run_gate()
    assert verdict.guarded_names > 0, "a zero denominator proves nothing"
    assert verdict.is_clean, verdict.report()
