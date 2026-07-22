---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S26'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Parse numeric and ISO heartbeat values strictly and reject stale malformed non-finite and implausibly future values

## Scope

- `src/vaultspec_a2a/authoring/discovery.py`

## Description

- Demonstrate each defect against the running code before changing anything.
- Invert the failure direction so a present-but-unusable heartbeat reads as
  stale rather than fresh.
- Accept an ISO-8601 timestamp alongside a numeric epoch, since a peer may
  publish either.
- Reject non-finite values and bound how far into the future a heartbeat may sit.
- Preserve the contract that an absent heartbeat is fresh.

## Outcome

Four defects were reproduced against the live function before any edit, and all four are
closed.

The failure direction was the serious one. The guard returned fresh for anything it could
not parse, so a record carrying an infinite heartbeat, a far-future timestamp, an object,
or an unparseable string read as a live peer. This guard decides whether a peer is treated
as running, so an unreadable value must not license liveness. A record claiming an infinite
heartbeat previously stayed fresh forever, which is precisely the shape a stale or forged
record takes.

ISO timestamps are now parsed. The sibling repository already handles both a numeric and an
ISO heartbeat on its side of this contract, so a peer publishing ISO was silently treated as
fresh regardless of age rather than being read.

Future heartbeats are bounded at one staleness window. That absorbs ordinary clock skew
between peers - which is real and should not be punished - without accepting a timestamp
that could pin freshness indefinitely.

Twenty-one tests cover the behaviour, including each unusable type individually and all
three ISO forms the parser accepts.

Gates: `ruff check src/` clean, `ty check src/` clean, and the authoring, lifecycle
discovery, and control suites report two hundred sixty-seven passed with twenty-three
deselected.

## Notes

Absence still means fresh, and that asymmetry is deliberate rather than an oversight. The
field is optional by contract, so its absence carries no information about liveness, while
a present value that cannot be read is evidence the record is wrong. Treating those two
identically is what produced the original defect.

The future bound reuses the staleness window rather than introducing a second constant. One
window is the largest skew that can be reconciled with the freshness rule itself, and adding
a separate tunable would invite the two to drift apart.
