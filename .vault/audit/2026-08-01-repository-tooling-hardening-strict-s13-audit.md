---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:47f4d682e76e8c2b5853db9e3404ae24ec1d67615cf5a95fd721965a35e8ba31'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `strict S13 cross-platform Ty target`

## Scope

Reviewed only the current `dev/toolchain.py` diff for W05.P09.S13: the `lint type-platforms` target, its source roots and platforms, aggregate placement, failure-continuation semantics, and rendered help.

## Findings

### type-platforms-s13 | low | Clean review: no release-blocking implementation defect found

Classification: clean review. Status: closed. The target runs Ty through the locked tooling profile as `python -m ty check --python-platform <platform>` for `linux`, `darwin`, and `win32`, each over the canonical committed Python roots `src`, `dev`, `docs`, `scripts`, and `packaging`. It remains out of `lint all` and is included in `lint strict`, consistent with the staged unfinished-burndown contract. The target is non-advisory and uses `keep_going=True`; the focused run emitted all three commands after Linux and Darwin failures and returned the strict gate result after the final Windows pass. Rendered `lint` help exposes the target and explains its strict-only placement. The Linux and Darwin Ty diagnostics are existing platform-specific burndown debt, not a regression in this change. Release blocker: none.

## Recommendations

No corrective action for S13. Continue the planned platform-specific Ty burndown before promoting `type-platforms` into `lint all`.
