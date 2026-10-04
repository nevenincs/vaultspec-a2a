---
tags:
  - '#audit'
  - '#desktop-native-isolation'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:f1f907159e58dbf7c4aeb38e34acf37b36192da2cff9f125bec3e62a953af59a'
related:
  - "[[2026-10-04-desktop-native-isolation-plan]]"
  - "[[2026-10-04-workspace-root-authority-audit]]"
---

# `desktop-native-isolation` audit: `implementation and OS proof`

## Scope

Build the missing desktop OS isolation capability under the accepted execution refusal. This audit records every source-backed integration issue and each implementation review. It does not treat native launch or handshake as completed-turn certification.

## Findings

### DNI-001 - Codex refresh provenance crosses the child authority boundary

High | security / confused deputy | open; S01.

`providers/_codex_auth.py:_write_seed` stores the source path in the writable run home; `_read_seed` trusts it and `write_back_refreshed_credential` uses it for a privileged atomic write. An agent able to write its run home can forge the refresh destination. Hold provenance in worker memory and confine the returned auth-file read; preserve rotation and concurrent refresh ordering. Source-backed finding from the independent read-only investigation; reproduction pending. Current armed desktop refusal blocks native exploitation but does not repair unarmed execution or future sandbox integration.

### DNI-002 - Default MCP probes inherit infrastructure environment

Medium | security / credential disclosure | open; S02.

`providers/_mcp_contract.py:_probe_environment` copies ambient environment for `env=None` and filters launch search variables, but not service credential families. A declared MCP child can receive control-plane values directly. Filter at the shared probe boundary and verify using a real MCP process. Current provider callers pass scrubbed environment; direct callers can omit it.

### DNI-003 - Native backend is an unbuilt certification prerequisite

High | security / execution availability | open; S03-S05.

Armed desktop execution remains refused by `control/provider_execution.py`. Windows synthetic restricted-token launches still exit `0xc0000142`, including the legitimate exit control; an original-token control succeeds and can read the synthetic private credential and write its project. Therefore the restricted-token spike is unproven. Linux `bwrap` can create user and PID namespaces on the available WSL Ubuntu host; selective mount, runtime, auth, IPC, descendants and completed-turn proofs remain pending. These results are primitive research, not eligibility evidence.

### S01 credential-return review | medium | accepted state-home aliases

Compatibility / availability; corrected, verification in progress. The fresh read-only candidate review reproduced seeding refusal beneath a Windows junction ancestor although the run directory itself was real and the state layout accepted that path. Initial confined traversal used an absolute spelling without canonicalizing its trusted root. The worker now records the canonical run directory separately from its stable cleanup lookup key; confined I/O checks that directory's original filesystem identity. A real junction/symlink test exercises refresh through an accepted alias. Returned-root replacement still refuses. Review found no surviving source-destination redirection route. Parent review additionally bounded returned credential size, JSON structure and parser failure handling; tests exercise hardlinks, substituted roots, oversized and invalid/deep JSON, retained-home authority release, ordering and real process locking.

### S01 Linux verification | low | inherited checkout configuration blocks two MCP-dependent controls

Verification environment; open until rerun. The mounted Windows checkout's local Vaultspec environment cannot satisfy POSIX owner-only mode checks, so two real MCP-dependent config-home tests failed before their expected provider-failure trigger. The same run passed 93 tests, including all credential-return security controls. Rerun those two from an isolated Linux working directory while importing the same repository source and locked environment; no source suppression, skip or permissions weakening.

### S03 primitive evidence | high | AppContainer has working read/write separation

Implementation prerequisite; open, primitive proof only. A uniquely created Windows AppContainer profile, explicitly removed after the synthetic children settled, completed the legitimate exit control (7), denied the private credential read (1), and wrote the permitted project file (0). The preceding restricted-token controls still failed DLL initialization. Node runtime, descendant, network/IPC, runtime closure and completed-provider-turn evidence remain required before implementation can reopen admission. Disposable helper files are in plugin-managed temporary storage; research does not grant execution eligibility.

### S01 final review | low | credential-return boundary verified

Resolved DNI-001 and the candidate's medium alias regression. Four baseline security cases reproduced the vulnerable behavior: forged seeded provenance, forged unseeded provenance, hardlinked returned auth and arbitrary UTF-8 overwrite. The final implementation ignores child seed files and holds the source, canonical home and filesystem identity in worker memory. Returned credentials use the shared no-follow, regular/single-link descriptor boundary, a 1 MiB limit and JSON-object validation. Cleanup releases refresh authority, including retained homes. The actual alias control and substituted-root denial both pass.

Windows evidence: the config-home/egress suite passed 91 tests before the final alias correction; final credential/filesystem-authority/callback ownership suite passed 62 tests. Desktop workspace and project confinement controls passed 49 tests, with one existing Linux-only skip and two POSIX race cases deselected for the Windows run. Lint, format, strict Basedpyright and Ty Windows/Linux/macOS checks passed on the four changed files. The same Linux source passed 93 tests initially, with two MCP-dependent controls blocked by mounted-checkout mode policy; those two then passed from an isolated Linux cwd. A consolidated Linux run is pending. No scan status or desktop native eligibility was changed.

Compatibility consequence: refresh provenance is intentionally process-bound; a fresh worker cannot acquire publication authority from a retained or abandoned child directory. Existing orphan sweeping did not perform refresh writeback, so crash recovery is still a separate prerequisite if the product later promises recovery of rotated credentials after an ungraceful worker loss. Low / operational recovery; deferred to an explicitly protected parent-owned recovery design, not child metadata.

### S01 checkpoint review | low | consolidated verification passed

PASS for the implemented credential-return Step. The consolidated Linux credential, config-home and callback ownership suite passed 95 tests from an isolated cwd with the same repository source and locked environment; the preceding mounted-checkout environmental finding is resolved. Windows final controls passed 62 tests and the final alias correction passed junction coverage. Formatting, lint, Ty for Windows/Linux/macOS, strict Basedpyright and diff whitespace checks passed. The candidate's medium alias regression is resolved; no open critical/high issue remains in S01. OS primitive research and its unresolved runtime/IPC controls remain S03 work and grant no eligibility.

### S02 final review | medium | MCP environment credential transfer closed

Security / credential disclosure; resolved DNI-002. The shared MCP probe boundary now scrubs both ambient and explicit environments using the provider environment policy, with case-insensitive matching for service/database aliases. A fresh interpreter launches the genuine production RAG MCP command, observes only presence of synthetic credential names, and completes initialization/tool discovery. Both environment modes exclude every tested control-plane spelling and preserve a declared ordinary option. The exported pre-change production module completed the same real handshake while inheriting all seven supplied infrastructure spellings; its security assertion failed, establishing the baseline without changing live source.

PASS for S02. Windows focused security tests passed 3 tests; nearest environment, MCP composition, egress and contract suites passed 111 tests with one existing selection exclusion. Linux focused security/environment tests passed 5 tests from the isolated cwd and locked environment. Formatting, lint, strict Basedpyright and Ty Windows/Linux/macOS checks passed on the three edited files; diff whitespace passed. The fresh read-only candidate reviewer checked SDK default merging, direct callers, auth reinjection, cache and retry paths and found no concrete surviving bypass or regression. Parent review confirmed snapshots leave the caller's authenticated environment intact. Initial new test runs exposed invalid synthetic parent settings and nested Windows path escaping; the fixtures were corrected without settings overrides, source bypasses, skips or mocks.

### S03 native runtime evidence | high | Windows named-pipe compatibility remains open

Implementation prerequisite; open DNI-003, S03-S05. Correcting restricted-token object default permissions allows the low-integrity process to run genuine Node v26.10.0, deny a private synthetic credential read with EPERM, write its selected project and reach a synthetic HTTP relay on loopback (200). Node descendants using inherited/ignored streams exit as requested (13), and a CMD descendant exits 17. Node's normal piped descendant launch still fails EPERM; widening the token default DACL and dropping its OWNER_RIGHTS entry do not resolve it. Separate AppContainer controls achieved basic CMD read/write separation but genuine Node initialization still failed. Neither candidate qualifies native production or restores desktop admission. Managed disposable probes modify only their unique synthetic files/profiles and remove their resources after children settle; no operator credential or existing path ACL is modified.

## Review trail

2026-10-04: independent pre-patch investigation traced shared native spawn, the separate MCP SDK launch, auth copy/refresh, actor relay and retained-handle process ownership. No agent edits or duplicated tests. Semantic discovery returned `index_unverifiable`; the named daemon status confirmed failed indexing, so named-module source inspection was used. Existing workspace callback and execution-refusal remediation remain governed by their completed plan.

## Recommendations

Complete S03 OS/runtime proof and record backend authority before S04 integration. Keep armed desktop refusal until S05 proves each admitted target and binary through actual provider work, authentication, actor IPC, project I/O and descendant cleanup. Maintain the process-bound credential return boundary; any later crash-recovery promise requires protected worker-owned provenance rather than a writable child-home seed file.
