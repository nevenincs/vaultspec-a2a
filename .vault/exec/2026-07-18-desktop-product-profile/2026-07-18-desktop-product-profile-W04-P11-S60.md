---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:e117ff517e2281966f1bd881a413a7e3c34487eb746fc85ace02bad3d1bfa759'
step_id: 'S60'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---
# Spawn each run-owned ACP or Codex provider root in a POSIX new session and owned process group or an assigned Windows Job Object or equivalently proven OS-owned job or tree before descendant work; correct empty-containment false success and prove assignment-failure cleanup through the exact retained provider identity before returning the spawn

## Scope

- `src/vaultspec_a2a/providers/_subprocess.py`

## Changes

- `M` `src/vaultspec_a2a/providers/_subprocess.py`
- `M` `src/vaultspec_a2a/utils/process.py`
- `M` `src/vaultspec_a2a/control/worker_management.py`
- `M` `src/vaultspec_a2a/providers/tests/test_provider_containment.py`
- `M` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`
- `M` `.vault/audit/2026-09-05-codebase-health-process-resource-lifetimes-audit.md`
- `M` `.vault/exec/2026-07-18-desktop-product-profile/2026-07-18-desktop-product-profile-W04-P11-S60.md`
- `M` `.vault/exec/2026-07-18-desktop-product-profile/2026-07-18-desktop-product-profile-W04-P11-summary.md`
- `verify:` `.venv/Scripts/python.exe -m pytest <S60 focused modules> -o addopts='' -q` -> `pass` (40 provider/process/worker tests in 56.25s)
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_a2a/providers/tests/test_provider_containment.py -m service -q` -> `pass` (5 real-process cases)
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py -k provider -o addopts='' -q` -> `pass` (2 passed in 13.74s)

## Notes

The broad integrated owned-tree run surfaced two persistent test-fixture failures outside S60: `test_terminal_child_tree_contained_and_reaped` omits the current `AcpSessionContext.closing` field, and `test_desktop_worker_tree_contained_and_reaped_on_graceful_shutdown` launches a gateway without binding the current lifecycle owner. Both remain queued for their current-contract test owners. An invalid first root-exit proof awaited pipe drain while a descendant intentionally retained stdout; it timed out after 10 seconds despite root return code 0 and was corrected to observe root exit before production containment closes the descendant and transport. Pytest startup also spent about 23 seconds before collection with zero peer sessions; this separate developer-time delay is queued under resource-aware test execution.
