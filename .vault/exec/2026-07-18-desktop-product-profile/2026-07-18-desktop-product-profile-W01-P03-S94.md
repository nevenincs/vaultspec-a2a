---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S94'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Project archive payloads directly into one exclusively claimed prefix of a caller-owned unpublished generation through continuously leased descriptor or handle authority and return deterministic evidence without inner rename or cleanup

## Scope

- `src/vaultspec_a2a/desktop/capsule.py`

## Description

- Add direct archive and verified-source projection APIs that accept the caller's
  already-live unpublished-generation authority.
- Validate the source snapshot before claiming one absent top-level prefix, then
  retain both generation and prefix authorities across every nested write.
- Reuse the bounded ZIP and tar emitters so deterministic prefixed path, mode,
  size, and SHA-256 evidence remains one model.
- Preserve the legacy quarantine and native no-replace publication APIs unchanged.
- Leave every direct-projection failure inert without inner rename, cleanup,
  activation, or outer-generation lifecycle mutation.
- Remediate every technical and editorial review finding before closure.

## Outcome

S94 now supplies an additive direct-generation projector for dashboard-owned
final-name unpublished generations. The projector validates a live caller lease,
requires exclusive parent mutation authority, snapshots trusted source bytes before
mutation, claims one absent empty prefix, and writes only through continuously held
descriptor or handle authority. It returns the existing deterministic
`ProjectedFile` evidence and never selects or activates the generation.

The Windows desktop suite passed 235 tests; the focused archive, publication-race,
and child-authority suite passed 36 tests. A real caller-leased ZIP probe proved
direct bytes, deterministic evidence paths, and collision refusal. Ruff, formatting,
Ty, diff hygiene, and independent technical and editorial review passed for source
hash `9DE4B05ABB637D40CB74E18C544A835E66C523C40E49A645E9EFAB3081883E47`.

## Notes

The first review cycles found and resolved a high-severity legacy API regression,
a medium missing-public-export defect, a medium collision-error misclassification,
and a high-severity production docstring leak of plan metadata. No finding remains.

This step does not supply the direct-generation process and substitution matrix,
exact create-new archive writer, complete-generation verifier, or dashboard receipt
activation. S96, S95, S14, and the dashboard-owned verification and receipt steps
remain open gates.
