---
tags:
  - '#audit'
  - '#infra-config'
date: '2026-03-28'
modified: '2026-03-28'
related:
  - '[[2026-03-28-infra-config-plan]]'
  - '[[2026-03-28-infra-config-adr]]'
  - '[[2026-03-28-post-layer2d-boundary-audit]]'
---

# `infra-config` Phase 1 Code Review

## Scope

Phase 1 — Settings decoupling: switch 7 API/worker files from
`settings.graph_recursion_limit` / `settings.max_cached_graphs` to
`domain_config`, and add `env_file=".env"` to `DomainConfig.model_config`.

---

## Findings

### DOMAIN-CONFIG-001 | PASS | `env_file` and `env_file_encoding` added correctly

`DomainConfig.model_config` in `domain_config.py` now contains
`env_file=".env"` and `env_file_encoding="utf-8"` alongside the
existing `env_prefix="VAULTSPEC_"` and `extra="ignore"`. This
matches the plan requirement exactly and ensures runtime equivalence
with `Settings` for env-sourced values.

---

### DOMAIN-CONFIG-002 | PASS | `graph_recursion_limit` default parity confirmed

`DomainConfig.graph_recursion_limit` defaults to `100`. `Settings` no
longer defines this field (confirmed by grep — zero matches in
`control/config.py`). No divergence.

---

### DOMAIN-CONFIG-003 | PASS | `max_cached_graphs` default parity confirmed

`DomainConfig.max_cached_graphs` defaults to `32`. `Settings` no longer
defines this field (zero grep matches in `control/config.py`). No
divergence.

---

### WS-DISPATCH-001 | PASS | Import swap correct, no residual `settings`

`api/ws_dispatch.py` imports `from ..domain_config import domain_config`
at module level (line 25) and accesses `domain_config.graph_recursion_limit`
at lines 185 and 275. No `settings` import or usage present. Import
ordering is stdlib → third-party → local (ruff isort compatible). No
unused imports.

---

### CANCEL-001 | PASS | Import swap and field access correct

`api/routes/cancel.py` imports `from ...domain_config import domain_config`
at module level and passes `domain_config.graph_recursion_limit` to
`cancel_thread()`. No residual `settings`. Import block ordering correct.

---

### MESSAGES-001 | PASS | Import swap and field access correct

`api/routes/messages.py` imports `domain_config` at module level and
passes `domain_config.graph_recursion_limit` to `send_followup_message()`.
No residual `settings`. Ordering correct.

---

### PERMISSIONS-001 | MEDIUM | Inline import inside function body is inconsistent with peer files

`api/routes/permissions.py` places `from ...domain_config import domain_config`
as an inline import *inside* `respond_to_permission_endpoint()` (line 54),
while all other switched files use a clean module-level import. The plan
notes this was the pre-existing pattern ("inline import inside function
body"), implying this mirrored the prior `settings` style there, but it
is now inconsistent across the route layer. There is no circular-import
reason for this file specifically; the inline placement adds unnecessary
per-call overhead (Python caches it after the first call, but it obscures
intent). Should be hoisted to module level in a follow-up cleanup.

---

### PERMISSIONS-002 | PASS | No residual `settings` in permissions route

Confirmed: no `settings` import or reference appears anywhere in
`api/routes/permissions.py` after the swap.

---

### THREADS-001 | PASS | Import swap and field access correct

`api/routes/threads.py` imports `domain_config` at module level and
passes `domain_config.graph_recursion_limit` to
`create_and_dispatch_thread()`. No residual `settings`. Ordering correct.

---

### DISPATCH-001 | PASS | Import swap and field access correct

`control/dispatch.py` imports `from ..domain_config import domain_config`
at module level (line 24) and uses `domain_config.graph_recursion_limit`
at line 247 (inside `redispatch_reconciling_threads`). No residual
`settings` import. Import ordering is correct.

---

### GRAPH-LIFECYCLE-001 | PASS | `max_cached_graphs` access correct

`worker/graph_lifecycle.py` imports `domain_config` at module level
(line 17) and accesses `domain_config.max_cached_graphs` at line 155
(LRU eviction guard). No residual `settings`. No logic changes beyond
the field access swap.

---

### EXECUTOR-001 | PASS | Split access: `settings.max_concurrent_threads` retained, `domain_config.graph_recursion_limit` used

`worker/executor.py` retains `from ..control.config import settings` at
line 17 (used exclusively for `settings.max_concurrent_threads` in
`at_capacity()`, line 101). `domain_config` is imported at line 18 and
used for `graph_recursion_limit` at lines 328 and 447. The two imports
coexist cleanly. This matches the plan intent: infra-level concurrency
cap stays on `Settings`; domain-level recursion limit moves to
`DomainConfig`.

---

### EXECUTOR-002 | LOW | `domain_config` import ordering relative to `settings`

In `executor.py` the import order is:
```
from ..control.config import settings       # line 17
from ..domain_config import domain_config   # line 18
```
Both are local (first-party) imports. Ruff isort groups first-party
imports together, so the order is stable. However, `domain_config` is
from a lower layer (Layer 1) while `settings` is from Layer 2 (`control`).
Alphabetically `control.config` < `domain_config`, so the current order
is alphabetically correct for ruff's isort. No action required, but worth
noting for future readers.

---

### CROSS-CUT-001 | PASS | Zero residual `settings.graph_recursion_limit` references

Full `src/vaultspec_a2a/` tree grep for `settings\.graph_recursion_limit`
returns no matches. The field is fully migrated.

---

### CROSS-CUT-002 | PASS | Zero residual `settings.max_cached_graphs` references

Full `src/vaultspec_a2a/` tree grep for `settings\.max_cached_graphs`
returns no matches. The field is fully migrated.

---

### CROSS-CUT-003 | PASS | Plan verification criterion met — zero `from.*control.config import settings` in the 7 switched files

All 7 switched files (`ws_dispatch.py`, `cancel.py`, `messages.py`,
`permissions.py`, `threads.py`, `control/dispatch.py`,
`worker/graph_lifecycle.py`) contain zero references to
`from.*control.config import settings`. The executor retains its
intentional `settings` import for `max_concurrent_threads` and is not
one of the 7 files the plan verification target covers.

---

### CROSS-CUT-004 | PASS | No logic changes beyond import swap detected

Review of all 9 files shows no altered control flow, no new error
handling, no removed validation. All changes are mechanical import-path
substitutions. The `domain_config` singleton was already available
pre-Phase-1; Phase 1 only routes the field reads to the correct source.

---

### CROSS-CUT-005 | PASS | No security issues introduced

No secrets, API keys, or sensitive values are exposed by these changes.
`DomainConfig` carries only numeric/float behavioural knobs. The new
`env_file=".env"` loads the same `.env` that `Settings` already loaded —
no new file access surface.

---

## Summary Table

| ID                  | Severity | File(s)                    | Finding                                                        | Disposition      |
|---------------------|----------|----------------------------|----------------------------------------------------------------|------------------|
| DOMAIN-CONFIG-001   | PASS     | `domain_config.py`         | `env_file` + `env_file_encoding` added correctly               | No action        |
| DOMAIN-CONFIG-002   | PASS     | `domain_config.py`         | `graph_recursion_limit` default (100) matches prior `Settings` | No action        |
| DOMAIN-CONFIG-003   | PASS     | `domain_config.py`         | `max_cached_graphs` default (32) matches prior `Settings`      | No action        |
| WS-DISPATCH-001     | PASS     | `api/ws_dispatch.py`       | Import swap correct, no residual `settings`                    | No action        |
| CANCEL-001          | PASS     | `api/routes/cancel.py`     | Import swap correct                                            | No action        |
| MESSAGES-001        | PASS     | `api/routes/messages.py`   | Import swap correct                                            | No action        |
| PERMISSIONS-001     | MEDIUM   | `api/routes/permissions.py`| Inline import inside function body; inconsistent with peers    | Follow-up hoist  |
| PERMISSIONS-002     | PASS     | `api/routes/permissions.py`| No residual `settings`                                         | No action        |
| THREADS-001         | PASS     | `api/routes/threads.py`    | Import swap correct                                            | No action        |
| DISPATCH-001        | PASS     | `control/dispatch.py`      | Import swap correct                                            | No action        |
| GRAPH-LIFECYCLE-001 | PASS     | `worker/graph_lifecycle.py`| `max_cached_graphs` access correct                             | No action        |
| EXECUTOR-001        | PASS     | `worker/executor.py`       | Split `settings`/`domain_config` usage is correct by design    | No action        |
| EXECUTOR-002        | LOW      | `worker/executor.py`       | Import ordering alphabetically correct for ruff isort          | No action        |
| CROSS-CUT-001       | PASS     | entire `src/` tree         | Zero residual `settings.graph_recursion_limit`                 | No action        |
| CROSS-CUT-002       | PASS     | entire `src/` tree         | Zero residual `settings.max_cached_graphs`                     | No action        |
| CROSS-CUT-003       | PASS     | 7 switched files           | Plan verification grep criterion met                           | No action        |
| CROSS-CUT-004       | PASS     | all 9 files                | No logic changes beyond import swap                            | No action        |
| CROSS-CUT-005       | PASS     | all 9 files                | No security issues                                             | No action        |

**Overall verdict:** Phase 1 is correct. One MEDIUM finding
(`PERMISSIONS-001`) and one LOW finding (`EXECUTOR-002`) — neither
blocks merge. The inline import in `permissions.py` should be hoisted
to module level in a follow-up hygiene pass (Phase 3 or standalone).
