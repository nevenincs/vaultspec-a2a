---
tags:
  - '#adr'
  - '#codebase-remediation'
date: '2026-10-07'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:c063081a552262d6c59e93056ed45bad7f8fc32c74cd98934477782e38955279'
related:
  - "[[2026-10-06-codebase-remediation-audit]]"
  - "[[2026-02-26-process-and-workspace-management-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-10-04-engine-discovery-security-adr]]"
  - "[[2026-07-15-dev-process-registry-adr]]"
  - "[[2026-07-24-codebase-health-adr]]"
  - "[[2026-09-05-codebase-health-process-resource-lifetimes-audit]]"
  - '[[2026-07-19-codebase-health-adr]]'
  - '[[2026-03-04-worker-process-architecture-adr]]'
---

# `codebase-remediation` adr: `one process-introspection backend, one contained spawn, ownership before credential` | (**status:** `accepted`)

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

## Problem Statement

Code paths are under `src/vaultspec_a2a/`.

Host process control is implemented several times, with divergent safety (R7-F1, R7-F2, R7-F3 in `2026-10-06-codebase-remediation-audit`):

- **Two introspection backends.** Hand-rolled `/proc`, `ps`, Toolhelp, TCP-table, `netstat` and `lsof` parsers (`utils/_process_tree.py:109-318,356-771`, `utils/process.py:74-169`, `lifecycle/singleton.py:161-224`) sit beside psutil. psutil is a locked base dependency (`pyproject.toml:39`) already used at `control/_worker_process_stop.py:9-121`, `control/worker_management.py:484-491` and `testing/children.py:85-97`.
- **Four spawn-into-containment protocols.** Providers and the test runner create the root suspended and assign the retained handle (`providers/_subprocess.py:299-351`, `testing/runner.py:236-260`). The worker is spawned running and assigned afterwards (`control/worker_management.py:160-168`, `control/_worker_readiness.py:82-87`). The engine wrapper assigns by pid and only logs a failure (`lifecycle/engine_serve.py:208-217`).
- **Three tree-kill strategies.** Containment (`utils/process.py:545-594`), taskkill or a parent-map snapshot (`utils/_process_tree.py:829-862`), and psutil suspend-and-signal (`control/_worker_process_stop.py:54-121,161-178`).
- **Credential to an unknown listener.** The gateway sends its worker IPC bearer to whatever holds the worker port: pre-spawn occupant probes (`control/_worker_health.py:428,585,629`), readiness after a bare TCP connect (`control/_worker_readiness.py:130-132`), and eviction (`control/_worker_health.py:553-559`). A test locks the leak in (`control/tests/test_worker_provenance.py:222-296`). The lifecycle manager already forbids exactly this (`lifecycle/manager.py:800-804`).

The only process-management record, `2026-02-26-process-and-workspace-management-adr`, is proposed. It prefers builtins and rejects Job Objects, which the code ships. The backend choice fixes a dependency strategy, and the credential rule changes which listeners the gateway will talk to, so both need a decision.

## Considerations

- psutil 7.2.2 is locked with abi3 wheels for all five desktop targets (`uv.lock:1953-1954`). It adds nothing to the desktop closure of `2026-07-18-desktop-product-profile-adr`.
- psutil has no Job Object or process-group containment API. Containment lives in `utils/process.ProcessContainment`, whose contract already requires suspended creation where containment must precede the first instruction (`utils/process.py:244-267`).
- `2026-09-05-codebase-health-process-resource-lifetimes-audit` (`exact-popen-cleanup-scans-host`) removed psutil from provider cleanup, because `children(recursive=True)` builds a machine-wide parent map. The current ancestry walk builds one too (`utils/_process_tree.py:377-405`).
- psutil `Process.children()` rejects a reused parent pid by comparing creation times (psutil 7.2.2 `psutil/__init__.py:977-991`). The hand-rolled ancestry walk has no such guard (`utils/_process_tree.py:377-398`).
- The public psutil `create_time()` is wall-clock based on Linux and macOS (psutil 7.2.2 `psutil/_pslinux.py:1849-1863`, `psutil/_psosx.py:475-479`). The recorded start fingerprints are clock-independent kernel values (`lifecycle/singleton.py:179-223`) and persist in the singleton and discovery records (`lifecycle/singleton.py:231-252`, `lifecycle/discovery.py:930`).
- System-wide `psutil.net_connections()` needs root on macOS. A per-process query over our own tree avoids that table; whether it needs elevation on each OS is probe P19 in `2026-10-06-codebase-remediation-audit`.
- `2026-10-04-engine-discovery-security-adr` already rules that no bearer reaches a listener before it proves itself; for an independently owned producer the proof is a fresh challenge.
- `2026-07-15-dev-process-registry-adr` binds detached registry processes to the taskkill tree-kill discipline.
- `2026-07-24-codebase-health-adr` makes the pairing verdict the armed adoption authority and keeps unarmed behaviour unchanged.

## Considered options

- **psutil as the one introspection backend (chosen).** One API replaces the per-OS parsers and the duplicate `/proc/<pid>/stat` readers, adds a pid-reuse guard to ancestry, and reaches macOS. Cost: a C-extension dependency, already locked and shipped.
- **Hand-rolled only.** Removes psutil from `control/`. Rejected: every per-OS parser stays, the macOS gap stays, and psutil remains locked for the shipped test kit (`testing/children.py:38`).
- **Descendant ownership before any credential (chosen).** The gateway confirms that the listener is a process it spawned before it sends a credential. No protocol, no secret, no worker change.
- **Proof-of-possession challenge before the worker bearer** (R7-F1 option c, the HMAC pattern of `authoring/_connection_proof.py`). Rejected: it needs a second secret handed to the worker and a challenge protocol on both sides, and it proves nothing that ancestry does not already prove for a child process.

## Constraints

- Containment primitives stay in `utils/process`: Job Object creation, handle assignment, suspended-thread resume, Job accounting and membership, and POSIX `killpg`. psutil never replaces them.
- Owned-tree termination never discovers members by parent pid or host scan. It reaps through the containment. Introspection informs liveness and ownership verdicts only.
- A start fingerprint stays clock-independent and comparable across processes and across A2A generations. A recorded fingerprint in an encoding the reader does not produce degrades to pid-liveness. It never reads as a pid-reuse mismatch.
- An ownership verdict that cannot be established is unresolved. Unresolved never authorizes a credential.
- Detached processes launched through `lifecycle/manager.spawn` (the dev-process registry and the `service` verbs) keep the strategy of `2026-07-15-dev-process-registry-adr`.
- **Scope of the credential rule.** It covers every process A2A spawns, including the gateway-owned worker in both profiles. A worker attached with `auto_spawn_worker=False` (Compose or registry-managed) is attached by operator configuration; its trust model is unchanged here.
- **Affected prior rulings.**
  - `2026-02-26-process-and-workspace-management-adr` is rejected.
  - `2026-07-18-desktop-product-profile-adr` "Security, singleton, and discovery" gains the ownership-before-credential amendment.
  - `2026-07-24-codebase-health-adr` Constraint "The unarmed paths must remain byte-for-byte behavior-compatible" is narrowed for the unarmed auto-spawn path only: a non-descendant occupant of the worker port is now a conflict there as well. The armed verdict logic is unchanged.
  - The `2026-07-19-codebase-health-adr` rule that only an owner-authorized desktop auto-spawn gateway may evict its prior worker now holds in code too: the unarmed eviction of a foreign occupant ends.

## Implementation

We will make psutil the single process-introspection backend behind `utils/_process_tree`, start every owned process through one contained-spawn helper, and present no credential to a listener before its ownership is confirmed.

- **One backend.** `utils/_process_tree` is the only module that inspects processes. It exposes liveness and wait-gone in sync and async forms, descendants, start identity, and the listener-ownership verdict, backed by psutil. The hand-rolled liveness, zombie, parent-map and listener-pid parsers and the duplicate `/proc/<pid>/stat` readers are deleted. No other module imports psutil.
  - Hypothesis: POSIX group-membership checks in `ProcessContainment` read processes through this backend.
  - Hypothesis: the start fingerprint comes from psutil where psutil yields a clock-independent value. Where it does not (public `create_time()` on Linux and macOS), one kernel start-time read stays inside `utils/_process_tree`. Either way there is one implementation.
- **One contained spawn.** `utils/process.spawn_contained()` is the only way to start an owned process. It creates the root so that no instruction runs outside containment: on Windows `CREATE_SUSPENDED`, Job assignment through the retained handle, then resume; on POSIX a new session and process group at exec. If admission fails it kills the exact retained root and raises, so no caller ever holds an uncontained owned process. The worker, the engine wrapper, provider roots and the test runner use it; the engine wrapper refuses to run its engine when admission fails. The provider admission pattern (`providers/_subprocess.py:362-418`) moves into it. Its sync and asyncio forms are an implementation detail.
- **One owned-tree kill.** `ProcessContainment.terminate` is the only kill for an owned tree, and repeat calls are idempotent once a containment exists. The psutil suspend-and-signal path, the uncontained worker branches and the per-pid provider fallback (`providers/_subprocess.py:460-465`) are deleted. `kill_pid_tree_async` serves detached processes only.
- **Ownership before credential.** A listener is ours when it is the expected root or one of that root's descendants. The backend reads the TCP listeners of that tree (`Process.net_connections()` over the root and its `children(recursive=True)`), not the host socket table. `classify_listener_ownership` keeps its three verdicts (`utils/_process_tree.py:321-353`) and is the only "is this listener ours" gate.
  - Pre-spawn, the root is the gateway itself. Only a descendant occupant, such as a prior generation it still owns, may receive a credentialed probe and, when the pairing verdict authorizes it, an eviction. A foreign or unresolved occupant is a conflict: no credential, no adoption, no eviction.
  - During readiness, the root is the spawned worker. The credentialed readiness probe runs only after a `CONFIRMED` verdict.
  - The lifecycle manager readiness gate (`lifecycle/manager.py:767-805`) uses the same verdict.
  - The rule does not depend on the backend: it can land on the current verdict before psutil replaces the parsers.
- **macOS.** Behaviour is host-dependent until owner question O9 (is macOS supported) is answered. psutil returns a macOS start time where the current reader returns `None` (`lifecycle/singleton.py:161-176`), but that value is wall-clock adjusted and P19 has not run on macOS. Until both are settled, a macOS fingerprint that is unreadable or unstable stays `None` and degrades to pid-liveness, and an unresolved listener verdict withholds the credential.
- **Proof.** Real-process tests show that a squatter bound to the worker port before first dispatch receives no `Authorization` header and causes a refused spawn, that readiness requires a confirmed verdict, and that a grandchild spawned by a root's first instruction is inside its containment. P19 runs the descendant-listener query on every supported OS before the backend change lands.

## Rationale

psutil wins on duplication. It is already locked and shipped, covers every desktop target, and replaces several per-OS parsers with one API, including the pid-reuse guard the ancestry walk lacks. Containment stays hand-rolled because psutil cannot provide it, and the suspended-spawn protocol is already proven on the provider and runner paths (`2026-09-05-codebase-health-process-resource-lifetimes-audit`). Extending that protocol to the worker and engine removes the timing assumption at `control/_worker_readiness.py:83-87` and the logged-only failure at `lifecycle/engine_serve.py:214-217`.

Descendant ownership wins over proof of possession because the gateway is the worker's parent. Ancestry is a fact the OS already holds, so checking it costs no protocol and no secret, and it refuses any squatter, armed or unarmed, including one that echoes `gateway_url` (`control/_worker_health.py:531,646-656`). Proof of possession stays the rule for independently owned producers, where ancestry proves nothing (`2026-10-04-engine-discovery-security-adr`).

## Consequences

- One introspection module, one spawn helper and one owned-tree kill remain. The parsers, the psutil stop path, the uncontained branches and the forward-only wrappers go (R7-F4, R7-F5, R7-F6).
- The gateway no longer leaks the worker IPC credential to a squatter. An unarmed auto-spawn gateway now refuses a foreign worker-port occupant instead of evicting or adopting it; a stale dev orphan is cleared by the registry `reap` verb.
- A host where psutil cannot read our own descendants' connections cannot confirm ownership, so its gateway cannot start a worker. This fails closed. P19 must pass on each supported OS first.
- psutil `children()` misses a descendant whose intermediate parent has exited; such a listener reads as not ours. This also fails closed.
- Descendant enumeration still builds a machine-wide parent map inside psutil, as the current walk does. That is accepted for ownership verdicts only; the kill path stays on containment.
- The stalled-child reaper in the shipped test kit kills by pid tree (`testing/children.py:189-205`). Its children move onto `spawn_contained`, or it is recorded as a detached-process exception.
- The externally managed attach path still presents the bearer to whatever answers at the configured worker URL. Tightening it is a separate decision.
- Reconsider if psutil drops a supported target, if P19 shows the per-process query needs elevation on a supported OS, or if a supported OS cannot give a clock-independent start identity.
