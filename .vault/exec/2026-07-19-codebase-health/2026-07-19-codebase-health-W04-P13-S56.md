---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S56'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Record package facades and parallel wire-domain field blocks as deliberate non-duplicates after ownership review

## Scope

- `.vault/audit/2026-07-19-codebase-health-audit.md, src/vaultspec_a2a/graph, src/vaultspec_a2a/providers`

## Description

- Read the two facades and the wire and domain schemas the similarity tool
  flagged.
- Determine, per match, whether the resemblance is shared behaviour or a shared
  shape over different content.
- Record the verdict in the rolling audit so the correct matches are not reopened.

## Outcome

Two of the four flagged matches are deliberate and are now recorded as such.

The two package facades resemble each other because a facade has one shape, but they
re-export disjoint symbols for independent packages. The resemblance is the pattern, not the
content, and merging them would couple two packages to erase a similarity that carries no
shared behaviour.

The wire and domain field blocks are two models of two concerns. The wire model bounds every
field for an untrusted boundary; the domain model carries internal defaults and no bounds
because the values are already trusted by the time they reach it. The core-layer-boundary
decision governs the separation, and the shared field names are that seam working rather than
duplication.

The audit already carried the two genuine duplicates from the same similarity list - the
integer coercion and the response mappings - and both were consolidated under their own
Steps. The disposition of the four matches is therefore split cleanly: two merged as
behaviour, two kept apart as deliberate.

## Notes

This Step produces a record rather than a code change, and the record's value is preventing a
later reader from acting on the similarity score for the two correct matches. A duplication
finding that lists deliberate parallels without adjudicating them invites exactly the merge
that would break the boundary, so the adjudication is the deliverable.

The judgement is per-match and cannot be delegated to the tool that produced the list. The
same audit list contained two real duplicates and two deliberate ones, which is the whole
point: AST similarity locates candidates, and a person decides which are debt and which are
design.
