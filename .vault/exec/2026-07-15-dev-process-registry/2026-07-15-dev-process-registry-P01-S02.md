---
tags:
  - '#exec'
  - '#dev-process-registry'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S02'
related:
  - "[[2026-07-15-dev-process-registry-plan]]"
---

# Implement the lifecycle verbs on the operator CLI: procs list/attach/kill/rebuild/rerun/resume/reap with Windows tree-kill and staleness verdicts

## Scope

- `src/vaultspec_a2a/cli/`
- `src/vaultspec_a2a/lifecycle/`

## Description

- Implement `manager.py`: the process-lifecycle primitives and verb
  orchestration over the registry and `procs.toml`. `tree_kill` fells a whole
  process tree by pid - Windows `taskkill /T /F /PID` (a bare terminate orphans
  grandchildren), POSIX `SIGTERM` then `SIGKILL` - blocking on the pid's
  disappearance. `render_command` substitutes the `{port}`/`{workspace}` tokens;
  `spawn` starts a detached child (new process group on Windows, new session on
  POSIX) so the server outlives the invocation; `_build_sha` captures the short
  git SHA for the record.
- Implement the seven verbs: `list_verdicts` (every record with its
  LIVE/STALE/DEAD verdict and endpoint), `attach` (verify pid alive plus a live
  loopback connect before handing back the endpoint - a connect probe, not a
  bind, since Windows `SO_REUSEADDR` defeats a bind check), `kill` (tree-kill
  then remove the now-dead record), `rebuild` (run the role's build command),
  `rerun` (kill, rebuild, re-spawn serve, re-register on the same port), `resume`
  (restart a died record on its original port/workspace, refused while alive),
  and `reap` (fell and clear every stale or dead orphan).
- Wire a thin `procs` command group into the operator CLI exposing all seven
  verbs, formatting the structured results and turning lifecycle errors into
  clean CLI exits; re-export the manager surface through the `lifecycle` package.

## Outcome

- 7 new lifecycle tests pass against real subprocesses, real loopback sockets,
  and real registry files - no mocks, no monkeypatch. `tree_kill` fells a real
  sleeping child; `resume` re-spawns a real serve command; `reap` distinguishes a
  dead child from this live test process. No pid is killed except one the test
  spawned.
- Full lifecycle suite: 46 pass. `ruff check`, `ruff format --check`, and
  `ty check` are clean on `manager.py` and the CLI; `procs list`/`procs --help`
  smoke-tested through the console entry.
- Created: `src/vaultspec_a2a/lifecycle/manager.py`,
  `src/vaultspec_a2a/lifecycle/tests/test_manager.py`.
- Modified: `src/vaultspec_a2a/cli/main.py`,
  `src/vaultspec_a2a/lifecycle/__init__.py`,
  `src/vaultspec_a2a/lifecycle/tests/conftest.py`.

## Notes

- Kill is an OS action, not a registry write, so once a pid is dead its record is
  freely removable - `kill`/`reap` never have to fight another owner's live
  claim, keeping the owner-check discipline intact without blocking an operator.
- No live acceptance-stack process (18770 / 18110 / 18111) was touched; all
  process tests spawn and kill only their own children by recorded pid.
