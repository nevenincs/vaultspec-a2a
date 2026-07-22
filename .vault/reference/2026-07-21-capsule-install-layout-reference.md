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

1. **`.data` closure audit — DONE (2026-07-21), resolved by the ADR revision.**
   All 144 unique wheels across the four shipped targets (closure 82/82/82/84,
   resolved from the committed `uv.lock` via the landed selection code, each
   fetched and sha256-verified against its lock pin) were opened and scanned for
   `.data/` members. Findings: exactly three required packages ship `.data/`
   content, and no wheel ships `.data/data` or `.data/platinclude`. `greenlet`
   3.5.3 ships `greenlet-3.5.3.data/headers/greenlet.h` on all four targets (a
   compile-time C header). `jsonpatch` 1.33 (`jsondiff`, `jsonpatch`) and
   `jsonpointer` 3.1.1 (`jsonpointer`) ship `.data/scripts` console scripts with
   literal `#!python` shebangs on all four targets (transitive langchain-core
   dependencies). `pywin32` 312 ships `.data/scripts/pywin32_postinstall.py` and
   `pywin32_testall.py` (plain, no shebang) on Windows. The guard is thus live -
   this exact closure would fail closed at materialization today. Ruling: the
   capsule is a library runtime whose only executable surface is its two product
   launchers, so `.data/headers` (build-time only) and `.data/scripts`
   (third-party CLIs and install helpers) are dropped, and the packages'
   importable `purelib`/`platlib` code still installs in full; `.data/data`,
   `.data/platinclude`, and unknown keys stay fail-closed. Re-audit on every lock
   change. Raw per-wheel evidence was captured during the audit in
   `scratchpad/unique_wheels.json` and `scratchpad/data_findings.json` (scratch,
   not vault artifacts).
2. **Windows launcher source — RESOLVED (2026-07-21) by the ADR revision.**
   The contract pins `Scripts/{name}.exe` (`manifest.py:524-527`) and stays
   unchanged; the launcher is composed from a content-addressed stub input.
   Grounding facts, retrieved 2026-07-21: pip and distlib build every
   `console_scripts` executable as stub bytes plus a shebang line plus a zipapp
   (`launcher + shebang + zip_data` in distlib's `scripts.py` on master), and
   CPython executes the appended zip so its `__main__` fully controls
   `sys.path` before importing the entrypoint. The stub's shebang parser
   accepts a `<launcher_dir>` token making the executable relocatable relative
   to its own directory, and the shebang may carry interpreter arguments, so
   isolated-mode parity with the POSIX launcher is expressible there. The
   console stubs (`t32`, `t64`, `t64-arm`) ship inside the distlib wheel;
   distlib 0.4.3 (2026-06-12) is licensed PSF-2.0, permitting redistribution
   with notice retention. Only one Windows target exists among the five
   (`x86_64-pc-windows-msvc`), so exactly one stub architecture is required.
   The build concatenates the bytes itself, so distlib is a stub donor, never a
   build- or run-time dependency, and output stays byte-identical. On Windows
   the standalone interpreter layout has no `bin/` segment
   (`runtime/cpython/python.exe`).
3. **Entrypoints derivation.** The Python-closure `entrypoints` semantics
   (which installed file is promoted to 0755) are exercised only by test
   fixtures today (`src/vaultspec_a2a/desktop/tests/_capsule_inputs.py:228`);
   the derivation rule is new normative content, not recovered practice.
