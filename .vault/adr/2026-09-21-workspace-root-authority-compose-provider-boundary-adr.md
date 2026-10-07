---
tags:
  - "#adr"
  - "#workspace-root-authority"
date: '2026-09-21'
related:
  - "[[2026-09-21-workspace-root-authority-adr]]"
  - "[[2026-08-03-production-boundary-adr]]"
  - "[[2026-08-03-current-project-binding-adr]]"
  - "[[2026-09-21-open-issue-remediation-audit]]"
supersedes:
  - '2026-09-21-workspace-root-authority-adr'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:02fbd3426a9cc583aafc71e565a49e28ad37c30018836f714a10f386141f3917'
---

# `workspace-root-authority` adr: `Compose provider execution is isolated from service state` | (**status:** `accepted`)

## Problem Statement

The superseded workspace-root decision treated the authenticated control caller
and the Compose mount inventory as a sufficient workspace-selection boundary.
Implementation review disproved that assumption. The shipped development,
integration, and production profiles mount one volume at `/app/data` into both
gateway and worker, run both as UID/GID 1001, and place the SQLite database,
`a2a-home/service.token`, and workspaces below that mount. A bearer-authenticated
caller can currently select `/app/data` as a run root. ACP filesystem reads then
reach the gateway bearer and durable database directly.

This is a high-severity capability-delegation defect. The bearer holder is the
trusted administrator, but the model and spawned provider are a lower-trust
principal. Owner-only mode on `service.token` does not separate processes with
the same UID. Restricting the selected root alone is also insufficient: a
provider or allowed terminal child can name absolute paths independently of its
working directory.

## Considerations

- All three Compose profiles give gateway and worker the same `/app/data`
  volume and place the database, A2A home, and workspace root beneath it.
- Both images inherit `USER appuser` at UID/GID 1001. The token handoff is mode
  0600, so the worker and provider identity can read it.
- Run admission canonicalizes and requires an existing directory but applies no
  Compose root constraint. Selecting `/app/data` reaches graph compilation and
  provider construction unchanged.
- ACP `fs/read_text_file` resolves symlinks and confines reads to the selected
  root, so selection of `/app/data` directly admits the credential and database.
  Those callbacks execute in the worker, not in the provider child.
- Provider subprocesses and ACP terminal children currently inherit the worker
  OS identity. Working-directory confinement is not filesystem confinement; a
  project script invoked through an allowed interpreter can name an absolute
  service-state path.
- The child environment builder removes all `VAULTSPEC_*` variables and known
  provider-secret families before intentionally re-injecting lane credentials.
  This is useful defense in depth, not a filesystem boundary, and acceptance
  must prove every service and database credential is absent from environment
  and argv.

The supported desktop profile remains a local, single-user dashboard product.
The later desktop workspace boundary decision replaces this record's original
arbitrary-project exception with the lifecycle-derived managed workspace tree.
Compose remains a trusted single-administrator control plane, but it no longer
equates administrator authority with model-process authority.

## Constraints

- Desktop workspace selection follows
  `2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr` and receives
  no new container or UID contract from this Compose decision.
- Compose remains a single-administrator profile; this decision does not claim
  tenant isolation.
- The worker must retain database and checkpoint authority while no provider,
  MCP/tool descendant, or terminal child inherits that authority.
- Privileged filesystem callbacks must enforce canonical, symlink-safe run-root
  containment independently of child-process identity.
- Failure to establish the Compose execution boundary is a provider-admission
  failure, never a fallback to the worker identity.

## Implementation

Adopt a layered Compose-only boundary.

First, Compose run admission accepts only canonical descendants of the
configured `VAULTSPEC_WORKSPACE_ROOT`. It rejects the root's ancestors and any
path whose canonical resolution escapes through a symlink. Every
workspace-bearing execution and catalog route uses the same helper. Desktop
workspace admission follows the later desktop workspace boundary decision.

Second, gateway discovery state and `service.token` move to an owner-only,
gateway-only mount that is absent from the worker filesystem. The worker keeps
only state it actually owns. Environment and process arguments remain scrubbed
of gateway, internal-control, database, and discovery credentials; intended
provider authentication is re-injected only through the existing lane-specific
seams.

Third, every provider root, MCP/tool descendant, and ACP terminal child in the
Compose worker executes under a dedicated agent UID/GID, distinct from the
worker service identity. A small audited POSIX launcher in the worker image is
the one spawn seam. Before exec it clears supplementary groups, changes to the
agent GID and UID, clears effective, permitted, inheritable, and ambient
capabilities, sets `no_new_privs`, and fails closed if any transition or
postcondition cannot be established. The worker receives only the SETUID and
SETGID capabilities needed to perform that drop; the exec'd tree has none.

Service-state directories and database files are owned by the worker identity
and are unreadable to the agent identity. The configured workspace root is the
only mutable data tree shared with the agent group. Shipped profiles explicitly
mark their service-owned named volume for a bounded startup migration: it
mirrors owner access to the agent group while preserving executable bits, never
follows symlinks, and refuses hard-linked, special, foreign-owned, or
concurrently replaced entries. The launcher applies a group-sharing umask only
after entering the agent identity, while the service keeps its owner-only umask
and privileged callbacks explicitly create group-shared workspace files and
directories. Operators adding bind mounts must disable managed migration,
prepare the documented agent UID/GID access beneath the configured workspace
root, and pass startup validation; mounts elsewhere are not admissible and host
content is never silently rewritten.

Worker-side ACP filesystem callbacks remain privileged code, so they continue
to enforce canonical, symlink-safe containment beneath the admitted run root.
They never use the child UID as their protection. Subprocess identity separation
is the independent boundary for provider-native tools and terminal execution.

## Rationale

A canonical Compose root check closes the confirmed privileged-callback route,
while a distinct capability-free execution identity closes absolute-path access
from provider-native and terminal tools. Neither layer substitutes for the
other. Keeping Compose process isolation profile-specific preserves the desktop
product's separate execution identity contract. A dedicated execution service could be stronger, but the UID,
mode, mount, and fail-closed launcher contract establishes the required boundary
inside the existing worker topology with a smaller compatibility surface.

## Considered options

**Document the bearer and mount inventory as the boundary.** Superseded. The
shared mount contains the bearer and database, and the same worker identity is
delegated to provider processes.

**Add only a Compose path-prefix check.** Rejected as incomplete. It prevents
the confirmed ACP callback path created by selecting `/app/data`, but does not
stop an agent subprocess from naming an absolute sibling path.

**Move only `service.token` to another volume.** Rejected as incomplete. It
protects one credential only when that volume is absent from the worker, while
leaving durable state readable to the same provider identity.

**Rely on command allowlists, prompts, or provider read-only mode.** Rejected.
These govern mutation and advertised tool shape, not OS read authority; scripts,
provider-native reads, and future tools can bypass a working-directory rule.

**Introduce a separate execution service or tenant architecture.** Deferred.
It could provide a stronger remote isolation model but is unnecessary for the
existing single-administrator Compose profile once the process identity and
filesystem boundary are real.

## Acceptance and migration

Issue #25 stays open until a real Compose proof demonstrates all of the
following:

1. Shipped workspace descendants are accepted; `/app/data`, service-state
   descendants, missing paths, relative paths, and symlink escapes are refused.
2. A real worker-spawned provider and an ACP terminal/tool child can read and
   write a workspace sentinel but receive an OS permission failure reading
   gateway-token and database sentinels by absolute path.
3. The same children have the dedicated UID/GID, no supplementary service
   groups, zero effective/permitted/inheritable/ambient capabilities, and
   `no_new_privs` set. A setuid or file-capability probe cannot regain service
   identity.
4. Worker-side ACP filesystem callbacks refuse canonical and symlink escapes
   even though the callback runs under the worker identity.
5. Captured child environment and argv contain no gateway bearer, internal
   bearer, database credential/URL, discovery credential/path, or other service
   secret, while required provider authentication and a completed provider turn
   still work.
6. Compose restart, health, SQLite/checkpoint, and workspace-write behavior stay
   green. Failure to install or apply the launcher boundary refuses provider
   execution rather than falling back to the worker identity.

Existing shipped Compose workspace paths remain compatible. Custom Compose
project mounts must move beneath `VAULTSPEC_WORKSPACE_ROOT` and grant the
documented agent identity access. Desktop project migration is governed by
`2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr`.

## Consequences

The confirmed credential and durable-state read path becomes enforceably closed
at both application and OS boundaries. The gateway bearer remains an
administrator capability without becoming a capability automatically delegated
to the model. Compose gains a documented UID/GID and mount-permission contract,
and provider startup fails loud on hosts that cannot supply it.

This is not a multi-tenant claim. The worker remains trusted service code with
database authority, and the operator remains responsible for provider binaries,
mounted project content, and bearer distribution. The narrower claim is that a
served model/provider tree cannot read Compose service state merely because it
runs work in an admitted project.

## Amendment: desktop workspace authority, 2026-10-04

The user's explicit desktop finding remediation authorizes the managed workspace
allowlist in `2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr`.
It supersedes only this record's original unrestricted desktop-project exception.
The original 2026-09-21 Compose decision and its process-isolation obligations
remain authoritative; desktop previously required no project migration under
that decision, and now requires projects within its lifecycle-derived tree.

### Application container retirement, 2026-10-04

The owner's later explicit native-production directive in 2026-10-04-container-release-native-production-adr retires the application Compose topology and its packaged identity launcher. The preceding claim that Compose deployment obligations remain authoritative is limited by this later ruling: these are historical obligations for the retired profile, not a requirement to ship application containers. Workspace authority and private-service-state protection remain binding; native isolation must be established by native execution evidence, not the retired Docker proof.

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

The subject of this record, Compose provider execution, is retired. `2026-10-04-container-release-native-production-adr` retires the application containers, and `2026-10-07-codebase-remediation-fixture-lanes-adr` leaves Compose carrying Jaeger only. No shipped profile mounts `/app/data`: `service/docker-compose.integration.yml` defines no gateway or worker service, no application Dockerfile remains under `service/docker/`, and the packaged launcher source and entrypoint are gone. The 2026-10-04 section "Application container retirement" above already limits the container obligations. This section states which clauses are historical and which still bind. The record stays accepted.

Historical, because they describe or build the retired container topology:

- Problem Statement and Considerations: the shared `/app/data` volume, the UID/GID 1001 images, and the 0600 `service.token` handoff between gateway and worker containers.
- Implementation, Second (the gateway-only mount absent from the worker filesystem) and Third (the dedicated agent UID/GID, the packaged POSIX launcher, the SETUID and SETGID capabilities, the bounded startup migration and the bind-mount rules).
- Constraints, "Compose remains a single-administrator profile"; Considered options and Rationale, the weighing of Compose boundary designs, kept as history; Consequences, the documented UID/GID and mount-permission contract.
- Acceptance and migration: the six Compose proofs and the Issue #25 gate (issue #25 is closed).

Still binding, now on the native profiles:

- **Workspace admission, Implementation First, stated without Compose.** A configured workspace root is the admission boundary: a run root must be an existing canonical directory within it, with aliases resolved before comparison (`control/workspace.py:56-84`; callers `api/workspace.py:13-36`, `control/dispatch.py:511`, `control/accepted_input.py:75-76`). The setting is `VAULTSPEC_A2A_WORKSPACE_ROOT` (`control/infra_config.py:224-233`, `.env.example:194`), not the unprefixed name in the original text. The armed desktop profile derives its boundary from its lifecycle tree under `2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr`.
- **Privileged callbacks, Implementation closing paragraph and Constraints.** Worker-side ACP filesystem callbacks enforce canonical, symlink-safe containment independently of any child process identity (`providers/_acp_rpc_handlers.py:130-141`, `desktop/_filesystem_authority.py:616`).
- **Scrubbed child environment.** Service, database and gateway credentials and the `VAULTSPEC_*` family never reach a provider child, and lane credentials re-enter only through lane-specific seams (`workspace/environment.py:63,84`).
- **Constraints, authority and fail-closed admission.** The worker keeps database and checkpoint authority while no provider, tool or terminal descendant inherits it, and a failure to establish an execution boundary refuses admission and never falls back to the worker identity. The container launcher is no longer the means. Native execution is governed by `2026-10-04-workspace-root-authority-desktop-native-admission-adr`, and the optional external launcher setting that remains states that it alone does not prove OS isolation (`control/infra_config.py:234-251`, `providers/_provider_execution.py:25-61`). Native isolation is shown by native execution evidence, not by the retired Docker proof.
