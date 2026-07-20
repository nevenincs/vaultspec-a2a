---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S97'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Lease one empty unpublished-generation child before any write

## Scope

- `src/vaultspec_a2a/desktop/_filesystem_authority.py`
- `src/vaultspec_a2a/desktop/tests/test_unpublished_generation.py`

## Description

- Require an absent single-component child name with no replacement.
- Acquire a Windows non-delete-shared directory handle or a POSIX no-follow
  directory descriptor before exposing write authority.
- Validate that the exact leased current child is empty without deleting or
  publishing any failure state.
- Retain the parent and child authorities across the caller's write scope and
  fail when either named identity changes.
- Prove live authority, collision preservation, poisoned-generation retention,
  non-empty refusal, and one-winner cross-process claims with production code
  and real filesystem objects.

## Outcome

S97 now supplies the narrow authority required by direct generation writers:
an absent name is claimed, the current empty child is leased before any write,
and failures remain inert inside the unreceipted generation. Windows reported
six focused passes; WSL CPython 3.13 reported ten focused and POSIX regression
passes. Ruff formatting and lint, Ty, and independent code review passed.

## Notes

POSIX has no portable atomic create-directory-and-return-descriptor operation.
The contract therefore does not assert that the leased inode is necessarily the
inode created by `mkdir`. An empty same-user substitution before lease
acquisition can only poison the inactive generation; complete generation
verification and receipt activation remain mandatory before selection. S94,
S96, S14, and dashboard receipt-bound verification retain those later gates.
