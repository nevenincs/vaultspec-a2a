---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S03'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify the process-registry prerequisite represented by repository-tooling plan step S07 before changing lifecycle registry consumers

## Scope

- `.vault/exec`
- `.vault/audit`
- `just/dev/service.just`

## Description

- Ground the named-process and stack ownership boundary with semantic code and
  vault searches.
- Read `just/dev/service.just`, `just/dev/stack.just`,
  `.vault/exec/2026-07-19-repository-tooling-hardening/2026-07-19-repository-tooling-hardening-W02-P04-S07.md`,
  and
  `.vault/exec/2026-07-19-repository-tooling-hardening/2026-07-19-repository-tooling-hardening-W02-P04-summary.md`
  in full.
- Confirm repository-tooling S07 is checked and its two Just modules have no
  uncommitted changes.
- Verify every named-process recipe delegates to the locked
  `vaultspec-a2a procs` command.
- Verify every stack recipe delegates to an isolated Docker Compose project.
- Exercise recipe discovery, the read-only process list, registry help, and
  representative service and stack dry runs without changing runtime state.

## Outcome

The process-registry prerequisite is certified. `just --list dev::service` and
`just --list dev::stack` completed successfully and listed all available service
and stack recipes. `just dev service list` reached the locked production
registry command-line interface and returned `no registered processes` with
exit code zero.

The focused dry runs preserved the ownership boundary:

- `just --dry-run dev service gateway-up cert-s03` rendered
  `uv run --no-sync --frozen --no-default-groups vaultspec-a2a procs up
  gateway-dev cert-s03`.
- `just --dry-run dev stack dev-up` rendered project
  `vaultspec-a2a-dev` with `service/docker-compose.dev.yml`.
- `just --dry-run dev stack database-config` rendered project
  `vaultspec-a2a-database` with `service/docker-compose.prod.yml` and
  `service/docker-compose.prod.postgres.yml`.
- `uv run --no-sync --frozen --no-default-groups vaultspec-a2a procs --help`
  exposed the registry verbs consumed by the service recipes.
- `just --fmt --check` passed, and `git diff --exit-code` confirmed both Just
  modules match the landed revision.

No production code or runtime configuration changed. The formal independent
review found no critical, high, medium, or low issue and returned `PASS`.

## Notes

No process was started, stopped, killed, rebuilt, resumed, rerun, or reaped. No
container command executed. Concurrent desktop, application programming
interface, database, and unrelated vault changes remained outside this step.
The review produced no findings to add to the audit queue.

Editorial review classified five clarity findings as medium severity and two as
low severity. The body now names the evidence, defines terminology, and states
the queue result directly. The approved plan supplies the machine-generated
title, and the execution template requires the line-by-line Description list.
Both retain their required forms.
