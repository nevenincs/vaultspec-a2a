---
tags:
  - "#exec"
  - "#core-layer"
date: "2026-03-23"
modified: '2026-03-23'
related:
  - "[[2026-03-23-core-layer-boundary-plan]]"
---

# core-layer phase-7 cleanup

Final phase: removed the `core/` compatibility shim and all imports pointing
to it.

## P7-A: audit remaining shim usage

Grep found 60+ import sites across `src/vaultspec_a2a/` and `docker/run.py`
still referencing `core`. All patterns catalogued:

- `from ..core.config import settings` (20+ sites)
- `from ...core.config import settings` (14 sites in tests/protocols/probes)
- `from ..core import EventAggregator` (4 sites)
- `from ..core.aggregator import ...` (5 sites)
- `from ..core.exceptions import ...` (7 sites)
- `from ..core.team_config import ...` (3 sites)
- `from ..core.reconciliation import ...` (1 site)
- `from ...core.metadata import ...` (1 site)
- `from vaultspec_a2a.core.* import ...` in `docker/run.py` (3 lines)

## P7-B: update all imports

Every import was rewritten to its canonical location:

| Old path | New path |
|---|---|
| `core.config` | `control.config` |
| `core.exceptions` | `thread.errors` |
| `core.aggregator` / `core import EventAggregator` | `streaming.aggregator` |
| `core.team_config` | `team.team_config` |
| `core.reconciliation` | `database.reconciliation` |
| `core.metadata` | `context.metadata` |
| `core.graph` | `graph.compiler` |
| `core import StreamableGraph` | `streaming.aggregator` |

Ruff auto-fixed 9 import-sorting issues caused by the path changes.

## P7-C: delete core/

Deleted `src/vaultspec_a2a/core/` in its entirety:

- `__init__.py` (redirect shim — 225 lines)
- 12 `.py` shim files (config, exceptions, models, state, aggregator,
  reconciliation, team_config, metadata, graph, context, phase, preamble, etc.)
- `nodes/` sub-package (shims + duplicated tests)
- `presets/` (duplicated from `team/presets/`)
- `tests/` (20 test files — originals live in new canonical locations)

## P7-D: verification

- **Zero core references**: `grep -r "vaultspec_a2a.core" src/ docker/` returns 0 hits
- **Layer 1 imports**: all 10 canonical imports pass
- **Ruff**: all checks passed
- **ty**: all checks passed
- **Test suite**: 1000 passed, 10 failed (all pre-existing ACP node_modules
  missing — `ConfigError: Claude ACP entry point not found`), 53 deselected
