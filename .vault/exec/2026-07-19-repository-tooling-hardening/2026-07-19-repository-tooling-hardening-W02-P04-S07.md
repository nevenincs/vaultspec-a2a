---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S07'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Route named services only through the process registry and stacks only through Compose

## Scope

- `just/dev/service.just`
- `just/dev/stack.just`

## Description

- Import native service and stack modules into the existing developer hierarchy.
- Route every supported process verb and named gateway, worker, and engine helper
  through the production process-registry CLI.
- Bind development, integration, PostgreSQL, production, and infrastructure
  lifecycle to explicit Compose files and isolated project names.
- Validate every Compose configuration, including the production-plus-PostgreSQL
  overlay pair, without starting or stopping containers.
- Prove root and nested discovery, real registry help/list behavior, safe dry runs,
  and the absence of direct process-management logic.

## Outcome

Named host-process lifecycle now has one owner: `vaultspec-a2a procs`. Stack
lifecycle now has one owner: Docker Compose. The native service module exposes
all real registry verbs plus explicit configured-role helpers, while the stack
module exposes bounded config/up/down/status surfaces for five isolated projects.
Formal review passed after all high findings were resolved.

## Notes

Real process listing found three existing dead registry records. They remain
untouched for explicit operator review and registry-owned reaping. Validation
used only help, listing, dry runs, and Compose configuration. Production and
database configurations fail closed without their required token and password;
validation supplied process-local non-secret values without weakening Compose
interpolation or embedding defaults. No process was started, killed, rebuilt,
resumed, or reaped, and no container lifecycle command executed. No scaffold
comments remain.
