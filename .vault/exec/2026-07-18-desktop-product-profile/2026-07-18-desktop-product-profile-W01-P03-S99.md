---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S99'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Define versioned offline Python and ACP closure inventories that bind every content-addressed package target selection lock identity license claim and expected installed inventory before generation assembly

## Scope

- `src/vaultspec_a2a/desktop/closure_inventory.py`
- `src/vaultspec_a2a/desktop/installed_inventory.py`
- `src/vaultspec_a2a/desktop/lock_reconciliation.py`
- `src/vaultspec_a2a/desktop/package_archives.py`
- `src/vaultspec_a2a/desktop/wheel_compatibility.py`
- `src/vaultspec_a2a/desktop/artifacts.py`
- `src/vaultspec_a2a/desktop/tests/test_artifacts.py`
- `src/vaultspec_a2a/desktop/tests/test_installed_inventory.py`
- `src/vaultspec_a2a/desktop/tests/test_lock_reconciliation.py`
- `src/vaultspec_a2a/desktop/tests/test_package_archives.py`

## Description

- Define immutable canonical Python-wheel, ACP-tarball, and installed-tree inventories.
- Reconcile exact lock bytes, target markers, Python patch compatibility, npm ranges,
  nested package paths, native SDK selection, libc, URLs, hashes, and integrity.
- Verify real wheel and npm archive structure, identity, target compatibility, bounds,
  safe member paths, license claims, license members, and license digests.
- Join each source inventory and lock to one content-addressed installed inventory.
- Constrain installed paths and license metadata to the dashboard schema domain.
- Exercise the production APIs with real canonical bytes, archives, locks, and files.
- Resolve or queue every formal review finding before closing the Step.

## Outcome

S99 supplies fail-closed prerequisite authority for later capsule assembly. Python and
ACP closure candidates now identify one reachable target-specific dependency graph,
bind exact lock and package bytes, reject desktop-excluded capabilities and incompatible
native artifacts, and carry canonical expected installed trees. Installed license rows
project collision-safe dashboard component tokens and are reconciled to the exact
declared source member, SPDX claim, and archive-derived digest.

The focused production-importing campaign passes 102 tests. The complete source-tree
desktop campaign passes 384 tests with 26 intentional deselections and one pre-existing
credential permission skip already queued as S98. Ruff, formatting, Ty, and diff
hygiene pass for the exact implementation reviewed by the formal reviewer fleet.

The immutable production hashes are `DEBC424AB4E1E14636D74F4378DAE724D03381EF81C9482ECBCE7596572CCB11`,
`E718823025C44C3C344571D1268A117739D5C15CFF07124710B66C26AE4FD139`,
`859D7AEAD439A3ED91BB88BDAF0C474CBD1D8FF9906F68BD9A5316B217FB4D25`,
`58AE0E524EF17A08E4D3627E016B0283E782F64C951AD55DDB61EBE1972FA124`,
`B6E242183440A3CF2466A8BAFCD434D769FABB209FD30E758A2A2D865C2E24D2`,
and `D350F226EFDFAECCB6FAB4A84E9C7FACD60EF29C93F38B7CECB0B8542118B90D`.
The four test hashes are `AB35618DB25014E28B08E32B72388309037FD1968BE0D21135431E09D9974AE6`,
`E63DBFD9F97A37B9F05D06D5514729E4110ADF06ED86845DA26F40635CDA0204`,
`5D9FCB0057F2961865484283417C0FD24036578EB81CE39AC845CDCD3E684B47`,
and `CCB25991CEB53483F65014A2BA81DCF62C28AAAD8FA65D4052D0F9D187C14BD6`.
Three independent formal reviewers matched those bytes and reported no S99 blocker.

## Notes

This Step does not assemble or authorize a release. S13 must still combine Python, ACP,
CPython, Node, the A2A distribution, and launcher files; enforce whole-capsule file and
license limits plus cross-closure collisions; recompute the complete installed-tree
evidence; and join the independently trusted dashboard component lock. S14 must verify
that complete unpublished generation before S15 may publish candidate evidence.

Archive scanners still duplicate bounded traversal and snapshot machinery. S100 owns
consolidating those authorities and retaining the exact verified package snapshot into
extraction. The existing credential test-policy violation remains queued as S98.
