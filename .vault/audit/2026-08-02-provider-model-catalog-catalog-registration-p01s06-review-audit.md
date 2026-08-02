---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:146cdabc2baf4654b454d38aabab8b5443d8d4acbad7da1c417d4838794907e4'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `catalog registration P01.S06 review`

## Scope

Formal review of P01.S06 factory-owned execution-mode catalog registrations, installed command contracts, Kimi Code 0.28.1 environment semantics, truthful unavailable behavior, execution/discovery alignment, direct real-behavior evidence, and shared-worktree collision handling.

## Findings

### cross-provider-zai-catalog | high | Resolved: Z.AI could borrow Claude wrapper choices

A concurrent factory variant registered the Z.AI lane through generic Claude-agent ACP discovery. A successful wrapper session could therefore publish Claude aliases as Z.AI choices without an independently proven Z.AI enumeration contract. The accepted registry binds both Z.AI and Zhipu to a static unavailable adapter with empty models and unknown authentication. The future billable Z.AI proof remains outside S06 and cannot authorize serving the lane.

### kimi-028-command-drift | high | Resolved: obsolete command shape could not match the installed runtime

The old factory pinned an unrelated Kimi version, depended on Git Bash, launched `kimi acp --config ...`, and treated legacy environment names as the runtime contract. Installed Kimi Code 0.28.1 exposes `kimi acp`, global `-m/--model`, and `kimi provider list --json`; it has no `--config` option. The factory now resolves the installed executable, discovers through the executable prefix, and executes an exact discovered alias as `kimi -m <alias> acp`.

### kimi-discovery-prefix | high | Resolved: ACP subcommand composition would make enumeration unreachable

Kimi provider discovery is a sibling command, not an ACP child. The registered adapter now passes only the resolved executable prefix to the Kimi catalog adapter, which owns `provider list --json`. Direct and installed-process tests protect that boundary.

### gemini-static-preselection | high | Resolved: discovery was constrained by a hard-coded model map

Gemini catalog discovery previously inherited a static `MODEL_MAP` value and the deprecated `--experimental-acp` spelling. The registration now opens current `--acp` without `--model`, allowing the installed provider to advertise its own choices. Exact execution still carries the separately selected value.

### openai-endpoint-split | high | Resolved: discovery and execution could target different API origins

The OpenAI catalog adapter uses the configured OpenAI-compatible base URL. `ChatOpenAI` construction now receives that same setting, so a selected catalog cannot come from one origin while execution silently targets another.

### kimi-ambient-override | medium | Resolved: inherited environment could change the effective provider or model

Workspace resolution now scrubs the legacy Kimi variables and the documented `KIMI_MODEL_*` family. Settings accept current names first and legacy key/base aliases only for migration, enforce the current temporary provider tuple as all-or-none, and reinject current names explicitly. Partial definitions fail readiness with a static reason; secrets do not enter diagnostics.

### execution-mode-vocabulary | medium | Resolved: generic mode labels could collapse distinct adapters

The registry uses exact lane keys: `claude-agent-acp:{node|binary}`, `codex-app-server`, `gemini-cli-acp`, `kimi-code-acp`, `openai-api`, `zai-claude-agent-acp:{node|binary}`, and `zhipu-openai-compatible-api`. Mock and deterministic providers are intentionally absent.

### reference-and-test-drift | medium | Resolved: lifecycle text and obsolete tests contradicted installed behavior

The reference now records Kimi Code 0.28.1 discovery, persisted and temporary configuration modes, exact registry keys, and the unavailable Z.AI/Zhipu boundary. Obsolete stub-style Kimi eligibility tests were replaced with real subprocess behavior. The repository rule forbidding fakes, stubs, monkeypatches, skips, and shadow logic remains satisfied.

### legacy-alias-contract | medium | Resolved after independent review

Independent review found that comments, `.env.example`, and the reference promised legacy `KIMI_API_KEY` and `KIMI_BASE_URL` migration fallback while Settings accepted only current names. Separate current and legacy Settings inputs now preserve the migration boundary without alias-source collapse. Effective properties choose a normalized nonblank current value first and otherwise a normalized nonblank legacy value. Current and legacy secret inputs are excluded from repr and model dumps, and the factory still re-injects only current `KIMI_MODEL_*` names.

### blank-current-migration-precedence | medium | Resolved after closure review

Closure review proved that `AliasChoices` treated a present blank current name as authoritative, so a copied `.env.example` could suppress an enabled legacy migration value. Kimi current and legacy inputs are now separate Settings fields; normalized effective properties fall through on blank or whitespace current values. Direct and real env-file tests cover blank, whitespace, both nonblank, neither present, and secret repr/model-dump safety.
### optional-kimi-definition-loss | medium | Resolved after independent review

Independent review found that workspace isolation scrubbed `KIMI_MODEL_MAX_CONTEXT_SIZE` and `KIMI_MODEL_CAPABILITIES` without Settings-owned reinjection, silently discarding installed Kimi Code 0.28.1 temporary-provider metadata. Settings now own both: context size is a positive bounded integer serialized canonically, and capabilities are normalized as nonblank unique bounded provider tokens in first-seen order and serialized comma-separated. Optional values without the required temporary tuple fail closed. Tests cover scrubbing, normalized explicit reinjection, bounds, invalid tokens, duplicates, legacy fallback, and current-name precedence.
### concurrent-factory-overwrite | medium | Resolved after ownership coordination

An external writer twice replaced the factory during S06, including reintroducing the cross-provider Z.AI adapter after an initial stable window. Work paused, the collision was reported, and reconciliation resumed only after an additional stable hash window and explicit owner direction. The accepted factory and test blobs were exact-staged, recorded, and verified byte-identical after static and behavior gates. The unrelated future Z.AI live-proof file was neither staged nor modified.

### shared-index-consumption | note | Preserved: concurrent commit atomically consumed the frozen S06 code payload

After exact staging and successful gates, concurrent commit `d4a75911` consumed the S06 payload together with its own unrelated provider change. No reset, amend, or history rewrite was attempted. The consumed S06 paths were `.env.example`; `control/config.py`; the two owned control tests; `providers/factory.py`; `providers/model_profiles.py`; the three owned provider tests; and the workspace environment plus its test. Factory remained `5698e35220b3246c298a6d39c4d223909872679a` before and after; factory tests remained `78365367f31b2bb19c30574df108d2f8de3c7555` before and after. HEAD, index, and worktree matched those frozen hashes when review began. The commit's `providers/conditions.py` change was unrelated to S06.

### future-selection-provenance | note | Deferred to S08/S09 without changing registration

The frozen run-level selection contract will distinguish outbound entry identifiers from response provenance and preserve bounded provider-native controls. That later serialization work does not alter S06's provider-owned registration or unavailable-lane boundary.

## Verification

- Ruff: pass on all owned Python files.
- BasedPyright: 0 errors, 0 warnings, 0 notes on all owned Python files.
- ty: pass on all owned Python files.
- Focused factory, settings, readiness, Kimi subprocess, environment, and example coverage: 124 passed after closure-review remediation.
- Provider adapter regression suite: 50 passed, 12 service tests deliberately deselected by the default marker expression.
- Explicit installed registered-lane service proof: 4 passed. Claude, Codex, and Gemini returned authenticated or not-applicable, available, non-empty catalogs without a prompt. Kimi Code 0.28.1 in an isolated empty home returned the exact truthful unavailable result and no models.
- Recorded staged/worktree blobs remained identical after gates: factory `5698e35220b3246c298a6d39c4d223909872679a`; factory tests `78365367f31b2bb19c30574df108d2f8de3c7555`.

Independent closure re-review returned PASS with zero open high, medium, or low findings. The reviewer verified all eight frozen remediation/lifecycle blobs before and after its gates, then passed 58 focused tests, Ruff, BasedPyright, ty, and scoped diff-check without editing or staging.
## Recommendations

- Keep Z.AI and Zhipu unavailable until each exact execution lane has independent prompt-free enumeration proof.
- Keep catalog authentication separate from completed-turn admission and later health/selectability derivation.
- Preserve provider-issued identifiers and controls; do not add fallback external model IDs to the factory.
- Re-run the installed registered-lane service proof when the installed CLI versions or persisted provider configuration changes.
