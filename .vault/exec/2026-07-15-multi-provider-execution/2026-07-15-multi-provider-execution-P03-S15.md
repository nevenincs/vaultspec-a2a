---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S15'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Author or extend a team profile assigning distinct providers per role (researcher=codex, synthesist=claude, adr-author=zai) on the vaultspec-adr-research preset

## Scope

- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`

## Description

Extended the shared `vaultspec-adr-research` preset with two mixed-provider model
profiles, purely additively (new profile blocks only; team-defaults and fast are
byte-unchanged, both still resolving all-claude).

- `codex` profile: researcher, synthesist, and adr-author pinned to the `codex`
  provider; the inner doc-reviewer falls through to the team default (claude). A
  genuinely mixed codex/claude collaboration where both materialized documents are
  codex-authored.
- `zai` profile: the same three research/authoring roles pinned to `zai`; the
  doc-reviewer keeps claude. Credential-gated - the acceptance harness skips this
  lane with a truthful reason naming the missing `ZAI_AUTH_TOKEN`, never faked.

The re-dispatch's exact split (researcher=codex, synthesist=claude, adr-author=zai)
degrades under a missing Z.ai credential; the achievable, team-lead-approved
ambition is the mixed codex/claude profile, which proves cross-provider
coordination live (see S16). The per-role `provider` overlay resolves through the
same `resolve_effective_assignment` precedence chain the gateway freezes at
run-start (`source=profile` attribution disclosed).

## Outcome

Both profiles land and resolve correctly: `codex` -> the three authoring roles on
codex, doc-reviewer on claude; `zai` -> the three on zai, doc-reviewer on claude.
Regression confirmed the additive change left team-defaults and fast resolving
all-claude, so the existing Claude acceptance lanes are provably untouched.

## Notes

The profiles live in the bundled `vaultspec-adr-research.toml`, a preset the
existing live-mixed Claude lane also uses; keeping the change additive was the
explicit constraint. Provider readiness needed no change: Provider.CODEX readiness
is command-resolvability only (already landed in P02), Provider.ZAI already gates
on the token.
