---
tags:
  - '#adr'
  - '#capsule-install-layout'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - '[[2026-07-18-desktop-product-profile-adr]]'
  - '[[2026-07-18-desktop-product-profile-plan]]'
  - '[[2026-07-21-capsule-install-layout-reference]]'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace capsule-install-layout with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     Status convention: the H1 status value is one of proposed, accepted,
     rejected, superseded, or deprecated. A new ADR starts as proposed; it
     moves to accepted or rejected when the decision is made; it becomes
     superseded when a later ADR replaces it (set by vault adr supersede,
     which also records superseded_by); and deprecated when it is retired
     without a direct successor.

     Amend vs supersede: refinements and concretization rewrite the accepted
     record's body in place (modified: carries the revision); a new ADR with
     supersession is only for a major pivot. One accepted record per
     decision.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `capsule-install-layout` adr: `one wheel-aware install-layout authority with a provenance-bearing installed inventory` | (**status:** `accepted`)

## Problem Statement

The landed capsule assembly planner trusts the installed closure inventory as
the declared installed tree and reserves every closure destination from it, but
nothing in production builds that inventory: its builder is called only from
test fixtures that declare arbitrary paths, and the file record carries no
per-file byte provenance. The bounded projector deliberately refuses generic
wheel installation and offers only verbatim prefix projection. The materializer
(plan step `W01.P03.S103` of `2026-07-18-desktop-product-profile-plan`) must
therefore write wheel and npm bytes into the capsule with no authority defining
where each byte lands or which source member produced it, and no way to
reconcile the written tree byte-exactly against a declared inventory. The
grounding for these facts and the wheel/npm install semantics lives in
`2026-07-21-capsule-install-layout-reference`. This record decides the
canonical install-layout authority, the production inventory builder, and the
provenance model, within the capsule boundary governed by
`2026-07-18-desktop-product-profile-adr`.

## Considerations

- The governing record requires a relocatable, offline, target-specific capsule
  that runs without system Python, pip, `uv`, or npm across five targets
  (`2026-07-18-desktop-product-profile-adr`).
- Wheel installation is spread-plus-`RECORD` semantics, not prefix projection;
  npm layout is already declared per package; source verification already proves
  `RECORD` completeness and retains member evidence
  (`2026-07-21-capsule-install-layout-reference`).
- Every capsule write must flow through the leased-descriptor filesystem
  authority already used by the projector
  (`2026-07-21-capsule-install-layout-reference`).
- The installed inventory is a content-addressed release input reconciled
  against its descriptor on load, so a format change is a version bump of that
  artifact, not an in-place mutation
  (`2026-07-21-capsule-install-layout-reference`).
- The parallel-implementation hazard is the motivating anti-pattern: if the
  materializer computed layout independently of the inventory builder,
  reconciliation would compare two implementations rather than the tree against
  one declaration.

## Considered options

- **One layout authority feeding a provenance-bearing inventory; the
  materializer consumes only the inventory — chosen.** A pure install-layout
  module maps verified archive members to installed destinations; the production
  builder applies it once at build time and persists the result; the record is
  extended so every file names its source archive and member; the materializer
  replays inventory records byte-for-byte. One definition, two consumers,
  byte-exact reconciliation by construction.
- **Generalize the verbatim projector to wheels.** Rejected: wheel installation
  is spread-plus-`RECORD` semantics; this is exactly the case the projector
  refuses, and weakening the guard would silently install `.data` members at
  wrong paths.
- **Vendor a standard wheel installer at build time and inventory the result.**
  Rejected: such tools target a live interpreter's sysconfig scheme, mutate
  `RECORD`, and expose no per-member provenance, so the materializer would
  replay a tree it cannot derive from records; it also adds a dependency whose
  layout policy this project would still have to constrain.
- **A separate provenance authority beside the unchanged inventory.** Rejected:
  a keyed sidecar splits one fact across two documents, reintroduces join drift,
  and prevents the model validator from atomically cross-checking file, license,
  and provenance identity as the inventory does today.

## Constraints

- The installed tree obeys the existing dashboard grammar: portable NFC ASCII
  paths, 0644/0755 modes only, sorted unique records, and the 80 000-file and
  8 GiB bounds. No symlinks, junctions, or empty directories are declarable or
  materializable (`2026-07-21-capsule-install-layout-reference`).
- The capsule layout roots are fixed by the landed plan: `runtime/python` and
  `runtime/acp` closure roots beside the verbatim `runtime/cpython` and
  `runtime/node` interpreter subtrees.
- Unsupported wheel features fail closed: `.data/headers` and `.data/data`
  members, shebang-rewriting scripts, and any unplaceable member raise a named
  build error; nothing is skipped or best-effort placed.
- Determinism: identical verified inputs must yield byte-identical inventories
  and capsule trees (canonical JSON, sorted members, normalized modes, epoch
  timestamps).
- Materialization performs no network access and mutates only through the
  leased-descriptor authorities; the generic projector's wheel refusal remains
  in force verbatim — this record adds the non-generic path beside it rather
  than overriding it.
- Two sub-decisions remain consciously open and must be grounded before the
  dependent step relies on them: the `.data` closure audit and the entrypoints
  0755 derivation (`2026-07-21-capsule-install-layout-reference`). The Windows
  `Scripts/{name}.exe` launcher source is resolved by this revision: a
  content-addressed stub input, not a contract change.

## Implementation

A new pure module (proposed `install_layout.py`) is the single layout
definition. **Wheel layout:** every archive-root member of a verified wheel
maps under one library root, honoring the spread rule for a scheme where
purelib and platlib coincide (true for the bundled per-target CPython, so
`Root-Is-Purelib` true and false wheels land identically); `.data/purelib` and
`.data/platlib` also map there, and all other `.data` keys are rejected fail-
closed until a closure audit proves them needed; per-file size and sha256 come
from `RECORD`-verified member evidence, not from re-hashing. **npm layout:**
each verified tarball projects verbatim to its declared nested-`node_modules`
destination, with no `.bin` links. **Entrypoints:** the layout derives each
closure's executable entrypoints (ACP root bin script; the Python module files
backing the two contract console-script references), promoted to 0755.
**Product launchers** stay outside the closures as plan-generated files at the
contract-pinned `bin/{name}` and `Scripts/{name}.exe` paths. The Windows
launcher is generated, not vendored whole: a content-addressed console stub -
the x86_64 simple-launcher binary shipped inside the pinned PSF-2.0 distlib
wheel, declared in the input cache by URL, sha256, version, and license like
every other asset - is concatenated at build time with a fixed ASCII shebang
addressing the bundled interpreter relative to the launcher's own directory
(the stub's `<launcher_dir>` token, carrying the same isolated-mode interpreter
flags as the POSIX launcher) and a deterministic epoch-stamped zip whose
`__main__` resolves the capsule root from its own location, pins the
`runtime/python` library root at the head of the import path, and calls the
contract console-script entrypoint. Stub bytes plus fixed shebang plus
canonical zip yield byte-identical launchers from identical inputs; the
packaging library donating the stub is never a build- or run-time dependency.
On Windows the bundled interpreter lives at the interpreter subtree root
(`runtime/cpython/python.exe`; the standalone-build Windows layout has no
`bin/` segment), and the launcher pair is written 0755 like its POSIX
counterpart. **Installed inventory v2:** the
file record gains `source_sha256` and `source_member`, the inventory version
becomes `vaultspec-installed-closure-v2`, and the source-to-installed join
additionally proves every provenance pair names a verified member of a closure
package; the tree-digest preimage is unchanged. **Production builder:** a
builder beside the fixture-only one consumes verified archive sessions, applies
the layout, and emits canonical inventory bytes into the content-addressed
input cache, invoked by the capsule build script (closing `W01.P03.S13`'s input
gap). **Materializer (`S103`):** consumes only the plan and the v2 inventories,
streaming each record's `source_member` from the archive named by
`source_sha256` through the leased nested-parent write path and verifying size
and sha256 during the write; reconciliation is byte-exact because the inventory
is the layout at materialization time. Interpreter subtrees keep verbatim
projection; `S14`/`S15` verify and publish the same declarations.

## Rationale

The chosen shape makes the declared tree and the written tree the same
artifact. Provenance inside the file record turns reconciliation from tree-
diffing into per-record proof and lets validation bind file, license, and
source identity atomically where the model already validates cross-record
facts. Extending the existing inventory rather than adding a sidecar keeps one
loading, descriptor, and join path. Deriving installed digests from the
already-proven `RECORD` evidence avoids a second trust root. Keeping the generic
projector's wheel refusal preserves the fail-closed boundary that motivated it
while supplying the spec-conformant path the refusal always implied
(`2026-07-18-desktop-product-profile-adr`;
`2026-07-21-capsule-install-layout-reference`).

## Consequences

- `W01.P03.S103` gains a complete implementation target: layout module, v2
  inventory with builder, and a record-replaying materializer; `S13`/`S14`/`S15`
  consume the same declarations for build, verification, and publication.
- The fixture-authored v1 inventories and every test fixture must migrate to v2
  with real provenance; the version-literal change is intentionally breaking so
  no unprovenanced inventory can pass reconciliation.
- Fail-closed `.data` handling may reject a future locked dependency; relaxing
  requires a closure audit and an amendment here, not an ad-hoc bypass.
- The Windows launcher is unblocked as a stub-plus-generated-payload
  concatenation; the launcher contract, manifest schema, and golden vectors are
  unchanged. The materializing Step must add the stub asset to the input cache,
  replace its fail-loud Windows refusal with the generator, and prove one
  composed launcher by live execution on Windows; the stub's
  relocatable-shebang behavior is documentation-verified until that run. The
  single vendored binary is architecture-specific: a future Windows arm64
  target requires its own stub asset through the same mechanism. Unsigned
  launcher executables share the antivirus-flagging exposure of every
  pip-installed script; code signing is not decided here.
- Inventory bytes grow by two provenance fields per record within existing
  bounds; the dashboard-visible tree digest is unaffected.
- The layout authority becomes the single place wheel/npm placement can change;
  any parallel placement logic in build or verify scripts is a defect by
  definition.
