---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S78'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Certify Arm64 Linux capsule closure and upload its pinned component contract

## Scope

- `.github/workflows/desktop-capsule.yml`

## Description

- Publish the capsule workflow on the default branch and dispatch it.
- Build the Arm64 Linux capsule from pinned inputs on a hosted runner.
- Verify the built capsule with the checkout-free verifier.
- Upload the capsule archive and its pinned component contract.

## Outcome

The Arm64 Linux leg completed successfully on a hosted runner. The build
assembled the target capsule from the pinned interpreter, runtime, and
adapter inputs, the verifier accepted it without a source checkout, and the
job uploaded the archive with its pinned component contract as a
digest-stamped artifact of roughly 144.7 megabytes, identified by the
content digest `522ef0c3d01b8cc6`.

This is the first execution of this target on real hardware; every earlier
claim for it was metadata-level only.

## Notes

The certification runs on hosted runners because the development host is
Windows-only. Landing the workflow required two fixes found only once
continuous integration executed: whole-tree formatting drift inherited from
the campaign branch, and Windows-only foreign-function helpers that carried
no in-body platform guard and therefore failed type checking on Linux.
