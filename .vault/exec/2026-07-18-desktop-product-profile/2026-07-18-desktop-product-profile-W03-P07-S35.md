---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S35'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove authenticated foreign attachment stale-owner recovery and immutable live-conflict behavior with real processes

## Scope

- `src/vaultspec_a2a/desktop_tests/test_discovery_ownership.py`

## Description

- Add a real-process certification of the desktop discovery ownership state
  machine, standing up a live resident (runtime singleton plus published
  versioned discovery naming an owner-restricted attach-credential file by path)
  in a child interpreter.
- Prove a foreign contender can read and validate a live compatible resident —
  fresh record, live recorded process, compatible protocol, a named credential
  reference that resolves to a real file — yet can never take lifecycle
  ownership: attachment is not ownership.
- Prove a live incompatible-protocol resident and a live resident with a
  corrupted discovery record are each an immutable conflict for both attachment
  and ownership.
- Prove stale discovery (the recorded gateway proven dead while its heartbeat is
  still recent) is quarantined only by the matching owner through stale takeover,
  and a foreign owner is refused.

## Outcome

The discovery-validation and conflict/quarantine machine is proven with real
processes. Gates: `ruff` clean; the S35 suite passes; the combined P07 desktop
certification (`test_runtime_singleton.py` and `test_discovery_ownership.py`)
6 passed.

## Notes

Full attach-credential authentication lands in `W03.P08`; this Step certifies the
discovery-validation and conflict/quarantine machine that gates it, and follows
the named credential-file reference only to prove the attach path is real, not to
authenticate against it. Honest scope boundary: the record advertises the
credential path, and a contender that reaches ownership is refused, but the
constant-time credential check itself is P08's surface. The unrelated concurrent
manifest/schema campaign (`W02.P06.S26`) still reddens three desktop
manifest/contract golden-vector tests in the shared working tree; none touch this
Step's discovery, singleton, or ownership surface.
