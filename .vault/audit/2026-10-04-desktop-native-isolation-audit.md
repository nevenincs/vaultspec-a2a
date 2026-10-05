---
tags:
  - '#audit'
  - '#desktop-native-isolation'
date: '2026-10-04'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:495efbe6e44e8a7c8e1c50d4427eec4d69a18e59005262f9c96d21cc209123f6'
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

### S03 research review | low | Linux primitive evidence supports bounded backend implementation

PASS for the Linux implementation prerequisite; this is not native/provider eligibility. The managed selective-mount probe and retained actual output prove synthetic private absolute/symlink/host-proc denial, selected role-home read, project write, read-only runtime, normal piped Node child exit 13, loopback HTTP 200 and removal of detached setsid descendants after the retained sandbox owner is killed. Runtime versions and persistent artifact locators are recorded in `2026-10-04-desktop-native-isolation-native-backend-primitives-research`. Review confirms no whole-host or application-home bind, private host process namespace is absent, and the evidence does not claim real provider auth/turn or a shipped runtime closure.

Low / verification coverage; open S04-S05: production needs descriptor-bound mount acquisition, capsule-owned helper/dependencies, all launch entry points and actual lane/target proof. Linux dependency discovery via ldd is research setup only and must not become runtime authority. Windows restricted-token pipes fail at both low and medium integrity; AppContainer also requires compatible LOCAL pipe naming and loopback transport. Windows/macOS remain refused. The distinct backend ADR was compared once against current accepted coverage; returned refinement/shared-artifact links preserve the native-admission and binary-proof rulings. Input truncation limits automated comparison, so scoped source/decision reading remains authoritative. No older ruling is superseded: the new decision authorizes implementation while conditional refusal remains binding.

### S04 candidate review | high | trusted bootstrap separation corrected

Security / pre-isolation execution; resolved DNI-004. The draft argv-only launcher inherited role cwd/environment. An actual disposable regression showed a project sitecustomize hook reading a synthetic private sentinel before isolation while the provider never started. The launch API now returns command, clean bootstrap environment and trusted capsule cwd together; source execution uses isolated Python mode. Bounded opaque role environment is applied through sealed anonymous helper arguments. A real compiled preload constructor runs inside the namespace and observes denial; the project Python startup hook never runs in the wrapper. Large ordinary options remain intact. NULs, invalid names, duplicate fields and oversized packets fail explicitly. Persistent baseline: artifacts/desktop-native-isolation/linux-bootstrap-baseline.py, SHA256 89532b4742cc818ae16271d59054c75fed66a268be888ce7c2201d536a13c7d2.

### S04 candidate review | high | encoded authority canonicalization corrected

Security / path validation; resolved DNI-005. Decoded absolute root paths could contain parent traversal while passing lexical managed-root and filesystem identity checks. Decoded roots now must equal existing canonical paths before constructing authority. A real sibling private directory with its actual identity is rejected through a managed-prefix parent traversal. Valid selected project/home round trips and stale-directory refusal remain supported.

### S04 candidate review | medium | helper bootstrap closure corrected

Portability / runtime closure; resolved DNI-006. Read-only inspection confirmed the initial ELF helper used host interpreter/libraries before namespace mounts existed. Build assembly and runtime enforce a static ELF with no interpreter or dynamic segment, validate unprivileged regular inputs before version execution and attest opened helper bytes. Genuine pinned upstream bubblewrap 0.11.1 was compiled statically with libcap in a temporary build tree; actual namespace controls pass. The dynamic system helper is refused before staging. Producer and exact input/helper hashes are recorded in the research trail. Release packaging remains S05; the test artifact is not a shipped capsule.

### S04 review | low | foundation verified, production qualification remains open

Verification / implementation prerequisite; open DNI-003 in S05-S06. Linux foundation/environment/runtime dispatch suites pass 18 real tests with the selected static helper; the added retained-owner/detached-descendant control is recorded in final verification. Private absolute/symlink/host-proc reads fail, no directory grants leak, project writes and selected synthetic auth work, runtime is read-only, piped child exits 13 and relay HTTP returns 200. Windows nearest suites pass 28 tests covering authority/parsers, unsupported platforms, native refusal, normal runtime/environment and genuine MCP credential filtering. Windows is not a backend proof. One fresh candidate review surfaced the three confirmed issues above, now corrected. Its initial finalization failed at the security service; a defensive read-only continuation completed without payloads, edits or duplicate tests. Locked standalone CPython lacks memfd/seal wrappers; typed libc ABI calls perform the actual sealed descriptor operation. No production caller or eligibility is introduced. Closed admission remains binding.

### S04 final verification | low | retained-owner cleanup proven

PASS for S04 foundation. Final Linux native suite passes 9 tests, including the actual production launch wrapper and a Node child that creates a detached descendant. The test identifies that descendant by its unique control argv and retained /proc identity, kills only the exact owned sandbox process and observes descendant termination. This extends the earlier 18-test combined foundation/environment/dispatch run; no source changes were made to the previously passing ordinary environment or dispatch paths. Windows nearest suites pass 28 tests; the new portable unsupported-platform case is checked separately. Ruff lint/format, strict Basedpyright, Ty Windows/Linux/macOS, diff whitespace and feature Vault checks pass. All three candidate findings are resolved and recorded; release closure assembly, all child entry points and real authenticated provider-turn qualification remain open S05-S06. No eligibility is restored.

### S05 candidate review | low | isolated MCP transport control required

Verification / coverage; pending DNI-007 in S05. Fresh read-only candidate review found no concrete surviving carrier, authority, cache, callback or lifetime defect. It correctly observed that cached unisolated MCP plus armed refusal did not prove an isolated MCP handshake. MCP SDK 2.2.0 merges trusted host default HOME/LOGNAME/PATH/SHELL/TERM/USER into the supplied wrapper environment and forwards cwd. Isolated Python startup and the helper's clean exec environment prevent role startup hooks, but actual production MCP transport evidence is required. The executor is assembling the genuine registry-selected vaultspec-rag Python runtime into a test capsule; this remains build-time test setup and must not become runtime package acquisition.

### S06 preparation research | high | Claude credential and managed-policy contract needs bounded refinement

Implementation prerequisite / decision coverage; open DNI-008 in S06-S07. Accepted default Claude auth resolves the selected operator subscription login and injects no newly selected credential; only declared oauth_token mode allows settings-token injection. Existing strict MCP/settings policy suppresses user/project/local sources while preserving host organisation-managed policy. A new scoped home must not silently change login identity, re-enable suppressed settings, discard managed policy or claim keychain/file-store parity. Codex already has worker-owned source-bound auth copy/refresh; Claude has no equivalent proved lifecycle. Record a desktop-only bounded identity-preserving preparation contract and supported-store proof before implementing that path. Unsupported stores and unqualified lanes remain refused.

Plan sequencing refinement: S05 now isolates shared launch transport and probes; S06 owns worker/model/catalog context issuance, role preparation and release closure; S07 owns final real-turn/artifact qualification. The existing approved scope is split for reviewable checkpoints; earlier audit references to S05-S06 qualification now continue through S07.

### S05 final review | low | shared launch authority and genuine MCP transport verified

PASS for S05; verification coverage DNI-007 resolved. Shared provider acquisition carries command, bootstrap environment and trusted cwd together, retains authority on the actual admitted session process and forwards it to terminal descendants. Independent MCP and version probes validate explicit root identity before cached proof. Armed desktop refusal remains first and unconditional. Final Linux context suite passes 5 real tests, including genuine production vaultspec-rag initialize/list-tools through the MCP SDK, project-terminal write/private-state denial and stale-directory refusal after a cached surface. Test assembly copies the actual registry-selected production Python distribution; it neither supplies a fake server nor downloads packages during a child launch. Windows context suite passes 5, nearest MCP/callback/resource suites pass 71 and nearest binary/refusal/terminal/subprocess suites pass 21 with one existing service test deselected; that service coverage was run explicitly, 6 passing real process/Job containment tests. Earlier Linux nearest binary and cached-MCP checks pass 7 including the then-current 3 context tests. Final Ruff lint/format, strict Basedpyright and Ty Windows/Linux/macOS pass for all 9 owned source files. Parent review of the final diff and test-producer correction confirms the fresh candidate's covered launch/cache/callback invariants; no surviving concrete bypass or regression was reported.

Low / test-producer correctness; resolved DNI-009. Initial isolated MCP assembly redundantly mapped capsule-contained dependencies, including lexical parent traversals emitted by ldd. Production canonical/protected-target checks correctly refused before launch. Test assembly now normalizes external target paths and leaves already-copied internal libraries in the read-only capsule. The same genuine handshake passes without weakening runtime validation. Build-time dependency inspection remains test setup, never launch authority.

High / implementation prerequisite; DNI-008 remains open S06-S07. Production worker issuance, credential-home identity/policy preservation, release assets and actual provider-turn qualification are not complete. No served eligibility or admission is restored.

### S06 candidate review | medium | role-home cleanup ordering corrected

Lifecycle / process containment; resolved DNI-010. The fresh read-only reviewer found that an async-generator forwarding wrapper could leave its inner ACP session suspended when a consumer closes a stream. Removing the surrounding role home then precedes the provider's reap. All three yielding wrappers now explicitly close their inner generators through aclosing: _astream, _stream_request and _astream_session. Prepared session cleanup completes before private grant release and home cleanup; asynchronous home removal is joined through complete_cleanup. Parent review of the actual final forwarding chain confirms the correction. The startup-refusal controls drive both real model implementations and verify no new home survives. Authenticated streaming, early-close and repeated-cancellation qualification remain S08 evidence requirements; source review is not a claim that those provider controls have run.

### S06 parent review | medium | constructor and catalog version probes lacked prepared context

Integration / availability; resolved DNI-011. Model construction and catalog version callbacks initially carried a workspace but had no role-home grant, so future isolated version acquisition would still refuse missing authority. Factory proof now prepares an empty worker-owned version-probe home from the admitted project, carries explicit native authority and removes that home afterward. A genuine static helper --version control returns 0.11.1 through isolation; the home is empty before execution and absent afterward. Missing/stale workspace and unsupported platform paths retain typed refusal. Unarmed factory proof preserves its original one-argument callback contract.

### S06 verification correction | low | direct settings mutation omitted state seating

Test setup / resolved DNI-012. The first startup-cleanup control changed desktop_app_home directly on the existing singleton without changing a2a_home. The sanctioned settings_override deliberately bypasses Settings construction, while production's _seat_desktop_profile validator seats a2a_home beneath the declared app home. Existing real child-construction coverage proves that validator behavior. Native for_home correctly refused the mismatched Codex home before child acquisition and cleanup removed it. The test now supplies the full seated profile instead of accepting that ValueError or weakening authority validation. Linux final role/foundation population passes 13 tests; Windows role/model-selection/MCP population passes 36. Initial four existing monkeypatched proof tests failed because an optional None keyword changed their callback shape; unarmed proof keeps the established call contract and final proof/catalog population passes 26, with five existing live selections deselected. No new mock, fake provider/server or skip was introduced.

### S06 final review | low | worker-bound role preparation verified within declared channels

PASS for S06. Worker composition now captures immutable app/runtime/project identities on an invocation copy before runtime-identity binding. Model, catalog, terminal, MCP and version paths carry the selected role's context; adding a home does not recapture a replaced project. Grants remain private model attributes and are absent from serialization. ACP prepares a fresh home only for the already selected Claude OAuth export or Z.ai token channel; the default subscription file store and other providers remain unqualified and refused. Existing Codex source-bound auth preparation and refresh return are preserved. Claude managed-policy directory presence, including redirected or unreadable presence, refuses rather than dropping host-managed policy. Windows/macOS role preparation remains refused.

Verification: final Linux 13 real role/foundation tests pass, Windows 36 role/model/MCP tests pass, proof/catalog 26 pass with five existing live tests deselected, final Ruff lint/format, strict Basedpyright and Ty Windows/Linux/macOS pass for all nine owned files, and whitespace passes. Earlier nearest Windows home/desktop coverage passed 49 tests after async cleanup changes. A fresh candidate review plus parent review of its corrective final diff found no surviving concrete filesystem bypass in the S06 implementation. Genuine authenticated model/catalog turns are not claimed.

Low / operational recovery; open DNI-013. Abrupt worker loss can leave the new vaultspec-native-home prefix beneath accounted app-state tmp/homes. Normal error/cancellation cleanup owns removal. Do not reuse the existing age-only orphan sweep for live native homes; lifecycle recovery with actual ownership evidence is follow-up work, and no rotated credential recovery is promised. The accepted default subscription file-store, host-managed policy preservation, release closure and real turn qualification remain high implementation prerequisite DNI-008, owned by S07-S08.

Plan sequencing correction: S06 owns worker/model/catalog/version context and selected-channel role preparation; S07 now owns release runtime closure assembly and actual frozen artifact controls; S08 owns authenticated target/lane qualification and any eligibility restoration. The approved scope has eight sequential checkpoints. Earlier S06-S07 qualification references continue through S08; no eligibility changed.

## Review trail

2026-10-04: independent pre-patch investigation traced shared native spawn, the separate MCP SDK launch, auth copy/refresh, actor relay and retained-handle process ownership. No agent edits or duplicated tests. Semantic discovery returned `index_unverifiable`; the named daemon status confirmed failed indexing, so named-module source inspection was used. Existing workspace callback and execution-refusal remediation remain governed by their completed plan.

## Recommendations

Complete S03 OS/runtime proof and record backend authority before S04 integration. Keep armed desktop refusal until S05 proves each admitted target and binary through actual provider work, authentication, actor IPC, project I/O and descendant cleanup. Maintain the process-bound credential return boundary; any later crash-recovery promise requires protected worker-owned provenance rather than a writable child-home seed file.
