---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:012d94c02f0ab0ac7059d52ef82617bb0d2b0bbd102b00a67e6b2eb5407a38cc'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` research: `Condition 17 pytest process lifecycle root`

## Result

The observed failure has two separate facts: pytest can finish the session and report passing assertions while the Python process remains alive, and code running inside that process cannot guarantee its own termination once interpreter shutdown is blocked. The evidence favors an outer process owner that treats session completion as a receipt, allows a short result-to-exit interval, and then reaps the entire contained process tree if natural exit never occurs.

## Findings

### A pytest result is not process completion

The resource plugin can observe `pytest_sessionfinish`, but that hook runs before Python interpreter shutdown. A non-daemon thread or another teardown resource can therefore keep the process alive after pytest has rendered `[100%]`. The intentional subprocess probe demonstrates this state directly: the hook publishes a result receipt, the process remains alive, and only the outer owner can end it. See `src/vaultspec_a2a/testing/plugin.py:82` and `src/vaultspec_a2a/testing/tests/test_runner.py:19`.

### Containment must precede test execution

The existing `ProcessContainment` abstraction creates a POSIX process session or Windows Job Object and terminates the owned tree through that operating-system boundary. Starting the pytest child under this containment prevents cleanup from depending on parent-PID discovery after a hang. See `src/vaultspec_a2a/utils/process.py:1050` and `src/vaultspec_a2a/utils/process.py:1331`.

### The completion signal needs an exact owner identity

Environment variables pass naturally to subprocesses, including nested pytest invocations. A path-only completion signal would let a nested session start the parent session's exit deadline. Binding the receipt to the contained runner child's PID makes nested inherited state inert; exclusive file creation also prevents replacement of an existing receipt. See `src/vaultspec_a2a/testing/plugin.py:68` and `src/vaultspec_a2a/testing/tests/test_runner.py:50`.

### Canonical commands must pass through the owner

An outer owner only protects commands that invoke it. The declarative test targets and maintained Just recipes are routed through one runner, and the CI contract rejects direct pytest commands in those recipes. Direct ad hoc pytest remains an operator escape hatch and does not provide process-exit evidence. See `dev/toolchain.py:183` and `dev/tests/test_ci_contract.py:91`.

## Sources

- `src/vaultspec_a2a/testing/runner.py:37`
- `src/vaultspec_a2a/testing/plugin.py:68`
- `src/vaultspec_a2a/testing/plugin.py:82`
- `src/vaultspec_a2a/testing/tests/test_runner.py:19`
- `src/vaultspec_a2a/testing/tests/test_runner.py:50`
- `src/vaultspec_a2a/utils/process.py:1050`
- `src/vaultspec_a2a/utils/process.py:1331`
- `dev/toolchain.py:183`
- `dev/tests/test_ci_contract.py:91`
