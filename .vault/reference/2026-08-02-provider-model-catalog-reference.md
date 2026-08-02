---
tags:
  - '#reference'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3fdc0ab24ef3ac8274801919af5bdab66dd5a50837e3d990982d6f09d3d8fd20'
related:
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
  - "[[2026-07-15-model-profiles-adr]]"
---

# `provider-model-catalog` reference: `provider model catalog and health integration reference`

This reference maps the current A2A and Dashboard catalog-selection path,
provider discovery surfaces, and health facts that can be reported without
spending a completion. It reflects the shared worktrees on 2026-08-02,
including the P01.S08 new-run admission contract.

## Summary

### Current cross-project path

- A2A `RunStartRequest` forbids extra fields and requires a stable `run_id` plus
  one explicit schema-v1 catalog selection. Optional override keys are bounded
  to the preset's required worker IDs and ordered fallbacks are capped at eight:
  `src/vaultspec_a2a/api/schemas/gateway.py`.
- Every primary, override, and fallback reference names an exact provider,
  execution mode, catalog revision, entry, and bounded native-control map.
  `profile_id`, missing schema versions, and arbitrary provider/model/control
  fields fail at the request boundary.
- Dashboard and the Rust pass-through carry the same literal
  `schema_version: 1` shape. Dashboard derives override keys from served
  `required_roles` and revalidates retained choices against the current catalog.
- Product preset TOMLs still encode provider lanes, and missing provider input
  can fall back to Claude: `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml:164`
  and `src/vaultspec_a2a/providers/model_profiles.py:85,218`.
- `Model` and every concrete provider mapping are static in
  `src/vaultspec_a2a/graph/enums.py:202-294`; resolution consumes that map in
  `src/vaultspec_a2a/providers/model_profiles.py:245`.

### Existing durable and architectural primitives

- Frozen assignments persist provider, capability, concrete `model_name`,
  fallback, provenance, and digest:
  `src/vaultspec_a2a/providers/model_profiles.py:610-666`. The compiler consumes
  the frozen name at `src/vaultspec_a2a/graph/compiler.py:154,266`.
- Run-start persists the normalized whole-team selection and a complete request
  digest. Replay canonicalizes omitted authoritative defaults from that persisted
  record without requiring the old catalog entry to remain current; a changed
  selection, override, fallback order, or control is refused.
- The accepted provider-abstraction architecture assigns model catalog and auth
  metadata to provider descriptors/registry. P01.S06 implements that boundary as
  exact provider-and-execution-mode registrations in
  `src/vaultspec_a2a/providers/factory.py`; an unverified lane remains registered
  but unavailable rather than borrowing another lane's catalog.
- ACP setup receives `configOptions`, locates the model-category option, and can
  set and verify a value before prompt:
  `src/vaultspec_a2a/providers/_acp_session.py:36-111`. This is an execution
  handshake for a preselected value, separate from the prompt-free served catalog endpoint.

### Provider discovery surfaces

| Lane | Authoritative discovery surface | Metadata available | Boundary |
|---|---|---|---|
| Generic ACP | session `configOptions`: `model`, `thought_level`, `model_config` | ordered opaque values, labels, descriptions, current/default values, adjacent controls | session-scoped; absence must remain absence |
| Codex CLI | app-server `model/list` and `modelProvider/capabilities/read` | models, ordered reasoning efforts, speed/service tiers, defaults, upgrade metadata | registered prompt-free through `codex-app-server` |
| Claude API | authenticated `GET /v1/models` | ids, names, limits, capabilities, supported effort values | Claude Code subscription choices should come from its ACP/config picker |
| Claude Code | ACP/config picker or `/model` | account-appropriate choices, aliases, default, managed restrictions | aliases move; preserve provider-issued values |
| Gemini API | authenticated `models.list` / `models.get` | supported actions and extended metadata | filter only by explicit `generateContent`; do not infer tiers |
| Kimi Code 0.28.1 | `kimi provider list --json` on the resolved executable, then exact `-m <alias> acp` selection | configured aliases; provider-defined thinking capability fields when present | current host persisted config is empty; discovery reports unavailable without inventing aliases |
| OpenAI API | authenticated `GET /v1/models` | `object: list`; model `id`, `created`, `object: model`, `owned_by` | S05 maps only `id`; no capabilities, controls, reasoning tiers, or chat suitability |
| Z.AI / Zhipu API | no verified official model-list contract in this pass | invocation docs list selected products | report catalog unavailable unless the endpoint or ACP advertises choices |

P01.S06 registers the external execution lanes explicitly: `claude-agent-acp:{node|binary}`,
`codex-app-server`, `gemini-cli-acp`, `kimi-code-acp`, `openai-api`,
`zai-claude-agent-acp:{node|binary}`, and `zhipu-openai-compatible-api`.
Claude, Codex, Gemini, Kimi, and OpenAI use their own prompt-free adapters. Z.AI
and Zhipu have no independently proven enumeration surface in this pass, so their
registrations return empty unavailable catalogs with unknown authentication.
Internal mock and deterministic providers are not registered. Catalog success is
never treated as completed-turn admission.
P01.S07 serves these registrations through authenticated
`GET /v1/provider-catalog?workspace_root=...`. The route requires one absolute,
existing directory, canonicalizes it for adapter cwd and cache identity, and
rejects caller-selected refresh or unknown query input. A process-wide service
bounds canonical workspace scopes to sixteen and seats one S01 single-flight
cache per scope. Public JSON carries `api_version: v1`, catalog
`schema_version: 1`, separate configured/transport/authentication/catalog/admission
facts, derived selectability, effective expiry, models, and native controls.
Internal model and option `provider_value` fields never leave A2A. Public opaque
identifiers obey the Rust edge's 512-character bound and control identifiers its
128-character bound; an invalid lane is isolated before cache insertion.

Catalog admission is exact-mode and deny-by-default. Only `codex-app-server`
currently has an intrinsically execution-mode-specific completed-turn citation.
Claude and Z.AI provider-level citations do not capture the runtime-configurable
ACP backend, so neither node nor binary catalog lanes inherit that evidence.

P01.S08 consumes that served truth at both prepare and create. A selection is
admitted only when its canonical workspace still serves the exact lane as
selectable, the catalog is available and unexpired, its revision matches, the
entry remains a member, and every supplied control option is attached to that
entry. Advertised control defaults are inserted into the normalized selection;
unsupported controls and options are never inferred. Required worker IDs must
be unique and number between one and sixty-four before overrides or capacity are
accepted. The complete normalized selection is persisted under
`provider_catalog_selection` and included in prepare, commit, and same-ID replay
identity. Legacy `model_profile` records remain readable for old-run restart but
are not accepted as new-run policy. P01.S09 owns exact provider-native value
freezing through compilation, modern restart, and frozen-assignment disclosure.

Kimi Code configuration has two distinct modes. Persisted aliases live under the
normal Kimi home, optionally relocated by `KIMI_CODE_HOME`. A temporary in-memory
provider requires the complete current tuple `KIMI_MODEL_NAME`,
`KIMI_MODEL_API_KEY`, and `KIMI_MODEL_BASE_URL`; optional
`KIMI_MODEL_MAX_CONTEXT_SIZE` and `KIMI_MODEL_CAPABILITIES` remain provider-owned but are explicitly bounded: context size is a positive 32-bit integer serialized canonically, while capabilities are normalized as at most sixteen unique bounded provider tokens in first-seen order and serialized as the comma-separated form the CLI expects.
Legacy KIMI_API_KEY and KIMI_BASE_URL are accepted only as settings migration
inputs. A nonblank current value wins; blank or whitespace current input falls
through to a nonblank legacy value. Legacy and current ambient values are
scrubbed before the factory re-injects only the normalized Settings-owned current
names. Discovery invokes the executable prefix only, never
`kimi acp provider ...`, and exact execution selects the discovered alias with
`-m`. No external model identifier is hard-coded.

The OpenAI-compatible S05 adapter deliberately projects only each opaque `id`
into `ModelCatalogEntry`. It discards `created` and `owned_by` because the
normalized entry has no corresponding fields and never repurposes them as
descriptions, capabilities, or controls. Discovery derives `/models` from the
lane-configured base URL, requires one exact HTTP 200 complete-list response,
refuses redirects, partial responses, and pagination signals, bounds credentials
and response/model/identifier sizes, emits static errors, and closes HTTP
resources on timeout or cancellation.

LangChain is an invocation abstraction here. `ChatOpenAI` accepts a model
string and exposes an underlying OpenAI client;
`init_chat_model(..., configurable_fields=...)` makes application fields
runtime-configurable. Neither is a cross-provider catalog. Discovery belongs
in provider descriptors beside LangChain, not a hard-coded LangChain mapping.

### Health currently served and required separation

`ProviderReadiness` remains a legacy profile-readiness aggregate, but P01.S07 does
not use it to populate catalog health. Each factory discovery result carries typed
configuration and transport evidence independently beside authentication and
catalog state. Missing commands affect transport only; explicit credentials or a
complete temporary provider definition affect configuration only; absent evidence
stays unknown. Successful authentication or catalog discovery may strengthen the
observed axes without becoming completed-turn admission.

The served health record exposes `configured`, `transport`, `authentication`,
`catalog`, exact-lane `admission`, derived `selectable`, bounded safe reasons, and
`checked_at`. Selectability is true only when configuration and transport are
available, authentication is authenticated or not-applicable, the catalog is
available and fresh, and that exact provider-plus-execution-mode lane is admitted.
Dashboard independently rechecks catalog status, revision, checked time, and
expiry before allowing a selection.
### Authoritative external references

- ACP config options: https://agentclientprotocol.com/rfds/session-config-options
- ACP model config category: https://agentclientprotocol.com/rfds/model-config-category
- Codex app-server: https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- Claude API models: https://platform.claude.com/docs/en/api/models/list
- Claude Code model configuration: https://code.claude.com/docs/en/model-config
- Gemini API models: https://ai.google.dev/api/models
- Kimi model selector: https://moonshotai.github.io/kimi-cli/en/reference/slash-commands.html
- OpenAI API models: https://platform.openai.com/docs/api-reference/models/object?lang=curl
- LangChain OpenAI: https://reference.langchain.com/python/langchain-openai/langchain_openai
- LangChain runtime configuration: https://reference.langchain.com/python/langchain/chat_models/base/init_chat_model
