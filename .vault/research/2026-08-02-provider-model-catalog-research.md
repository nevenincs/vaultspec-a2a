---
tags:
  - '#research'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:b230ef01c76274fd2edf0320b712bf6739b3537c275438f295eab81ddff5975c'
related:
  - "[[2026-08-02-provider-model-catalog-reference]]"
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
  - "[[2026-07-15-model-profiles-adr]]"
---

# `provider-model-catalog` research: `cross-project provider model selection reconciliation`

Can Dashboard let a user choose the actual provider/model or a supported
reasoning level without hard-coding model identifiers, while A2A reports
truthful provider health? The infrastructure can support this only through a
provider-owned catalog contract above the invocation layer. ACP and several
provider APIs expose live choices; LangChain does not normalize discovery. The
governing A2A and Dashboard decisions conflict, so an explicit cross-project ADR
is required before implementation.

## Findings

### The accepted decisions conflict, and code follows the older one

Dashboard's owner amendment requires provider-free teams and a user-selected
provider and model at run start, with highest precedence:
`Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-08-01-a2a-agent-flow-adr.md:170-192`.
A2A's accepted model-profile ADR still requires a `profile_id`-only edge and
forbids model-name input: `.vault/adr/2026-07-15-model-profiles-adr.md:37-46`.
The older topology decision also rejects per-request overrides:
`.vault/adr/2026-02-27-team-composition-topology-adr.md:551`.

Code still carries `profile_id` Dashboard to A2A and statically maps
`low/mid/high/max` to provider ids. The related Reference inventories the path.
A new ADR must explicitly supersede the conflicting clauses rather than leave
two incompatible accepted truths.

### Direct selection is feasible without arbitrary caller strings

ACP lets an agent advertise ordered selectors categorized as `model`,
`thought_level`, and model-adjacent `model_config`, including current values and
live updates. Codex app-server exposes `model/list` with ordered reasoning
efforts and speed/service tiers. Claude and Gemini provide authenticated model
list APIs, while Kimi refreshes provider models and exposes model/thinking
selection through its CLI and ACP lane. These are runtime catalogs, not ids
authored in Dashboard code or team TOML.

A bounded option is a server-issued catalog entry: A2A enumerates through the
provider adapter, serves only returned entries, accepts only a served entry,
revalidates it at run start, and freezes the exact provider-issued value. A
provider that cannot enumerate reports `catalog_available=false`; it gets no
guessed static list. This permits direct user choice without accepting a free
string or retaining central hard-coded model policy.

### Model choice and level choice are different facts

A model list does not inherently define VaultSpec `low/mid/high/max`. OpenAI's
generic list has id/owner/availability; Gemini exposes supported actions;
Claude exposes supported effort values; Codex orders reasoning efforts; ACP
allows provider-defined thought/model controls. Levels must be surfaced only
with provider-owned provenance, never inferred from names, price folklore, or a
static cross-provider `MODEL_MAP`.

Persona levels can remain recommendations/default intent. An exact model and
supported effort selected by the user can take highest precedence. A selected
provider-defined level must resolve against the live catalog and freeze its
resulting exact assignment. The ADR still must choose whole-team selection or
per-role overrides; today's per-role frozen assignments can support either.

### LangChain is downstream of discovery

Installed `langchain-core@1.5.3` and `langchain-openai@1.4.1` accept a configured
model and expose configurable invocation fields and underlying clients. They do
not produce a portable catalog across ACP, Codex, Claude, Gemini, Kimi,
OpenAI-compatible, and Z.AI transports. Provider-specific discovery belongs in
the descriptor/registry architecture accepted by
`.vault/adr/2026-02-25-llm-context-provider-abstraction-adr.md:51`; LangChain
executes after catalog resolution.

### Health must be factual and multi-dimensional

Current readiness conflates configuration, executable resolution, and credential
presence; Dashboard cannot distinguish unavailable from unauthenticated. The
provider response needs independent configured, installed/resolvable,
authenticated-with-unknown, catalog availability/freshness, completed-turn
admission, and derived selectability facts. A successful no-completion
account/catalog/session probe can establish authentication; an environment
variable cannot. ACP auth methods, Codex `account/read`, and authenticated API
catalog requests provide lane-specific evidence. Completed-turn admission stays
separate because a valid login does not prove the harness can complete a turn.

### Options the ADR must settle

- Retain named profiles and improve health. Wire-cheap, but contradicts the
  Dashboard mandate and preserves static model ownership.
- Accept free-form provider/model strings. Flexible, but not bounded against
  account availability and unsuitable for the engine edge.
- Serve provider-owned catalogs and accept only offered entries. Evidence favors
  this because it combines direct choice, bounded input, provenance, and honest
  absence without hard-coded ids.
- Surface universal tiers. Feasible only as an optional provider-supplied
  projection; inferred universal tiers would fabricate semantics.

The ADR must also settle whole-team versus per-role choice, caching/freshness,
selection tokens and replay, catalog-change behavior, and explicit supersession.
No paid completion or credential-bearing live catalog request was made in this
pass; feasibility comes from code, installed contracts, prior live proofs, and
authoritative documentation.

## Sources

- `Y:/code/vaultspec-dashboard-worktrees/main/.vault/adr/2026-08-01-a2a-agent-flow-adr.md:170-192`
- `.vault/adr/2026-07-15-model-profiles-adr.md:37-46`
- `.vault/adr/2026-02-27-team-composition-topology-adr.md:551`
- `.vault/adr/2026-02-25-llm-context-provider-abstraction-adr.md:51`
- `.vault/reference/2026-08-02-provider-model-catalog-reference.md`
- `langchain-core@1.5.3`
- `langchain-openai@1.4.1`
- https://agentclientprotocol.com/rfds/session-config-options
- https://agentclientprotocol.com/rfds/model-config-category
- https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- https://platform.claude.com/docs/en/api/models/list
- https://code.claude.com/docs/en/model-config
- https://ai.google.dev/api/models
- https://moonshotai.github.io/kimi-cli/en/reference/slash-commands.html
- https://platform.openai.com/docs/api-reference/models/object?lang=curl
- https://reference.langchain.com/python/langchain-openai/langchain_openai
- https://reference.langchain.com/python/langchain/chat_models/base/init_chat_model
