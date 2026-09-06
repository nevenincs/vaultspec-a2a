---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:8e8a6c42344f88d33ec1d2496491f21a684579834be40c3fdd18b9faf2497f53'
step_id: 'S08'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Apply a reviewed locked dependency correction for the Starlette BlockingPortal deprecation and verify the warning disappears without suppression

## Scope

- `uv.lock`

## Changes

- `M` `pyproject.toml`
- `M` `uv.lock`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `A` `.vault/reference/2026-09-06-embedded-runtime-remediation-starlette-blocking-portal-dependency-reference.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P02-S08.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `verify:` implementation/review chain `17095d27ca7e8727ec205155a7a209de5b58d0b5` -> `333080e4a351b9450158c8b8375d9beb301a98a1` PASS
- `verify:` locked dependency graph -> `pass` (211 packages; Starlette source and installed `direct_url.json` bind requested revision and commit `bbee894422c6cc1306327335ae385b901ccfec13`)
- `verify:` dependency compatibility -> `pass` (188 installed distributions compatible; FastAPI 0.141.1 / Starlette 1.6.0 / AnyIO 4.15.1 remain within declared bounds)
- `verify:` warnings-as-errors real TestClient GET -> `pass` (three canonical `anyio.from_thread.BlockingPortal` accesses; zero deprecated `anyio.abc.BlockingPortal` accesses)
- `verify:` representative worker/control/internal-auth coverage -> `pass` (28 passed)
- `verify:` complete twelve-module TestClient consumer coverage -> `fail` under existing owners (197 passed; team-status projection remains MEDIUM/open under `W05.P13.S67`; plan-approval fixture remains MEDIUM/open under `W02.P03.S78`/`W02.P03.S13`; both reproduced against registry Starlette 1.6.0)
- `verify:` direct changed-Starlette-surface coverage -> `pass` (105 passed; one intentional deselection)
- `verify:` unreleased Starlette tree risk -> `open` pending official release (MEDIUM; immutable source is 27 commits / 54 files / 2,586 additions / 357 deletions beyond tag 1.6.0)
- `verify:` distribution support boundary -> `pass` for uv-locked Dashboard-embedded binary; independently pip-resolved wheels remain outside the supported product contract until an official Starlette release carries the correction
- `verify:` Deptry, Ruff, dependency integrity and `git diff --check` -> `pass`
- `verify:` whole-tree Ty -> `fail` under `W06.P14.S72` (five unchanged provider-model test diagnostics remain LOW/open)
- `verify:` remediation and robustness Core checks -> `pass` (19 checks, zero diagnostics each)
- `verify:` legacy/deprecated correction boundary -> `pass` (no filter, shim, AnyIO downgrade, old runtime option or legacy/deprecated support claim)
- `verify:` formal dependency-correction review `333080e4a351b9450158c8b8375d9beb301a98a1` -> `pass`
