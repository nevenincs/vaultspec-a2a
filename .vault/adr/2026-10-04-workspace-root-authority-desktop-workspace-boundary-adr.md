---
tags:
  - '#adr'
  - '#workspace-root-authority'
date: '2026-10-04'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:108466715de5f37bd3a70735d52f6980010b41064c2781165e786bb6817df334'
related:
  - "[[2026-10-04-workspace-root-authority-audit]]"
  - "[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-08-03-current-project-binding-adr]]"
---
# `workspace-root-authority` adr: `Desktop attach authority is bounded by the managed workspace tree` | (**status:** `accepted`)

## Problem Statement

Desktop attach authentication currently grants caller-selected filesystem roots that can include lifecycle credentials and service state. The confirmed path and stored-root copy are documented in `2026-10-04-workspace-root-authority-audit`.

## Considerations

The desktop profile already derives and provisions an application-home `workspaces/` tree. Attach, lifecycle, and worker credentials have separate authority. Existing arbitrary desktop selection contradicts that separation when privileged callbacks use a caller-selected state directory as their sandbox.

## Considered options

- Use the existing managed workspace tree: chosen. It gives a trusted lifecycle-derived allowlist with no new credential, storage schema, or API field.
- Mint per-project lifecycle capabilities: deferred. This can restore external project selection later, but requires new issuance, session-binding, and client contracts.
- Deny named credential directories while admitting arbitrary roots: rejected. Ancestors and unenumerated credential locations remain selectable.

## Constraints

Desktop execution and workspace-bearing queries accept only existing canonical directories within the application's derived `workspaces/` tree. The allowlisted tree itself cannot redirect to state or another directory. Saved metadata, worker admission, provider cwd, and filesystem callbacks must apply the current policy. Canonical symlink, traversal, and Windows prefix aliases must not bypass containment. Existing configured Compose containment and unconfigured development behavior remain compatible.

This decision replaces only the unrestricted desktop-project exception in `2026-09-21-workspace-root-authority-compose-provider-boundary-adr`; that record continues to govern Compose process isolation. It does not establish an operating-system sandbox for desktop provider or terminal children.

## Implementation

We will centralize profile workspace admission and derive the desktop allowlist from the trusted application home. Reuse that boundary for initial and query admission, saved roots, worker dispatch, and provider roots. Existing valid projects within the tree retain their canonical run binding; previously saved outside projects cannot resume under desktop until they are placed within the allowed tree.

## Rationale

The existing lifecycle-derived root closes the reported delegation error without expanding attach authority or implementing a new protocol. Rejecting all outside roots also excludes application home, state, credentials, their ancestors, and filesystem-root selections.

## Consequences

Desktop clients that supplied arbitrary project paths must place their projects within application-home `workspaces/`; links to outside projects do not grant authority. A future external-project capability needs its own decision. Accepted 2026-10-04 under the user's explicit request to fix the supplied finding, whose remediation authorizes an explicit desktop workspace allowlist. This authorizes implementation but does not imply verification has completed.

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

`2026-10-04-container-release-native-production-adr` retires the application Compose topology, and `2026-09-21-workspace-root-authority-compose-provider-boundary-adr`'s own 2026-10-07 reconciliation amendment records that Compose provider execution, the subject it continued to govern, is itself retired. Two clauses of this record name that now-historical subject and are historical in turn:

- Constraints, "Existing configured Compose containment and unconfigured development behavior remain compatible." No Compose profile remains to be compatible with; unconfigured development behavior is unaffected.
- Constraints, "This decision replaces only the unrestricted desktop-project exception in `2026-09-21-workspace-root-authority-compose-provider-boundary-adr`; that record continues to govern Compose process isolation." The referent's Compose process isolation is retired; what continues to bind from that cross-reference is the non-Compose workspace-admission boundary the 09-21 record's own reconciliation names (`control/workspace.py:56-84`), which is this record's own subject and is unaffected by the historicization.

Still binding and unchanged: this record's own Implementation and Constraints otherwise stand. The desktop allowlist is derived from the application's lifecycle-derived `workspaces/` tree (`control/workspace.py:49-62,65-86`; the desktop boundary is armed by `settings.desktop_app_home`), and `2026-10-04-workspace-root-authority-desktop-native-admission-adr` governs native execution separately, as this record's Constraints already state.
