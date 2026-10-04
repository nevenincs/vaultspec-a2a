---
tags:
  - '#adr'
  - '#workspace-root-authority'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:d613830457f3c17a1dadc29b6267bdcc1dd7bfcf16ff2a6e26577b1e637c38f3'
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
