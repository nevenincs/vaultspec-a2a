---
tags:
  - '#reference'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:a234135696d764534df9dd3deb066a2d54f7babd69f20f4838ea876c83ca38e5'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
---
# `service-lifecycle-architecture` reference: `Compose and host lifecycle seams`

Code snapshot `d449031e334f9e77c5bbc459c50b7c35134578c2` (2026-09-24). This records the implementation boundaries relevant to issue #18, not a new architecture choice.

## Summary

- The repository exposes five explicitly named Compose projects, each bound to a particular file set (`Justfile:101` through `Justfile:105`). The stack recipes delegate configuration, up, down, and status to Compose. Dev, integration, and production use `up -d --build --wait`; database and infrastructure start only the selected PostgreSQL or Jaeger service with `up -d --wait` (`Justfile:737` through `Justfile:833`). The recipes expose no shared log or restart verb today.
- The current Compose files describe a headless server product. Dev has gateway and worker; integration adds VidaiMock and Jaeger; production has gateway, worker, and Jaeger; the PostgreSQL overlay changes the production database (`service/README.md:1`, `service/docker-compose.dev.yml:6`, `service/docker-compose.integration.yml:10`, `service/docker-compose.prod.yml:14`, `service/docker-compose.prod.postgres.yml:6`). Gateway and worker healthchecks use HTTP, and production defines dependency order and restart policies (`service/docker-compose.prod.yml:19`, `service/docker-compose.prod.yml:39`, `service/docker-compose.prod.yml:44`, `service/docker-compose.prod.yml:62`, `service/docker-compose.prod.yml:84`, `service/docker-compose.prod.yml:87`).
- The Docker doctor invokes `docker --version` and `docker compose version`. It does not contact the daemon or inspect port owners (`dev/doctor/_docker.py:31` through `dev/doctor/_docker.py:54`). A future port preflight or daemon probe would be additional behavior.
- The service certifier invokes Compose through an argv subprocess with an explicit project name and environment (`src/vaultspec_a2a/service_tests/harness.py:69` through `src/vaultspec_a2a/service_tests/harness.py:120`). It starts VidaiMock and Jaeger in that project, launches gateway and worker as host subprocesses, probes their readiness, captures Compose logs, and tears its project down (`src/vaultspec_a2a/service_tests/harness.py:371`, `src/vaultspec_a2a/service_tests/harness.py:398`, `src/vaultspec_a2a/service_tests/harness.py:517`, `src/vaultspec_a2a/service_tests/harness.py:576`). It is a certification harness, not a shipped container supervisor.
- Named host gateway, worker, and engine processes use the separate registry's list, up, attach, kill, rebuild, rerun, resume, and reap verbs (`Justfile:92`, `Justfile:677` through `Justfile:735`; `src/vaultspec_a2a/lifecycle/manager.py:500`). The accepted desktop product has a Docker-free lifecycle (`2026-07-15-dev-process-registry-adr`, `2026-07-18-desktop-product-profile-adr`).

## Translation boundary

The existing project name/file mapping and subprocess pattern show how a host caller can invoke Compose without a new controller (`Justfile:101`, `src/vaultspec_a2a/service_tests/harness.py:85`). Configured services and running containers have separate observations; resolved configuration includes an internal-token interpolation (`service/docker-compose.prod.yml:36`). A direct Engine client can inspect or mutate containers that Compose created without translating all topology; replacing Compose as the creator would require an equivalent account of its files, health order, volumes, networks, and cleanup. The accepted Compose decision and repository tooling decision remain the governing owners (`2026-03-20-service-lifecycle-architecture-adr`, `2026-07-19-repository-tooling-hardening-adr`).
