---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:2022525319be42fbce6d22fdee4a492b2a1d27c9333b6763a8870ca2ff8aa3e2'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `real CI anti-drift guard review`

## Scope

Formal read-only review of `W05.P10.S18` against the strict-quality ADR amendment, its plan, and the anti-drift reference. Reviewed the current changes to `dev/toolchain.py` and `dev/tests/test_ci_contract.py`, together with the live root `Justfile` and hosted workflow consumed by the guard. Status: blocked pending the two medium contract-coverage findings below. No fakes, stubs, mocks, patches, monkeypatches, or mirrored tool-command construction were found.

## Findings

### hosted-sentinel-enumeration | medium | The guard does not prove that the hosted sentinel set is exactly eight

`test_ci_contract` verifies that each of its eight expected `just lint <sentinel>` commands appears once, but it never enumerates the matching hosted lint steps and compares that set to the declared sentinel set. A duplicate or an additional differently shaped sentinel invocation can therefore be added without failing the guard, despite the required exact-eight hosted result boundary.

### type-platform-command-contract | medium | The Type-platform executable contract is not fully asserted

The guard checks each platform token and the trailing canonical Python paths, but it does not assert the `uv run ... python -m ty check` command root and ordering. A drift to another executable, module, or subcommand that retains `--python-platform` and the path suffix would pass, leaving the required command/root/platform contract unprotected.

### remediation-closure | low | Both previously-blocking anti-drift coverage gaps are resolved

The remediation now derives the hosted `just lint` sentinel runs from the parsed `test` job and asserts their exact ordered equality with the eight declared sentinels, without constraining unrelated non-lint workflow steps. It also asserts each `type-platforms` `Cmd.argv` prefix from locked `uv run` through `python -m ty check --python-platform <platform>` before independently asserting the canonical Python-root suffix. The real-artifact guard still uses the live registry, tracked root recipe, and parsed workflow; no fake, stub, mock, patch, monkeypatch, or mirrored tool-command construction was introduced. Current blocker status: cleared.

## Recommendations

- Enumerate the `test` job's named `just lint` sentinel runs and assert exact equality with the eight declared sentinel commands, while retaining the current per-step guard and advisory assertions.
- Assert the `Cmd.argv` command root and Ty module/subcommand ordering for each `type-platforms` step, without creating a second target registry or constructing a mirrored execution command.
- Re-run the focused guard, `just test harness`, Ruff/format checks, and `git diff --check` after remediation; then replace this blocker status with the resulting evidence.

### remediation-closure | low | Both previously-blocking anti-drift coverage gaps are resolved

The remediation now derives the hosted `just lint` sentinel runs from the parsed `test` job and asserts their exact ordered equality with the eight declared sentinels, without constraining unrelated non-lint workflow steps. It also asserts each `type-platforms` `Cmd.argv` prefix from locked `uv run` through `python -m ty check --python-platform <platform>` before independently asserting the canonical Python-root suffix. The real-artifact guard still uses the live registry, tracked root recipe, and parsed workflow; no fake, stub, mock, patch, monkeypatch, or mirrored tool-command construction was introduced. Current blocker status: cleared.
