"""Real-behavior tests for static module-docstring resolution."""

import pytest

from docs._ext.module_docstrings import _PACKAGE_ROOT, _module_path


def test_module_path_resolves_package_source() -> None:
    """Resolve a production package to its real ``__init__`` source."""
    path = _module_path("vaultspec_a2a.api")

    assert path == (_PACKAGE_ROOT / "api" / "__init__.py").resolve()


@pytest.mark.parametrize(
    "module_name",
    [
        "other_package.module",
        "vaultspec_a2a..api",
        "vaultspec_a2a.api/../../README",
        r"vaultspec_a2a.api\..\..\README",
    ],
)
def test_module_path_rejects_out_of_boundary_names(module_name: str) -> None:
    """Reject names that cannot identify an in-package Python module."""
    with pytest.raises(ValueError, match="module must be inside"):
        _module_path(module_name)


def test_module_path_rejects_missing_module() -> None:
    """Reject a valid dotted name without a corresponding source file."""
    with pytest.raises(ValueError, match="module source does not exist"):
        _module_path("vaultspec_a2a.not_a_real_module")
