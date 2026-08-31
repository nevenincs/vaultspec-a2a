---
tags:
  - '#reference'
  - '#dashboard-bundled-runtime'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:ea61bf40254bbd472f3b502d9a83bcdeb3a5178377f1dc28c23c64a49f93276f'
related:
  - "[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]"
  - "[[2026-07-24-dashboard-bundled-runtime-adr]]"
---
# `dashboard-bundled-runtime` reference: `corrected consumer input for the subordination decision`

## Summary

The accepted `2026-08-01-dashboard-bundled-runtime-subordination-adr` decided
that the dashboard's records bind and this repository supplies what they
require. That direction is correct and this document does not question it.
But the enumeration step that followed — "read the consuming project's
accepted records" — was performed against stale input, and the staleness was
the dashboard's fault, not a misreading here. This document is the corrected
consumer input, provided so this repository can re-run its own conformance
step against what the consumer actually requires today. It does not
supersede, edit, or reverse the subordination record; re-deciding on
corrected input is that record's own framework, applied by its owners.

## What went wrong with the input, and whose fault it was

The dashboard reversed capsule consumption in its accepted
`2026-07-24-a2a-product-provisioning-adr`. That record deliberately amends
its parent records at CLAUSE level and records no whole-document
supersession, because most of each parent remains valid. The consequence:
until 2026-08-01, six other accepted dashboard ADRs still described capsule
consumption with no forward pointer to the amendment. A reader applying
exactly the subordination record's stated method found accepted records
describing the capsule and nothing indicating the relevant clauses were
dead. The fault is the dashboard's record hygiene, not this repository's
reading.

That gap is now closed on the dashboard side: as of dashboard commit
`585142a285`, each affected record carries a dated forward amendment note
naming exactly which clauses are narrowed or replaced (and which stand),
plus a `related:` edge to the amending record.

## The consumer's current requirement

The governing dashboard record is `2026-07-24-a2a-product-provisioning-adr`
(accepted), INCLUDING its 2026-07-31 amendment, in the dashboard
repository's `.vault/adr/` directory. What it decides:

- The fetched capsule is replaced by a frozen PyInstaller onedir as the a2a
  component. The capsule apparatus and the capsule manifest are NOT
  consumed; there is no separate capsule manifest to cross-verify.
  Component trust is the dashboard member manifest's composition-time file
  digests over the onedir's files as ordinary release files.
- Under the 2026-07-31 amendment (directed by the product owner), this
  repository PUBLISHES a per-target frozen binary artifact as a release
  asset: fixed per-target archive names, a `.sha256` sidecar per archive,
  attached to the release for the tag; four targets (Apple Silicon macOS,
  Arm64 Linux, x86-64 Linux, x86-64 Windows), each built natively. The
  dashboard fetch-verifies-and-bundles the released artifact. There is no
  source coupling: the dashboard's commit pin retires in favour of a
  version reference.
- The producer lands first: the dashboard's consume path is written against
  a real published artifact, never a promise.
- The producer-side release gate must prove the published artifact can
  START, STOP, and SERVE ITS API before publication: start the gateway,
  reach `/health` and `/readiness`, stop it, assert the process is gone.
  A version/help smoke alone is insufficient evidence about precisely the
  surface the consumer depends on.
- The runtime contract the consumer codes against is frozen and
  distribution-shape independent: the discovery record schema, owner-ACL
  bearer handoff, authenticated health, readiness, drain, and shutdown
  verbs, and the `serve`/`setup`/`start`/`stop`/`status`/`restart` CLI
  surface.
- The frozen output must satisfy the dashboard's generation tree rules: no
  empty directories and no links or reparse objects in the immutable
  bundled tree.

## Evidence the capsule-consume path was never wired live

Recorded in the dashboard's 2026-07-24 record: its `product-release.yml`
had zero runs, and the `A2A_CAPSULE_BASE_URL` fetch input was an empty
fail-closed placeholder. Verified in the dashboard tree on 2026-08-01: no
reference to `A2A_CAPSULE_BASE_URL` remains, the capsule-manifest parsing
authority and the producer-consumer capsule contract check
(`a2a_contract_check`) are deleted, and `packaging/a2a-component.lock.json`
is currently a source pin awaiting the amendment's version-reference
reshape. No live contract ever consumed the capsule or its manifest.

## What this asks of this repository

Nothing is decided here. Specifically worth re-examining on this corrected
input: the retention of the capsule apparatus and manifest, the "manifest
gains a producer" commitment, and the stopped retirement work — each was
justified by consumer records whose capsule clauses are now visibly
amended. The subordination record's governance conclusions — consumer
authority, supplier conformance, conformance verified against records
rather than fixtures — are unaffected by this correction and worth
preserving verbatim in any successor decision.
