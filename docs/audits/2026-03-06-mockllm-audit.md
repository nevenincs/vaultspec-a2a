# MockLLM Implementation Audit — 2026-03-06

## Source ADRs

- ADR-032: Decoupled Mock LLM Architecture
- ADR-033: Dockerized Mock Seeder & Standardization

## Aligned Requirements

| # | ADR Requirement | Evidence |
|---|----------------|---------|
| 1 | MockChatModel extends ChatOpenAI (ADR-032 §2) | `lib/providers/mock_chat_model.py:15` |
| 2 | Proxies to VidaiMock via HTTP (ADR-032 §2) | `lib/providers/mock_chat_model.py:128-135` |
| 3 | VidaiMock Dockerfile (ADR-032 §2.1) | `docker/vidaimock.Dockerfile:1-18` |
| 4 | 7 YAML tapes (ADR-032 §2.2) | `lib/core/presets/mock/tapes/providers/*.yaml` |
| 5 | Tape volume mount in docker-compose (ADR-032 §2.2) | `docker-compose.dev.yml:99` |
| 6 | Mock seeder daemon (ADR-033 §1) | `docker/run.py` + `docker-compose.dev.yml:106-134` |
| 7 | Dockerfiles centralized in `docker/` (ADR-033 §2) | `docker/{dev,prod,vidaimock}.Dockerfile` |

## Findings

| ID | Priority | Status | Description | File:Line | Fix Applied |
|----|----------|--------|-------------|-----------|-------------|
| MOCK-001 | HIGH | Fixed | `_astream` bypasses VidaiMock streaming — fetches full response with `stream: False`, then re-trickles in Python with `asyncio.sleep(0.05)` per token. VidaiMock's SSE streaming capability is completely unused. Comment at lines 79-82 explains VidaiMock's whitespace splitter mangles structured JSON blocks. | `lib/providers/mock_chat_model.py:124,158-193` | Rewrote `_astream()` to send `stream: true` and iterate SSE `data:` lines via `httpx.AsyncClient.stream()`. `mock-coder-success.yaml` tape set to `stream.enabled: true`. VidaiMock v0.1.2 sends complete tool call chunks — no delta accumulation needed. |
| MOCK-002 | MED | Fixed | `mock-coder-human` tape emits `run_command` tool call instead of `session_request_permission`. ADR-032 §2.3 specifies the interrupt flow requires `session_request_permission`. The `mock-human-in-loop.toml` team sets `auto_approve = false` but the tape doesn't trigger the permission interrupt path. | `lib/core/presets/mock/tapes/providers/mock-coder-human.yaml:6`, `lib/core/presets/teams/mock-human-in-loop.toml:15` | Replaced `run_command` with `session_request_permission` tool call + JSON args with description + options array (optionId/name/kind) |
| MOCK-003 | MED | Fixed | No `__all__` declaration in `mock_chat_model.py`. `MockChatModel` not exported from `lib/providers/__init__.py` facade. Violates CLAUDE.md architectural mandate. | `lib/providers/mock_chat_model.py` (missing), `lib/providers/__init__.py` (missing) | Added `__all__ = ["MockChatModel"]` to mock_chat_model.py; added lazy import + `__all__` entry in providers/__init__.py |
| MOCK-004 | MED | Fixed | `_agent_config` stored as plain attribute after `super().__init__()`, not as Pydantic `PrivateAttr`. Won't survive `model_copy()` calls — worker node calls `model.model_copy(update={"permission_callback": ...})` which drops plain attributes. | `lib/providers/mock_chat_model.py:32`, `lib/core/nodes/worker.py:176` | Declared `_agent_config: AgentConfig \| None = PrivateAttr(default=None)` in class body; assigned after `super().__init__()` |
| MOCK-005 | MED | Open | Tapes are in `providers/` subdirectory (`/app/tapes/providers/*.yaml`) but VidaiMock `--config-dir /app/tapes` may expect flat files. Works only if VidaiMock scans recursively. Needs verification against VidaiMock docs. | `docker-compose.dev.yml:92,99`, `lib/core/presets/mock/tapes/providers/` | — |
| MOCK-006 | LOW | Fixed | Four `print(f"DEBUG: ...")` statements in production code. Should be `logger.debug()` to respect log level configuration. | `lib/providers/mock_chat_model.py:95,137,156,196` | Replaced all 4 print statements with `logger.debug()` calls |
| MOCK-007 | LOW | Open | `_agenerate` override manually accumulates `_astream` chunks into `ChatResult`. `ChatOpenAI` already provides this when `streaming=True`. The override may cause subtle behavioral differences from the parent class. | `lib/providers/mock_chat_model.py:59-74` | — |
| MOCK-008 | LOW | Fixed | Tape names minor divergence from ADR-032 §2.2 text. Actual 7 tapes: `mock-planner`, `mock-reviewer`, `mock-coder-success`, `mock-coder-fail-tool`, `mock-coder-human`, `mock-coder-invalid`, `mock-coder-loop`. | `lib/core/presets/mock/tapes/providers/` | Updated ADR-032 §2.2 tape list to exact 7 tape names |
| MOCK-009 | MED | Open | MockChatModel extends ChatOpenAI instead of BaseChatModel. ChatOpenAI brings OpenAI-specific validation (API key, model name) that doesn't apply to a mock and may cause spurious errors. Correct base class is BaseChatModel directly. May be folded into MOCK-001 scope or handled standalone after Batch 1. | `lib/providers/mock_chat_model.py:15` | — |

## VidaiMock Infrastructure Findings

| ID | Priority | Status | Description | File:Line | Fix Applied |
|----|----------|--------|-------------|-----------|-------------|
| VIDAI-001 | HIGH | Fixed | VidaiMock Dockerfile downloads `releases/latest` (currently v0.1.2) with no version pinning. Builds are non-reproducible. | `docker/vidaimock.Dockerfile` | Pinned to `releases/download/v0.1.2/vidaimock-linux-x64.tar.gz` |
| VIDAI-002 | MED | Open | v0.1.2 changelog: "Fix OpenAI Streaming Mock to Emit Proper Chunks and [DONE] Termination Event". May resolve the whitespace splitter concern in `mock_chat_model.py:82-86`. Python re-trickling workaround (MOCK-001) may no longer be necessary if tapes enable streaming. | `docker/vidaimock.Dockerfile`, `lib/providers/mock_chat_model.py:82-86` | — |
| VIDAI-003 | INFO | Open | All 7 tapes have `stream.enabled: false`. Streaming disabled at tape level, not just bypassed in Python. MOCK-001's Python re-trickling is the ONLY source of streaming behavior. | `lib/core/presets/mock/tapes/providers/*.yaml` | — |
| VIDAI-004 | LOW | Open | VidaiMock docs do not specify whether `--config-dir` scans subdirectories recursively. Tapes are in `providers/` subdirectory under mount point. Relates to MOCK-005. Needs empirical testing. | `docker-compose.dev.yml:92,99` | — |
| VIDAI-005 | INFO | Open | VidaiMock offers `benchmark` and `realistic` modes. Docker-compose uses `realistic` with `--latency 200`. No documentation on how modes interact with whitespace splitter for structured JSON content. | `docker-compose.dev.yml:92` | — |

## Architectural Gaps

| ID | Priority | Status | Description | File:Line | Fix Applied |
|----|----------|--------|-------------|-----------|-------------|
| ARCH-001 | HIGH | Fixed | model_copy drops _agent_config — VidaiMock URL routing lost, all workers hit wrong tape after copy. Resolved by MOCK-004 (PrivateAttr). | `mock_chat_model.py:32`, `worker.py:176` | Fixed by MOCK-004 in Batch 1 |
| ARCH-004 | MED | Fixed | MockChatModel lacks permission_callback — mock-human-in-loop HIL path never wired. | `worker.py:173` | Added `permission_callback: Any \| None = Field(default=None, exclude=True)` to MockChatModel class body; `hasattr(model, "permission_callback")` now returns True |
| ARCH-006 | LOW | Informational | Supervisor in mock topologies always hits mock-success-single tape (no agent_config passed to ProviderFactory). | `graph.py` supervisor resolution | — |
| ARCH-007 | LOW | Informational | mock-seeder autonomous=True means mock-human-in-loop runs same as mock-autonomous. | `docker/run.py:104` | — |

## Asset Inventory

| Asset Type | Count | Location |
|-----------|-------|---------|
| Agent TOMLs (mock) | 7 | `lib/core/presets/agents/mock-*.toml` |
| Team TOMLs (mock) | 7 | `lib/core/presets/teams/mock-*.toml` |
| YAML tapes | 7 | `lib/core/presets/mock/tapes/providers/` |
| Dockerfiles | 3 | `docker/{dev,prod,vidaimock}.Dockerfile` |
| Factory wiring | 1 | `lib/providers/factory.py:105-107` (`Provider.MOCK -> MockChatModel`) |
