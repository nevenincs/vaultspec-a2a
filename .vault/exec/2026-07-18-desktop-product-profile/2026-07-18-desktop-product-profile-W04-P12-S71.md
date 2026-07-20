---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S71'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S71 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Certify a clean installed capsule starts and stops the standalone vaultspec-mcp adapter under caller ownership and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_standalone_mcp.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Certify a clean installed capsule starts and stops the standalone vaultspec-mcp adapter under caller ownership

## Scope

- `src/vaultspec_a2a/desktop_tests/test_standalone_mcp.py`

## Description

- Add a service-marked installed-capsule gate following the established pattern:
  build the real wheel, install the locked base closure plus the wheel into a
  clean interpreter, and exercise the shipped standalone MCP console script from
  that installed environment.
- Prove the clean capsule ships the caller-invokable standalone MCP entrypoint and
  that its help text advertises the transport options a caller drives it with.
- Prove the adapter runs entirely under caller ownership: the test launches the
  console script directly over the streamable-HTTP transport, waits for it to bind
  its own loopback port, confirms it is alive, then terminates it and confirms the
  port is released - the adapter's whole lifecycle is the caller's to start and
  end, with no desktop gateway created in the test.

## Outcome

Two real-behavior tests pass (2 passed in ~12s on a warm build cache): the capsule
ships the caller-owned standalone MCP entrypoint, and the caller starts and stops
it as an independent process. A pre-flight check confirmed the streamable-HTTP
adapter binds without a live gateway (it connects to the gateway lazily on a tool
call, not at boot), so a bogus gateway URL is used to make the caller-only
ownership explicit. Lint, format, and type checks pass, and the wider desktop
baseline remains green. Because no desktop gateway is ever started in this gate,
the adapter is proven to run and be reaped entirely under caller ownership, never
launched or adopted by the desktop lifecycle - complementing the lazy-worker and
boot-spawn gates that already prove the gateway spawns only its own worker.

## Notes

The gate is service-marked because it runs a wheel build and provisions a clean
environment, consistent with the other installed-capsule gates. The standalone
adapter is exercised over streamable-HTTP rather than stdio because binding a
loopback port gives a clean, race-free started/stopped signal without an MCP
client handshake.
