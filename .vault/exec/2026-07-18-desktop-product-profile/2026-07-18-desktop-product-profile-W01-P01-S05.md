---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S05'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove installed desktop metadata excludes Torch and RAG while optional profiles remain resolvable

## Scope

- `src/vaultspec_a2a/desktop_tests/`
- `pyproject.toml`
- `uv.lock`

## Description

- Build the production wheel with the declared Hatch wheel target.
- Read wheel and installed `Requires-Dist` and `Provides-Extra` metadata.
- Export locked base, server, and RAG `pylock.toml` dependency closures.
- Dry-run server installation against a clean native interpreter.
- Dry-run RAG installation for the supported CPython 3.13 x86-64 Windows target.
- Install the base closure and wheel into an isolated CPython 3.13 environment.
- Import production gateway and worker telemetry in independent child processes.
- Keep the certification harness external to installed packaged test modules.
- Declare the standards-based metadata parser as a dev-only dependency.

## Outcome

The new source-side certification gate builds the real `vaultspec-a2a` wheel and
uses that artifact's metadata as its dependency-partition authority. The wheel
and the clean installed distribution expose exactly the distinct `server` and
`rag` extras. Torch and `vaultspec-rag` remain conditional RAG roots, the four
service roots remain conditional server requirements, and neither optional
root set appears in the unconditional desktop requirements.

Canonical locked uv exports verified pyproject and lock consistency and
produced independent base, server, and RAG closures. The base closure is
contained by both optional closures. Every metadata-declared server root is
present only in the server closure, and every metadata-declared RAG root is
present only in the RAG closure. Native server dry-run installation and an
explicit CPython 3.13 x86-64 Windows RAG dry run succeeded without mutating the
clean environment.

The base closure and production wheel were installed into a new CPython 3.13
environment with the wheel installed without dependency inference. Installed
dependency checking passed. Installed distribution inspection proved that the
production module resolved from that environment rather than the checkout and
that no package added only by the server or RAG closure was installed.
Independent isolated interpreters then imported the production gateway and
worker entrypoints. Both initialized the mandatory OpenTelemetry SDK without an
exporter package; OTLP remained unavailable and service names were
`vaultspec-a2a` and `vaultspec-worker` respectively.

`packaging>=25.0` is now an explicit dev-only dependency and participates in the
existing deptry allowance for test-only imports. `uv lock` retained 171 package
records. Before and after the declaration, the package name/version/source
inventory retained SHA-256
`8793a232a790eca31be9ea57c92be5f394b0f85021925d4d1dc064a5d97cec4a`.
Only the root project's dev dependency metadata changed in `uv.lock`; the
existing `packaging==26.2` registry record and every other package record stayed
unchanged.

The locked `--no-dev --no-emit-project` exports were identical before and after:
base retained 87 records and SHA-256
`bd752a4c1310dc7c385257816f22f387236c58ad6a8e417af3f80dad7d9ad2f1`,
server retained 98 records and SHA-256
`836563aaf55505cd746d273c701de168d8d3137e1ce95141b61388c2e7c1adcc`,
and RAG retained 146 records, 144 unique names, and SHA-256
`0f01c385c494e7005f721ddebd92dd4e334222637f75d46030129a09af07bc98`.
The 30 sorted wheel dependency and extra metadata fields retained SHA-256
`96a037432ebcb734c4293b4a17bfc431f36796442151904af91ed9eb695187ab`.
The dev-only parser declaration therefore caused no published metadata, base,
server, or RAG closure drift.

The focused artifact gate collected five tests and all five passed. Ruff
formatting and linting, scoped ty checking, `uv lock --check`, and focused
deptry checking passed for the new desktop test package.

The resolution commands were `uv pip install --python <clean-python>
--dry-run -r pylock.server.toml` and `uv pip install --python <clean-python>
--dry-run --python-platform x86_64-pc-windows-msvc --python-version 3.13 -r
pylock.rag.toml`; both returned zero. `uv pip check --python <clean-python>`
reported all installed packages compatible. The final focused command was `uv
run --frozen --no-sync pytest
src/vaultspec_a2a/desktop_tests/test_dependency_closure.py -vv`, which reported
five passed in 15.04 seconds.

## Notes

This gate satisfies the earlier audit's durability obligation without importing
`vaultspec_a2a.telemetry.tests` from the installed wheel. Future removal of
test modules from production packaging therefore cannot remove the external
clean-install probe. The harness uses real wheel construction, uv exports,
installation metadata, production imports, and child interpreters; it contains
no fake, mock, stub, patch, monkeypatch, skip, or xfail path.

The optional resolution assertions certify the executing interpreter's native
server target, a supported x86-64 Windows RAG target, and the locked
cross-platform closure; they do not broaden the target claims recorded by S02.
Generic manylinux 2.28 remains blocked by the locked
`tree-sitter-language-pack` wheel floor, and the locked Torch profile does not
support Intel macOS or older macOS 13 ARM64 targets. The RAG and server profiles
remain deliberately distinct.

S06 must configure wheel inclusion and exclusion so `desktop_tests/`, like all
other package test trees, is absent from the shipped production artifact. S12
must inspect the clean built wheel and fail if `desktop_tests/` or another test
tree is present. This gate is intentionally source-side and imports only
installed production modules, so satisfying that packaging obligation will not
weaken its clean-install coverage.

Independent test review found two low-severity harness issues: redundant
success bookkeeping and a transitive parser import. The redundant assertions
were removed, and the parser is now an explicit dev-only dependency with
standards-based requirement and marker evaluation. Architecture review also
required locked export consistency, exact optional roots, target-bounded RAG
resolution, marker-aware installed-environment validation, and `uv pip check`;
all are incorporated and the focused gate passes after those revisions.

The S05 plan row remains open for final architecture acceptance. No phase
summary or commit was created.
