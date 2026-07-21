---
tags:
  - '#reference'
  - '#capsule-install-layout'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-18-desktop-product-profile-plan]]'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #reference) and one feature tag.
     Replace capsule-install-layout with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `capsule-install-layout` reference: `wheel and npm install semantics, provenance, and the open sub-decisions`

Grounding for the install-layout decision: how a Python wheel and an npm
tarball must land in a relocatable, offline capsule tree, what the existing
code already proves, and the three facts the decision leaves open. Coding
agents implementing the layout authority, the provenance-bearing inventory,
and the materializer consult this document.

## Summary

### Wheel installation semantics (binary-distribution-format spec, PEP 427 lineage)

A wheel's archive-root members unpack into the scheme root selected by the
`Root-Is-Purelib` metadata flag. A `.data/` directory spreads its
`{purelib, platlib, headers, scripts, data}` subtrees onto the corresponding
sysconfig paths of the target environment. A conforming installer verifies
every member against `.dist-info/RECORD` (path, sha256, size) and rewrites
`#!python` script shebangs. For the bundled per-target CPython the purelib and
platlib scheme paths coincide, so `Root-Is-Purelib` true and false wheels land
identically under one library root. Source:
`packaging.python.org/en/latest/specifications/binary-distribution-format/`
(retrieved 2026-07-21).

### npm layout for the pinned ACP adapter

The npm dependency layout is already declared per package in the source
closure: `AcpPackageArtifact.install_path` pins each tarball's nested
`node_modules` destination and the graph is path-based
(`src/vaultspec_a2a/desktop/closure_inventory.py:344-431`, `:483-520`). npm's
own `.bin` symlink farm and hoisting need not be reproduced: the inventory
model admits only ordinary 0644/0755 files, and providers launch the adapter
by explicit path under the bundled Node runtime.

### What the existing code already proves (reuse, do not re-derive)

- `src/vaultspec_a2a/desktop/package_archives.py:463-548` proves `RECORD`
  completeness and per-member sha256/size for every closure wheel and retains
  the sorted member list as evidence (`:631`) — the layout authority derives
  installed records from these already-verified facts.
- `src/vaultspec_a2a/desktop/installed_inventory.py:120-133` — `InstalledFileRecord`
  carries only path/mode/size/sha256; `:144` — only `InstalledLicenseRecord`
  names a `source_member`; `:353` — `build_installed_closure_inventory` is
  test-only (no production caller); `:189-212` — the `tree_digest` preimage;
  `:505-547` — content-addressed load-time reconciliation; `:58-86`, `:215-288`
  — the portable-path grammar, 0644/0755-only modes, sorted-unique records, and
  80 000-file / 8 GiB bounds.
- `src/vaultspec_a2a/desktop/capsule.py:820`, `:918` — the generic projector's
  deliberate `"wheel installation is not a generic projection"` refusal;
  `:433-567` — the leased-descriptor nested-parent write path every capsule
  write must use; `:137-138` — the executable-bit mode-normalization rule.
- `src/vaultspec_a2a/desktop/manifest.py:524-527` — the contract pins the
  product launchers as `bin/{name}` (POSIX) and `Scripts/{name}.exe` (Windows);
  `:349-371`, `:856-859` — the two console-script references.
- `src/vaultspec_a2a/desktop/capsule_assembly.py:271-317`, `:507-515` — the
  landed planner reserves closure and generated-launcher destinations and
  trusts `InstalledClosureInventory` as the declared tree.
- `src/vaultspec_a2a/desktop/artifacts.py:1139-1155` — the source-to-installed
  join point the provenance extension must strengthen.

### Three open sub-decisions (must be resolved before the dependent step relies on them)

1. **`.data` closure audit.** No sweep exists of whether any locked desktop
   wheel ships `.data/` members or a non-trivial `Root-Is-Purelib: false`
   spread. The decision fails closed on unsupported `.data` keys, so
   correctness is safe today; relaxing that requires this audit first.
2. **Windows launcher source.** The contract pins `Scripts/{name}.exe`
   (`manifest.py:524-527`) but no launcher-stub asset exists in
   `scripts/desktop_capsule_inputs.toml`. The `.exe` sourcing — a
   content-addressed stub input versus a contract change to a script shim —
   needs a grounded reference fact before the Windows launcher is materialized.
3. **Entrypoints derivation.** The Python-closure `entrypoints` semantics
   (which installed file is promoted to 0755) are exercised only by test
   fixtures today (`src/vaultspec_a2a/desktop/tests/_capsule_inputs.py:228`);
   the derivation rule is new normative content, not recovered practice.
