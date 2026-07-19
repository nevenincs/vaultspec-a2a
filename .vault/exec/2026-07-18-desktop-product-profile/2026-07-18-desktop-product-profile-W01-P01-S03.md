---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S03'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Lock ACP 0.59.0 and eliminate stale JavaScript adapter identities from the Node closure

## Scope

- `package-lock.json`

## Description

- Ground the adapter identity and launch path in semantic RAG results and current source truth.
- Regenerate the npm lock twice in an isolated temporary project with engine enforcement.
- Install the locked production closure with `npm ci` in that isolated project.
- Exercise the production provider factory against the isolated project-local adapter entry point.
- Assert exact adapter and SDK archive pins and reject every stale adapter identity.

## Outcome

The adopted production lock has a single root dependency:
`@agentclientprotocol/claude-agent-acp` at the exact, range-free version
`0.59.0`. Its lock entry resolves the `0.59.0` registry archive with integrity
`sha512-GejLH5qxsI5IoSDfhyOVDEsRNxqi6y0Rcj5FstVeOwMACSht/bUXII0HILbzOQNoA5qlyZle3FRvf+CAjD7Rpg==`,
declares Node `>=22`, publishes `dist/index.js`, and pins
`@agentclientprotocol/sdk` to `1.2.1`. The SDK entry resolves the `1.2.1`
registry archive with integrity
`sha512-jwYUdOQR7tc+Zfch53VL4JJyUNK/46q03uUTYb+PjECsmnNl94XFXOfYLJ8RBpMNidXd1rpOAVgb0vqD98xImA==`.

Two isolated `npm install --package-lock-only` regenerations under Node
24.12.0 and npm 11.5.2 preserved SHA-256
`A1CF23FA9DC8D10B7261E9DD90BADDACEE84054ACF545DCB5E62CFF95B1984FF`.
An isolated, engine-strict `npm ci` installed 111 real packages and preserved
the same digest. The installed adapter reported version `0.59.0`, required
Node `>=22`, and contained its declared entry point.

The production `classify_provider_command` implementation selected the
project-local Node entry at
`node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js` from that
clean installation. Structural assertions passed for the exact root,
adapter, and SDK pins and confirmed that
`@zed-industries/claude-agent-acp`, `0.23.1`, and `0.20.2` do not occur in the
production lock.

## Notes

The canonical lock bytes were already present at step start as blob
`1c638b2a85f87ca03e57137a44faa4604a16f58e`, introduced by commit
`a7896cc`. Independent regeneration proved those bytes canonical, so this
adoption step did not manufacture a no-op lock diff or touch the shared
`node_modules` tree.

The semantic RAG index still returned the predecessor Zed adapter identity.
Current full-file inspection, Git provenance, isolated npm regeneration, the
installed package manifest, and real production-factory execution overrode
that stale retrieval result. The S03 plan row remains open for independent
review.
