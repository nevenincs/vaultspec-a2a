---
tags:
  - '#adr'
  - '#workspace-root-authority'
date: '2026-10-04'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:8cce2d792b74ee7d16954d8f0b5a3bb6f8b217cde06cbc2b54e832a3ad02f02b'
related:
  - "[[2026-10-04-workspace-root-authority-audit]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr]]"
  - "[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]"
  - '[[2026-10-01-provider-binary-policy-adr]]'
---

# `workspace-root-authority` adr: `desktop native admission` | (**status:** `accepted`)

## Problem Statement

Desktop managed-root checks constrain privileged callbacks but do not constrain provider-native tools, MCP descendants, or terminal processes running under the worker's OS identity. The independent synthetic-state reproduction in `2026-10-04-workspace-root-authority-audit` confirms absolute-path private-state reads. No desktop process isolation backend is implemented or certified.

## Considerations

The user requested all remaining known fixes and instructed continuation after the stricter refusal option was presented. Native process separation cannot be inferred from cwd checks, command allowlists, owner-only files shared with the same user, or lifetime Job Objects/process groups. A Windows restricted-token probe failed even its legitimate execution control during DLL initialization; an unverified launcher must not be advertised as isolation. Desktop native execution availability is therefore an explicit compatibility cost of immediate closure.

## Considered options

- Fail closed until an OS isolation backend is implemented and verified: chosen for immediate remediation. Keep attachment, health, filesystem queries, lifecycle ownership, and cancellation available, while no native provider/tool child inherits private-state authority.
- Keep same-user execution available and document the high finding: rejected under the user's instruction to continue remediation.
- Ship a speculative restricted-token, AppContainer or provider read-only wrapper: rejected. Runtime, authentication, IPC/network access, descendants, and native read denial need real proof before that backend can grant execution eligibility.

## Constraints

An armed desktop profile cannot admit native provider, terminal or MCP probe execution while the repository has no proven desktop OS isolation backend. The shared command/spawn boundary must refuse regardless of desktop launcher-related settings, provider command spelling or spawn mode. Readiness and eligibility must describe the refusal before reservation/actor credential acceptance. Default development and existing Compose identity launch behavior remain unchanged. This decision does not claim a desktop sandbox is implemented.

All current armed desktop new-run start, prepare and commit entries report this execution restriction before worker startup, reservation or actor binding. Explicit in-process broker tests can still exercise the independent admission contract outside the desktop profile. This is an execution-availability restriction for the current desktop product, not a claim that any in-process test lane certifies desktop native isolation.

## Implementation

We will expose one profile execution refusal policy to readiness/eligibility and enforce it at the shared provider/tool command boundary. Desktop refusal occurs before OS child acquisition. Native execution can be reopened only when a later implemented backend proves that provider and tool descendants cannot read synthetic lifecycle credentials/service state by absolute path, while admitted project I/O, provider authentication, local actor IPC, cleanup and a real provider turn remain functional on each admitted target.

## Rationale

Refusing unisolated native launch is the narrowest complete available closure of the proven read route. It applies to all current launch paths and does not rely on enumerating sensitive files. The callback fix remains an independent trusted-worker boundary. The existing Compose identity contract does not establish an equivalent shipped desktop backend.

## Consequences

Desktop health and lifecycle remain usable, but native agent runs are unavailable until a verified desktop isolation backend ships. This is an explicit security compatibility restriction, not successful desktop sandbox certification. Development and Compose keep their existing execution contracts. Reconsider when the supported backend and completed native/provider controls exist. Authorization basis: the user requested tackling all remaining known issues and then explicitly instructed continuation after the stricter fail-closed option was presented on 2026-10-04.

## Amendment: ACP terminal isolation, 2026-10-06

The user's explicit instruction to fix the latest scan's two high findings authorizes closure of the unisolated ACP terminal route documented in 2026-10-06-security-cloud-remediation-audit. The earlier default-development exception continues for ordinary provider launch, but no longer permits ACP terminal/create without the session process's validated native launch authority bound to the configured project. A terminal capability declaration alone cannot grant host execution. Initialize advertises terminal support only when that authority exists and validates; create independently revalidates before acquisition. Missing, stale or mismatched authority refuses before child execution. General interpreters remain usable inside the existing isolated runtime, project and selected role-home grants. This adds no target eligibility and no new isolation backend. Output, wait, kill, release and cleanup for retained terminals remain available. The compatibility cost is explicit: unisolated development terminals are unavailable; they do not fall back to same-user execution.

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

`2026-10-04-container-release-native-production-adr` retires the application Compose topology, so the Consequences clause "Development and Compose keep their existing execution contracts" names a retired half. Historical: the Compose half; no application container profile remains to keep an execution contract.

Still binding: the Development half, unchanged in code. `native_execution_refusal_reason` (`control/provider_execution.py:8-23`) refuses native execution only `if settings.desktop_profile_armed`; every other profile - a checkout or development host - returns `None` and is not refused by this record's policy. `desktop_profile_armed` (`control/config.py:347-355`) is armed exactly when an explicit application home is configured, so an unarmed (development) host keeps exactly the execution contract this record describes, with no Compose-specific branch anywhere in that seam. The 2026-10-06 ACP terminal isolation amendment's own "default-development exception" is this same unarmed path and is unaffected.
