---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S30'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Implement the cross-platform lifetime singleton and owner-matching stale-lock classification for one desktop app home

## Scope

- `src/vaultspec_a2a/lifecycle/singleton.py`

## Description

- Add `lifecycle/singleton.py`: an operating-system-held runtime singleton
  scoped to one desktop application home, held for the gateway lifetime.
- Guard the home with an exclusively locked anchor file whose byte-zero region
  is taken through the platform's native advisory lock (`msvcrt.locking` on
  Windows, `fcntl.flock` on POSIX), so the lock dies with the holding process
  and a crash never wedges the home; no third-party dependency is used.
- Publish an atomic owner record (temp write, fsync, rename) carrying record
  version, pid, an owner identity, a process start fingerprint, and an
  acquired-at stamp; the record never carries a credential, token, or secret.
- Compute a cross-platform start fingerprint (Windows process creation
  `FILETIME`, Linux `/proc/<pid>/stat` starttime) that guards pid reuse; where
  no cheap source exists the reader degrades to pid-liveness alone.
- Classify a home HELD, STALE, FOREIGN, MALFORMED, or FREE; quarantine and take
  over only an owner-matching stale record and refuse a live or foreign-stale
  resident with a typed fail-closed conflict.
- Wait out an orphaned lock left by a just-terminated Windows holder with a
  bounded retry while short-circuiting immediately on a proven live holder.
- Add real multi-process tests spawning child interpreters that hold the lock,
  proving exclusion, stale detection after a real kill, owner-only takeover, and
  refusal to steal a live holder.

## Outcome

Runtime singleton lands with real-process certification. Gates: `ruff` and `ty`
clean on the module; `pytest src/vaultspec_a2a/lifecycle -q` 111 passed. The
desktop discovery record (`S31`) reuses this module's start-fingerprint helpers
as the single authority for proving a recorded process dead.

## Notes

The gateway wiring that acquires this singleton before listener bind lands in
`S33`; the two-real-gateway certification lands in `S34`. Start fingerprints are
unavailable on macOS (no cheap source), where classification rests on
pid-liveness alone — an accepted, documented degradation.
