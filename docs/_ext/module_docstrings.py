"""Render Python module docstrings without importing runtime modules."""

from __future__ import annotations

import ast
from pathlib import Path
from textwrap import indent
from typing import TYPE_CHECKING

from sphinx.util.docutils import SphinxDirective

if TYPE_CHECKING:
    from docutils import nodes
    from sphinx.application import Sphinx
    from sphinx.util.typing import ExtensionMetadata

_PACKAGE = "vaultspec_a2a"
_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
_PACKAGE_ROOT = (_SOURCE_ROOT / _PACKAGE).resolve()


def _module_path(module_name: str) -> Path:
    """Return the source path for an in-project module."""
    parts = module_name.split(".")
    if (
        not parts
        or parts[0] != _PACKAGE
        or any(not part.isidentifier() for part in parts)
    ):
        raise ValueError(f"module must be inside {_PACKAGE!r}: {module_name!r}")

    module_base = _SOURCE_ROOT.joinpath(*parts)
    candidates = (module_base.with_suffix(".py"), module_base / "__init__.py")
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(_PACKAGE_ROOT) and resolved.is_file():
            return resolved
    raise ValueError(f"module source does not exist: {module_name!r}")


class AutoModuleDoc(SphinxDirective):
    """Register a module and render its source docstring as reStructuredText."""

    required_arguments = 1
    final_argument_whitespace = False
    has_content = False

    def run(self) -> list[nodes.Node]:
        module_name = self.arguments[0]
        try:
            source_path = _module_path(module_name)
        except ValueError as exc:
            raise self.error(str(exc)) from exc

        self.env.note_dependency(str(source_path))
        module = ast.parse(source_path.read_text(encoding="utf-8"), source_path)
        docstring = ast.get_docstring(module, clean=False)
        if not docstring:
            raise self.error(f"module has no docstring: {module_name!r}")

        first_line = docstring.splitlines()[0]
        rst = (
            f".. py:module:: {module_name}\n"
            f"   :synopsis: {first_line}\n\n"
            f"{indent(docstring, '   ')}\n"
        )
        return self.parse_text_to_nodes(rst)


def setup(app: Sphinx) -> ExtensionMetadata:
    """Register the static module-docstring directive."""
    app.add_directive("automoduledoc", AutoModuleDoc)
    return {
        "version": "1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
