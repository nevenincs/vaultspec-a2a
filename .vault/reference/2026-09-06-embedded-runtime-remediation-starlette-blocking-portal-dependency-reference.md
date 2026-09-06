---
tags:
  - '#reference'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:7d3716151df2a26b2668e0da4005f406b0f2e46dc3e1027f1e779beb62b52660'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-05-embedded-runtime-robustness-audit]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
---
# `embedded-runtime-remediation` reference: `Starlette BlockingPortal dependency correction provenance`

The S08 dependency deep dive compared the locked graph, the installed package source, the official AnyIO deprecation change, the official Starlette correction, and the repository's twelve direct TestClient consumer modules. It records the exact source boundary used by the frozen binary build.

## Summary

The pre-S08 lock resolves AnyIO `4.15.1`, FastAPI `0.141.1`, HTTPX `0.28.1`, and registry Starlette `1.6.0`. The constraints are compatible: FastAPI requires Starlette `>=0.46.0`, while Starlette requires AnyIO `>=3.6.2,<5`. Compatibility does not remove the warning. Installed `starlette/testclient.py` accesses `anyio.abc.BlockingPortal` at lines 53, 380, and 423. With deprecations promoted to errors, importing `starlette.testclient` exits one at line 53 with the exact direction to use `anyio.from_thread.BlockingPortal`.

AnyIO PR 1169, merged 2026-08-16, made the old export an emitting lazy deprecated alias. The canonical class has lived in `anyio.from_thread` since AnyIO 3. Official source: `https://github.com/agronholm/anyio/pull/1169` and the AnyIO version history.

Starlette PR 3498, merged 2026-09-05, replaces the three TestClient annotation accesses with `anyio.from_thread.BlockingPortal`. The immutable merge is `bbee894422c6cc1306327335ae385b901ccfec13`; upstream reported eleven passing checks. Official sources: `https://github.com/Kludex/starlette/issues/3497`, `https://github.com/Kludex/starlette/pull/3498`, and `https://github.com/Kludex/starlette/commit/bbee894422c6cc1306327335ae385b901ccfec13`.

PyPI's current Starlette release is still `1.6.0`, tag `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, published 2026-08-08 before the correction. No released Starlette/AnyIO combination both retains current AnyIO and removes Starlette's deprecated access. Downgrading AnyIO would conceal the access, and warning filters would suppress evidence, so neither satisfies S08.

The immediate correction uses the exact official merged commit through `tool.uv.sources` and regenerates `uv.lock`; `uv lock` reports registry Starlette `1.6.0` updated to source metadata `1.6.0 (bbee8944)` with the graph still at 211 packages. This uv-only source applies to the repository's locked frozen-binary build. It is not emitted in wheel `Requires-Dist`, so an independently pip-resolved wheel remains outside this binary component's supported distribution boundary until Starlette publishes the correction.

The immutable commit pin has a broader tree than the three-line PR patch. The tag-to-commit comparison spans 27 commits and 54 files, with 2,586 additions and 357 deletions. This is a MEDIUM dependency-provenance and regression surface requiring the Starlette-facing suites before S08 review. Official comparison: `https://github.com/Kludex/starlette/compare/4f250d6b814587e20c5365f0a5f0c4d42bcb929f...bbee894422c6cc1306327335ae385b901ccfec13`.

After locked sync, the warning-as-error import exits zero. The installed TestClient has zero `anyio.abc.BlockingPortal` accesses and exactly three `anyio.from_thread.BlockingPortal` accesses at lines 53, 374, and 417. A real Starlette TestClient GET also succeeds with deprecations treated as errors. `uv run --locked --group freeze` reports installed `direct_url.json` with both requested revision and commit ID `bbee894422c6cc1306327335ae385b901ccfec13`; locked export emits the same immutable Git source, and the binary builder invokes PyInstaller through that interpreter. The representative worker/control/internal-auth set passes 28 tests with deprecations treated as errors. The twelve repository consumer modules produce 197 passes and two failures; reinstalling registry Starlette 1.6.0 reproduces both failures unchanged and restores the original warning. They are current-source test drift, not dependency regressions.
