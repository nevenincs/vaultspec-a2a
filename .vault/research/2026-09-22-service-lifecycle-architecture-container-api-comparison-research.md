---
tags:
  - '#research'
  - '#service-lifecycle-architecture'
date: '2026-09-22'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:b80cd519e71cab794e0317e79b363167819ca21dd6ea88048a40dddf0a7b66e7'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-03-31-integration-testing-service-certification-research]]"
  - '[[2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
---
# `service-lifecycle-architecture` research: `container API comparison for issue 18`

Issue #18 asks whether a direct Docker Engine client, including Bollard, should manage the containerized gateway, worker, and supporting services. At code snapshot `d449031e334f9e77c5bbc459c50b7c35134578c2`, the evidence favors Docker Compose CLI itself as the automation boundary for the currently named lifecycle, inventory, health-state, and log operations. Existing host callers can invoke it through argv. The evidence does not establish that a direct Engine client is required or that a hybrid is unsafe. Choosing the Compose CLI boundary would answer the issue's direct-API question negatively and requires an explicit architecture decision; it does not close the other issue goals.

## Findings

### Compose has project-level control and machine-readable observations

The current `Justfile` pins five Compose project names and file sets and delegates configuration, up, down, and status to Compose (`Justfile:101`, `Justfile:737`, `Justfile:832`). Production gateway, worker, and Jaeger declare HTTP healthchecks, dependency ordering, and restart policies in Compose (`service/docker-compose.prod.yml:14`, `service/docker-compose.prod.yml:39`, `service/docker-compose.prod.yml:87`, `service/docker-compose.prod.yml:100`). Docker documents `up --wait` as waiting for running or healthy services, `ps --format json` as JSON Lines with project, service, state, health, and published ports, and `config --services` or `config --format json` as resolved configuration views. Compose also supplies create, start, stop, restart, down, and logs commands. Restart does not apply changed environment/configuration; `up` can recreate a service when its configuration or image changes. These are documented capabilities, not proof of a product-level health aggregate or port-owner diagnosis. https://docs.docker.com/reference/cli/docker/compose/ ; https://docs.docker.com/reference/cli/docker/compose/up/ ; https://docs.docker.com/reference/cli/docker/compose/ps/ ; https://docs.docker.com/reference/cli/docker/compose/config/ ; https://docs.docker.com/reference/cli/docker/compose/restart/

### The alternatives differ by ownership strategy, not only language

| Strategy | Capability and cost evidenced | Boundary in this repository |
| --- | --- | --- |
| Invoke Compose CLI from existing host callers | All named container lifecycle verbs, project logs, service list, and structured status are already exposed. Existing code uses subprocess argv (`src/vaultspec_a2a/service_tests/harness.py:85`, `src/vaultspec_a2a/service_tests/harness.py:107`). | Compose remains the repository's stack mutation route. Callers still have to add useful health interpretation, error reporting, and port diagnostics. |
| Use python-on-whales `0.81.0` to invoke Compose | Its Compose API exposes config, up, down, start, stop, restart, ps, logs, and events; it invokes Compose v2 behind the Python API. | Same Compose owner, with a new Python dependency. It is not a direct Engine API merely because its call site is Python. |
| Add docker-py `7.2.0` or Bollard `0.21.1` beside Compose | Both expose container-level Engine lifecycle, inspection, and logs. Compose labels identify its project and services, so a bounded adjunct can address Compose-created containers without recreating their topology. | A mutating adjunct introduces a second operational path. A read-only adjunct does not need to translate Compose files; replacing Compose as stack creator would require equivalent handling of project topology, networks, volumes, environment, dependency order, and cleanup. Those implementation costs have not been measured. |

The current comparison does not justify a Rust binary on its own. Bollard provides local Unix-socket and Windows named-pipe connection methods, but transport availability is not proof that a new binary fits this repository's packaging or the full Compose stack. Docker SDK documentation describes container operations; Docker's Compose model and labels describe project identity. https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/compose/ ; https://github.com/gabrieldemarmiesse/python-on-whales/releases/tag/v0.81.0 ; https://docker-py.readthedocs.io/en/7.2.0/containers.html ; https://docs.rs/bollard/0.21.1/bollard/struct.Docker.html ; https://docs.docker.com/compose/intro/compose-application-model/ ; https://docs.docker.com/reference/compose-file/services/

### A small Engine mutation did reconcile through Compose

On a Windows host using Docker Desktop's Linux engine `29.8.0` and Compose `5.5.1`, an isolated one-service project used the cached `alpine:latest` image (`sha256:320994c3b997e2ec6433f717f153e108023c5bec8fefa8d76b83451d16d05ea8`), a `sleep 300` command, and a trivial healthcheck. After `docker compose up -d --wait`, direct `docker stop` made `compose ps -a --format json` report `exited`. A second `compose up -d --wait` restored `running` and reused the container ID. Direct `docker rm -f` followed by `compose up -d --wait` recreated it with a new ID. `compose down --remove-orphans` removed the project container and network; no project containers remained. The experiment demonstrates basic stop/removal reconciliation, so the earlier claim that any Engine mutation necessarily breaks Compose is unsupported. It does not prove full gateway/worker/Jaeger reconciliation, concurrent writers, environment or volume changes, failure recovery, or a native Linux-host path.

### The remaining issue goals are distinct from client choice

The Docker doctor checks Docker and Compose version commands, not daemon readiness or port ownership (`dev/doctor/_docker.py:31`). The service certifier uses an isolated Compose project only for VidaiMock and Jaeger, then launches gateway and worker as host subprocesses with its own environment and readiness probes (`src/vaultspec_a2a/service_tests/harness.py:69`, `src/vaultspec_a2a/service_tests/harness.py:398`). Named host processes belong to the accepted process registry, not to the container controller (`Justfile:677`, `2026-07-15-dev-process-registry-adr`). The Compose profiles and host certifier have separate configuration paths, so adding an Engine client does not by itself create one environment source of truth. The accepted desktop profile remains Docker-free (`2026-07-18-desktop-product-profile-adr`).

### Daemon access is a shared privilege of CLI and SDK approaches

Both Docker Compose CLI and a direct Engine client require authority to control the daemon. Docker warns that daemon access can grant host-level control; changing the client library does not reduce that authority. The current gateway and worker Compose definitions do not mount a Docker socket (`service/docker-compose.prod.yml:14`, `service/docker-compose.prod.yml:57`). `docker compose config` interpolates variables, and the production Compose file contains an internal-token interpolation (`service/docker-compose.prod.yml:36`). Exposing its raw JSON through a status API could disclose secrets. https://docs.docker.com/engine/security/ ; https://docs.docker.com/engine/security/protect-access/ ; https://docs.docker.com/reference/cli/docker/compose/config/

The original issue asks for a Bollard comparison and a recommendation; it does not itself require a four-client, two-platform prototype before a proposal. Later issue comments and the earlier draft added that gate. No full-stack alternative-client prototype or native Linux-host comparison was performed here. Those limits must remain visible if a direct Engine path is selected. https://github.com/nevenincs/vaultspec-a2a/issues/18

## Sources

Repository code and accepted decisions above were read at `d449031e334f9e77c5bbc459c50b7c35134578c2` on 2026-09-24. The isolated Docker experiment above ran on 2026-09-24 with the named engine, Compose, image ID, and commands; its cleanup reported zero remaining project containers.

https://docs.docker.com/reference/cli/docker/compose/
https://docs.docker.com/reference/cli/docker/compose/up/
https://docs.docker.com/reference/cli/docker/compose/ps/
https://docs.docker.com/reference/cli/docker/compose/config/
https://docs.docker.com/reference/cli/docker/compose/restart/
https://docs.docker.com/compose/intro/compose-application-model/
https://docs.docker.com/reference/compose-file/services/
https://docs.docker.com/engine/security/
https://docs.docker.com/engine/security/protect-access/
https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/compose/
https://github.com/gabrieldemarmiesse/python-on-whales/releases/tag/v0.81.0
https://docker-py.readthedocs.io/en/7.2.0/containers.html
https://docs.rs/bollard/0.21.1/bollard/struct.Docker.html
https://github.com/nevenincs/vaultspec-a2a/issues/18
