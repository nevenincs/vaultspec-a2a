---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-0` `step-2`

Extracted `sequenced_to_dict` serializer to `ipc/serializers.py`.

- Created: `src/vaultspec_a2a/ipc/serializers.py`
- Modified: `src/vaultspec_a2a/api/event_adapter.py`

## Description

Moved `sequenced_to_dict` from `api/event_adapter.py` to `ipc/serializers.py`.
Removed the function definition and its `dataclasses.asdict` import from the
source file. No `api/` code uses `sequenced_to_dict` so no re-import was needed
in `event_adapter.py`.

## Tests

No test changes in this step. Function verified importable in step 3.
