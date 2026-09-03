---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-04'
modified: '2026-09-03'
body_schema: 'body-v1'
body_hash: 'sha256:cf885265befd5c1e9e1627e2fe748a81d330757e4fc4cdd2f0bcd147172ddb7f'
step_id: 'S25'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Inventory what the ACP family persists in the operator's real config home, and whether a2a can enumerate it

## Scope

- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/_config_home_roots.py`

## Description

- Ground the ACP home contract semantically rather than by grep, confirming the
  lane states its own posture in `src/vaultspec_a2a/providers/acp_chat_model.py`.
- Enumerate the operator's real CLI config home by metadata only - directory
  counts, file counts, byte totals - without reading any session content.
- Identify which of those directories correspond to run workspaces this project
  created, and test whether those workspaces still exist.
- Re-establish the orphaning by a second, independent method after finding the
  first one lossy.
- Read the orphan sweep in `src/vaultspec_a2a/providers/_config_home_roots.py`
  to establish whether this project can reclaim any of it.

## Outcome

**The ACP family's transcript is not destroyed - it is retained forever, outside
this project's ownership, and this project cannot enumerate or reclaim it.** That
inverts the concern Layer 3 was written to address.

The lane declares the posture itself: the CLI's own transcript lives in the
operator's real config home like any interactive session, and is "not ours to
move". That sentence is accurate about ownership and was read here as settling
the question. It does not describe what accumulates.

Measured, metadata only:

- The operator's CLI config home carries 107 project-partitioned directories,
  totalling 5.8 GB.
- This repository's own directory holds 193 session files and 729 MB.
- 23 of the 107 directories correspond to RUN WORKSPACES this project created -
  ephemeral scratchpad directories under the system temporary root.
- All 23 of those workspaces no longer exist. The transcripts do: 14.5 MiB keyed
  to paths that have been deleted.

The orphaning was established twice because the first method was unsound. Naive
reconstruction of a filesystem path from an encoded directory name is lossy for
any path containing hyphens, so the 23-of-23 result was re-derived by extracting
each session identifier and testing whether its directory still exists under the
temporary root. Both agree; only the second is load-bearing.

This project cannot reclaim any of it. The orphan sweep is scoped to this
project's own temporary-home root and further narrowed by the caller's directory
prefix, explicitly so a sweep for one CLI never collects a directory belonging to
another product. The operator's config home is outside that root entirely, so no
reaper reaches it, and nothing declares it.

That is precisely the shape the retention vocabulary exists to prevent: its own
rationale states that an artifact nobody can enumerate is one no reaper can find,
and that unbounded growth follows from cleanup that cannot see its target. Here
the cleanup is not merely blind - reaching into the operator's home would cross a
boundary this project chose deliberately.

## Notes

Deliberately did NOT read any session file content. The question was what
accumulates and whether it is enumerable, and both are answerable from directory
and file metadata. Reading transcripts would have meant reading other projects'
material from a shared operator home to answer a question about volume.

The 5.8 GB total is NOT attributable to this project - it is the operator's whole
CLI history across 107 projects, most of it interactive work unrelated to any
run. Only the 23 run-workspace directories and this repository's own directory
are plausibly this project's doing, and only the 23 are unambiguously orphaned.
The larger number is context, not an accusation.

Not established here, and left for the following Step: whether the Gemini and
Kimi configured homes accumulate comparably. Both read an operator-supplied path
rather than a per-run directory, so the same ownership question applies, but
neither was inspected.

Not actioned: whether this project should declare, disclose, or bound this
persistence is a decision the amendment Phase owns. The finding is that the
persistence exists, is unbounded, is orphaned on every completed run workspace,
and is invisible to every mechanism this project has for reclaiming artifacts.
