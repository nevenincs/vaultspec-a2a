---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:d493ef4c8517ca03e558ad5ea36386282325eca0f9142f0ca14a89d4c0eabe05'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `Ty portability review`

## Scope

Independent read-only review of `W06.P11.S19` against the accepted repository-tooling-hardening ADR, its plan, and the current diff in `src/vaultspec_a2a/control/tests/test_spawn_containment_ownership.py` and `src/vaultspec_a2a/utils/process.py`. Reviewed type portability, runtime semantics, platform gates, regression-test integrity, and change scope.

## Findings

### ty-portability-clean | low | No correctness, portability, platform-gate, test-integrity, or scope defect found

The Windows-only `ctypes` imports now occur after explicit `win32` guards, so Linux and macOS neither resolve nor execute Windows-only symbols. The Windows paths retain the same `WinDLL`, last-error, TCP-table, and handle-count behavior. The Windows-specific resource tests remain explicitly platform-gated while the cross-platform containment invariant is exercised without a skip. The two-file delta contains no suppression, shim, fake, stub, mock, patch, monkeypatch, or unrelated behavior change. No follow-up finding is queued.

## Recommendations

- No remediation is recommended for this reviewed delta. Preserve the explicit platform gates and retain the three-platform Ty lane with the focused real-process ownership regression suite.
