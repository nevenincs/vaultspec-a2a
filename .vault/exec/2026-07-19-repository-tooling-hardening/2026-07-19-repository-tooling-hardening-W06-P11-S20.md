---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:db409d081416561e846b16e035c64846dfdeed1761d8c1a46377b30a39b8fb8b'
step_id: 'S20'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Type the health-instrument boundary without suppressions and preserve its measured-result contract.

## Scope

- `dev/health/report.py`

## Description

- Define private structural protocols for Radon complexity blocks and callables.
- Bind untyped Radon API members through two explicit import-boundary casts.
- Preserve direct Radon measurements, exception boundaries, and output ordering.
- Verify strict Basedpyright, Ty, Ruff, and formatter checks for the module.
- Compare default report, census, and JSON outputs against pre-change fingerprints.
- Complete independent review of the live Radon adapter.

## Outcome

The health instrument passes strict Basedpyright without a suppression. Its locked Radon API remains the metric authority, while the three non-gating output modes are byte-for-byte identical to their pre-change results and the gate keeps its expected exit status.

## Notes

The execution-record scaffold command exceeded its local timeout after creating the record; the record was verified before its guarded body update. No runtime wrapper, metric reimplementation, test double, or dependency change was introduced.
