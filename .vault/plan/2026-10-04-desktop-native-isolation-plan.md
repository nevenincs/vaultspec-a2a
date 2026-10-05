---
tags:
  - '#plan'
  - '#desktop-native-isolation'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-10-04-workspace-root-authority-desktop-native-admission-adr]]'
  - '[[2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr]]'
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-10-01-provider-binary-policy-adr]]'
  - '[[2026-10-05-desktop-native-isolation-linux-namespace-backend-adr]]'
modified: '2026-10-05'
body_schema: body-v2
body_hash: 'sha256:ffdda64cf7eb9b2c991c133aab513955956260290973e3d6fe2fede921bc20c1'
---

# `desktop-native-isolation` plan

Build and verify the OS boundary required to restore desktop agent execution.

## Description

Approved 2026-10-04

The user requested the remaining known security fixes, then explicitly instructed continuing to build the missing desktop isolation capability. The accepted native-admission decision governs the refusal until OS isolation and completed-turn evidence qualify a target. Managed workspace authority governs grants; desktop product and binary policy govern runtime closure and provider eligibility. S01 and S02 repair concrete credential-transfer paths within these accepted boundaries, without changing admission. S03 gathers actual OS evidence and records the distinct backend decision before S04 executes. Backend implementation details may change in response to proof; no unverified target becomes eligible. Docker is not a production prerequisite under the owner's current native-binary deployment ruling.

## Steps

- [x] `S01` - Keep credential refresh destinations in worker-owned memory and confine returned credential reads; `src/vaultspec_a2a/providers/_codex_auth.py, _codex_config_home.py, providers/tests/test_codex_credential_writeback.py, desktop/_filesystem_authority.py and rolling isolation audit`.
- [x] `S02` - Scrub control-plane credentials at the independent MCP probe boundary; `src/vaultspec_a2a/providers/_mcp_contract.py, workspace/environment.py as needed, real MCP security tests and rolling isolation audit`.
- [x] `S03` - Prove viable native OS primitives and settle backend authority before integration; `bounded synthetic Windows/Linux experiments, new isolation research and backend ADR, exact runtime/auth/IPC compatibility`.
- [x] `S04` - Implement and verify the Linux backend, path-bound authority and build-owned runtime closure; `desktop/native_isolation.py, desktop/_linux_launcher.py, desktop/_linux_helper.py, desktop/_linux_runtime_assets.py, desktop/tests/test_native_isolation.py, utils/runtime_exec.py and its real execution tests, shared infrastructure environment filtering and rolling isolation audit`.
- [x] `S05` - Carry explicit Linux launch authority through shared native execution and independent probes; `shared provider launch transport, independent MCP/version probe context and cache binding, session-owned terminal authority, focused real process/protocol tests. Desktop eligibility remains refused`.
- [x] `S06` - Prepare worker-owned role authority and carry it through provider model and catalog callers; `native workspace capture after worker composition, selected-channel ACP home preparation and cleanup, existing Codex home ownership, model/catalog/version context, real lifecycle tests. Unsupported or unqualified stores and targets retain refusal`.
- [x] `S07` - Package and verify the qualified Linux runtime closure; `declared helper and dependency inputs, frozen launcher dispatch and build assets, release assembly and real artifact controls. No runtime package acquisition or unproved eligibility`.
- [x] `S08` - Supply bounded trusted Linux resolver runtime data and verify the legitimate network control; `Linux backend authority and sealed runtime-data descriptors, resolver-source trust and parsing, scoped backend ADR refinement, source and real frozen DNS/private-state controls, no all-/etc grant or CI resolver fallback`.
- [x] `S09` - Package the required certificate trust data and verify genuine native provider work; `scripts/build_linux_isolation.py, pinned dependency certificate bundle and artifact data manifest, source and actual frozen Codex account/turn controls, certificate immutability/private-state controls, packaging documentation and integrated audit`.
- [x] `S10` - Join provider and role cleanup when a live stream closes; `providers/_stream_lifetime.py, codex_chat_model.py and acp_chat_model.py, explicit genuine native provider lifecycle controls, completed streams and early-close cancellation interruption concurrent callback and beta event paths, frozen launcher reaping, rolling review and findings queue`.
- [ ] `S11` - Make ACP authentication and failed-refresh health reflect independent provider evidence; `provider-owned no-prompt selected-login verifier and its factory composition, ACP catalog success authentication, provider catalog health/cache transitions, actual positive invalid absent and default-store compatibility controls, rolling audit`.
- [ ] `S12` - Complete target qualification and restore only verified desktop eligibility; `control/provider_execution.py, provider readiness and binary proof, desktop admission and health, actual Linux artifact provider turns using existing selected Windows logins, actor IPC, full frozen worker integration, unsupported-target refusal, consumer adoption evidence, docs and integrated audit`.

## Parallelization

Execute Steps sequentially. Use read-only security investigation and candidate review as required by the remediation skill. Shared runtime, authentication, admission and Vault records have one write owner in this workstream; preserve concurrent repository work.

## Verification

Use real files, OS processes and protocol transports. Credential refresh must return only to its worker-selected source, preserve newest-refresh ordering and process locking, and refuse redirected or multiply linked returned credentials. MCP probes must not inherit gateway, worker, lifecycle or database credentials. A backend requires an actual project read/write control, absolute-path private-state denial, descendant containment and cleanup, provider authentication, actor IPC and a completed real provider turn on each admitted target and binary identity. Unsupported or unproved targets retain the execution refusal. Run focused tests and the repository's lint, formatting and type checks; review each implemented pass, classify every finding and append it to the rolling audit before closing and committing its Step. Plan completion requires all Steps closed and integrated review passing.
