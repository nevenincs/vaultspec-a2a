---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-04'
modified: '2026-09-03'
body_schema: 'body-v1'
body_hash: 'sha256:eba63ce9bddbe0f30f25b3f0fc0904a6361fccc6c0b477c3f7f5c550785934c0'
step_id: 'S26'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Establish whether the Gemini and Kimi configured homes retain session content nobody has inspected

## Scope

- `src/vaultspec_a2a/providers/factory.py`
- `src/vaultspec_a2a/providers/kimi_catalog.py`

## Description

- Confirm both settings are actually plumbed to a spawn rather than declared
  and unused, by reading the environment builders in `providers/factory.py`.
- Establish that neither home variable is set on this machine, so each CLI falls
  back to its own default under the operator's real profile.
- Inventory each default home by metadata only - directory counts, byte totals,
  key shapes - without opening a session file.
- Test the Gemini key scheme against known workspace names two independent ways
  before trusting any orphan count derived from it.
- Establish whether the orphan sweep reaches either home, and whether any
  artifact declaration covers them.

## Outcome

**Both lanes accumulate, neither is reachable, and neither is declared - but the
three provider families now differ in shape, so nothing here generalizes.**

Both settings are real: the environment builders inject them at spawn. Neither is
set on this machine, and the Gemini builder only overrides the child's profile
when the setting is present, so with it unset the child inherits the operator's
real profile unmodified - the same no-override shape as the ACP family, reached
by a different route.

**Gemini accumulates substantially and is largely this project's own doing.** Its
default home carries two project-partitioned trees holding 959 directories each,
keyed by workspace-directory BASENAME with underscores sanitized to hyphens. 305
of those keys are pytest-shaped and match this repository's own test function
names directly - one sample decodes to the dispatch-assignment agreement test. 495
of the 959 history entries are already older than the twenty-four-hour threshold
this project uses for its own orphan reclamation, so this is an actively growing
accumulation rather than a historical residue: every test or development run that
touches the lane adds an entry, the temporary workspace is then reclaimed
upstream, and the provider-side copy survives it.

The key scheme was verified twice before any orphan count was trusted, because
the underscore-to-hyphen sanitization makes the transform lossy in the reverse
direction. Both a pytest-generated name and a randomly-generated temporary name
were matched back to live directories to confirm the mapping.

**Kimi accumulates almost nothing so far, and cannot be attributed by name at
all.** Its default home is dominated by the CLI's own installed binary; the
session tree is a single working-directory-keyed folder holding one session, tens
of kilobytes, dated to this project's one recorded certification window. Its key
is an opaque hash rather than a reversible encoding of a workspace name, so
unlike Gemini there is no path to establishing whether that entry is orphaned.
That a single entry exists despite many past invocations suggests a coarser
partition than per-workspace, but that was not established.

**Neither home is reachable or declared.** The orphan sweep is scoped to this
project's own temporary-home root and filtered by the caller's prefix; neither
default home sits under that root nor matches any prefix in use. No artifact
declaration names either lane - the only provider-side declarations cover the
per-run Codex home and the ACP handler surface.

## Notes

No session content was read on either lane. One manifest file in the Gemini home
would likely have allowed a precise attribution of which entries belong to this
project, and it was deliberately left unopened: it is a manifest rather than a
transcript, but opening it to answer a question about VOLUME would have crossed
the line this investigation set for itself. That leaves a real gap - the exact
this-project fraction of the 959 is unestablished, and the 305 pytest-shaped keys
are a floor, not a total.

The three provider families are now known to differ from each other, which is the
result that matters most here. The ACP family retains full sessions keyed by
absolute workspace path; Gemini retains per-workspace directories keyed by
basename, in volume, mostly self-inflicted; Kimi retains almost nothing under an
opaque key. An earlier version of this work generalized one lane's behaviour to
the others and was wrong; a remediation designed against any single shape would
be wrong in the same way.

Not established for Kimi, and it needs the CLI's own source or documentation
rather than more inspection: whether its partition is per-workspace or per-host.
