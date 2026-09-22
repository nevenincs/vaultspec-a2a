---
tags:
  - '#research'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:c876155051a912dc83362ebb53ab6747464102f8539347005f8ae127ad38edea'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-03-31-integration-testing-service-certification-research]]"
  - '[[2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
---
# `service-lifecycle-architecture` research: `container API comparison for issue 18`

Issue #18 asks whether a programmatic Docker API should manage the gateway/worker/Jaeger topology. The evidence favors keeping Docker Compose as the owner of shipped server stacks and development/integration container profiles, and deferring a direct Engine API until a named capability cannot be met by a bounded host-side Compose facade. This is a recommendation from evidence, not a new decision or satisfaction of #18's programmatic-API criterion. The desktop profile and named host development processes have different lifecycle owners (`2026-03-20-service-lifecycle-architecture-adr`, `2026-07-15-dev-process-registry-adr`).

## Findings

### Compose is the existing stack contract

Compose owns topology, volumes, health-gated dependency ordering, restart policy, and aggregate logs. The gateway and worker Compose healthchecks make HTTP requests; `up --wait` consumes their container health state, so it already tests more than process existence. It does not provide richer product-specific health aggregation or preflight port-owner diagnosis. Justfile selects five project names/files and delegates stack commands; the service certifier uses its own Compose project for VidaiMock/Jaeger and host subprocesses for gateway/worker. The accepted desktop profile remains Docker-free. `Justfile:103`, `Justfile:739`, `service/docker-compose.integration.yml:35`, `service/docker-compose.integration.yml:42`, `service/docker-compose.integration.yml:88`, `src/vaultspec_a2a/service_tests/harness.py:398`, `src/vaultspec_a2a/service_tests/harness.py:409`, `2026-07-18-desktop-product-profile-adr`, https://docs.docker.com/reference/cli/docker/compose/up/.

### API alternatives have different ownership costs

| Option | What it supplies | Boundary against this repository |
| --- | --- | --- |
| Compose CLI | Project-scoped `up`, `down`, `ps`, `logs`; `up --wait` consumes declared healthchecks. | Current owner; a host-side facade can add one missing operator view without recreating topology. |
| Bollard `0.21.1` | Async direct Engine create/start/stop/restart/inspect/log calls; Unix socket and Windows named-pipe connections. | A Rust binary would need to translate/invoke Compose's networks, mounts, env, ordering, and project cleanup, plus add a Rust build. |
| Docker SDK for Python `7.2.0` | Direct daemon container lifecycle, inspect and logs from Python. | Closer in language, but still does not execute Compose project semantics by itself. |
| python-on-whales `0.81.0` | Python wrapper for `docker compose` commands, including `up`, `down`, `ps`, `logs`. | Retains Compose ownership, but is a CLI facade, not the issue's direct programmatic Engine API. |

The Bollard/SDK ownership cost is an inference from their container-level API and the repository's declared project topology, not a prototype measurement. The current explicit CLI calls avoid adding either dependency. `service/docker-compose.integration.yml:9`, `Justfile:103`, `src/vaultspec_a2a/service_tests/harness.py:107`, https://docs.rs/bollard/0.21.1/bollard/struct.Docker.html (page identifies `0.21.1`), https://docker-py.readthedocs.io/en/7.2.0/containers.html, https://docker-py.readthedocs.io/en/7.2.0/client.html, https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/compose/ (source version `0.81.0`, commit `1cbe8a22895b3b52e63f6c0d87944284e025f7ca`).

### Issue #18 capability map separates already-owned behavior from gaps

| Goal | Present owner/evidence | Possible bounded follow-up |
| --- | --- | --- |
| Service registry/topology | Compose service declarations and named Justfile projects (`service/docker-compose.integration.yml:9`, `Justfile:103`). | Machine-readable inventory only if an operator consumer needs it. |
| Health/restart | HTTP container healthchecks, `up --wait`, restart policies (`service/docker-compose.prod.yml:19`, `service/docker-compose.prod.yml:39`, `service/docker-compose.prod.yml:44`). | Aggregate application health beyond Compose state. |
| Logs | Compose CLI and certifier capture (`src/vaultspec_a2a/service_tests/harness.py:576`, `src/vaultspec_a2a/service_tests/harness.py:580`). | Bounded host-side multi-service tail if demanded; no shared recipe today. |
| Environment | Compose declarations and certifier environment builder (`service/docker-compose.integration.yml:21`, `src/vaultspec_a2a/service_tests/harness.py:409`). | Audit config sources before claiming a single source of truth. |
| Port precheck | CLI/plugin version check is present, not daemon/port-owner readiness (`dev/doctor/_docker.py:31`). | Diagnose conflict before `up`; failure message should name owner. |
| Zombie cleanup | Host process registry/reap is separate from containers (`Justfile:719`, `src/vaultspec_a2a/lifecycle/registry.py:1`, `src/vaultspec_a2a/lifecycle/registry.py:325`). | Keep host and container cleanup distinct. |
| Windows/Linux | Compose CLI invoked cross-platform; Bollard has both transports. | Live parity proof for any new facade or Engine client. |

### Security and decision boundary

Daemon authority must stay host-side: Docker documents socket access as sensitive, while the current Compose worker configures a dedicated agent UID/GID and fail-closed launcher to separate provider execution from service state. This documents an implemented boundary, not a claim that every profile has passed a live attack test. A bounded next step is to select one gap above, prototype CLI JSON/subprocess, python-on-whales, docker-py, and Bollard against an isolated Compose project on Windows and Linux, then decide whether the capability justifies a durable API owner. Adopting a direct Engine API or transferring stack ownership needs an ADR amendment or distinct accepted ADR. https://docs.docker.com/engine/security/protect-access/, `service/docker-compose.integration.yml:74`, `service/docker/prod.Dockerfile:61`, `service/docker/prod.Dockerfile:103`, `src/vaultspec_a2a/providers/_subprocess.py:140`, `src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py:113`.

No alternative-client prototype, Rust build, cross-platform proof, or failure-recovery benchmark was run; those costs remain unmeasured.

## Sources

Repository locators above are pinned to commit `a66e583f929c2ca6205744728b07052429ba3426`.

https://docs.docker.com/reference/cli/docker/compose/up/ (Docker CLI documentation read 2026-09-22; docs repository snapshot `71fa06427156ab4e87b88cdc9983d2efea8b7519`)
https://docs.docker.com/engine/security/protect-access/ (Docker docs read 2026-09-22; same snapshot)
https://docs.rs/bollard/0.21.1/bollard/struct.Docker.html (`bollard@0.21.1`, read 2026-09-22)
https://docker-py.readthedocs.io/en/7.2.0/containers.html (`docker-py@7.2.0`)
https://docker-py.readthedocs.io/en/7.2.0/client.html (`docker-py@7.2.0`)
https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/compose/ (`python-on-whales@0.81.0`, source commit `1cbe8a22895b3b52e63f6c0d87944284e025f7ca`)
https://github.com/gabrieldemarmiesse/python-on-whales/blob/1cbe8a22895b3b52e63f6c0d87944284e025f7ca/pyproject.toml
https://github.com/nevenincs/vaultspec-a2a/issues/18
