---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W02.P04` summary

Phase P04 seated every mutable desktop path explicitly: a typed desktop
profile binds an explicit mutable app home and immutable capsule root, armed
settings derive state paths only from that authority, the desktop gateway
invocation matches the component manifest's declared entrypoint, and a
certification gate proves state stays app-home-seated across launch-directory
changes and capsule relocation. All four Steps (S16 through S19) are closed;
independent review returned PASS and its medium finding was remediated.

- Modified: `src/vaultspec_a2a/control/config.py`,
  `src/vaultspec_a2a/cli/main.py`
- Created: `src/vaultspec_a2a/desktop/profile.py`,
  `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`

## Description

S16 defined the frozen desktop profile: fail-closed validation of absolute,
distinct, non-nested roots with capsule asset checks grounded in the provider
factory's installed-asset authorities, and a single state-path derivation
covering database, checkpoint, workspaces, runtime logs, and root discovery
paths, with credentials, receipts, temporary homes, and snapshots reserved
for their consuming phases. S17 added the armed app-home setting so database,
checkpoint, workspace, and application-home paths derive solely from the app
home via the profile authority, with launch-directory-relative defaults
rejected when armed and unarmed behavior byte-for-byte unchanged, including
the import surface. S18 added the desktop-serve invocation that validates
roots fail-loud, materializes provisioned directories, arms the profile
through the environment, and re-executes the existing serve path, matching
the manifest-declared gateway entrypoint with no new run-control verbs. S19
certifies seating: armed paths are invariant across real launch-directory
changes and a real capsule relocation, a relative app home is refused when
armed, and unarmed paths stay launch-relative. The review's medium finding —
the derivation authority overstating itself while diverging from operative
log and discovery conventions — was remediated by reconciling the log path to
the runtime convention, the discovery path to the root service record, and
narrowing provisioning to consumed directories only.

## Tests

Twenty-five targeted tests across the profile, seating, invocation, and
certification suites pass, plus the full control suite (91 passed), all with
real directories, real environment seams, real child processes, and real
relocations; no fakes, mocks, stubs, patches, monkeypatches, skips, or
expected failures. Two review lows remain tracked: Windows process
replacement semantics are certified via the discovery record in the runtime
identity phase, and the desktop facade re-export lands once the concurrent
session's facade changes settle.
