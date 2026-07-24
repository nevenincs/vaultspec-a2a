# PyInstaller onedir spec for the dashboard-bundled a2a runtime binary.
#
# Shape decision (see the dashboard-bundled-runtime decision record): onedir,
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
# - collect_all("vaultspec_core"): dispatched only through the binary's
#   run-module verb (never statically imported), so PyInstaller's import
#   analysis cannot see it; it must be collected explicitly.
# - The run-module dispatch targets (worker, authoring stdio bridge) are
#   likewise reached dynamically via runpy and are pinned as hidden imports
#   even though static analysis usually finds them through the CLI.

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    "vaultspec_a2a.worker.__main__",
    "vaultspec_a2a.protocols.mcp.authoring_stdio",
    "vaultspec_core",
    "vaultspec_core.__main__",
]

# The desktop binary is the pruned runtime closure. The `rag` and `server`
# optional-dependency groups (the Torch/RAG embedding stack and the PostgreSQL
# drivers) are never part of the dashboard-bundled desktop runtime - a2a
# resolves them lazily only under those profiles. Exclude them explicitly so a
# build environment that happens to have the extras installed cannot bloat the
# binary or pull an unshippable native closure into the shipped tree.
excludes = [
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
    "asyncpg",
    "psycopg",
    "langgraph.checkpoint.postgres",
]

for package in ("vaultspec_a2a", "vaultspec_core"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="vaultspec-a2a",
)
