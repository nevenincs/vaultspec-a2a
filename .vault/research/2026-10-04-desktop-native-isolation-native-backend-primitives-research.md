---
tags:
  - '#research'
  - '#desktop-native-isolation'
date: '2026-10-04'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:5936e8e110772f420849063d1184eb5bd9d17f380c386ba559d00d068a5df3a2'
related:
  - "[[2026-10-04-desktop-native-isolation-plan]]"
  - "[[2026-10-04-desktop-native-isolation-audit]]"
  - "[[2026-10-04-workspace-root-authority-desktop-native-admission-adr]]"
  - "[[2026-10-04-container-release-native-production-adr]]"
---

# `desktop-native-isolation` research: `native backend primitives`

Which native OS boundary can restore desktop provider work while withholding lifecycle credentials and service state? Linux selective namespaces support the measured runtime, filesystem, relay and detached-child controls. Windows restricted tokens separate owner-only files but conflict with unmodified Node's normal pipe creation; AppContainer runtime qualification is still being measured. No primitive result qualifies a production lane or changes the accepted execution refusal.

## Findings

### Linux selective mounts and PID namespaces satisfy the measured primitive controls

The available Ubuntu WSL host uses kernel 6.18.40.1-microsoft-standard-WSL2, bubblewrap 0.11.1, Node v22.23.1 and CPython 3.14.4. The retained helper constructs an empty mount namespace, binds only the synthetic project and run home writable, and binds the actual executable, shared-library dependencies and standard library read-only. It creates user/PID/IPC/UTS/cgroup namespaces, disables further user namespaces, drops capabilities, creates isolated proc/dev/tmp, starts a new session, keeps host networking for the role relay, and enables parent-death termination.

Measured results: private absolute path, a project symlink to that path and a host process-root path all fail ENOENT; selected synthetic provider auth is readable; project writes succeed; normal piped Node descendant exits 13; runtime overwrite fails EROFS; loopback HTTP returns 200. Killing the actual retained sandbox owner removes the measured descendants, including one that calls setsid. This is runtime/primitive evidence using synthetic credentials, not genuine provider authentication or a completed model turn. Production integration must replace host-discovered research dependencies with a verified capsule closure and bind mount grants to opened identities. Sources: target-bound persistent `artifacts/desktop-native-isolation/linux-native-mount-probe.py` (SHA256 `05d3d3f39b67f167b14ca7d4ab98305d93ba54b1ddb1379960253b6795dbfe8a`) and `artifacts/desktop-native-isolation/linux-native-mount-probe.log` (`306b765370ecfc82934f7cfe2391eaee8709b4d123b59d7bb8d1ce6a92d82511`). Bubblewrap explicitly delegates sandbox policy to the caller: https://github.com/containers/bubblewrap/blob/main/README.md. Namespace lifecycle grounding: https://man7.org/linux/man-pages/man7/pid_namespaces.7.html.

### Windows restricted-token read separation conflicts with native pipe defaults

A low-integrity primary token with a random restricting capability and deny-only Administrators initially failed legitimate DLL initialization. Narrowing its object default permissions to usable child-owned objects corrected that failure. Genuine Node v26.10.0 then denies owner-only synthetic credentials, writes the scoped project, reaches loopback HTTP, and creates descendants with ignored/inherited streams. Normal piped descendants fail EPERM. Removing OWNER_RIGHTS or adding Everyone to TokenDefaultDacl did not resolve the failure. The independent native probe also reproduces it at medium integrity, so low integrity alone is not its cause.

The installed libuv 1.52.1 pipe path requests write/write-attribute/WRITE_DAC access to both pipe ends. Windows creates a special default named-pipe descriptor for a NULL descriptor; the restricted access check cannot acquire those requested rights through its restricting SIDs. An explicit synthetic per-run pipe descriptor works, but no repository-native mechanism yet makes stock Node and all other descendants use it. Adding the operator's user SID to the restricting set would restore owner-private reads and is not an acceptable fix. WRITE_RESTRICTED does not provide the required read boundary. Sources: independent native probe findings in the rolling audit; https://github.com/libuv/libuv/blob/v1.52.1/src/win/pipe.c; https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights; https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken.

### AppContainer remains a runtime candidate, not an admission basis

### AppContainer needs compatible pipe naming and a working local relay

The independent follow-up on Windows build 26200 uses genuine Node v26.10.0/libuv 1.52.1. A private low windowstation/desktop plus the supported preserve-symlinks flags lets Node load the synthetic script, deny the private read, write the project and create an ignored-stdio child (13). Without the private desktop the Node control still exits 0xc0000142. Default piped child creation hangs beyond its five-second timeout and the outer owner terminates it at ten seconds. Native AppContainer pipe creation using the installed libuv's non-LOCAL spelling fails error 5; LOCAL and LOCAL/uv spellings pass the same access masks. The source's collision retry on access-denied supports the inferred hang cause; no debugger stack was collected. Loopback HTTP returns ETIMEDOUT.

Upstream libuv commit `2cadaa40167050baf7c6905ac897e6fb57afb2c6` (2026-07-13, PR 5181) adds AppContainer detection and the LOCAL prefix. A runtime containing that correction has not been qualified here, and it does not establish loopback relay, provider auth, other binaries or descendant cleanup. Windows remains a research candidate. Only uniquely created synthetic paths/profiles were altered and cleaned; no real account, operator directory ACL or global loopback exemption was changed. Evidence: target-bound persistent `artifacts/windows-isolation-research/evidence.md` (`e8727e3ab8dff15ead35914e888645c86e67b5dfe210cdd6825ba6e83e0776ae`) and `artifacts/windows-isolation-research/observed-outputs.log` (`6f198ad5cceab6f2927de811e59e1f370976920a1d50894efca3a747309a46a2`), with the actual native pipe/AppContainer helper sources retained beside them. Sources: https://github.com/libuv/libuv/commit/2cadaa40167050baf7c6905ac897e6fb57afb2c6; https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea; https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control.

### Integration must carry trusted path authority across every launch path

`src/vaultspec_a2a/providers/_subprocess.py:179` currently receives only argv; shared spawn also receives cwd/env but those values do not themselves mint desktop filesystem authority. The independent MCP SDK launch at `providers/_mcp_contract.py:415` has no project cwd and caches command/tool identity. Binary version probes and catalog/auth setup are additional native entries. A backend must receive worker/lifecycle-selected project, role auth home and immutable runtime authority, bind them before native use, and refuse missing/stale context before a cache hit or child acquisition. Callback confinement and process lifetime remain independent requirements. Existing refusal is governed by `2026-10-04-workspace-root-authority-desktop-native-admission-adr`.

### Remaining proof gaps determine the allowed implementation scope

No actual isolated model turn, shipped capsule/helper closure, Windows ARM64 or Linux ARM64 qualification, or macOS boundary has been proved. Claude's subscription auth currently depends on the real user config home and requires a role-scoped preparation contract. Linux namespace policy is viable on the available research host; that does not establish supported-host availability. Unsupported or unproved targets remain refused. Production Docker is excluded by `2026-10-04-container-release-native-production-adr`.

### S04 bootstrap proof requires self-contained helper and separated role startup

An actual project Python startup hook in the draft wrapper read a synthetic private sentinel before namespaces; the provider never started. The revised API separates trusted command/environment/cwd from role data, uses isolated Python mode from source and bounded opaque environment chunks. The helper starts clean; role variables travel in sealed anonymous arguments. A genuine compiled project preload constructor runs in the target and observes private-file denial, while project sitecustomize never executes in the wrapper. This corrects the boundary without granting provider eligibility.

The copied system bubblewrap bootstraps from host interpreter/libraries. Production now requires static ELF with no interpreter/dynamic segment. Genuine upstream v0.11.1 was compiled with /usr/bin/cc -static -O2, static libcap 2.75 and require_userns enabled; optional SELinux support was not compiled in. The development archive was extracted into a temporary build tree without global package installation/configuration changes. Upstream source archive SHA256 fb6ebf0264dfe9fb88777d352deeedf5aecf2e36e78da148157036b647f86e0f; libcap archive SHA256 74fa71aa089d90d720722f6278314b90b72fa2e1631aea5dc32b770d0324ce86; helper SHA256 acb396d2eef44125ee6d0898460e99f45ecf850e8f535aac247e2519785b6591. Persistent producer: artifacts/desktop-native-isolation/build-static-test-helper.py, SHA256 356ea5b790bb4944af8b30a74652dce3847499efc5405d2b7e863f10185e4d43. Persistent bootstrap baseline: artifacts/desktop-native-isolation/linux-bootstrap-baseline.py, SHA256 89532b4742cc818ae16271d59054c75fed66a268be888ce7c2201d536a13c7d2. Both live in the existing target-bound security artifact directory. The producer is test evidence, not release qualification.

Locked Linux foundation/environment/runtime suites pass 18 tests with static helper, Node 22.23.1 and Python 3.13.14. Standalone CPython omits os.memfd_create and seal constants; typed libc calls use Linux UAPI flags and actual target execution proves their transport. The source-to-helper argument descriptor is consumed/closed before target execution. Primary grounding: https://raw.githubusercontent.com/containers/bubblewrap/v0.11.1/bubblewrap.c; https://raw.githubusercontent.com/containers/bubblewrap/v0.11.1/meson.build; https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/memfd.h; https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/fcntl.h. Node 22 evidence does not qualify the repository Node 26.8.1 engine or a real provider turn.

### S05 real independent MCP transport works with the explicit isolated carrier

The final Linux test `src/vaultspec_a2a/providers/tests/test_native_launch_context.py:test_genuine_mcp_handshake_uses_isolated_runtime_context` uses the genuine registry-selected vaultspec-rag distribution and its production server entry point. The test-only producer copies its resolved Python standard library/site packages and supplies only external shared-library mappings to the static-helper capsule. MCP SDK 2.2.0 forwards the trusted wrapper cwd and merges its six default host environment fields; the isolated bootstrap ignores role startup hooks, and the helper clears inherited environment before applying the role packet. Actual initialize and list-tools match the registry's read-only declaration. Replacing the selected workspace then refuses before cached surface reuse. Final Linux context population passes 5 tests (28.95 seconds), with no mock server or skipped target claim. This proves transport integration, not authenticated provider work or a release capsule. The initial producer's redundant internal-library mapping was refused by the unchanged canonical/protected-target contract and corrected only in test assembly.

### S06 scoped role preparation preserves only already selected credential channels

Accepted harness provisioning distinguishes default operator subscription discovery from explicitly selected oauth_token settings mode. Binary policy unconditionally scrubs ANTHROPIC_API_KEY and preserves host-managed policy while suppressing user/project/local setting sources. The existing worker-owned Codex seed/refresh lifecycle is reusable. Claude has no proved equivalent identity-preserving file-store transfer/refresh mechanism, so S06 does not copy operator Claude credentials or enable a new authentication fallback. A prepared fresh home carries only the already selected environment channel and strict session settings; absent selected channel and present /etc/claude-code managed policy refuse. This fits the existing selected-channel and unsupported-target constraints; default file/keychain support needs later bounded proof before implementation or eligibility.

The available Linux research host has no Claude/Codex credential file, no exported CLAUDE_CODE_OAUTH_TOKEN and no /etc/claude-code directory. Only metadata/presence was checked; no operator credential contents were read or transferred from Windows. Synthetic selected-channel controls prove home binding/private-state denial and cleanup, not real authentication. Primary documentation describes CLAUDE_CONFIG_DIR relocation and Linux subscription-file auth, and organisation managed settings under /etc/claude-code; those live documents do not establish compatibility of an untested pinned CLI or justify dropping managed policy. Sources: https://code.claude.com/docs/en/authentication; https://code.claude.com/docs/en/env-vars; https://code.claude.com/docs/en/managed-settings.

Fresh candidate review surfaced suspended async-generator cleanup ordering. Explicit closure propagates through all yielding wrappers before prepared-home removal; asynchronous removal is joined. The final Linux role/foundation tests pass 13, including actual static-helper version probing from an empty home and genuine model startup refusal with no leaked home. Authenticated stream/cancel/early-close behavior remains S08. Release packaging is separated into S07 because the product composes a2a inside a larger immutable capsule; helper/dependency placement must follow that actual composition rather than assume the binary parent is the full runtime root.

## Sources

- Target-bound persistent helper and log named above; use the Codex Security artifact reader with the repository target and persistent relative paths.
- `src/vaultspec_a2a/providers/_subprocess.py:179`; `src/vaultspec_a2a/providers/_mcp_contract.py:415`; `src/vaultspec_a2a/control/provider_execution.py:8`.
- `2026-10-04-desktop-native-isolation-audit`; `2026-10-04-workspace-root-authority-desktop-native-admission-adr`; `2026-10-04-container-release-native-production-adr`.
- https://github.com/containers/bubblewrap/blob/main/README.md
- https://man7.org/linux/man-pages/man7/pid_namespaces.7.html
- https://github.com/libuv/libuv/blob/v1.52.1/src/win/pipe.c
- https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights
- https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken
- https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control

- Target-bound persistent `artifacts/windows-isolation-research/evidence.md` and `artifacts/windows-isolation-research/observed-outputs.log`, with retained native probe sources.
- https://github.com/libuv/libuv/commit/2cadaa40167050baf7c6905ac897e6fb57afb2c6
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea
