---
tags:
  - '#audit'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:9a5e46c1bae8d2fd204cb4d6bdef3882f131b3553980633bf66fd12bf8f66afc'
related:
  - "[[2026-09-22-service-lifecycle-architecture-container-api-comparison-research]]"
  - "[[2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference]]"
---
# `service-lifecycle-architecture` audit: `issue 18 evidence review`

## Scope

Independent review of the new comparative Research and code Reference for issue #18 against accepted lifecycle/profile decisions and the code snapshot `a66e583f929c2ca6205744728b07052429ba3426`. First pass required revision; bounded second pass narrowed locator defects; final independent pass was PASS. This is evidence review, not implementation or issue closure.

## Findings

### recommendation | high | comparative evidence omitted an answer-first recommendation

Resolved in Research: the evidence now favors Compose for server stacks and defers a direct Engine API pending a named capability and accepted decision. It explicitly preserves #18's programmatic-API criterion as open.

### profile-ownership | medium | server Compose claims could spill into desktop and host-process lifecycle

Resolved in both records with the Docker-free desktop ADR and host-process registry boundary; neither is recast as a container stack.

### recipe-commands | medium | reference overstated build behavior for database and infrastructure projects

Resolved with separate recipe forms and exact `Justfile:739` through `Justfile:837` locators.

### docker-doctor | medium | CLI version probe was described as daemon readiness

Resolved: `dev/doctor/_docker.py:31` checks Docker and Compose commands, not daemon state or port owners.

### compose-readiness | medium | research undercounted existing HTTP healthchecks

Resolved with `service/docker-compose.integration.yml:42`, `service/docker-compose.integration.yml:88`, and `up --wait` behavior; richer product aggregation remains a possible gap.

### execution-boundary | medium | security statement lacked the configured launcher and spawn seam

Resolved with `service/docker-compose.integration.yml:74`, `service/docker/prod.Dockerfile:103`, and `src/vaultspec_a2a/providers/_subprocess.py:140`; no unrun live proof is claimed.

### source-locators | medium | initial recipe, harness, log, and reap citations pointed too broadly or at the wrong lines

Resolved with exact project recipes (`Justfile:103`), certifier logs (`src/vaultspec_a2a/service_tests/harness.py:576`), host reap (`Justfile:719`, `src/vaultspec_a2a/lifecycle/registry.py:325`), and cited translation boundaries in both records.

### issue-coverage | medium | comparison omitted the issue's individual capability goals

Resolved with a bounded matrix for inventory, health, logs, environment, port precheck, zombie cleanup, and Windows/Linux proof; it does not imply those goals or #18 are complete.

### external-provenance | low | external documentation lacked stable version or source pins

Resolved with Bollard `0.21.1`, docker-py `7.2.0`, python-on-whales `0.81.0`/source commit, Docker docs snapshot/date, and full repository commit in Research.

### source-tail | low | issue source and trailing whitespace needed cleanup

Resolved: issue #18 URL is in Research Sources and `git diff --check` passes.

## Recommendations

No new task-queue item: the unresolved programmatic Docker API adoption criterion is already owned by issue #18. Do not add a direct Engine client or alter the accepted Compose ADR from these evidence records. If a concrete unmet operator capability emerges, prototype it on an isolated project and decide the API/ownership boundary before implementation.
