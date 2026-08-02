---
tags:
  - '#plan'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:5a56d033627e810c9569223f765092f3a9adadb30bfac0d638a9c73b3a19be3b'
tier: L1
related:
  - '[[2026-07-15-model-profiles-adr]]'
---

# `model-profiles` plan

## Steps

- [x] `S01` - Add regression coverage for desired ACP model propagation and exact configuration RPC; `src/vaultspec_a2a/providers/tests/test_factory.py and ACP protocol tests`.
- [x] `S02` - Make every served fast profile resolve all roles to Model.LOW; `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml and vaultspec-solo-coder.toml`.
- [ ] `S03` - Retain desired model and negotiated configuration options in ACP session state; `src/vaultspec_a2a/providers/_acp_types.py and _acp_session.py`.
- [ ] `S04` - Select the negotiated ACP model config with configId and fail closed before prompts; `src/vaultspec_a2a/providers/acp_chat_model.py and _acp_session.py`.
- [ ] `S05` - Remove obsolete ACP session set model transport and malformed setter; `src/vaultspec_a2a/providers/acp_chat_model.py and utils/enums.py`.
- [ ] `S06` - Pass frozen concrete model names through compiler and factory without Kimi override; `src/vaultspec_a2a/providers/model_profiles.py graph/compiler.py and providers/factory.py`.
- [ ] `S07` - Prove factory compiler and preset resolution preserve explicit low models; `src/vaultspec_a2a/providers/tests and src/vaultspec_a2a/graph/tests`.
- [ ] `S08` - Route real provider tests through fast or direct Model.LOW with pre-spawn guards; `src/vaultspec_a2a/service_tests and src/vaultspec_a2a/providers/tests`.
- [ ] `S09` - Run a real ACP configuration handshake without prompting and reaping subprocesses; `src/vaultspec_a2a/providers/tests`.
- [ ] `S10` - Run focused static and live verification then review findings and update audit; `src/vaultspec_a2a/providers .vault/audit and plan execution records`.
