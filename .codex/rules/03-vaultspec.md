---
name: 03-vaultspec
trigger: always_on
---

# Vaultspec workflow and ownership

- Ground significant work in the repository's current research, reference, ADR, plan, audit, and prior execution records before acting.
- Use the matching `vaultspec-*` skill and agent persona for each workflow phase. Execute only approved plans and one Step per implementation commit.
- Scaffold Vault artifacts through `vaultspec-core vault add`; update plan state through `vaultspec-core vault plan step` verbs; validate artifacts through Core rather than hand-authoring machine-owned metadata.
- Treat project-locked Vaultspec Core and RAG versions as execution authority. Ambient tools are diagnostic inputs only.
- Core exclusively owns framework Git-ignore policy and synchronization of canonical rules, agents, skills, system prompts, hooks, MCP definitions, and provider projections.
- Change canonical rule sources with `vaultspec-core spec rules` verbs and regenerate provider outputs with Core sync. Never hand-edit generated provider projections.
- Keep validation read-only. Formatting, synchronization, indexing, upgrades, and repairs require explicit maintenance commands.
- Run a formal code review against the actual implementation before closing any Step.
