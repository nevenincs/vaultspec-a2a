---
tags:
  - '#audit'
  - '#workspace-root-authority'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:2cd32ba8cc5266e1c957905e7ec55c039b43a8b5782e9d9f692278ebb53f74e6'
related:
  - "[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]"
  - "[[2026-10-01-provider-binary-policy-adr]]"
---

# `workspace-root-authority` audit: `MCP probe executable and identity isolation`

## Scope

User-authorized security remediation on 2026-10-04 for the reported workspace-controlled PATH execution in pre-session harness MCP probes. Direct work enforces the existing absolute-launcher and Compose agent-identity commitments; no separate plan or change to Compose capabilities is required. Both ACP and Codex use the same registry renderer and verifier. Read-only investigation and independent candidate review were performed; review findings were confirmed with real processes and addressed before final verification.

## Findings

### workspace-probe-path | critical | Workspace executable search reached service-owned MCP probes

Type: security, privilege-boundary violation. Status: resolved in this change. Workspace environment construction prepended a project virtual environment, while the registry rendered bare `uvx`. The verifier directly launched that name using the run environment, before provider identity containment. `src/vaultspec_a2a/providers/_harness_mcp_registry.py:601` now binds the launcher to a cached absolute service-resolved path shared by ACP and Codex. `src/vaultspec_a2a/providers/_mcp_contract.py:105` excludes workspace executable and Python search paths from probes, and `:412` applies the configured identity launcher before probing and before successful-contract cache lookup. Ordinary workspace tool PATH remains available to providers. The setuid launcher now accepts only the image's UID/GID 1002, refusing root, worker, and mixed identities.

### probe-cleanup-authority | medium | Identity-dropped probes survived SDK timeout cleanup

Type: lifecycle regression. Status: resolved in this change. Independent review identified that worker UID 1001 cannot signal UID 1002 after dropping identity under the existing SETUID/SETGID-only capability policy. A real stalled probe and child reproduced the SDK's EPERM warning and survived its kill escalation. `service/docker/provider_identity_launcher.c:105` adds probe-only supervision: the audited parent remains signalable by the worker, executes no caller-selected code, and drops to the agent identity before killing the unreaped child's process group. It acts as a subreaper and reaps group descendants without requiring a container init. The child enters the existing capability-free, no-new-privileges boundary before exec. No additional service capability is granted. `src/vaultspec_a2a/providers/_mcp_contract.py:252` disarms the deadline before joining SDK teardown and shields that join from repeated native cancellation; an overlapping cancellation/deadline had otherwise interrupted the SDK's AnyIO cleanup shield. Timeout and explicit cancellation now leave neither the stalled server nor its child alive.

### agent-runtime-storage | medium | Lower-identity acquisition could not write the worker's uv directories

Type: compatibility regression. Status: resolved in this change. Fresh-cache testing exposed permission failures in uv's cache and tool directories under the worker home. `service/docker/prod.Dockerfile:130` configures agent-owned cache, tool, and interpreter-install locations under `/var/cache/vaultspec-mcp`; the image creates the protected parent for UID/GID 1002. A real fresh-cache registry MCP handshake succeeds under the same identity and capability bounds as the shipped worker.

## Verification

- `uv run --no-sync pytest -q` over registry, ACP/Codex rendering, contract, interpreter pin, pinning, withheld-tool, egress-axis, subprocess and CLI-resolution tests: 163 passing cases across the initial focused runs. Five unrelated live cases were deselected by existing suite configuration. A final contract/security/subprocess run after cleanup changes passed all 22 selected cases.
- New `src/vaultspec_a2a/providers/tests/test_mcp_probe_security.py:15` runs the production registry/verifier in a fresh interpreter with workspace-planted uvx and Python commands. The real MCP contract passes and the planted commands leave no marker.
- `docker build --target identity-launcher -f service/docker/prod.Dockerfile -t vaultspec-mcp-identity-fix .`: compiled with `gcc -std=c11 -O2 -Wall -Wextra -Werror`.
- `dev/audit/mcp_probe_isolation.py:136`, executed in a disposable worker image containing current source and the compiled launcher, proves UID/GID 1002, empty supplementary groups, zero effective/permitted/inheritable/ambient capabilities, SETUID/SETGID-only bounding capabilities, no-new-privileges, denial of a worker-owned sentinel, permitted workspace writes, rejection of privileged/mixed launcher identities, a fresh-cache real MCP contract, and cleanup of stalled probes and descendants on timeout/cancellation. Final command: `docker run --rm --name vaultspec-mcp-isolation-final-check vaultspec-mcp-isolation-final`; no init process is required for descendant reaping.
- Ruff lint, Ruff format checks, and Ty checks pass on all ten changed Python files. The repository-wide `uv run --no-sync ty check src dev docs scripts packaging` also passes. The full deployment and unrelated repository suites were not rerun. Validation reused an existing worker dependency image and overlaid current source and the newly compiled launcher; this is not a claim that a complete production image was rebuilt or deployed.

## Recommendations

Rebuild and roll out the worker image to apply the source, launcher, and agent-owned uv directories together. Preserve the existing Compose capability policy. The review has no unresolved in-scope finding after the confirmed cleanup correction; future changes to probe supervision must retain timeout, cancellation, and descendant-reaping proof.
