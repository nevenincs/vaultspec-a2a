---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S23'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Remove the discovery record when the gateway that published it exits

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Trace the shutdown path to establish what removal already exists rather than
  adding a second mechanism beside it.
- Close the gap found there: a malformed record was unlinked without its
  credential, stranding a token no reader could reach.
- Route both removal branches through one helper that refuses a link-like
  destination.
- Add tests for the malformed-record case and for the link refusal.

## Outcome

The Step as written assumed removal was missing. It is not: the gateway cancels its
heartbeat and removes its own record on clean shutdown, and the owned-record branch
already removed the credential alongside it. That assumption is corrected here rather
than acted on.

The real defect was narrower and is now closed. The malformed-record branch unlinked the
record and left the credential behind. Because an unreadable record can never again
reference its token, that credential became unreachable by any reader and uncollectable
by any exit path - a stranded secret with no owner. Both branches now route through one
helper, and fourteen tests pass in the discovery suite.

The helper refuses a link-like destination rather than following it. Removal is a
privileged operation, and unlinking through a symlink placed where the credential belongs
would let anyone able to write the discovery directory redirect the unlink at a file of
their choosing. That refusal is covered by a test which skips rather than passing
vacuously on a host that cannot create symlinks; it executed here.

Gates: `ruff check` and `ty check` report all checks passed, and the discovery suite
reports fourteen passed.

## Notes

The crash case remains open and is the honest residue of this Step. Nothing removes a
record when the process dies without unwinding, which is exactly how the record examined
earlier in this Wave survived its gateway by two days. The existing classification
already treats such a record as reclaimable by the next resident, so the exposure is
bounded to the interval before another gateway starts - but during that interval a
consumer reading the record still resolves a gateway that is not running.

Closing that properly means either a liveness check at read time on the consumer side,
which is another repository, or a supervisor that reclaims on behalf of a dead process.
Neither belongs in this Step, and neither is currently carried by this plan.
