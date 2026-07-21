---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S03'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Run an armed gateway and record whether the published discovery record carries a handoff reference

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Build the real application against a throwaway home so the machine's live discovery
  record is never touched, and read back the minted engine-facing credential.
- Drive the real publication routine twice against that throwaway home, once with a
  credential and once without, and compare the resulting record shapes on disk.
- Enumerate every caller of the publication routine across the tree and classify each
  as production or test.
- Date the credential-handoff feature against the modification time of the machine's
  live discovery record.

## Outcome

The premise this Step existed to test is false, and the governing research is wrong on
this point.

The credential is always present. Application construction assigns it unconditionally
from configuration or a freshly generated value, so it cannot be absent by the time the
record is published; the live check reported a 64-character credential with nothing
configured. The earlier reasoning that an entrypoint could be bypassed was mistaken
about which function performs the assignment.

The record shapes are unambiguous. Publishing with a credential yields a record carrying
a handoff reference and creates the credential file beside it. Publishing without one
yields exactly three keys and removes the credential file. The machine's live record
carries exactly those three keys, so it was published without a credential.

The reason is age, not a code defect. Exactly one production caller publishes this
record and it always supplies the credential; every other caller in the tree is a test,
and each of those is scoped to a temporary directory and also supplies one. The
credential-handoff feature landed at 20:39 on 2026-07-19. The live record was written at
17:23 the same day, more than three hours earlier, within one second of a manual gateway
run's redirected output file in the same directory. It predates the feature.

## Notes

The conclusion inverts a finding this feature's research rated as the highest-severity
item. There is no live authentication defect in the publication path. What exists is a
stale record that has sat in the machine-global home for two days describing a gateway
that no longer runs, and any reader trusting it would resolve a null credential. That is
a retention failure, which is the subject of this plan, rather than an authentication
failure.

The correction narrows but does not eliminate the cross-repository exposure. A consumer
reading this record still obtains no credential, and the consumer's own tolerance for a
stale or credential-free record is a property of that repository, unchanged by this
finding and still unverified from here.

Two adjacent facts were established and are worth carrying forward. Nothing removes a
discovery record when the gateway that wrote it exits, so a stale record outlives its
process indefinitely. And a tokenless publication silently unlinks the credential file
rather than refusing, which is what makes an accidental tokenless write destructive to a
healthy record rather than merely inert. The next Step addresses the second.
