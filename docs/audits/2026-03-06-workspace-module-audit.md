# Workspace Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/workspace/` — 3 source files (git_manager.py, environment.py, __init__.py)
**Baseline:** Last audited 2026-02-28 (Third-Pass Deep Audit Fix Sprint)

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

*None identified.* The workspace module has been hardened well through multiple audit sprints. Security controls (input validation, path traversal protection, credential scrubbing, mutex serialization) are comprehensive.

---

### HIGH Findings

*None identified.* All previous HIGH findings (path traversal, rebase inversion, credential leakage) have been resolved.

---

### MEDIUM Findings

#### MED-01: `merge_worktree` with REBASE strategy leaves main repo on `target_branch`

**File:** `git_manager.py:429-453`

After `merge_worktree()` completes, the main repo's working directory remains checked out on `target_branch`. If the user was on a different branch before calling `merge_worktree()`, their branch context has changed. The `checkout target_branch` at line 429 is necessary for the merge, but there's no "restore original branch" step.

This is by design (the function's purpose is to merge into target_branch), but could surprise callers who expect the repo state to be preserved.

#### MED-02: `resolve_env_vars` scrubs `LANGCHAIN_TRACING_V2` but not `LANGSMITH_*` keys

**File:** `environment.py:83`

```python
"LANGCHAIN_TRACING_V2",
```

`LANGCHAIN_TRACING_V2` is in the scrub list, but `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, and `LANGSMITH_PROJECT` are NOT scrubbed. Per the INFRA sprint notes, `LANGSMITH_*` are the canonical names — the scrubbing is incomplete. An agent subprocess could inherit `LANGSMITH_API_KEY` and send tracing data to the parent's LangSmith project.

#### MED-03: `_BRANCH_NAME_RE` allows `.` which enables `..` in branch names

**File:** `git_manager.py:27`

```python
_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_/.-]*$")
```

The regex allows `.` characters. While git itself rejects `..` in branch names (it violates refname rules), the regex doesn't prevent `some..branch` from passing validation. Git would reject it at execution time, but the validation is supposed to be defense-in-depth.

**Mitigation:** Git's own validation catches this, so no real risk. The regex is primarily for preventing shell/path injection.

---

### LOW Findings

#### LOW-01: `resolve_venv` traversal bound of 10 is undocumented in function signature

**File:** `environment.py:46`

```python
for _ in range(10):  # bounded to prevent infinite traversal
```

The bound is explained in a comment but not in the docstring. Callers have no visibility into this limit.

#### LOW-02: Facade `__init__.py` is clean — all exports match sub-module `__all__`

No issues. The workspace facade correctly re-exports `GitManager`, `MergeStrategy`, `WorktreeInfo`, `resolve_env_vars`, and `resolve_venv` using the `as` pattern for re-export.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 0     | — |
| HIGH     | 0     | — |
| MEDIUM   | 3     | Post-merge state, incomplete credential scrub, regex permissiveness |
| LOW      | 2     | Documentation, facade compliance |

### Assessment

The workspace module is the most security-hardened module in the codebase. Every method that touches git commands validates inputs with regex, resolves paths to prevent traversal, uses `asyncio.shield()` for cancellation safety, and serializes destructive operations under a global mutex. The credential scrubbing in `environment.py` is thorough.

The only actionable concern is **MED-02**: `LANGSMITH_*` keys should be added to the scrub set alongside the existing `LANGCHAIN_*` entries.

### Recommended Fix Priority

1. **MED-02**: Add `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` to the scrub set in `environment.py`.

---

## Cycle 2 — Security Deep Dive (2026-03-06)

**Focus areas** (per team-lead brief):
1. Git operations security (agent_id validation, command injection vectors)
2. Terminal command allowlist vs actual usage
3. File I/O safety boundaries
4. Stale `lib.` paths
5. Cross-platform issues (Windows primary)

---

### Stale `lib.` Paths

**ZERO stale `lib.` references** found in `workspace/` module. All imports use proper relative patterns. Cleanest module in the codebase post-migration.

---

### Git Operations Security Assessment

#### Command Injection Vectors: **NONE FOUND**

All git commands execute via `asyncio.create_subprocess_exec` (git_manager.py:106), which bypasses the shell entirely. Arguments are passed as an argv array via `CreateProcess` on Windows. No shell metacharacter injection is possible.

**Input validation chain:**
1. `agent_id` → `_AGENT_ID_RE`: `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` — no `/`, `.`, or `-` prefix. Tight.
2. `base_branch` / `target_branch` → `_BRANCH_NAME_RE`: `^[a-zA-Z0-9][a-zA-Z0-9_/.-]*$` — allows `/` and `.` but no shell chars. Git flag injection blocked by requiring alphanumeric first char.
3. `worktree_path` → `_validate_worktree_path()`: absolute check + `resolve()` + `is_relative_to(repo_root)`. Triple-gate.

**Mutex protection:** All destructive operations (`create_worktree`, `remove_worktree`, `merge_worktree`, file writes via ACP) acquire `_git_mutex`. `asyncio.shield()` prevents mid-operation cancellation from corrupting `.git` state.

---

### NEW HIGH Findings

#### HIGH-01: `acp_chat_model.py` imports private `_git_mutex` from workspace

**File:** `providers/acp_chat_model.py:731`

```python
from ..workspace.git_manager import _git_mutex
```

The ACP chat model's `_on_fs_write_text_file` handler imports the private `_git_mutex` to coordinate file writes with git operations. This breaks encapsulation — `_git_mutex` is a module-level private symbol not in `__all__`. If git_manager.py refactors the mutex (e.g., makes it instance-level on GitManager), the ACP model breaks silently.

**Recommendation:** Export a public context manager from workspace (e.g., `workspace_write_lock()` or add `_git_mutex` to `__all__` with a public name).

---

### Escalated Findings (from MED to HIGH)

#### HIGH-02: `resolve_env_vars` missing `LANGSMITH_API_KEY` scrub (escalated from MED-02)

**File:** `environment.py:72-89`

Escalated because `LANGSMITH_API_KEY` is a credential, and ADR-027 established `LANGSMITH_*` as canonical naming. Users following canonical docs will set `LANGSMITH_API_KEY` instead of `LANGCHAIN_API_KEY`. The current scrub_keys only has the legacy `LANGCHAIN_API_KEY`.

**Missing from scrub_keys:**
- `LANGSMITH_API_KEY` (credential — MUST scrub)
- `LANGSMITH_TRACING` (not a credential but enables tracing to parent's project)

---

### Terminal Sandbox Assessment

**Note:** The terminal sandbox is NOT in the workspace module — it lives in `providers/acp_chat_model.py` (`_on_terminal_create`, `_on_terminal_resize`, `_on_terminal_write`). The workspace module only provides the git mutex that the ACP chat model uses for file writes.

The file I/O sandbox (`_sandbox_path` at `acp_chat_model.py:677-683`) uses workspace-derived `self.workspace_root`:
```python
cwd = Path(self.workspace_root or self.cwd or str(Path.cwd()))
resolved = (cwd / path).resolve()
if not resolved.is_relative_to(cwd.resolve()):
    raise ValueError(f"Path {path!r} escapes sandbox")
```

**MED-02 (from Cycle 1 scope extension):** If both `workspace_root` and `cwd` are `None`, the sandbox boundary falls back to `Path.cwd()` — the API server's process directory. This is a wider sandbox than intended.

---

### Cross-Platform Analysis (Windows Primary)

#### WIN-01: `resolve_venv` Windows path handling — CORRECT

`environment.py:123-125` checks for Windows `Scripts/` first, falls back to Unix `bin/`. `os.pathsep` at line 128 correctly uses `;` on Windows.

#### WIN-02: `create_subprocess_exec` on Windows — CORRECT and SECURITY-POSITIVE

Uses `CreateProcess` API, not `cmd.exe /c`. No shell metacharacter injection possible.

#### WIN-03: `Path.resolve()` on substituted drives may break path confinement

**Files:** `git_manager.py:213, 318, 322`

`Path.resolve()` on Windows resolves subst drives and junction points to their physical paths. If `repo_root` is accessed via a subst drive (e.g., `Y:\code\project` → `C:\Users\hello\code\project`), then:
- `repo_root = Path("Y:\\code\\project")` → `self._root.resolve()` = `C:\Users\hello\code\project`
- `worktree_path = Path("Y:\\code\\project\\agent\\coder")` → `resolved` = `C:\Users\hello\code\project\agent\coder`
- `resolved.is_relative_to(self._root.resolve())` → `True` (both resolve to `C:\` path)

**Status:** Actually CORRECT in this case — both sides resolve consistently. Only breaks if `repo_root` was stored WITHOUT resolving but `worktree_path` IS resolved, or vice versa. Current code resolves both sides (`self._root.resolve()` at line 214, 322).

**However:** `self._root` is stored unresolved at construction time (line 83: `self._root = repo_root`). If `repo_root` is `Y:\code\project` and later `_validate_worktree_path` is called with a path using the physical `C:\` prefix, it would fail — the comparison would be `C:\...\agent\coder` vs `C:\...\project` (correct) but only because BOTH sides resolve. If either side used the unresolved path, it would break.

**Conclusion:** Current implementation is correct but fragile — correctness depends on BOTH sides calling `.resolve()` at comparison time. The `__init__` could store the resolved path to make this robust.

---

### Test Coverage Gaps

| Missing Test | Finding |
|--------------|---------|
| `LANGSMITH_API_KEY` scrubbing | HIGH-02 |
| `..` in branch name rejection | MED-03 from Cycle 1 |
| Detached HEAD handling in `merge_worktree` | Line 410-414 |
| Windows junction/subst path resolution | WIN-03 |
| `_sandbox_path` fallback to `Path.cwd()` | MED-02 (providers) |

---

## Cycle 2 Summary

| Severity | New | Cycle 1 | Key Themes |
|----------|-----|---------|------------|
| CRITICAL | 0   | 0       | — |
| HIGH     | 2   | 0       | Private mutex import, LANGSMITH credential scrub |
| MEDIUM   | 0   | 3       | Post-merge state, regex permissiveness |
| LOW      | 0   | 2       | Documentation |
| WIN      | 0 issues | 0  | Path.resolve() correct but fragile |

**Total open: 0 CRIT, 2 HIGH, 3 MED, 2 LOW**

### Recommended Fix Priority

1. **HIGH-02**: Add `LANGSMITH_API_KEY` to `scrub_keys` in `resolve_env_vars()` — one-line credential fix
2. **HIGH-01**: Export public `workspace_write_lock()` context manager from workspace facade
3. **MED-02** (Cycle 1): Add `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` to scrub
4. **MED-03** (Cycle 1): Add `".." in name` guard to `_BRANCH_NAME_RE` validation
