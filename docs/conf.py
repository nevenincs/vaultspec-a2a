"""Configure the Vaultspec A2A Sphinx documentation build."""

import sys
from pathlib import Path

_DOCS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_DOCS_ROOT / "_ext"))

project = "Vaultspec A2A"
extensions = ["module_docstrings"]
root_doc = "index"
nitpicky = True
exclude_patterns = ["_build"]
