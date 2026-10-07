---
tags:
  - '#adr'
  - '#codebase-remediation'
date: '2026-10-07'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:cc42040c9cd25df476579db49caec6c7bf67a72b61a948f9a36a003fde637fd6'
related:
  - "[[2026-10-06-codebase-remediation-audit]]"
  - "[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]"
  - "[[2026-03-31-decoupled-mockllm-adr]]"
  - "[[2026-08-04-canonical-homes-adr]]"
  - "[[2026-10-04-container-release-native-production-adr]]"
  - '[[2026-03-29-infra-config-phase2-adr]]'
  - '[[2026-10-07-codebase-remediation-task-queue-retirement-adr]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
---
# `codebase-remediation` adr: `one deterministic fixture lane behind a lane-plugin seam; shipped artifacts carry product code only` | (**status:** `accepted`)

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

## Problem Statement

Three model stand-ins do one job, and the product ships them. VidaiMock with `MockChatModel` and its tapes, the in-process deterministic model, and the langchain fake chat models with `_StubProviderFactory` each stand in for a provider. Only the deterministic lane uses the real seams (R6-F3, R6-F15). Both fixture chat models ship in the wheel, and a production graph branch keys on the mock model's type string (R6-F4). The PyInstaller onedir is frozen from an editable install, and no gate proves it holds no test content (R6-F17). Acceptance run bundles are committed under `src/` (R6-F5). One deterministic fixture preset is missing from the wheel excludes (X1). The findings are recorded in `2026-10-06-codebase-remediation-audit`.

Paths are relative to `src/vaultspec_a2a/` unless they start with a repository-root entry.

## Considerations

- The deterministic lane already drives the real `permission_callback` seam plus tool-call, failure, cancel-window and relay-burst scenarios through the real factory (`providers/deterministic_chat_model.py:46-66,243-301`). VidaiMock adds only supervisor routing (R6-F3).
- The mock lane needs a production special case: `graph/nodes/_worker_tool_calls.py:95-170`, keyed on `_llm_type == "mock-chat-model"` at `:116` and called at `:200`.
- The wheel denylist excludes `testing/` and most fixture presets, but neither fixture chat model and not `team/presets/teams/vaultspec-adr-research-clarify.toml` (`pyproject.toml:229-267`).
- The onedir is frozen from `uv sync --locked --no-default-groups --group freeze` (`.github/workflows/release.yml:195`), which is an editable install, with `collect_all("vaultspec_a2a")` (`packaging/pyinstaller/vaultspec-a2a.spec:81-85`). Whatever sits under the package root is frozen.
- The gateway spawns the worker with `os.environ.copy()` (`control/worker_management.py:137,166`). One environment reaches both processes, and the worker is where models are built.
- `2026-08-04-canonical-homes-adr` rules that `testing/` is wheel-excluded and that no production module imports it. The static import guard `tests/test_wheel_import_boundary.py` cannot see a module named in a runtime string.
- The cross-repository consumer runs A2A from a source checkout and selects the lane by provider id `deterministic` and execution mode `in-process-deterministic` (dashboard `frontend/e2e/agent/harness.ts:100,263,423`).

## Considered options

- **Deterministic lane only, moved to `testing/`, armed through a seam a product install cannot reach.** Chosen. One stand-in remains and no fixture code ships. It costs a product registration seam and the migration of the VidaiMock-backed tests.
- **Keep the deterministic lane in the product as a declared certification capability, and delete only VidaiMock and the mock lane.** Rejected. It is smaller, but fixture code and its scripted branches keep shipping, which the product does not require.
- **Keep all three mechanisms.** Rejected. The duplication and the fixture branch in the production graph persist.
- **Register the lane through `pytest11` or `[project.entry-points]`.** Rejected. Entry points land in the wheel's `entry_points.txt` and would point at an excluded module, which is dangling metadata.
- **Import `vaultspec_a2a.testing` conditionally from product code.** Rejected. It reverses the dependency direction the boundary guards police.
- **Add test-only entry modules.** Rejected. They still need an environment-selected worker command, so they need the same seam with more surface.

## Constraints

- Exactly one scripted in-process fixture lane exists: the deterministic lane. Its code lives under `src/vaultspec_a2a/testing/`.
- These are removed: VidaiMock (`service/docker/vidaimock.Dockerfile` and the `vidaimock` service in `service/docker-compose.integration.yml`), `MockChatModel`, the tapes under `team/presets/mock/`, the mock agent and team presets, `Provider.MOCK`, the `mock_api_base` setting with `DEFAULT_MOCK_API_BASE`, the mock branch at `graph/nodes/_worker_tool_calls.py:95-170` with its call at `:200`, the langchain fake chat models in tests, and `_StubProviderFactory`. Compose keeps Jaeger.
- Product code never names `vaultspec_a2a.testing`, neither by import nor by string constant. No production branch keys on a fixture lane's identity or model type.
- Product exposes one generic lane-registration protocol and one setting, `lane_plugins` (`VAULTSPEC_A2A_LANE_PLUGINS`): a comma-separated list of module paths. Each named module must expose `register_lanes(registry)`.
- Product honours `lane_plugins` only when `serve_in_process_lanes` is armed and `desktop_profile_armed` is false. Each of these is a typed startup refusal, never a silent skip: a non-empty value outside that double arm, a module that fails to import, and a module without `register_lanes`.
- The setting reaches the worker only through the environment the gateway hands it (`control/worker_management.py:137,166`). No second propagation channel is added.
- A registered lane is admitted and served only while the double arm holds. Registration grants no served eligibility outside it. It is no exception to the completed-turn admission rule for product lanes.
- The deterministic lane keeps its wire identity: provider id `deterministic`, execution mode `in-process-deterministic`, model `deterministic`.
- Entry points are not used for lane registration.
- The wheel and the PyInstaller onedir carry product code only. Gates enforce both. The wheel gate is the component-contract check, which builds a real clean-commit wheel. The binary gate is a release check that walks the real onedir. Neither artifact contains `testing`, `acceptance`, any `tests` or `*_tests` tree, the deterministic model, or a fixture preset.
- Committed acceptance run bundles are never stored under `src/`. Acceptance runs write their bundles to an untracked root.
- Affected prior ruling: D-06 of `2026-03-29-infra-config-phase2-adr` kept `_StubProviderFactory` and `FakeChatModel` because VidaiMock covered execution paths. This decision reverses D-06; that record needs a matching amendment.
- Affected prior wording: `2026-10-04-container-release-native-production-adr` and the 2026-10-04 production scope correction in `2026-03-20-service-lifecycle-architecture-adr` name VidaiMock as a Compose development fixture. After this decision Compose carries Jaeger only.

## Implementation

We will consolidate every model stand-in onto the deterministic lane. We will move that lane out of the product behind an inverted registration seam.

- **Product side.** `providers/` declares the registration protocol and the registry. The in-process lane machinery is driven by registered lanes instead of named fixture providers. That machinery is in `providers/factory.py`, `providers/in_process_catalog.py`, `providers/lane_admission.py`, `providers/provider_catalog_service.py` and `providers/provider_readiness.py`. The setting is declared in `control/infra_config.py`, `control/env_registry.py` and `.env.example`; `control/tests/test_env_example_coverage.py` enforces that.
- **Testing side.** The deterministic model moves under `testing/`; the working hypothesis is `testing/lanes/`, whose package implements `register_lanes`. The test boot environment builders set `VAULTSPEC_A2A_LANE_PLUGINS` wherever they set `VAULTSPEC_A2A_SERVE_IN_PROCESS_LANES=true` outside the desktop profile. In-process tests seat it through the settings override.
- **Consolidation.** The deterministic lane gains supervisor-routing and loop scenarios. The VidaiMock-backed service tests move to deterministic presets. The deterministic lane, selected through the real `ProviderFactory`, replaces the langchain fakes and `_StubProviderFactory`.
- **String-import guard.** A guard rejects any string constant in a shipped module that names a wheel-excluded package. It derives the excluded set from the same `pyproject.toml` excludes that `tests/test_wheel_import_boundary.py` reads. This closes the runtime-string bypass of the static import guard.
- **Order.** The onedir exclusion of test content lands before the deterministic model moves into `testing/`. Otherwise `collect_all` over the editable install would freeze it.
- **Fixture presets.** Fixture presets stay source-only. They are covered by the wheel denylist or moved under `testing/`, and the denylist gains `vaultspec-adr-research-clarify.toml`. The gates assert absence from the artifacts, not a source location.
- **Hypotheses.** The protocol's member set (catalog registration, execution mode, model constructor, readiness) may change within the constraints above.
- **Unknown.** It is not yet known whether `Provider.DETERMINISTIC` can leave the product `Provider` enum (`graph/enums.py:239`) without a wider vocabulary change, since presets parse their provider into that enum. If the member stays, it stays as a name only, with no product branch attached.
- **Unresolved.** Where the one approved acceptance bundle lives is an owner question (O4 in `2026-10-06-codebase-remediation-plan`).

## Rationale

The deterministic lane is the only stand-in that exercises the real seams, so keeping it and deleting the other two removes duplication without losing coverage (R6-F3, R6-F15). Moving it into `testing/` removes code the product does not require (R6-F4).

The inverted seam keeps the dependency direction the boundary guards police: the product knows a protocol, never the test package. Entry points would put a reference to an excluded module into shipped metadata.

Control of the environment already implies control of the process (`PYTHONPATH` and every `VAULTSPEC_A2A_*` setting), so a plugin named in the environment adds no new authority. Three things keep the seam closed on product installs: the double arm, the desktop-profile refusal, and the onedir carrying no `testing/` to load.

## Consequences

- One stand-in mechanism remains. The production graph has no fixture branch, and no fixture code ships in the wheel or the binary.
- The CI `native-integration` job no longer needs a VidaiMock image. Compose provides Jaeger only.
- Cost: the VidaiMock-backed service tests and 11 fake-model test files migrate (R6-F15).
- Cost: the dashboard e2e launch must also set `VAULTSPEC_A2A_LANE_PLUGINS`. That is a cross-repository change, announced with the remediation's second contract event.
- Desktop-profile gateways serve no plugin lane. Some desktop suites fetch an in-process selection under the armed profile today: `desktop_tests/_catalog.py`, `desktop_tests/test_worker_provenance.py:145,276` and `desktop_tests/test_owned_process_tree.py:291`. They must build their refused-run requests without a served fixture lane. Desktop execution is already refused before selection validation (`control/provider_execution.py:18`, `api/routes/_gateway_run_start.py:255,558`).
- Excluding `vaultspec-adr-research-clarify.toml` leaves shipped installs with no preset that declares `[team.clarification]`.
- `2026-10-07-codebase-remediation-task-queue-retirement-adr` removes the queue-tool lane and the deterministic tool-call scenario. Together with the mock branch removed here, `graph/nodes/_worker_tool_calls.py` keeps no node-owned tool-call lane.
- `2026-03-31-decoupled-mockllm-adr` is rejected in favour of this decision. `2026-03-31-integration-testing-smoke-tests-api-verification-adr` is amended: the deterministic lane is the certification replay.
- Reconsider this decision if desktop native execution is qualified and a desktop-profile certification lane becomes necessary. Reconsider it if a product install ever needs a scripted lane.
