---
tags:
  - '#reference'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:f965dbc5f4a1ca61813dfdd57744daeaf8d2d8dd7ad993a40a3e340bb580908d'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
---
# `service-lifecycle-architecture` reference: `Compose and host lifecycle seams`

Code snapshot `a66e583f929c2ca6205744728b07052429ba3426` (origin/main, 2026-09-22). This maps issue #18's implementation seams; it is not a replacement design.

## Summary

- Justfile fixes five distinct Compose project names and file sets. Dev/integration/prod run `up -d --build --wait`; database and infrastructure run selected services with `up -d --wait`; all expose `config`, `down --remove-orphans`, and `ps`. The Docker doctor checks only CLI and Compose-plugin version commands, not daemon readiness or port occupancy. No shared stack-log recipe is present. `Justfile:103`, `Justfile:739`, `Justfile:779`, `Justfile:799`, `Justfile:819`, `dev/doctor/_docker.py:31`.
- Compose declarations own server gateway/worker images, environment, mount boundaries, HTTP healthchecks, dependency ordering, and production restart policy. Integration adds VidaiMock and Jaeger; the PostgreSQL overlay extends production. These are not constructed in Python. `service/docker-compose.dev.yml:5`, `service/docker-compose.integration.yml:9`, `service/docker-compose.integration.yml:35`, `service/docker-compose.integration.yml:42`, `service/docker-compose.integration.yml:88`, `service/docker-compose.prod.yml:13`, `service/docker-compose.prod.yml:39`, `service/docker-compose.prod.postgres.yml:5`.
- The service certifier starts only VidaiMock/Jaeger in its own Compose project, then launches gateway and worker as host subprocesses with explicit environment and readiness probes. It captures Compose logs before `down -v --remove-orphans`. This mixed test topology is not a general product container supervisor. `src/vaultspec_a2a/service_tests/harness.py:107`, `src/vaultspec_a2a/service_tests/harness.py:398`, `src/vaultspec_a2a/service_tests/harness.py:409`, `src/vaultspec_a2a/service_tests/harness.py:453`, `src/vaultspec_a2a/service_tests/harness.py:517`, `src/vaultspec_a2a/service_tests/harness.py:576`, `src/vaultspec_a2a/service_tests/harness.py:580`.
- Named host development processes use registry verbs surfaced by Justfile; `service-reap` handles stale process records. The gateway's `LazyWorkerSpawner`/`WorkerWatchdog` supervise a child process, not a container. The accepted desktop decision separately forbids Docker dependency, outside server Compose ownership. `Justfile:680`, `Justfile:719`, `src/vaultspec_a2a/lifecycle/registry.py:1`, `src/vaultspec_a2a/lifecycle/registry.py:325`, `src/vaultspec_a2a/control/worker_management.py:254`, `src/vaultspec_a2a/control/worker_management.py:579`, `2026-07-18-desktop-product-profile-adr`.

Translation boundary: a host-side interface could consume the existing Compose project names/files (`Justfile:103`), but a direct Engine client cannot execute those declarations without invoking or recreating Compose semantics (`service/docker-compose.integration.yml:9`, `service/docker-compose.integration.yml:35`). Neither the gateway child-process manager nor provider tree is an appropriate daemon client (`src/vaultspec_a2a/control/worker_management.py:254`, `src/vaultspec_a2a/providers/_subprocess.py:140`). The accepted lifecycle ADR owns the server stack choice (`2026-03-20-service-lifecycle-architecture-adr`); a durable programmatic API owner remains a separate decision.
