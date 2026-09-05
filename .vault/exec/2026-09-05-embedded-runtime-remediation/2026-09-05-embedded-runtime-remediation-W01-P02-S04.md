---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:a60371aebdcf61230c7509811a2ef873f9fa8dbe544aaf9c1abdce1b346298f2'
step_id: 'S04'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Run PostgreSQL URL checks under the locked server dependency profile and make that profile explicit while preserving the SQLite binary profile

## Scope

- `pyproject.toml`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `M` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P02-S04.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `M` `pyproject.toml`
- `M` `src/vaultspec_a2a/control/tests/test_sync_url_derivation.py`
- `verify:` task-specific `server-env` locked sync, profile capture, and URL/engine suite -> `pass` (15 passed; digest `72A2469C6A2956EC43258544492963DEF6F246AB3DD6DC3D409DDDCEBE6D9EBD`)
- `verify:` task-specific `freeze-env` locked sync and driver distribution/import capture -> `pass` (all absent; digest `F4EAE3C18DA15E33EA94FE9FE7ED240D1213D0726F75ABAA7D2EBFD493B4FCDF`)
- `verify:` task-specific `build-env` locked server-plus-freeze sync and binary build -> `pass` (smoke passed; profile digest `C33782735C1BD675894952BBE93752946A103AAE4EC480A588D750B2DF94DA56`)
- `verify:` bounded artifact-path and `PYZ-00.toc` scan -> `pass` (5,720 modules, 2,746 files, zero blocked matches; digest `A0D70509F1B8FE6233C4B5CA7B70E511A01DF345649BBEAA19E303DF5B49B059`)
- `verify:` source/status manifest capture -> `pass` (digest `15CBFE69856D5EFD6490C62455E955663A558D5D1F005D667D682B73B8C849DB`)
- `verify:` S04 durable-command removed-option scan -> `pass` (zero matches)
- `verify:` `uv lock --check`, `ruff format --check`, `ruff check`, and `ty check` -> `pass`

## Notes

The original evidence used an unsupported no-op environment option and placeholder probes. The correction uses task-specific `UV_PROJECT_ENVIRONMENT` directories, explicit locked synchronization, and `uv run --no-sync`; the shared `.venv` is outside every corrected command.

### Server profile and URL/engine suite

Run from `Y:\code\vaultspec-a2a-worktrees\main`:

```powershell
$env:UV_PROJECT_ENVIRONMENT=[IO.Path]::GetFullPath((Join-Path (Get-Location) 'tmp/embedded-runtime-remediation-s04/server-env'))
uv sync --locked --no-default-groups --extra server --group tooling
@"
import hashlib,importlib.metadata as md,json,subprocess,sys,tomllib
from pathlib import Path
root=Path.cwd(); project=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))
def version(dist):
 try: return md.version(dist)
 except md.PackageNotFoundError: return None
out={'profile':'server','project_root':str(root.resolve()),'environment':str(Path(sys.prefix).resolve()),'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'server_requirements':project['project']['optional-dependencies']['server'],'freeze_requirements':project['dependency-groups']['freeze'],'installed':{dist:version(dist) for dist in ('asyncpg','psycopg','psycopg-binary','psycopg-pool','langgraph-checkpoint-postgres','pytest','vaultspec-a2a')}}
raw=json.dumps(out,sort_keys=True,separators=(',',':')); print(raw); print(hashlib.sha256(raw.encode()).hexdigest().upper())
"@ | uv run --no-sync python -
uv run --no-sync python -m pytest src/vaultspec_a2a/control/tests/test_sync_url_derivation.py -q
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

```json
{"environment":"Y:\\code\\vaultspec-a2a-worktrees\\main\\tmp\\embedded-runtime-remediation-s04\\server-env","freeze_requirements":["pyinstaller>=6.11","vaultspec-core>=0.1.56,<0.2"],"head":"5e8cbb7b78d990f269e03c3dfe2a27ddb7a72ff8","installed":{"asyncpg":"0.31.0","langgraph-checkpoint-postgres":"3.1.2","psycopg":"3.3.5","psycopg-binary":"3.3.5","psycopg-pool":"3.3.1","pytest":"9.1.1","vaultspec-a2a":"0.3.0"},"profile":"server","project_root":"Y:\\code\\vaultspec-a2a-worktrees\\main","server_requirements":["asyncpg>=0.30.0","langgraph-checkpoint-postgres>=2.0.0","opentelemetry-exporter-otlp-proto-grpc>=1.39.1","psycopg[binary,pool]>=3.2.9"]}
```

SHA-256 `72A2469C6A2956EC43258544492963DEF6F246AB3DD6DC3D409DDDCEBE6D9EBD`; pytest: 15 passed.

### Freeze-only driver absence

```powershell
$env:UV_PROJECT_ENVIRONMENT=[IO.Path]::GetFullPath((Join-Path (Get-Location) 'tmp/embedded-runtime-remediation-s04/freeze-env'))
uv sync --locked --no-default-groups --group freeze
@"
import hashlib,importlib.metadata as md,importlib.util,json,subprocess,sys,tomllib
from pathlib import Path
root=Path.cwd(); project=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))
def version(dist):
 try: return md.version(dist)
 except md.PackageNotFoundError: return None
blocked=('asyncpg','psycopg','langgraph.checkpoint.postgres')
out={'profile':'freeze','project_root':str(root.resolve()),'environment':str(Path(sys.prefix).resolve()),'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'freeze_requirements':project['dependency-groups']['freeze'],'server_requirements':project['project']['optional-dependencies']['server'],'blocked_imports':{name:importlib.util.find_spec(name) is not None for name in blocked},'installed':{dist:version(dist) for dist in ('pyinstaller','vaultspec-core','vaultspec-a2a','asyncpg','psycopg','langgraph-checkpoint-postgres')}}
raw=json.dumps(out,sort_keys=True,separators=(',',':')); print(raw); print(hashlib.sha256(raw.encode()).hexdigest().upper()); assert not any(out['blocked_imports'].values()); assert all(out['installed'][name] is None for name in ('asyncpg','psycopg','langgraph-checkpoint-postgres'))
"@ | uv run --no-sync python -
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

```json
{"blocked_imports":{"asyncpg":false,"langgraph.checkpoint.postgres":false,"psycopg":false},"environment":"Y:\\code\\vaultspec-a2a-worktrees\\main\\tmp\\embedded-runtime-remediation-s04\\freeze-env","freeze_requirements":["pyinstaller>=6.11","vaultspec-core>=0.1.56,<0.2"],"head":"5e8cbb7b78d990f269e03c3dfe2a27ddb7a72ff8","installed":{"asyncpg":null,"langgraph-checkpoint-postgres":null,"psycopg":null,"pyinstaller":"6.22.2","vaultspec-a2a":"0.3.0","vaultspec-core":"0.1.73"},"profile":"freeze","project_root":"Y:\\code\\vaultspec-a2a-worktrees\\main","server_requirements":["asyncpg>=0.30.0","langgraph-checkpoint-postgres>=2.0.0","opentelemetry-exporter-otlp-proto-grpc>=1.39.1","psycopg[binary,pool]>=3.2.9"]}
```

SHA-256 `F4EAE3C18DA15E33EA94FE9FE7ED240D1213D0726F75ABAA7D2EBFD493B4FCDF`.

### Server-equipped build and blocked-module scan

```powershell
$env:UV_PROJECT_ENVIRONMENT=[IO.Path]::GetFullPath((Join-Path (Get-Location) 'tmp/embedded-runtime-remediation-s04/build-env'))
uv sync --locked --no-default-groups --extra server --group freeze
@"
import hashlib,importlib.metadata as md,json,subprocess,sys
from pathlib import Path
def version(dist):
 try: return md.version(dist)
 except md.PackageNotFoundError: return None
root=Path.cwd(); out={'profile':'server+freeze-build','project_root':str(root.resolve()),'environment':str(Path(sys.prefix).resolve()),'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'installed':{dist:version(dist) for dist in ('pyinstaller','vaultspec-core','vaultspec-a2a','asyncpg','psycopg','psycopg-binary','psycopg-pool','langgraph-checkpoint-postgres')}}
raw=json.dumps(out,sort_keys=True,separators=(',',':')); print(raw); print(hashlib.sha256(raw.encode()).hexdigest().upper())
"@ | uv run --no-sync python -
uv run --no-sync python scripts/build_binary.py --dist tmp/embedded-runtime-remediation-s04/dist
@"
import ast,hashlib,json,re,sys
from pathlib import Path
root=Path.cwd().resolve(); artifact=(root/'tmp/embedded-runtime-remediation-s04/dist/vaultspec-a2a').resolve(); toc=(root/'build/vaultspec-a2a/PYZ-00.toc').resolve(); binary=artifact/'vaultspec-a2a.exe'
blocked_roots=('asyncpg','psycopg','langgraph.checkpoint.postgres')
parsed=ast.literal_eval(toc.read_text(encoding='utf-8')); modules=sorted(row[0] for row in parsed[1]); blocked_modules=sorted(name for name in modules if any(name==base or name.startswith(base+'.') for base in blocked_roots))
files=sorted(path for path in artifact.rglob('*') if path.is_file()); relatives=[path.relative_to(artifact).as_posix() for path in files]; path_pattern=re.compile(r'(?i)(^|/)(?:asyncpg|psycopg)(?:[._/-]|$)|(^|/)langgraph/checkpoint/postgres(?:[._/-]|$)'); blocked_paths=sorted(name for name in relatives if path_pattern.search(name))
manifest=hashlib.sha256()
for path,name in zip(files,relatives,strict=True): manifest.update(name.encode()); manifest.update(b'\0'); manifest.update(hashlib.sha256(path.read_bytes()).digest())
out={'environment':str(Path(sys.prefix).resolve()),'artifact_root':str(artifact),'pyz_toc':str(toc),'module_match_grammar':'name == root or name.startswith(root + dot); roots=asyncpg,psycopg,langgraph.checkpoint.postgres','path_match_grammar':path_pattern.pattern,'pyz_module_count':len(modules),'artifact_file_count':len(files),'blocked_modules':blocked_modules,'blocked_paths':blocked_paths,'pyz_toc_sha256':hashlib.sha256(toc.read_bytes()).hexdigest().upper(),'artifact_manifest_sha256':manifest.hexdigest().upper(),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest().upper()}
raw=json.dumps(out,sort_keys=True,separators=(',',':')); print(raw); print(hashlib.sha256(raw.encode()).hexdigest().upper()); assert not blocked_modules and not blocked_paths
"@ | uv run --no-sync python -
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

Build-profile output:

```json
{"environment":"Y:\\code\\vaultspec-a2a-worktrees\\main\\tmp\\embedded-runtime-remediation-s04\\build-env","head":"5e8cbb7b78d990f269e03c3dfe2a27ddb7a72ff8","installed":{"asyncpg":"0.31.0","langgraph-checkpoint-postgres":"3.1.2","psycopg":"3.3.5","psycopg-binary":"3.3.5","psycopg-pool":"3.3.1","pyinstaller":"6.22.2","vaultspec-a2a":"0.3.0","vaultspec-core":"0.1.73"},"profile":"server+freeze-build","project_root":"Y:\\code\\vaultspec-a2a-worktrees\\main"}
```

SHA-256 `C33782735C1BD675894952BBE93752946A103AAE4EC480A588D750B2DF94DA56`.

Scan output:

```json
{"artifact_file_count":2746,"artifact_manifest_sha256":"1AE311B54FFCE2672E67F0AA34F12F72C5860E0897A3F54E8A2B9026E4097D73","artifact_root":"Y:\\code\\vaultspec-a2a-worktrees\\main\\tmp\\embedded-runtime-remediation-s04\\dist\\vaultspec-a2a","binary_sha256":"474B0E685AF45C6070D1C96E9792832F15D0D1A4E9ADCE750CCFD8191C6BF9DD","blocked_modules":[],"blocked_paths":[],"environment":"Y:\\code\\vaultspec-a2a-worktrees\\main\\tmp\\embedded-runtime-remediation-s04\\build-env","module_match_grammar":"name == root or name.startswith(root + dot); roots=asyncpg,psycopg,langgraph.checkpoint.postgres","path_match_grammar":"(?i)(^|/)(?:asyncpg|psycopg)(?:[._/-]|$)|(^|/)langgraph/checkpoint/postgres(?:[._/-]|$)","pyz_module_count":5720,"pyz_toc":"Y:\\code\\vaultspec-a2a-worktrees\\main\\build\\vaultspec-a2a\\PYZ-00.toc","pyz_toc_sha256":"06AA128FA3F0723EA4772C10D45132D16C6F5FAEEEAD29E03538F14724755DBA"}
```

SHA-256 `A0D70509F1B8FE6233C4B5CA7B70E511A01DF345649BBEAA19E303DF5B49B059`.

The build again exposed the existing `frozen-binary-collects-test-modules` finding. It remains medium/open under `W04.P10.S50`, with proof at `W05.P13.S65`. This diagnostic build ran while unrelated shared-worktree changes were present; it is not a release artifact.

### Source and working-tree boundary

The replay input hashes are `pyproject.toml` `053DD14A...`, `uv.lock` `CEE4A33B...`, the PyInstaller spec `8F68285D...`, `scripts/build_binary.py` `6B07B8EA...`, and the URL test `8D0C6DE5...`. The canonical source/status capture at head `5e8cbb7b78d990f269e03c3dfe2a27ddb7a72ff8` hashes to `15CBFE69856D5EFD6490C62455E955663A558D5D1F005D667D682B73B8C849DB`; it lists the S04 plan/pyproject changes and every concurrent codebase-health/runtime path, all preserved outside this commit.
### Removed-option assertion

```powershell
$removedOption='--'+'isolated'
$files=@('pyproject.toml','src/vaultspec_a2a/control/tests/test_sync_url_derivation.py','.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md','.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md','.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P02-S04.md')
$matches=@(Select-String -LiteralPath $files -SimpleMatch $removedOption)
$raw=([ordered]@{files=$files;match_count=$matches.Count}|ConvertTo-Json -Compress)
$raw
[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($raw)))
if($matches.Count -ne 0){$matches|ForEach-Object{"$($_.Path):$($_.LineNumber):$($_.Line)"};exit 1}
```

```json
{"files":["pyproject.toml","src/vaultspec_a2a/control/tests/test_sync_url_derivation.py",".vault/audit/2026-09-05-embedded-runtime-robustness-audit.md",".vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md",".vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P02-S04.md"],"match_count":0}
```

SHA-256 `8735358CD9B1B5698509F0F9953DB772001638670CF8638839C8E7C532EDEE93`.
