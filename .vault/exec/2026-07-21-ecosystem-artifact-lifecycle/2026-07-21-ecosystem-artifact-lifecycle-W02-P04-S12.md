---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S12'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Route the process registry record writer through the shared helper

## Scope

- `src/vaultspec_a2a/lifecycle/registry.py`

## Description

- Replace the inline temporary-write and rename in the registry record writer with
  a call to the shared helper.
- Leave the live-owner refusal that precedes the write untouched.

## Outcome

The registry writer routes through the audited helper, closing the third and last
instance of the pattern. This writer had never been observed to leak, but it carried the
identical defect: no removal on failure, and a temporary name that its own record
enumeration would not have matched, so any residue it produced would have been invisible
to the registry own listing.

## Notes

This Step closes a latent rather than an observed defect, which is worth stating plainly.
The evidence for it was structural, from reading the code alongside the writer that did
leak, rather than an artifact found on disk. The module docstring already claimed that
writes here mirror the discovery machinery temp-and-rename discipline; that claim is now
true in the failure path as well as the success path.
