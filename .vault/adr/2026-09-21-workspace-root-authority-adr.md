---
tags:
  - "#adr"
  - "#workspace-root-authority"
date: '2026-09-21'
related:
  - "[[2026-08-03-current-project-binding-research]]"
  - "[[2026-07-18-desktop-product-profile-research]]"
  - "[[2026-08-03-current-project-binding-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
superseded_by: '2026-09-21-workspace-root-authority-compose-provider-boundary-adr'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:e0ee256bded4ad45a469232c7ac441717b265b5e5adb56dae1dcd144f6609819'
---
# `workspace-root-authority` adr: `authenticated control credentials grant workspace selection authority` | (**status:** `superseded`)

## Problem Statement

Run admission accepts a caller-selected absolute workspace root. The accepted
project-binding decision constrains every admitted run to that root, but does not
state whether choosing the root is itself a privileged control operation. Issue
#25 cannot be closed safely until that authority is explicit for both the
dashboard-managed desktop profile and the Compose server profile.

## Considerations

- The dashboard supplies a workspace on every run stage; arbitrary user project
  locations are part of that contract. See
  `2026-08-03-current-project-binding-research` and
  `2026-07-18-desktop-product-profile-research`.
- Every engine-facing request already requires the attach bearer, including
  Compose and development; `src/vaultspec_a2a/api/auth.py:80`.
- Admission rejects missing, relative, or nonexistent execution roots and pins
  the accepted root throughout execution;
  `2026-08-03-current-project-binding-adr`.
- Workspace-local configuration is intentionally loaded beneath the admitted
  root; `src/vaultspec_a2a/team/team_config.py:706`.
- Compose filesystem isolation is expressed by container mounts. An application
  allowlist would duplicate that operator boundary.

## Considered options

- **Treat the authenticated control caller as the workspace-selection authority
  - chosen.** Desktop delegates this capability only to the dashboard attach
  credential. Compose delegates it to holders of the operator-issued gateway
  bearer, bounded by the filesystem presented to the service.
- **Add path-prefix allowlists to every profile - rejected.** This breaks
  arbitrary desktop workspaces and duplicates dashboard project authority.
- **Add a Compose-only application allowlist - rejected for the existing
  trusted-control profile.** It can provide defense in depth, but adds a second
  mount inventory and a breaking migration without an existing tenant boundary
  to enforce. A future shared or multi-tenant profile must reconsider it.
- **Accept any absolute path without treating the bearer as authority -
  rejected.** This leaves the security contract implicit.

## Constraints

- Desktop workspace selection remains unrestricted after successful attach
  authentication.
- Compose documentation must state that the gateway bearer is a control
  capability whose holder may select any workspace visible inside the service
  filesystem.
- Relative, missing, and unusable paths remain refused. Admission-time authority
  does not weaken the accepted run-bound project pin or sandbox containment.
- No endpoint may accept caller-selected workspace roots outside the existing
  authenticated engine-facing surface.

## Implementation

Document the gateway bearer as workspace-selection authority for unarmed
Compose and development profiles and the attach credential as that authority
for the armed desktop profile. Add contract tests proving workspace-bearing
routes remain authenticated and that relative or nonexistent execution roots
are refused while arbitrary existing roots remain valid. Review Compose mounts
and examples so they expose only operator-intended roots. No new allowlist,
environment variable, or wire field is introduced.

## Rationale

The bearer already gates the complete engine-facing control surface. Making
workspace selection part of that capability matches the existing dashboard
contract, preserves arbitrary desktop projects, and places Compose isolation
with the operator who controls bearer distribution and filesystem mounts. An
application prefix list would be a second authority that can drift from both.
This decision was accepted on 2026-09-21 under the user's delegated
architectural authority after orchestrator review of the profile boundary,
compatibility, and migration impact.

## Consequences

Issue #25's remaining path concern becomes a documented trust contract rather
than a traversal defect. Existing desktop and Compose clients require no
migration. Operators must treat the gateway bearer as a high-authority control
credential and restrict mounted roots accordingly. A future multi-tenant server
profile requires a separate decision because bearer-wide root selection is not
tenant isolation and this decision makes no multi-tenant safety claim.
