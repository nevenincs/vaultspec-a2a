---
tags:
  - '#adr'
  - '#desktop-native-isolation'
date: '2026-10-05'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:435bd3659e32cdfe1e312e796ff9c05439255cbe77d9fd57d4f6470f34b7e307'
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

Mount only the lifecycle/worker-selected managed project, one worker-created role auth home, immutable runtime closure and the bounded resolver data described below. Do not infer authority from PWD/HOME/CLI arguments or mount the application home, parent config home, service stores or other role homes. Validate and retain opened filesystem identities through mount acquisition. Runtime helper and mapped runtime dependencies belong to a pinned capsule closure; no ambient helper/tool/package installation fallback at launch. Clear infrastructure credentials before intentional role additions. All native entry points, including MCP/cache/version/catalog/terminal paths, require a valid trusted context and the same boundary.

Keep user/PID/IPC/UTS/cgroup isolation, no-new-privileges, dropped capabilities, new terminal session, private proc/dev/tmp and retained-owner death propagation. Keep host networking only for existing authenticated provider/actor transports and DNS through the host-selected resolver; no host file/socket/handle is granted by it. Runtime is read-only; project and role home are writable. Preserve callback confinement and exact retained-process ownership independently.

Windows, macOS and any unverified Linux target remain refused. Implementation does not grant lane eligibility. Admission requires the existing completed real-turn and binary-identity standard plus actual isolated provider authentication, actor IPC, project I/O, private-state denial and detached-child cleanup on the admitted artifact/target. A missing helper, unavailable namespace, incomplete closure or missing/stale authority fails before provider execution.

The trusted Linux launcher may acquire fixed host /etc/resolv.conf, validate a regular single-link root-owned source through nonfollowing retained descriptors, parse a bounded supported resolver grammar and render a sealed anonymous read-only snapshot at child /etc/resolv.conf. Only finite resolver-specific aliases are supported; shared filesystem confinement remains unchanged. Root-owned sticky /mnt/wsl is permitted solely for the exact /mnt/wsl/resolv.conf alias on the research host, not as a production WSL prerequisite. Refresh the snapshot for each actual launch; no serialized caller source or resolver bytes are accepted. Preserve the selected loopback stub, ordered nameservers and effective supported domain/search/options. Missing, unsafe, changing, malformed or unsupported input refuses; no replacement resolver, host directory/socket mount or unrecognized policy omission is allowed. Reserve the child resolver path against runtime mappings including ancestor/descendant collisions. This authorizes bounded DNS data, not full host NSS/hosts, managed proxies or custom CA parity; those remain explicit qualification gaps.

S18 amendment (2026-10-06, security-cloud-remediation): for the two fixed systemd-resolved aliases `/run/systemd/resolve/stub-resolv.conf` and `/run/systemd/resolve/resolv.conf`, the exact `/run/systemd/resolve` directory and the regular single-link leaf may additionally belong to the local `systemd-resolve` service identity, resolved through the host account database. All preceding directories and the `/etc/resolv.conf` alias remain root-owned. Reject a non-root service identity equal to the calling identity. No other alias gains this exception; retain nonfollowing descriptors, unsafe-mode rejection, bounded parsing, race checks and sealed snapshots. This explicitly narrows the original root-only source requirement for the host-managed resolver service.

## Implementation

We will implement a native Linux namespace backend driven by a worker-owned path-bound launch authority and a verified capsule helper/runtime closure. Shared spawn and independent probes must use that context; provider auth preparation exposes only the selected role material. Readiness and admission retain refusal until target-specific qualification passes. Wrapper/FD transport details may change within the constraints; no caller-selected string becomes a filesystem grant.

S04 refinement: require a static unprivileged ELF helper without interpreter or dynamic segment, so host library resolution cannot precede capsule mounts. Validate that contract before build-time helper version execution. Trusted bootstrap uses its own environment and capsule cwd; role cwd/environment are target data, and source wrapper uses Python isolated mode. Sealed anonymous arguments keep role credentials out of helper argv. These details implement the existing pinned-closure/trusted-context constraints without changing eligibility or deployment prerequisites.

S08 refinement: the reproduced real frozen Node DNS failure requires the bounded resolver exception above. Acquire it inside the trusted launcher after authority/closure validation, without changing path-authority serialization or version-cache identity; close source FDs before helper execution and account for consumption of the sealed data FD. Source and rebuilt artifact DNS-only/system lookups, child lookup and HTTPS controls accompany private-state, immutability and retained-owner controls. The existing all-known-issues/native-backend implementation authorization covers this scoped runtime prerequisite; target admission remains refused through genuine selected OAuth qualification in S09.

S18 amendment evidence and authorization: Full Validation run 37466091654 exposed the normal systemd-resolved service ownership on gw-server-linux-runner. The upstream service declares `User=systemd-resolve` and `RuntimeDirectory=systemd/resolve` (https://raw.githubusercontent.com/systemd/systemd/main/units/systemd-resolved.service.in). The user's explicit instruction to continue until CI root causes are fixed authorizes this bounded compatibility repair. The original root-only wording above records the prior constraint; this dated amendment defines its limited exception. Native admission and provider qualification remain unchanged. Independent review identified and reconciled the decision wording drift in security-cloud-remediation S18.

## Rationale

The measured Linux primitive already satisfies the load-bearing native read, normal child-stream, local relay and detached-child controls. Its empty filesystem avoids an enumerated blacklist of sensitive directories. Token experiments have not established equivalent Windows runtime behavior, so platform-specific implementation and proof gates preserve truthful eligibility without introducing unsupported deployment machinery.

## Consequences

Linux gains an implementable backend while unsupported targets retain an explicit availability restriction. Capsule assembly acquires a helper/runtime-closure responsibility and namespace availability becomes a readiness prerequisite. Synthetic auth/runtime proof is insufficient for rollout; real model work remains required. Reconsider platform support only after equivalent end-to-end proof. Authorization basis: the user requested all remaining known security issues and repeatedly instructed continuing to build the missing native isolation capability; the approved plan already includes evidence-led backend selection and integration.
