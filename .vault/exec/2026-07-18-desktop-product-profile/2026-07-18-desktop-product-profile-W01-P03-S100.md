---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S100'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Consolidate bounded archive inspection and retained consume authority

## Scope

- `src/vaultspec_a2a/desktop/_archive_authority.py`
- `src/vaultspec_a2a/desktop/_capsule_archive_io.py`
- `src/vaultspec_a2a/desktop/package_archives.py`
- `src/vaultspec_a2a/desktop/capsule.py`
- `src/vaultspec_a2a/desktop/manifest.py`
- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/tests/test_artifacts.py`
- `src/vaultspec_a2a/desktop/tests/test_package_archives.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_archives.py`
- `src/vaultspec_a2a/desktop/tests/test_manifest.py`

## Description

- Consolidate retained regular-file snapshots, ZIP/TAR member validation,
  central-directory preflight, raw TAR control inspection, and bounded gzip decoding.
- Reject unsafe member paths, semantic collisions, ancestor conflicts, unsupported types,
  encryption, expansion bombs, forged directory counts, ZIP64 overrides, sparse TARs,
  cumulative extension abuse, and invalid stream framing before extraction.
- Stream wheel `RECORD` verification without whole-member allocation.
- Retain the exact verified wheel, ACP, license, and root-distribution bytes through
  read-only scope-bound consumer sessions.
- Exercise the production authorities with real ZIP, TAR, gzip, package, closure, and
  replacement-race inputs without mocks, fakes, patches, skips, or mirrored logic.
- Run formal multi-agent code review and record every surfaced issue in the rolling audit.

## Outcome

Package, capsule, and manifest consumers now share one archive-policy implementation.
High-level ZIP and TAR readers are preceded by bounded structural inspection, ordinary ZIP
and TAR retain separate cardinality ceilings, and final projection still enforces the
dashboard-wide tree bound. Package verification may be detached for reporting, but only a
retained session authorizes reading the exact verified bytes. Combined closures expose
sequential typed sessions that reverify and retain Python wheels, ACP packages, external
licenses, and the root A2A wheel without holding the complete closure open at once.

The focused production-importing campaign passes 117 tests. The complete desktop campaign
passes 365 tests with one previously known POSIX credential permission skip. Ruff lint and
formatting, locked repository-wide Ty, diff hygiene, and prohibited-test-pattern review
pass. Three independent reviewers matched the exact byte set and approved with no
remaining S100 blocker.

The production hashes are
`6ABD5ACB14539502AC25B39159E849A560BA18539AAC8D42107D0FCAF9E0D413`,
`7921F39C94AAE9988E27E437F068658DF8E8887F70630FC6EE6159B670254942`,
`15A9C9E59A63F51E4ACFA7AF370093A0EE76EBF4FCBB8D57F158A01EC9BD677A`,
`7E4C1DBA66780E389B2A065B90694EFE31947127D1747D16175CEA886EE343E8`,
`CB0E8451011B8461B1D41F9E9EA7682A34D0EF57BCC6294A4CFE82E51C412074`, and
`E9B4986F79B32379E9D16461836FF48A7427DFA1D8921567C451A6BD9A80C99D`.
The test hashes are
`08F82CA781B0A6BF873EABF07E2A14EAFC281117403ED3B937D45CF0ED044092` and
`7F0162A5A9A1091CD4829C10336E29BE2BE329A9E65A7C1901C17EF0C5470FD5`;
the in-scope capsule and manifest tests required no byte changes.

## Notes

This Step grants no release authority. Whole-generation assembly, complete verification,
publication, trusted dashboard component-lock reconciliation, receipt issuance, and
activation remain later gates. One low controlled-input compatibility limitation is
carried: an EOCD-like signature embedded inside a ZIP comment may be normalized to a safe
rejection because the runtime `ZipFile` parser cannot consume it. It is not a validation
bypass and does not affect generated desktop closure artifacts.
