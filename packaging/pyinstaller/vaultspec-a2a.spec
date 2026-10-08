# PyInstaller onedir spec for the dashboard-bundled a2a runtime binary.
#
# Shape: onedir,
# never onefile - a long-lived service must not self-extract to a temp
# directory on every boot, and the dashboard bundles a directory per target
# anyway. The dashboard's release pipeline invokes scripts/build_binary.py,
# which drives this spec; the spec is versioned here because the runtime owns
# knowledge of its own hidden imports and data files.
#
# Collection policy:
# - collect_all("vaultspec_a2a"): the package ships non-code assets the wheel
#   force-includes or packages (the component-manifest schema snapshot, the
#   Alembic migration scripts, team preset TOML files); collect_all captures
#   package data alongside submodules so a data-file miss cannot silently ship.
#   The binary is frozen from an editable install, so collect_all would also
#   sweep in everything else under the package root: the test trees, the test
#   execution package with its fixture lanes, and the fixture presets. Both its
#   submodules and its data files are therefore held to the wheel's own exclude
#   list, read from pyproject.toml, so the two artifacts cannot disagree about
#   what is product code.
# - collect_all("vaultspec_core"): dispatched only through the binary's
#   run-module verb (never statically imported), so PyInstaller's import
#   analysis cannot see it; it must be collected explicitly.
# - The run-module dispatch targets (worker, authoring stdio bridge) are
#   likewise reached dynamically via runpy and are pinned as hidden imports
#   even though static analysis usually finds them through the CLI.

import tomllib
from pathlib import Path, PurePosixPath

from PyInstaller.compat import is_win
from PyInstaller.utils.hooks import collect_all

_SPEC_DIR = Path(SPECPATH).resolve()
_WINDOWS_ICON = _SPEC_DIR / "vaultspec.ico"
_PROJECT_ROOT = _SPEC_DIR.parent.parent
_PACKAGE = "vaultspec_a2a"

with (_PROJECT_ROOT / "pyproject.toml").open("rb") as _pyproject:
    _WHEEL_EXCLUDES: tuple[str, ...] = tuple(
        tomllib.load(_pyproject)["tool"]["hatch"]["build"]["targets"]["wheel"][
            "exclude"
        ]
    )


def _excluded(package_path: PurePosixPath) -> bool:
    """Whether the wheel excludes this package-relative path or any parent of it.

    The patterns are rooted at the project, where the package sits under
    ``src/``, and matched the way the wheel import-boundary guard matches them.
    A file is excluded when it or any directory above it matches, so a pattern
    naming a tree keeps out everything beneath it.
    """
    rooted = PurePosixPath("src", package_path)
    candidates = (rooted, *(parent for parent in rooted.parents if parent.parts))
    return any(
        candidate.full_match(pattern)
        for candidate in candidates
        for pattern in _WHEEL_EXCLUDES
    )


def _shipped_module(name: str) -> bool:
    """Whether a submodule of the package belongs in the binary."""
    module = PurePosixPath(*name.split("."))
    return not (
        _excluded(module) or _excluded(module.with_name(f"{module.name}.py"))
    )


def _shipped_data(entry: tuple[str, str]) -> bool:
    """Whether one collected (source, destination directory) pair ships."""
    source, destination = entry
    return not _excluded(
        PurePosixPath(Path(destination).as_posix(), Path(source).name)
    )


datas = []
binaries = []
hiddenimports = [
    "vaultspec_a2a.worker.__main__",
    "vaultspec_a2a.protocols.mcp.authoring_stdio",
    "vaultspec_a2a.desktop._linux_launcher",
    "vaultspec_core",
    "vaultspec_core.__main__",
]

# The desktop binary is the pruned runtime closure. The `rag` optional
# dependency group (the Torch/RAG embedding stack) is never part of the
# dashboard-bundled desktop runtime - a2a reaches it only out of process under
# that profile. Exclude it explicitly so a build environment that happens to
# have the extra installed cannot bloat the binary or pull an unshippable native
# closure into the shipped tree. The `otlp` extra's gRPC trace exporter is
# excluded for the same reason: the binary ships without it, and telemetry runs
# without exporting when the module is absent.
# setuptools is a BUILD tool that PyInstaller drags into its own output: it is
# PyInstaller's dependency, not the runtime's. Nothing here imports it or
# `pkg_resources` - the shipped onedir carried `setuptools/` and no
# `pkg_resources/` at all, which is the shape of a package nothing asked for.
#
# It is excluded because of what it SHIPS, not its size. `setuptools` vendors
# `jaraco.text`, whose sample data file is literally named `Lorem ipsum.txt`,
# and a space is not a portable install path segment. The dashboard's product
# builder refuses the composed tree over it:
#
#     vaultspec-product-build: composed file name is not a portable install
#     path: invalid composed tree: unsafe portable path segment
#     "Lorem ipsum.txt"
#
# That refusal took out all four Compose legs of vaultspec-dashboard v0.1.7 and
# is why that release carries no assets.
excludes = [
    "setuptools",
    "pkg_resources",
    "_distutils_hack",
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "tokenizers",
    "safetensors",
    "huggingface_hub",
    "sentence_transformers",
    "sympy",
    "vaultspec_rag",
    "opentelemetry.exporter.otlp",
    "grpc",
]

pkg_datas, pkg_binaries, pkg_hidden = collect_all(
    _PACKAGE, filter_submodules=_shipped_module
)
datas += [entry for entry in pkg_datas if _shipped_data(entry)]
binaries += pkg_binaries
hiddenimports += pkg_hidden

pkg_datas, pkg_binaries, pkg_hidden = collect_all("vaultspec_core")
datas += pkg_datas
binaries += pkg_binaries
hiddenimports += pkg_hidden

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vaultspec-a2a",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(_WINDOWS_ICON) if is_win else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="vaultspec-a2a",
)
