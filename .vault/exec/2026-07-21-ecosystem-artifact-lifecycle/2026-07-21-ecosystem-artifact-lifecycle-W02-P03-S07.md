---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S07'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Attach a retention declaration to the worker autospawn stderr log seam

## Scope

- `src/vaultspec_a2a/control/worker_management.py`

## Description

- Declare the port-keyed worker stderr log, expressing the port as part of the
  root expression so the declaration describes the family rather than one file.
- Record why this artifact accumulated, in a comment beside the declaration: the
  filename is keyed by a port that changes every dev-band boot, so each boot
  minted a new file and nothing reclaimed the previous one.
- State the enforcement precisely, including that the sweep runs once per gateway
  boot rather than continuously.
- Expose the declaration and a module-level collection.

## Outcome

The artifact is declared, and the declaration is the first in this plan to describe a
seam whose enforcement already exists and works. The sweep deletes orphaned logs for
ports with no live registry claim, and the mechanism text names both that behaviour and
its limit: because the sweep runs at gateway boot, orphans from a boot that never
recurs are reclaimed only when some later gateway starts.

Gates: `ruff check` and `ty check` both report all checks passed on the changed module.

## Notes

This seam is the most instructive one in the service and is worth preserving as
precedent. It accumulated fifteen files before anyone noticed, the cause was a naming
scheme rather than absent cleanup code, and the fix was a sweep that reconciles filenames
against a separate registry's liveness records. That is the same shape as every other
finding in this feature's research: the cleanup was not missing so much as unable to see
its targets.

The declaration deliberately does not claim the enforcement is complete. A sweep tied to
boot is weaker than a continuous reaper, and saying so in the mechanism keeps the
residual exposure legible to the next reader instead of burying it behind a satisfied
disposition.
