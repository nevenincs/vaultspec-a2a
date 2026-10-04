---
tags:
  - '#adr'
  - '#desktop-native-isolation'
date: '2026-10-05'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:b878c5744bcd8c9982a13837dcc4e1afee0897730a887f52f399f5807c4948bd'
related:
  - "[[2026-10-04-desktop-native-isolation-native-backend-primitives-research]]"
  - "[[2026-10-04-workspace-root-authority-desktop-native-admission-adr]]"
  - "[[2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr]]"
  - "[[2026-10-04-container-release-native-production-adr]]"
  - "[[2026-10-01-provider-binary-policy-adr]]"
---

# `desktop-native-isolation` adr: `Linux namespace backend with proof-gated native admission` | (**status:** `accepted`)

## Problem Statement

Desktop needs an OS boundary before native agent execution can resume. The measured Linux namespace primitive supports selective project/runtime access and descendant cleanup; stock Windows Node pipe behavior remains incompatible with the tested token boundaries. The backend choice, path authority and qualification limits must be explicit before integration.

## Considerations

`2026-10-04-desktop-native-isolation-native-backend-primitives-research` records actual filesystem, runtime, synthetic auth, HTTP relay and detached-child controls. `2026-10-04-container-release-native-production-adr` excludes a production Docker dependency. `2026-10-04-workspace-root-authority-desktop-native-admission-adr` requires complete provider and native evidence before reopening eligibility.

## Considered options

- Selective Linux mount/user/PID namespaces using a capsule-owned bubblewrap helper: selected for implementation because the measured controls pass and existing native runtime/process ownership can remain.
- Same-user launches or callback-only confinement: rejected; native absolute paths retain the service authority.
- Windows restricted-token or AppContainer launch using existing stock runtimes: retained as research only; normal Node pipe creation is unqualified, and runtime-only changes do not prove auth/relay/cleanup.
- Docker/WSL as a production prerequisite: rejected by native production scope. The available WSL host is a Linux test host, not a Windows production backend.

## Constraints

Mount only the lifecycle/worker-selected managed project, one worker-created role auth home and immutable runtime closure. Do not infer authority from PWD/HOME/CLI arguments or mount the application home, parent config home, service stores or other role homes. Validate and retain opened filesystem identities through mount acquisition. Runtime helper and mapped runtime dependencies belong to a pinned capsule closure; no ambient helper/tool/package installation fallback at launch. Clear infrastructure credentials before intentional role additions. All native entry points, including MCP/cache/version/catalog/terminal paths, require a valid trusted context and the same boundary.

Keep user/PID/IPC/UTS/cgroup isolation, no-new-privileges, dropped capabilities, new terminal session, private proc/dev/tmp and retained-owner death propagation. Keep host networking only for existing authenticated provider/actor transports; no host file/socket/handle is granted by it. Runtime is read-only; project and role home are writable. Preserve callback confinement and exact retained-process ownership independently.

Windows, macOS and any unverified Linux target remain refused. Implementation does not grant lane eligibility. Admission requires the existing completed real-turn and binary-identity standard plus actual isolated provider authentication, actor IPC, project I/O, private-state denial and detached-child cleanup on the admitted artifact/target. A missing helper, unavailable namespace, incomplete closure or missing/stale authority fails before provider execution.

## Implementation

We will implement a native Linux namespace backend driven by a worker-owned path-bound launch authority and a verified capsule helper/runtime closure. Shared spawn and independent probes must use that context; provider auth preparation exposes only the selected role material. Readiness and admission retain refusal until target-specific qualification passes. Wrapper/FD transport details may change within the constraints; no caller-selected string becomes a filesystem grant.

## Rationale

The measured Linux primitive already satisfies the load-bearing native read, normal child-stream, local relay and detached-child controls. Its empty filesystem avoids an enumerated blacklist of sensitive directories. Token experiments have not established equivalent Windows runtime behavior, so platform-specific implementation and proof gates preserve truthful eligibility without introducing unsupported deployment machinery.

## Consequences

Linux gains an implementable backend while unsupported targets retain an explicit availability restriction. Capsule assembly acquires a helper/runtime-closure responsibility and namespace availability becomes a readiness prerequisite. Synthetic auth/runtime proof is insufficient for rollout; real model work remains required. Reconsider platform support only after equivalent end-to-end proof. Authorization basis: the user requested all remaining known security issues and repeatedly instructed continuing to build the missing native isolation capability; the approved plan already includes evidence-led backend selection and integration.
