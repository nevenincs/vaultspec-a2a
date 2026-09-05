---
tags:
  - '#reference'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:8430d2cc9a4d54cfa73d1e17fc6dbc2737aa0bcd6bbca633791feae43b226202'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-05-embedded-runtime-robustness-research]]"
  - "[[2026-09-05-embedded-runtime-robustness-audit]]"
---

# `embedded-runtime-remediation` reference: `qualification-inputs`

## Summary

This record freezes the inputs for plan Step `W01.P01.S01`. It records the execution baseline before behavioral remediation. Later qualification must replace the baseline commit and binary hash with the exact corrected artifacts it tests; doing so does not change any A01-A34 acceptance threshold.

## Identity baseline

| Item | Frozen S01 value | Qualification meaning |
| --- | --- | --- |
| A2A repository commit | `0b94bf8636d7145ae9420adeb1af635ef81f9dd7` | Clean tracked checkout used for this evidence capture and fresh binary build. |
| A2A release identity | `vaultspec-a2a 0.3.0` | Reported by the freshly built executable and locked environment. |
| Fresh S01 executable | `tmp/embedded-runtime-remediation-s01-binary/vaultspec-a2a/vaultspec-a2a.exe` | Local qualification-input artifact built by the repository freeze recipe; ignored and not a release asset. |
| Fresh executable SHA-256 | `B5F1DA8EDD6A6DC99C3FBD81645EFBA4BDF6646544B4140F4C51AE81E2EDF08F` | Exact binary identity for S01 evidence only. |
| Fresh onedir extent | executable `30,533,532` bytes; `2,128` files; `141,715,717` total bytes | Records the built closure before later packaged-pair qualification. |
| Freeze command | `uv run --locked --group freeze python scripts/build_binary.py --dist tmp/embedded-runtime-remediation-s01-binary` | Completed successfully, including version, help, and disallowed `run-module os` smoke checks. |
| Earlier audit executable | SHA-256 `EDE9B961F7D52952FD1522DB23295AE810490D01C029ADEF869C37EB6354E688`; version `0.3.0`; `30,533,532` bytes | Retained as historical pass-two evidence from source baseline `9438cf0bc1465a13892cb7fad197c44bd72c0360`; it is not substituted for the fresh S01 artifact. |
| Dashboard checkout generation | `330b2efe294c8ab134fff2142f9fae98afd14fec` | Current clean tracked intended consumer checkout at capture time. |
| Dashboard component lock | A2A commit `d59b41b6c1ac8b6e498326ea74ab32898ac9c08b`, release `vaultspec-a2a 0.1.0` | The current product generation does not select the S01 A2A baseline. `W01.P01.S02` owns the coordinated contract boundary; `W04.P10` owns lifecycle conformance; `W05.P13` owns packaged-pair proof. |

The intended qualification pair is therefore identified but not yet composable: A2A work starts from commit `0b94bf8...`, while Dashboard generation `330b2ef...` still pins a different A2A source and release identity. No Dashboard result may be attributed to the fresh S01 executable until the lock, generated release files, manifest digests, discovery generation, and launched process identity all agree.

## Host and locked toolchain

The named host is Windows kernel `10.0.26200`, x64, reported product label `Windows 10 Pro`, AMD Ryzen 9 5900X with 12 cores and 24 logical processors, and `137,346,269,184` bytes of physical memory. The project-locked Python is `3.13.11`; ambient `python` resolves to `3.14.7` and is excluded from certification commands.

Resolved locked versions are Vaultspec Core `0.1.73`, LangGraph `1.2.11`, HTTPX `0.28.1`, pytest `9.1.1`, PyInstaller `6.22.2`, Uvicorn `0.52.4`, and uv `0.12.8`. Provider executables observed on this host are Codex CLI `0.153.2`, Claude Code `2.1.261`, Gemini CLI `0.58.0`, Kimi `0.36.1`, and Node `26.8.1`. Executable presence and a version response are inventory facts only; neither is completed-work proof.

## Reproducible capture manifest

Every digest below is SHA-256 over the exact compact JSON line shown, encoded as UTF-8 with no trailing newline. The retained raw line is the immutable S01 observation. Replay must use the named repository commit and locked environment; a later checkout is expected to produce a different identity capture and must be retained as a new qualification observation rather than overwriting this one.

### Repository and executable identity capture

The pre-build repository commands were:

```powershell
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=no
git -C Y:\code\vaultspec-dashboard-worktrees\main rev-parse HEAD
git -C Y:\code\vaultspec-dashboard-worktrees\main status --porcelain=v1 --untracked-files=no
Get-Content -Raw Y:\code\vaultspec-dashboard-worktrees\main\packaging\a2a-component.lock.json
Get-FileHash tmp\embedded-runtime-remediation-s01-binary\vaultspec-a2a\vaultspec-a2a.exe -Algorithm SHA256
& tmp\embedded-runtime-remediation-s01-binary\vaultspec-a2a\vaultspec-a2a.exe --version
Get-ChildItem tmp\embedded-runtime-remediation-s01-binary\vaultspec-a2a -File -Recurse | Measure-Object Length -Sum
```

The empty status arrays retain the clean tracked state observed before the build. Untracked/ignored build output is excluded explicitly. Canonical raw output, digest `338CA23E8C5E20B1545F7E391555471F9A9FE12EFF5040DFA2854AF7B743B824`:

```json
{"a2a_prebuild_head":"0b94bf8636d7145ae9420adeb1af635ef81f9dd7","a2a_prebuild_tracked_status":[],"a2a_release_identity":"vaultspec-a2a 0.3.0","binary_exe_bytes":30533532,"binary_file_count":2128,"binary_sha256":"B5F1DA8EDD6A6DC99C3FBD81645EFBA4BDF6646544B4140F4C51AE81E2EDF08F","binary_total_bytes":141715717,"dashboard_head":"330b2efe294c8ab134fff2142f9fae98afd14fec","dashboard_lock_a2a_commit":"d59b41b6c1ac8b6e498326ea74ab32898ac9c08b","dashboard_lock_release":"vaultspec-a2a 0.1.0","dashboard_tracked_status":[]}
```

### Host and toolchain capture

```powershell
Get-ComputerInfo | Select-Object WindowsProductName,WindowsVersion,OsBuildNumber,OsArchitecture,CsProcessors,CsTotalPhysicalMemory | ConvertTo-Json -Depth 5 -Compress
python --version
uv run --locked python --version
uv --version
uv run --locked python -c "import importlib.metadata as m; print({n:m.version(n) for n in ['vaultspec-a2a','vaultspec-core','langgraph','httpx','pytest','pyinstaller','uvicorn']})"
codex --version
claude --version
gemini --version
kimi --version
node --version
```

Canonical raw output, digest `8C0CA3EA0CA0A905ADAF7CB10D9F5465DB5E2C1716B9D873A06A00B22B904A8B`:

```json
{"ambient_python":"3.14.7","cpu":"AMD Ryzen 9 5900X 12-Core Processor","logical_processors":24,"os_architecture":"64-bit","os_build":"26200","os_product_label":"Windows 10 Pro","physical_cores":12,"physical_memory_bytes":137346269184,"project_python":"3.13.11","versions":{"claude-code":"2.1.261","codex-cli":"0.153.2","gemini-cli":"0.58.0","httpx":"0.28.1","kimi":"0.36.1","langgraph":"1.2.11","node":"26.8.1","pyinstaller":"6.22.2","pytest":"9.1.1","uv":"0.12.8","uvicorn":"0.52.4","vaultspec-a2a":"0.3.0","vaultspec-core":"0.1.73"}}
```

### Runtime configuration capture

```powershell
@'
import hashlib, json
from vaultspec_a2a.control.config import settings as s
from vaultspec_a2a.domain_config import domain_config as d
domain_names = ["event_queue_maxsize","max_subscriptions_per_client","max_stream_connections","ingest_event_stall_timeout_seconds","context_limit_tokens","mount_token_ceiling","max_concurrent_threads"]
setting_names = ["sqlite_busy_timeout_ms","db_pool_size","db_pool_max_overflow","provider_timeout_seconds","host","port","mcp_host","mcp_port","worker_host","worker_port","worker_heartbeat_timeout_seconds","cb_failure_threshold","cb_recovery_timeout_seconds","worker_poll_initial_interval_seconds","worker_poll_max_interval_seconds","worker_ready_timeout_seconds","watchdog_poll_interval_seconds","ipc_flush_interval_seconds","ipc_max_flush_retries","ipc_retry_backoff_base_seconds","ipc_max_event_buffer","acp_startup_timeout_seconds","acp_rpc_timeout_seconds","acp_interactive_auth_timeout_seconds","acp_turn_idle_timeout_seconds","acp_chunk_queue_maxsize"]
raw = json.dumps({"domain": {n: getattr(d,n) for n in domain_names}, "settings": {n: getattr(s,n) for n in setting_names}}, sort_keys=True, separators=(",",":"))
print(raw)
print(hashlib.sha256(raw.encode()).hexdigest().upper())
'@ | uv run --locked python -
```

Canonical raw output digest: `45F14465AE768AEBA54389817851FCE9BCF20FFF6CCCE10DFEC0AA6D21F74D7A`. The exact raw line is:

```json
{"domain":{"context_limit_tokens":120000,"event_queue_maxsize":512,"ingest_event_stall_timeout_seconds":90.0,"max_concurrent_threads":5,"max_stream_connections":256,"max_subscriptions_per_client":512,"mount_token_ceiling":20000},"settings":{"acp_chunk_queue_maxsize":1024,"acp_interactive_auth_timeout_seconds":900.0,"acp_rpc_timeout_seconds":15.0,"acp_startup_timeout_seconds":300.0,"acp_turn_idle_timeout_seconds":600.0,"cb_failure_threshold":3,"cb_recovery_timeout_seconds":30.0,"db_pool_max_overflow":10,"db_pool_size":5,"host":"127.0.0.1","ipc_flush_interval_seconds":0.05,"ipc_max_event_buffer":10000,"ipc_max_flush_retries":3,"ipc_retry_backoff_base_seconds":0.1,"mcp_host":"0.0.0.0","mcp_port":8200,"port":18000,"provider_timeout_seconds":120,"sqlite_busy_timeout_ms":5000,"watchdog_poll_interval_seconds":5.0,"worker_heartbeat_timeout_seconds":90.0,"worker_host":"127.0.0.1","worker_poll_initial_interval_seconds":0.1,"worker_poll_max_interval_seconds":2.0,"worker_port":18001,"worker_ready_timeout_seconds":30.0}}
```

### Provider-mode captures

```powershell
@'
import hashlib, json, os
from pathlib import Path
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.providers.factory import ProviderFactory
from vaultspec_a2a.providers.in_process_catalog import in_process_lane_serving_armed, served_in_process_lanes
from vaultspec_a2a.providers.lane_admission import catalog_lane_admission_reason, is_catalog_lane_admissible
regs = ProviderFactory().catalog_registrations(Path.cwd(), serve_in_process_lanes=False)
external = [{"provider_id":r.key.provider_id,"execution_mode":r.key.execution_mode,"admissible":is_catalog_lane_admissible(r.key),"reason":catalog_lane_admission_reason(r.key)} for r in regs]
armed = in_process_lane_serving_armed()
internal = {"armed":armed,"arming_env_present":"VAULTSPEC_SERVE_IN_PROCESS_LANES" in os.environ,"mock_api_base_configured":bool(settings.mock_api_base and settings.mock_api_base.strip()),"currently_served":[{"provider_id":x.provider_id,"execution_mode":x.execution_mode} for x in served_in_process_lanes(armed=armed,mock_api_base=settings.mock_api_base)],"armed_without_mock":[{"provider_id":x.provider_id,"execution_mode":x.execution_mode} for x in served_in_process_lanes(armed=True,mock_api_base=None)],"armed_with_mock":[{"provider_id":x.provider_id,"execution_mode":x.execution_mode} for x in served_in_process_lanes(armed=True,mock_api_base="http://127.0.0.1:8100")]}
for value in (external, internal):
    raw=json.dumps(value,sort_keys=True,separators=(",",":")); print(raw); print(hashlib.sha256(raw.encode()).hexdigest().upper())
'@ | uv run --locked python -
```

The external canonical raw output, digest `D6984BB51A13ECB80418EABE8CD737C77A93FCF8507FD01710D8D6C3E5FAE7DD`, is:

```json
[{"admissible":false,"execution_mode":"antigravity-cli","provider_id":"antigravity","reason":"provider lane antigravity/antigravity-cli has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"claude-agent-acp:node","provider_id":"claude","reason":"provider lane claude/claude-agent-acp:node has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":true,"execution_mode":"codex-app-server","provider_id":"codex","reason":null},{"admissible":false,"execution_mode":"gemini-cli-acp","provider_id":"gemini","reason":"provider lane gemini/gemini-cli-acp has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"kimi-code-acp","provider_id":"kimi","reason":"provider lane kimi/kimi-code-acp has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"openai-api","provider_id":"openai","reason":"provider lane openai/openai-api has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"zai-claude-agent-acp:node","provider_id":"zai","reason":"provider lane zai/zai-claude-agent-acp:node has no exact completed-turn proof; evidence from another execution mode is not inherited"},{"admissible":false,"execution_mode":"zhipu-openai-compatible-api","provider_id":"zhipu","reason":"provider lane zhipu/zhipu-openai-compatible-api has no exact completed-turn proof; evidence from another execution mode is not inherited"}]
```

The in-process canonical raw output, digest `65BA2E9474D8F99E513CDA7BBAE7D556844F592DEE682D05359434EE8E31E1D1`, is:

```json
{"armed":false,"armed_with_mock":[{"execution_mode":"in-process-deterministic","provider_id":"deterministic"},{"execution_mode":"in-process-mock","provider_id":"mock"}],"armed_without_mock":[{"execution_mode":"in-process-deterministic","provider_id":"deterministic"}],"arming_env_present":false,"currently_served":[],"mock_api_base_configured":false}
```

### Dashboard bounds and source capture

```powershell
git -C Y:\code\vaultspec-dashboard-worktrees\main rev-parse HEAD
rg -n "A2A_(READ|CONTROL|DISCOVERY)_BUDGET|A2A_HEARTBEAT_STALE_MS|A2A_HEALTH_TIMEOUT" Y:\code\vaultspec-dashboard-worktrees\main\engine\crates\vaultspec-api\src\routes\ops\a2a.rs
rg -n "GATEWAY_STOP_PLAN_BUDGET|DISCOVERY_FRESHNESS" Y:\code\vaultspec-dashboard-worktrees\main\engine\crates\vaultspec-api\src\routes\a2a_lifecycle.rs
rg -n "CONNECT_TIMEOUT|MAX_DEADLINE" Y:\code\vaultspec-dashboard-worktrees\main\engine\crates\vaultspec-product\src\gateway_drain.rs
Get-FileHash Y:\code\vaultspec-dashboard-worktrees\main\packaging\a2a-component.lock.json,Y:\code\vaultspec-dashboard-worktrees\main\engine\crates\vaultspec-api\src\routes\ops\a2a.rs,Y:\code\vaultspec-dashboard-worktrees\main\engine\crates\vaultspec-api\src\routes\a2a_lifecycle.rs,Y:\code\vaultspec-dashboard-worktrees\main\engine\crates\vaultspec-product\src\gateway_drain.rs -Algorithm SHA256
```

Canonical bound output, digest `A0B49E9EFD2B0EB760C00BA5944BFC4ECA7DFBD5C860A399215831D54480DC76`:

```json
{"broker_catalog_discovery_seconds":45,"broker_control_seconds":60,"broker_health_probe_seconds":1.5,"broker_read_seconds":15,"broker_resident_freshness_seconds":120,"lifecycle_discovery_freshness_seconds":30,"lifecycle_stop_plan_seconds":5,"product_drain_connect_seconds":5,"product_drain_max_deadline_seconds":600}
```

### Source manifest

The source manifest is captured with this exact command from the A2A repository root:

```powershell
$a2aSources = @('pyproject.toml','uv.lock','scripts/build_binary.py','packaging/pyinstaller/vaultspec-a2a.spec','src/vaultspec_a2a/domain_config.py','src/vaultspec_a2a/control/config.py','src/vaultspec_a2a/database/session.py','src/vaultspec_a2a/providers/factory.py','src/vaultspec_a2a/providers/lane_admission.py','src/vaultspec_a2a/providers/in_process_catalog.py','src/vaultspec_a2a/streaming/ingest.py','src/vaultspec_a2a/api/app.py')
$dashboardRoot = 'Y:\code\vaultspec-dashboard-worktrees\main'
$dashboardSources = @('packaging/a2a-component.lock.json','engine/crates/vaultspec-api/src/routes/ops/a2a.rs','engine/crates/vaultspec-api/src/routes/a2a_lifecycle.rs','engine/crates/vaultspec-product/src/gateway_drain.rs','engine/crates/vaultspec-product/src/control.rs')
$records = @(
  $a2aSources | ForEach-Object { [ordered]@{repository='A2A';source=$_;sha256=(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash} }
  $dashboardSources | ForEach-Object { [ordered]@{repository='Dashboard';source=$_;sha256=(Get-FileHash -LiteralPath (Join-Path $dashboardRoot $_) -Algorithm SHA256).Hash} }
)
$raw = $records | ConvertTo-Json -Compress
$raw
[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($raw)))
```

Its canonical compact JSON digest is `C409D644640E82F8BB80FAFABC9DC8D0D354D83695D04BD9C3D44F380D811425`. The exact raw line is:

```json
[{"repository":"A2A","source":"pyproject.toml","sha256":"650E80C290E7C9423B6EB7B3D07CCF6A6BC52069C2A3873141CF86BA5D1E5553"},{"repository":"A2A","source":"uv.lock","sha256":"CEE4A33BA05E31D7929A533702D6E6AAF11F750A9AB735447548E674FAE84210"},{"repository":"A2A","source":"scripts/build_binary.py","sha256":"6B07B8EA6527FF73FC4EF30FB263B5E62E6D149187FC84B5DD3FEC456C368EBB"},{"repository":"A2A","source":"packaging/pyinstaller/vaultspec-a2a.spec","sha256":"8F68285D9B6585DAA17639FBF86E5E803C261A015D3A2952C0693854867BE803"},{"repository":"A2A","source":"src/vaultspec_a2a/domain_config.py","sha256":"B9DBB9E63378B2092562C4BF48BCDBFCB7EADC4F360E94DD78D33061510FBDB2"},{"repository":"A2A","source":"src/vaultspec_a2a/control/config.py","sha256":"DC9777747487C8F879F39CA021449ECDA4D323133C7BE887B744EE4D07EEC43E"},{"repository":"A2A","source":"src/vaultspec_a2a/database/session.py","sha256":"FC4F30A3A148E2D2237BF3ADC8F3A4F26C4245B1B97172751687FFE084839116"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/factory.py","sha256":"2324098BE2A974066E9221BD46A351CD3C3B274C601CDAE0CEBE0FF49A0D7066"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/lane_admission.py","sha256":"B32DC03D043B563E42DA49126085FBFACB4F8CF74E23D8779A9800F05B4010FF"},{"repository":"A2A","source":"src/vaultspec_a2a/providers/in_process_catalog.py","sha256":"255EB765761FCF17D6362AAB20143933D5633038CEFDC35FC5971B89F8A9015C"},{"repository":"A2A","source":"src/vaultspec_a2a/streaming/ingest.py","sha256":"9B582B14569E11F2BD7DAF3D9E69B71DC4004E1D8EC035114C5723928041F67A"},{"repository":"A2A","source":"src/vaultspec_a2a/api/app.py","sha256":"84A409EF24A321F533852FB861CBE21C98C47461ADCCB94EF05B977B0B9E7869"},{"repository":"Dashboard","source":"packaging/a2a-component.lock.json","sha256":"B4EB3FC93A05FB1B83E4391F0C81D614EA8F22BAB450B2CF3CB11BDD2DFB8A1D"},{"repository":"Dashboard","source":"engine/crates/vaultspec-api/src/routes/ops/a2a.rs","sha256":"B82A5893856840EDE50874D847F07C6F4FADB803CAE371CD58E3D5C52F78D5C0"},{"repository":"Dashboard","source":"engine/crates/vaultspec-api/src/routes/a2a_lifecycle.rs","sha256":"2FCF2F581025E310F53BB171F222E738BB20304036E504719FA53D065452AF38"},{"repository":"Dashboard","source":"engine/crates/vaultspec-product/src/gateway_drain.rs","sha256":"D43E210F67132858551AAD4C52A6DDC6789A95C8C14729BBFD2BC759E1F99025"},{"repository":"Dashboard","source":"engine/crates/vaultspec-product/src/control.rs","sha256":"5D4745ED163F9B8B9A8A54D4A4C9DDA9034F682F76B918A08CE38324B329D214"}]
```

Material source hashes are:

| Repository | Source | SHA-256 |
| --- | --- | --- |
| A2A | `pyproject.toml` | `650E80C290E7C9423B6EB7B3D07CCF6A6BC52069C2A3873141CF86BA5D1E5553` |
| A2A | `uv.lock` | `CEE4A33BA05E31D7929A533702D6E6AAF11F750A9AB735447548E674FAE84210` |
| A2A | `scripts/build_binary.py` | `6B07B8EA6527FF73FC4EF30FB263B5E62E6D149187FC84B5DD3FEC456C368EBB` |
| A2A | `packaging/pyinstaller/vaultspec-a2a.spec` | `8F68285D9B6585DAA17639FBF86E5E803C261A015D3A2952C0693854867BE803` |
| A2A | `src/vaultspec_a2a/domain_config.py` | `B9DBB9E63378B2092562C4BF48BCDBFCB7EADC4F360E94DD78D33061510FBDB2` |
| A2A | `src/vaultspec_a2a/control/config.py` | `DC9777747487C8F879F39CA021449ECDA4D323133C7BE887B744EE4D07EEC43E` |
| A2A | `src/vaultspec_a2a/database/session.py` | `FC4F30A3A148E2D2237BF3ADC8F3A4F26C4245B1B97172751687FFE084839116` |
| A2A | `src/vaultspec_a2a/providers/factory.py` | `2324098BE2A974066E9221BD46A351CD3C3B274C601CDAE0CEBE0FF49A0D7066` |
| A2A | `src/vaultspec_a2a/providers/lane_admission.py` | `B32DC03D043B563E42DA49126085FBFACB4F8CF74E23D8779A9800F05B4010FF` |
| A2A | `src/vaultspec_a2a/providers/in_process_catalog.py` | `255EB765761FCF17D6362AAB20143933D5633038CEFDC35FC5971B89F8A9015C` |
| A2A | `src/vaultspec_a2a/streaming/ingest.py` | `9B582B14569E11F2BD7DAF3D9E69B71DC4004E1D8EC035114C5723928041F67A` |
| A2A | `src/vaultspec_a2a/api/app.py` | `84A409EF24A321F533852FB861CBE21C98C47461ADCCB94EF05B977B0B9E7869` |
| Dashboard | `packaging/a2a-component.lock.json` | `B4EB3FC93A05FB1B83E4391F0C81D614EA8F22BAB450B2CF3CB11BDD2DFB8A1D` |
| Dashboard | `engine/crates/vaultspec-api/src/routes/ops/a2a.rs` | `B82A5893856840EDE50874D847F07C6F4FADB803CAE371CD58E3D5C52F78D5C0` |
| Dashboard | `engine/crates/vaultspec-api/src/routes/a2a_lifecycle.rs` | `2FCF2F581025E310F53BB171F222E738BB20304036E504719FA53D065452AF38` |
| Dashboard | `engine/crates/vaultspec-product/src/gateway_drain.rs` | `D43E210F67132858551AAD4C52A6DDC6789A95C8C14729BBFD2BC759E1F99025` |
| Dashboard | `engine/crates/vaultspec-product/src/control.rs` | `5D4745ED163F9B8B9A8A54D4A4C9DDA9034F682F76B918A08CE38324B329D214` |

## Supported-mode inventory

The inventory comes from `ProviderFactory.catalog_registrations(..., serve_in_process_lanes=False)` and the exact-key admission gate. These are the complete external catalog registrations at the frozen commit.

| Provider/mode | Served disposition | Current evidence statement |
| --- | --- | --- |
| `antigravity/antigravity-cli` | blocked | No exact-mode completed-turn proof. |
| `claude/claude-agent-acp:node` | blocked | Provider-level history does not transfer to this catalog execution mode. |
| `codex/codex-app-server` | selectable | The exact catalog key is admitted by the recorded completed-turn declaration. Later W05 proof must rerun three real turns through the intended Dashboard/binary pair. |
| `gemini/gemini-cli-acp` | blocked | No exact-mode completed-turn proof. |
| `kimi/kimi-code-acp` | blocked | Handshake or executable availability is not a completed turn. |
| `openai/openai-api` | blocked | No exact-mode completed-turn proof. |
| `zai/zai-claude-agent-acp:node` | blocked | Provider-level history does not transfer to this catalog execution mode. |
| `zhipu/zhipu-openai-compatible-api` | blocked | No exact-mode completed-turn proof. |

The conditional in-process inventory is:

| Provider/mode | Current posture | Conditional served posture |
| --- | --- | --- |
| `deterministic/in-process-deterministic` | hidden; `VAULTSPEC_SERVE_IN_PROCESS_LANES` is absent/false | Served when the explicit arming flag is true. |
| `mock/in-process-mock` | hidden; arming is false and no mock API base is configured | Served only when explicitly armed and `mock_api_base` names a nonblank tape-server endpoint. |

At S01 the effective in-process registration set is empty. Explicit arming without a mock base produces only the deterministic key; explicit arming with a mock base produces both keys in that order. These are certification lanes and cannot establish external-provider or packaged-consumer success.

## Frozen pre-test limits

| Boundary | Frozen value or formula | Required use |
| --- | --- | --- |
| Durable follow-up-message queue `Q` | No declared atomic per-run or service capacity exists at S01. | A10 remains blocked until `W02.P04.S16` establishes `Q`; then test exactly `Q` plus `Q+1`. This absence does not relax the criterion. |
| Worker execution concurrency `C` | `max_concurrent_threads = 5` | A28 runs 30 minutes at five occupied executions and separately at ten submitted executions. |
| Progress subscriber queue | `event_queue_maxsize = 512` per subscriber | A22 must force overflow and require an explicit gap/resynchronization outcome. |
| Stream registry | `max_stream_connections = 256`; `max_subscriptions_per_client = 512` | A28 reports peak bounded connections and subscriptions. |
| ACP chunk queue | `acp_chunk_queue_maxsize = 1,024` per session | Provider stream load must not silently lose terminal meaning. |
| Worker IPC event buffer | `ipc_max_event_buffer = 10,000`, currently drop-oldest; flush `0.05s`, three retries, `0.1s` exponential base | A22/A26 must distinguish delivery loss or overflow from authoritative state. |
| Input and IPC bounds | internal frame/body `1,048,576` bytes each; context limit `120,000` estimated tokens; mount ceiling `20,000` tokens | A16 samples 80%, 95%, and above the declared context limit without changing units after results. |
| SQLite admission and locking | Resolved database/checkpoint backends are SQLite; busy timeout is `5,000ms`. File SQLite currently instantiates SQLAlchemy `AsyncAdaptedQueuePool` with observed library defaults size `5` and overflow `10`, but A2A does not pass `db_pool_size` or `db_pool_max_overflow` for SQLite. | A25 records lock refusal separately. A28 treats the observed library pool shape as version-bound evidence, not an operator-declared SQLite capacity. |
| PostgreSQL connection pool | `db_pool_size = 5` plus `db_pool_max_overflow = 10`; these kwargs are applied only when the URL begins with `postgresql`. | PostgreSQL qualification uses a maximum configured QueuePool checkout population of 15; it does not transfer that contract to SQLite. |
| Graph stall deadline `B` | `max(90s, run step_timeout_seconds + 30s)` | A24 permits valid silence through the run's own budget and requires a true stall to resolve by `B` plus one observation/poll interval. |
| ACP turn idle deadline | `600s`, reset by protocol activity | A24/provider drills distinguish a long active turn from silence. |
| Provider call timeout | `120s`; ACP startup `300s`; ACP management RPC `15s`; interactive auth `900s` | A19/A20 record which bound actually fired and preserve the supplied condition. |
| Worker liveness | heartbeat stale after `90s`; watchdog poll `5s`; breaker opens after three failures and probes after `30s` | A21/A24 report detection time separately from the frozen five-second post-detection visibility target. |
| Worker startup | `30s`, poll from `0.1s` to `2s` | A26/A27 record startup and replacement identity. |
| Gateway drain | current application quiescence wait `5s` | A26 measures one total lifecycle deadline after remediation; the current five-second inner wait is an observed input, not proof of total bounded shutdown. |
| Dashboard resident broker discovery | heartbeat stale after `120s`; health probe timeout `1.5s` | The attach/pass-through broker uses these values; A21 records detection and projection separately. |
| Dashboard broker calls | read `15s`; control `60s`; cold provider catalog discovery `45s` | A01/A21/A29 keep each operation class distinct and record the broker timeout that fires. |
| Dashboard product lifecycle discovery | freshness `30s`; gateway stop-plan request budget `5s` | This product-managed discovery predicate is distinct from the resident broker's `120s` predicate; S02 must reconcile semantics without collapsing them. |
| Dashboard product drain | per-call connect `5s`; caller-supplied drain/stop deadline hard ceiling `600s` | A26 records the selected drain-call and stop deadlines within this ceiling and one total observed lifecycle duration. |
| Gateway/control endpoints | gateway `127.0.0.1:18000`; worker `127.0.0.1:18001`; MCP `0.0.0.0:8200` with loopback Host/Origin defaults | A04/A21 name the tested endpoint and isolation configuration. |

The frozen campaign sample sizes remain: A03 uses 20 simultaneous callers; A09 uses 100 distinct messages plus 20 identical retries; A14 and A18 use 10 repeats at each named boundary; A28 uses 30 minutes for each load shape; A29 uses at least 100 samples separately for status, message, and cancel acknowledgements with p95 at most one second and p99 at most three seconds. A21 retains five seconds after detection. Post-quiescence A28 RSS growth remains bounded by the greater of ten percent of baseline and 50 MiB.

## A01-A34 applicability

All 34 campaign criteria apply to the embedded-runtime qualification. The qualification column identifies boundaries or conditional subcases; a missing prerequisite is `BLOCKED`, not non-applicable.

| Criterion | Applicability | Qualification boundary or condition |
| --- | --- | --- |
| A01 | applicable | Source plus intended Dashboard/package pair. |
| A02 | applicable | Local durable stores plus Dashboard CRUD. |
| A03 | applicable | Local 20-caller admission race. |
| A04 | applicable | Local and Dashboard auth, generation, and workspace isolation. |
| A05 | applicable | Complete mode inventory; provider boundary for every selectable external lane. |
| A06 | applicable | Exact lane/model/capability agreement; no sibling proof transfer. |
| A07 | applicable | Three real turns for each admitted external lane; currently Codex is the sole selectable catalog lane. |
| A08 | applicable | Durable message acceptance locally and through Dashboard. |
| A09 | applicable | Local ordering and replay drill. |
| A10 | applicable, currently blocked | The absent durable queue `Q` is owned by S16. |
| A11 | applicable | Typed clarification locally, on admitted real lanes, and through Dashboard. |
| A12 | applicable | Permission decisions locally and on each claiming provider lane. |
| A13 | applicable | Cancellation races locally, on applicable real lanes, and through Dashboard. |
| A14 | applicable | Local crash-boundary recovery, 10 repeats each. |
| A15 | applicable | Positive command effects for advertised commands; truthful refusal for genuinely unsupported commands. |
| A16 | applicable | Actual assembled provider input at 80%, 95%, and above limit. |
| A17 | applicable by lane claim | Every lane claiming compaction needs real effect proof; unsupported lanes must refuse truthfully. |
| A18 | applicable | Compaction races, 10 repeats each; provider subcase only on a lane executing compaction. |
| A19 | applicable | Local faults plus safely reachable exact-provider faults; inaccessible provider faults remain blocked. |
| A20 | applicable | Retry/breaker/failover locally and on safely testable real-provider conditions. |
| A21 | applicable | Provider, worker, stream, database, and engine discovery independently degraded. |
| A22 | applicable | Snapshot, disconnect, overflow, stale cursor, and reload. |
| A23 | applicable | Source ownership audit plus local state interleavings. |
| A24 | applicable | Run-derived local deadline and real-provider long-work case. |
| A25 | applicable | Disposable store crash, locking, disk-full, and read-only cases. |
| A26 | applicable | Local and Dashboard-owned drain, replacement, and child census. |
| A27 | applicable, currently blocked | Requires a component lock and Dashboard generation selecting the tested binary. |
| A28 | applicable | Local and Dashboard/package sustained load at `C` and `2C`. |
| A29 | applicable | Named host/load; 100 samples per operation. |
| A30 | applicable | Local and Dashboard diagnostics/log retention with canaries and UTF-8 bounds. |
| A31 | applicable | Addressed messaging always; provider subagent/background subcases only where separately claimed. |
| A32 | applicable | Every measurement must retain exact command, identity, boundary, exclusions, and queue update. |
| A33 | applicable | Negotiated protocol lanes; absent optional capability must refuse without authorization. |
| A34 | applicable | Every provider lane that supplies a stop outcome; coarser/unknown only when the transport supplies no finer fact. |

## Evidence exclusions and ownership

No source test, mock or deterministic lane, skipped test, handshake, executable version response, catalog enumeration, or helper-only binary smoke substitutes for required external-provider or Dashboard evidence. The Dashboard lock mismatch and absent message `Q` are tracked gaps, not permission blockers. Their owners are `W01.P01.S02`/`W04.P10`/`W05.P13` and `W02.P04.S16`/`W05.P11.S52`, respectively.
