"""Code stands alone: production modules must not cite a vault document by name.

``.vault/`` is this repository's OWN removable development scaffolding - the
research, ADRs, plans, audits and ledgers that record why and how the product
was built. The system mandate states the boundary directly: "Vault documents
cite code by locator; code never cites the vault." A module that names one of
these documents has taken a runtime dependency on a file nobody ships, and a
reader who later deletes ``.vault/`` (as the mandate says they may) finds a
comment, docstring or log message pointing at nothing.

This is NOT a ban on the word "vault", or on ``.vault/`` as a path shape:
``vaultspec_a2a`` orchestrates agents that work inside OTHER projects'
vaultspec-governed workspaces, so production modules like
``authoring/submitter.py`` and ``context/harness.py`` legitimately read and
write an arbitrary WORKSPACE's ``.vault/``/``.vaultspec/`` trees as the
product's own domain subject - exactly the "product-domain vault paths...are
valid" carve-out the same mandate states. What those modules never do, and
this guard checks, is name one of THIS repository's own document stems -
``2026-10-06-codebase-remediation-plan``, an ADR's dated filename, and so on -
which is a citation of this project's development record, not of the feature
the product implements.

Test modules are exempt on purpose: several service tests cite a real ADR by
name to exercise the product's OWN citation-checking behaviour (an agent
grounding its output in a document), which needs a real, realistic document
name as fixture data. That is product functionality under test, not a code
module depending on its own development record.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Final

from dev.paths import REPO_ROOT, is_test_code

_SOURCE_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Below this many documents, the vault glob is treated as mis-rooted rather
#: than as a corpus that genuinely shrank to nothing worth checking against.
_MINIMUM_VAULT_DOCUMENTS: Final = 100

#: Below this many files, the production scan is treated as mis-rooted. The
#: shipped package holds well over twice this in production modules alone.
_MINIMUM_PRODUCTION_MODULES: Final = 300


def _vault_document_stems() -> frozenset[str]:
    """Return every ``.vault/`` document's filename stem, with no extension."""
    vault = REPO_ROOT / ".vault"
    stems = frozenset(path.stem for path in vault.rglob("*.md"))
    assert len(stems) >= _MINIMUM_VAULT_DOCUMENTS, (
        f"only {len(stems)} vault document(s) were found under {vault} - a "
        "mis-rooted scan must not pass vacuously"
    )
    return stems


def _production_modules() -> list[Path]:
    """Return every production (non-test) module under the shipped package."""
    modules = [
        path
        for path in _SOURCE_ROOT.rglob("*.py")
        if not is_test_code(path.relative_to(_SOURCE_ROOT))
    ]
    assert len(modules) >= _MINIMUM_PRODUCTION_MODULES, (
        f"only {len(modules)} production module(s) were scanned under "
        f"{_SOURCE_ROOT} - a mis-rooted scan must not pass vacuously"
    )
    return modules


def test_no_production_module_cites_a_vault_document_by_name() -> None:
    """A production module naming one of this repo's own documents is a defect."""
    stems = _vault_document_stems()
    modules = _production_modules()

    offenders: dict[str, list[str]] = defaultdict(list)
    for path in modules:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for stem in stems:
            if stem in text:
                offenders[str(path.relative_to(_SOURCE_ROOT))].append(stem)

    assert not offenders, (
        "production code cites a .vault/ document by name, taking a runtime "
        "dependency on scaffolding nobody ships:\n  "
        + "\n  ".join(
            f"{module}: {', '.join(sorted(cited))}"
            for module, cited in sorted(offenders.items())
        )
        + "\n\nCite the fact directly, or move it to a module-level comment "
        "that explains the WHY without naming the record."
    )
