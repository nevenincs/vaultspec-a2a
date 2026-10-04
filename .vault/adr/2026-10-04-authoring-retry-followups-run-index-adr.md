---
tags:
  - '#adr'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:a41223690551c6b93f8db6971a612e92448ff78a0664af17de7b194a1444526d'
related:
  - "[[2026-10-04-a2a-edge-conformance-authoring-retry-audit]]"
  - "[[2026-10-04-authoring-retry-followups-journal-retirement-adr]]"
  - "[[2026-10-04-authoring-retry-followups-parent-authority-adr]]"
  - "[[2026-07-19-codebase-health-adr]]"
---

# `authoring-retry-followups` adr: `Run-indexed authoring retirement without cross-run cleanup poisoning` | (**status:** `accepted`)

## Problem Statement

Deletion opens every flat journal, so unrelated corrupt or attacker-supplied historical files can consume another run's cleanup attempts. The authoring retry audit records both the installation-sized scan and the real Linux corrupt-file failure. The user explicitly instructed continued remediation without leaving known degradation.

## Considerations

Run/role journal filenames already deterministically bind their owner. Production replay is private to the worker; historical shared files are not active replay authority. Durable deletion elects closure before reclamation, and old binaries refuse the retained close marker and version-2 owner header. The saga already owns retry and truthful cleanup reporting.

## Considered options

- Ignore all SQLite failures during each full scan: rejected; hides failure to reclaim known run-owned data and retains the scan cost.
- Move every active journal to a new layout: rejected; needlessly changes replay paths and risks splitting active identity across old and new files.
- Add a private store/run/role index, preserve paths and close markers, and use authoritative ownership at deletion: chosen. Newly prepared journals register before any write/delivery. Historical discovery is a one-time validated inventory, rather than work repeated for each deleted run.

## Constraints

Accepted under the user's 2026-10-04 instruction to keep fixing the known degraded cleanup behavior. Preserve active call fingerprints, lifecycle references, keys and journal paths. Keep pending, rejected and completed identities until explicit durable deletion. Never import shared call records into active private replay. Index files are service-private, bound to their store root and version, and contain only ownership identifiers. A shared writer cannot modify them. Registration checks the same run marker before committing; retirement closes the run before reading its indexed owners.

A historical candidate enters the cleanup index only when its single owner row and supported source version match its deterministic run/role filename. Unclassifiable files are not deletion authority and remain untouched; neither corrupt foreign files nor newly forged shared files may fail another run's cleanup. Known indexed ownership, rather than readable SQLite payload, authorizes reclamation after closure. Corruption of an indexed run-owned database must be reclaimed without manual repair. Linked entry replacement must not follow its target; directory entries or unsafe roots remain real failures, reported by the existing saga. Genuine index/filesystem failure is never suppressed or reported as successful cleanup.

## Implementation

Maintain a versioned SQLite index under the private authoring state root, separately bound to each store directory. On first access inventory legacy deterministic journals once with read-only, nonblocking owner inspection; persist completion and validated owner rows transactionally. Register each new canonical run/role journal before its first journal transaction. Query only the deleting run's rows, durably write its close marker, and atomically install compact closed owner headers through exclusive descriptors. Indexed retirement can replace a corrupt file or a linked entry without opening its contents or following that entry. Keep foreign paths and unclassified historical files unchanged.

Remove that run's index rows only after every indexed journal is compacted successfully; the retained marker and headers keep stale binaries closed. Later cleanup passes query the index and do not enumerate the whole store again. Index ownership/version corruption fails explicitly rather than inventing an empty inventory. Keep manifest-driven independent outcomes, claims, retry and abandonment for actual external failures.

Review refinement in the same authorized pass: compacted databases also reclaim their exact SQLite -journal/-wal/-shm entries, without following linked targets, before index rows are forgotten. A real crashed writer proved that retaining a hot rollback journal could restore old records over the replacement header. Sidecar obstruction remains a truthful incomplete cleanup and retains indexed retry ownership. Capture dangling configured store links in the deletion manifest and refuse them explicitly rather than treating them as absent.

## Rationale

The run-owned index separates ownership proof from data readability and turns ordinary deletion into work proportional to that run's journals. It fixes the observed failure rather than lowering error handling or requiring an agent to remove a corrupt file. Preserving journal paths avoids changing active replay identity.

## Consequences

Historical inventory costs one store traversal during adoption or a newly created index; steady-state cleanup avoids installation-sized scans. Unknown historical files are preserved because they have no proven run ownership. This is not a claim that deletion reclaimed arbitrary files in the shared workspace. Index rows are reclaimed on successful deletion, while the accepted small close markers/headers remain. The retirement ADR's source-owner inspection and per-delete scan descriptions are refined by a dated amendment; its retention and engine contracts are unchanged.
