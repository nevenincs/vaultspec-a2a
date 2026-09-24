---
tags:
  - '#audit'
  - '#service-lifecycle-architecture'
date: '2026-09-24'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:fec90c521c392eecf389a1594ce12c432b9aef284cb6484818419c1ed47613a7'
related:
  - "[[2026-09-22-service-lifecycle-architecture-container-api-comparison-research]]"
  - "[[2026-09-22-service-lifecycle-architecture-compose-host-lifecycle-reference]]"
  - "[[2026-09-22-service-lifecycle-architecture-container-api-boundary-adr]]"
  - "[[2026-09-22-service-lifecycle-architecture-issue18-evidence-review-audit]]"
---
# `service-lifecycle-architecture` audit: `independent revalidation of issue 18 container API evidence`

## Scope

Independent review on 2026-09-24 of the proposed container-API ADR, its comparative Research and code Reference, the prior evidence-review Audit, accepted lifecycle/profile decisions, issue #18, current code at `d449031e334f9e77c5bbc459c50b7c35134578c2`, primary Docker/client documentation, and an isolated Docker experiment. The prior Audit reviewed the Research and Reference at `a66e583f929c2ca6205744728b07052429ba3426` before the ADR existed; its PASS did not certify the ADR or later code.

## Findings

### decision-content | high | the proposed ADR never proposed a choice

Status: corrected in the ADR body. The earlier draft listed open options and a required investigation, then said no client was selected. It functioned as an issue plan rather than one architecture decision. The revised ADR explicitly proposes Compose CLI as the programmatic control boundary and remains `proposed`.

### authority | high | later issue comments became mandatory decision gates

Status: corrected in Research and ADR. The original issue asks for a Bollard comparison and recommendation. A later comment added a fixed four-client, two-platform prototype requirement; the draft treated that as accepted authority. The independent review uses the original issue, accepted decisions, and verified evidence to state a proposal. It does not treat an agent-authored comment or a proposed document as user approval. Issue #18 remains the task queue for any unmet direct-API requirement.

### option-shape | medium | strategies and client libraries were mixed as alternatives

Status: corrected in Research and ADR. Compose CLI, python-on-whales, docker-py, Bollard, and a hybrid were not options at one architectural level. The revised comparison first separates Compose-only, Engine adjunct, and Engine replacement strategies, then identifies applicable clients.

### governing-decision | high | a new Python controller would duplicate accepted ownership

Status: corrected during integrated review. The accepted `2026-07-19-repository-tooling-hardening-adr` keeps Justfile as a thin Compose passthrough and rejects a new Python supervisor. An intermediate rework draft proposed a central Python controller without proving a need for it. The final proposal retains direct Compose CLI invocation by existing host callers and adds no supervisor or controller.

### reconciliation | medium | the direct Engine cost was overstated for an adjunct

Status: corrected in Research and ADR. A read-only or bounded mutating client can address Compose-created containers by project/service identity without rebuilding topology. On a Windows host with Docker Engine `29.8.0` and Compose `5.5.1`, direct stop and removal of an isolated Alpine service were reconciled by a subsequent Compose `up`. This is narrow evidence, not full-stack or native Linux proof.

### compose-observability | medium | existing structured Compose output was undercounted

Status: corrected in Research and Reference. Official Compose docs provide `config --services`, `config --format json`, and `ps --format json`, including state, health, and published ports. The earlier Research treated machine-readable inventory mainly as a possible future gap.

### security | medium | the client comparison implied a privilege difference

Status: corrected in Research and ADR. Compose CLI and Engine SDK clients both need Docker daemon authority. The actual boundary is host versus service process, selected project identity, and secret-safe output; switching client language is not a privilege reduction.

### source-drift | medium | evidence was pinned to changed code

Status: corrected in Reference and Research. The earlier records declared `a66e583f929c2ca6205744728b07052429ba3426` as their snapshot, but relevant Compose files, Justfile, and harness had changed before this ADR revalidation. The revised records cite current code at `d449031e334f9e77c5bbc459c50b7c35134578c2` and preserve the snapshot distinction.

### proof-limit | medium | full-stack and native Linux behavior remain unproven

Status: open, owned by issue #18. The local experiment covers one cached Alpine service on a Windows host with a Linux Docker backend. It does not validate gateway/worker/Jaeger behavior, concurrent mutation, recovery, or native Linux-host operation. The ADR stays proposed; accepting a direct Engine path would need capability-specific evidence.

## Recommendations

Keep the rewritten ADR proposed until the owner decides whether #18 requires a direct Engine API or accepts Compose CLI as its programmatic control boundary. No issue closure or implementation is implied by this documentation pass. Retain the earlier Audit as a historical review of its stated older snapshot; use this record for the current independent verdict and the open evidence gap.
