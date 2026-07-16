---
tags:
  - '#audit'
  - '#test-double-closeout'
date: '2026-07-16'
modified: '2026-07-16'
related: []
---

# `test-double-closeout` audit: `test-double close-out`

## Scope

Owner directive: close out ALL test doubles in `vaultspec-a2a` (mocks, monkeypatches, patches, shims, fakes, stubs), per the standing hard mandate - "NO monkeypatching; if a feature is needed to wrangle environment, make it part of the official API", integration tests exercise real boundaries, no tautological tests. This audit records the remediation of the four confirmed violations and the explicit KEEP rulings for sanctioned constructs, so a future sweep does not re-flag them.

Remediation landed on `main` at commit `f9693a7` (fast-forward from `903777a`; single commit `test(src): replace monkeypatch doubles with real process/API boundaries`).

## Findings

### test-double close-out | negative-headline | no unittest / MagicMock / @patch anywhere in the tree

The codebase carries no `unittest` imports, no `MagicMock`/`Mock`, and no `@patch`/`mock.patch` usage. The only doubles present were `pytest.MonkeyPatch`-based env/attr mutation in four tests; all four are now removed. The residual scan over the three touched modules finds zero `monkeypatch`/`setattr`/`setenv`/`delenv` CALLS and no `unittest` import - the only surviving "monkeypatch" strings are explanatory comments.

### test-double close-out | high | workspace credential-scrub tests used ~12 monkeypatch.setenv

`src/vaultspec_a2a/workspace/tests/test_workspace.py` `TestCredentialScrubbing` injected secret-like env via ~12 `monkeypatch.setenv` calls, violating the file's own "no monkeypatching" docstring. FIX: a module-scoped `resolved_env` fixture spawns ONE real child process that runs the real `resolve_env_vars` over a parent-built environment (all secret keys, `VAULTSPEC_*`, both `CLAUDE_CODE_*` allow/deny sets, the Z.ai pass-through pair, a safe var). The seven tests each assert their own slice of the scrub/preserve contract against the one real snapshot, per-secret parametrization retained, every slice-assert carrying a message that names the var/guarantee. Expected sets derived from the scrub allowlist in `workspace/environment.py`, not from a run. The child return code is asserted zero with stderr surfaced.

### test-double close-out | high | telemetry sdk-disabled test was a frozen-at-import no-op plus isinstance tautology

`src/vaultspec_a2a/telemetry/tests/test_telemetry.py::test_configure_telemetry_sdk_disabled` set `OTEL_SDK_DISABLED` after import (the module constant is frozen at import, so the setenv did nothing) and asserted only `isinstance(..., bool)`. FIX: a subprocess probe imports and calls `configure_telemetry` with the env set BEFORE import; the disabled run asserts `sdk_available` True AND `sdk_enabled` False, a control run (var absent) asserts `sdk_enabled` True. Discriminates disabled-vs-absent; the return-code gate proves the child actually ran.

### test-double close-out | high | telemetry langsmith-off test carried a hidden COVERAGE BUG

`test_configure_telemetry_langsmith_off` deleted `LANGCHAIN_TRACING_V2`, but the product constant `_LANGSMITH_ENABLED` reads `LANGSMITH_TRACING`. The test touched the WRONG env var and, being frozen-at-import plus asserting only `isinstance(bool)`, would have passed regardless of either variable - a latent coverage gap the monkeypatch masked. FIX: a subprocess probe asserts the real `LANGSMITH_TRACING` read in both directions (absent -> False, `=true` -> True), closing the gap while riding the mechanism conversion.

### test-double close-out | high | logging Rich-path test patched sys.stdout/stderr.isatty

`src/vaultspec_a2a/utils/tests/test_logging.py::test_setup_logging_attaches_correlation_filter_rich_path` used `monkeypatch.setattr(sys.stdout, "isatty", ...)` to force the interactive Rich path. FIX (the only PRODUCT-code change): `setup_logging` in `src/vaultspec_a2a/utils/logging.py` gains a keyword-only `force_interactive: bool | None = None`. Default `None` reproduces today's exact auto-detect (`stdout.isatty() and stderr.isatty()`); an explicit bool overrides, with the `no_color`/`ci`/`force_json` guards still applied on top. It is a genuine, documented feature (deterministic Rich-path selection under a supervisor whose streams do not report as TTYs), not a test hook. The test drives `force_interactive=True`. A repo-wide grep confirmed no product caller passes the parameter, so the `None` default leaves every existing call unchanged.

### test-double close-out | keep | sanctioned constructs NOT to be re-flagged

The following are legitimate and must survive future double-hunts:

- Bucket B sanctioned recording / deterministic `BaseChatModel` implementations - real LangChain model subclasses used as genuine deterministic test doubles at the model seam, not `Mock`s.
- The graph `FakeChatModel` unit-isolation carve-out - a real model implementation used to isolate pure graph-node logic in unit tests (permitted unit-level isolation of pure logic), not an integration-boundary fake.
- `Provider.MOCK` - a PRODUCT enum member (the always-ready mock provider used by real run-start flows and evidence batteries), not test scaffolding.
- The streaming protocol duck-types guarded by protocol-drift checks - real structural types validated against the live protocol, not stubs.

## Recommendations

- No further action on the four remediated tests; they now exercise real process/API boundaries and are validated (ruff, ty, pytest 111 passed including deprecation-warnings-as-errors).
- Future test-double sweeps should treat the KEEP list above as settled and scope their search to `monkeypatch`/`setattr`/`Mock`/`@patch`/`unittest` CALL sites, ignoring the sanctioned model doubles and the `Provider.MOCK` product enum.
- Validation for this change used main's venv shadowed via `PYTHONPATH` because the `Y:` drive was full at landing time; a clean-venv re-run is optional and not required for correctness.
