---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:0b8d37809a480c68544cc9214a497d3ab1c322094c20eb934b7381230f2be60a'
step_id: 'S85'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Correct condition 17 at its outer process-lifecycle root: run every canonical pytest target beneath one OS-contained owner, accept pytest session completion only as a receipt that starts a bounded result-to-exit deadline, reap the complete owned tree on violation, and report natural exit separately from passing assertions

## Scope

- `src/vaultspec_a2a/testing`
- `src/vaultspec_a2a/utils/process.py`
- `dev/toolchain.py`
- `dev/just/test.just`
- `dev/just/build.just`
- `dev/tests/test_ci_contract.py`

## Changes

- `A` `src/vaultspec_a2a/testing/runner.py`
- `A` `src/vaultspec_a2a/testing/runner_child.py`
- `M` `src/vaultspec_a2a/testing/plugin.py`
- `A` `src/vaultspec_a2a/testing/tests/_runner_exit_probe.py`
- `A` `src/vaultspec_a2a/testing/tests/_runner_descendant_probe.py`
- `A` `src/vaultspec_a2a/testing/tests/test_runner.py`
- `M` `src/vaultspec_a2a/utils/process.py`
- `M` `dev/toolchain.py`
- `M` `dev/just/test.just`
- `M` `dev/just/build.just`
- `M` `dev/tests/test_ci_contract.py`
- `verify:` `uv run python -m vaultspec_a2a.testing.runner --run-timeout 120 --exit-timeout 5 -- src/vaultspec_a2a/testing/tests/test_runner.py dev/tests/test_ci_contract.py -q` -> `pass`
