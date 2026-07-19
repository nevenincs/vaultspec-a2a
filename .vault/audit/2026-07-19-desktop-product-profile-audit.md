---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` audit: `W01 P01 S01 dependency profile review`

Status: PASS

## Scope

Reviewed only the S01 changes to `pyproject.toml` and its Step Record against
the accepted desktop product profile. Concurrent lockfile, authoring, provider,
test, preset, database, and scratch changes were excluded.

## Findings

### default-otel-import | high | Moving the OTLP exporter to server breaks default telemetry initialization

Gateway and worker startup both invoke `configure_telemetry`. Its `_check_otlp`
probe calls `importlib.util.find_spec` on the nested OTLP exporter module without
handling a missing `opentelemetry.exporter` parent. A real isolated environment
containing `opentelemetry-sdk` without the exporter reproduced
`ModuleNotFoundError`. The default metadata resolves but is not yet runnable.

### torch-source-portability | medium | The CUDA source override is uv-project metadata rather than wheel-extra metadata

The `extra = "rag"` selector correctly scopes uv lock resolution, but
`tool.uv.sources` is not emitted as wheel `Requires-Dist` metadata. Ordinary
wheel consumers receive the Torch extra without the custom index. The capsule
must therefore consume the uv-managed lock, and the Step Record must not claim
that wheel metadata alone carries the override.

## Recommendations

- Keep S01 open and route the high-severity telemetry issue to the executor.
- Guard optional OTLP detection without retaining the exporter in the desktop
  base, then prove gateway and worker telemetry initialization from a real clean
  base installation.
- Narrow the CUDA statement to uv-managed source and locked capsule resolution.

## Resolution log

- Added plan Step `S93` through the plan CLI immediately after S01 to own the
  optional OTLP guard and clean-base runtime proof.
- Updated the S01 Step Record to state that the CUDA source override is uv
  project metadata used by the locked capsule and is not published in wheel
  `Requires-Dist` metadata.
- Implemented S93 with ordered parent-namespace probing and no exception catch,
  preserving visible failures from installed but broken exporters.
- Proved the gateway and worker production telemetry bindings from a real
  default-only installation with the exporter namespace absent.

## Follow-up review

The S93 remediation and corrected S01 record passed independent review. No
critical or high findings remain, and both S93 and S01 may close.

### probe-gate-durability | medium | Preserve the clean-base regression proof as a durable gate

The S93 probe is an executable real-behavior harness, not a pytest-collected
test or registered quality task. Its installed module invocation will also
become unavailable when packaged tests are excluded. This does not invalidate
the clean-install evidence for S93, but S05 must register an external harness
against the installed production package or replace it with equivalent
installed-metadata coverage.

Follow-up verification reproduced the default-only clean installation, both
gateway and worker profiles, all 29 focused telemetry tests, the installed
exporter branch, Ruff, formatting, targeted type checking, lock consistency,
and the default, server, and RAG export closures.

## `W01 P01 S02` lock review

Status: PASS

The regenerated lock is deterministic and retains 171 package identities,
versions, and sources. Two isolated non-upgrading regenerations from committed
metadata produced the same bytes, and the repository lock check passed under
CPython 3.13.

Default and server dry-runs passed for all five accepted targets. Exported
closure inspection confirmed that the desktop base contains neither server nor
RAG packages, the server extra restores only its declared capability, and RAG
remains separate. Intel macOS's locked `cryptography` source build belongs to
the later capsule assembly and native certification gates. The recorded Torch,
macOS, and manylinux limits apply to the ADR-excluded optional RAG capability,
not to the mandatory desktop base.

The initial review identified one low-severity Step Record overstatement: uv
also normalized transitive environment markers for CUDA and NVIDIA packages,
Torch, and `phart`, rather than changing only root dependency classification.
The record now discloses that normalization while preserving the verified fact
that no package identity, version, or source changed. Follow-up review passed.

## `W01 P01 S03` Node lock review

Status: PASS

No findings were identified. The existing canonical lock pins the sole root
adapter dependency to exact `@agentclientprotocol/claude-agent-acp` 0.59.0,
requires Node 22 or newer, and records the SDK 1.2.1 archive plus resolved URLs
and integrity metadata throughout the production closure. The predecessor Zed
identity and versions 0.23.1 and 0.20.2 are absent.

Two isolated lock regenerations, an engine-strict clean installation, a dry-run
installation, and real production factory classification preserved the tracked
lock digest and selected the installed project-local adapter entrypoint. The
lock bytes already entered history in commit `a7896cc`; a record-only adoption
is therefore correct and avoids manufacturing a no-op lock diff. Capsule-owned
adapter resolution and removal of source-checkout installation guidance remain
assigned to the later package-authority step.

## `W01 P01 S04` runtime-acquisition review

Status: PASS

The new typed resolver keeps non-desktop behavior unchanged and makes desktop
selection return a stable, path-free unavailable-capability result instead of
an executable launch specification. Desktop policy filters launch arguments,
autonomous tool names, Claude and project configuration, Codex configuration,
and model composition. It also removes stale runtime-acquired entries while
preserving unrelated authoring state.

Initial independent review required two revisions. First, desktop admission
accepted contradictory metadata that marked an entry both desktop-available
and runtime-acquired. Admission now requires explicit availability together
with explicit `runtime_acquisition=false`, and omitted or contradictory values
fail closed. Second, an empty current declaration returned before cleaning
pre-attached ACP or Codex RAG state. Desktop cleanup now runs for that case,
while the non-desktop empty declaration remains the prior identity no-op.

Follow-up review passed with no remaining findings. Nine focused tests use the
production resolver and real ACP and Codex model objects; the impacted provider
and configuration suites, Ruff, and scoped type checking also pass. Application
selection of the desktop policy remains explicitly assigned to S16, so this
step does not claim end-to-end desktop runtime closure.

## `W01 P01 S05` installed dependency-closure review

Status: PASS

The source-side certification gate builds the real production wheel, exports
the locked base, server, and RAG closures, installs the base closure and wheel
into an isolated CPython 3.13 environment, and checks the installed graph with
`uv pip check`. Its isolated child interpreters import the installed gateway
and worker entrypoints rather than a packaged test module. Both initialize the
OpenTelemetry SDK with the expected service identity while the optional OTLP
exporter remains absent.

The built and installed metadata agree on exactly the `server` and `rag`
extras. The direct server roots are exactly AsyncPG, the Postgres LangGraph
checkpointer, the OTLP gRPC exporter, and Psycopg; the direct RAG roots are
exactly Torch and `vaultspec-rag`. The installed base is disjoint from every
package added only by the optional closures. Server resolution passes on the
native interpreter, while RAG resolution is deliberately bounded to the
supported CPython 3.13 x86-64 Windows target and preserves S02's recorded
manylinux and macOS limitations.

Initial architecture review required locked rather than frozen export
validation, exact optional-root assertions, target-bounded RAG resolution,
marker-aware installed-environment validation, and removal of mechanically
guaranteed success assertions. A transitive parser import was replaced with an
explicit dev-only `packaging` declaration. The resulting lock change affects
only root-project dev metadata: all 171 package records and the published base,
server, and RAG closures retain their prior identities and fingerprints.

Independent follow-up review found no unresolved critical, high, or medium
issues. Five real-artifact tests, the combined 34-test telemetry and desktop
suite, Ruff, formatting, scoped type checking, focused dependency lint, and
`uv lock --check` pass. The source-side test package is still present in the
current wheel; excluding it is explicitly owned by S06 and must be verified
from the built artifact by S12. Because the probe imports only installed
production modules, that later exclusion will not weaken this regression gate.

## `W01 P02 S06` production wheel-shape review

Status: PASS

The repaired Hatch target packages the production Python tree and its required
resources while excluding every ordinary test tree, `desktop_tests`,
`service_tests`, package-level `conftest.py`, VidaiMock tapes, mock agent and
team presets, and the deterministic ADR acceptance preset. A clean commit
archive produces a 228-entry wheel with 224 package entries while retaining all
11 migration assets, nine production agent presets, two production team
presets, and the bundled context rule.

Initial architecture review found a high-severity closure and evidence defect.
The first exclusion list missed the root pytest configuration and 13
`service_tests` files, while its archive check only searched literal `tests`
and `desktop_tests` paths. Its recorded counts also came from a dirty worktree
that contributed an untracked preset, so the claimed 269-entry artifact was not
the committed source artifact. Review additionally found certification-only
mock and deterministic resources in the desktop product wheel.

The target now states Hatch's actual behavior: every non-excluded file below
the package root can enter the artifact, including untracked files in a dirty
build. Verification therefore builds from a clean commit archive. Product
packaging excludes certification resources without deleting them or changing
source and Compose workflows. The installed desktop preset inventory is the
curated artifact inventory; S08 owns only the package-resource loading seam,
and S12 must enforce the exact installed production discovery set as part of
its clean-artifact contract.

Independent follow-up review reproduced the clean counts and found no remaining
critical, high, or medium issues. The S05 real-wheel dependency gate remains
five-for-five, TOML parsing confirms the exact 14 exclusions, Ruff and lock
checks pass, and the required migration, production-preset, and context assets
remain present. S10 must move or force-include its repository-root schema, and
S12 must reject dirty or forbidden archive content by exact identity.

## `W01 P02 S07` package-owned migration review

Status: PASS

The runtime migration configuration now resolves Alembic's `env.py`, revision
scripts, and template from the installed `vaultspec_a2a.database.migrations`
package. It attaches no checkout-level `alembic.ini`, preserves the existing
developer CLI configuration separately, and completes a clean-wheel migration
from an unrelated working directory through revision `0007`.

Initial independent review found two high-severity defects. Alembic stores main
options through an interpolating parser, so a literal percent sign in either the
installed script path or database URL failed before startup. In addition,
concurrent async callers dispatched Alembic into separate threads even though
its command proxy is process-global; real two-database probes cross-wired the
contexts and left missing or partially stamped databases. Review also found a
medium error-contract gap for missing package resources.

Both configuration values are now escaped only for Alembic storage and round
trip to their original values. The synchronous command is serialized by a
process-wide lock acquired inside the worker thread, preserving event-loop
responsiveness while protecting Alembic's global context. Missing or incomplete
package resources produce a stable, path-safe `FileNotFoundError`, and the new
configuration builder is included in the module's public API.

Follow-up review found no unresolved critical, high, or medium issues. Fifteen
focused migration tests and all 118 database tests pass, including a real
SQLite database beneath a percent-containing directory, encoded SQLite and
PostgreSQL configuration round trips, and concurrent upgrades of two distinct
databases. Ruff, formatting, and scoped type checking pass. The tests import
production code and exercise real package resources and databases without
fakes, mocks, stubs, patches, skips, or mirrored migration logic.

## `W01 P02 S08` package-owned preset review

Status: PASS

The preset-loading seam now derives bundled agent and team directories from the
installed `vaultspec_a2a.team` package resource. Workspace overrides retain
their precedence, and source and Compose profiles retain their wider preset
inventory. Desktop product curation remains the S06 packaging authority; no
dashboard-side preset filter exists or is required for the clean capsule.

Independent review installed the clean S06 wheel into isolated CPython 3.13.
The resource authority resolved beneath `site-packages`; discovery returned
exactly nine production agent presets and two production team presets, no mock
or deterministic certification id, and real workspace override and missing-id
behavior remained correct. All 120 team tests, Ruff, formatting, and scoped
type checking pass.

The original Step Record incorrectly said a product-layer selection filter
removed source-side mock ids. The record and module documentation now state the
actual boundary: the desktop wheel excludes certification resources, while the
loader reads whatever valid inventory its installed package contains. S12 must
retain this clean-installed inventory proof. No unresolved critical, high, or
medium issue remains.

## `W01 P02 S09` capsule-owned provider asset review

Status: PASS

The default Node-backed ACP classifier now has one explicit capsule-assets
authority. When configured, it resolves production-owned Node and ACP relative
identities into absolute canonical files and never falls back to the checkout
or `PATH`. Omitted capsule-root selection consults settings; explicit `None`
retains the Compose and project-local classifier. The later desktop profile step
remains responsible for activating this seam.

Initial review found three high-severity boundary defects: relative roots yielded
working-directory-sensitive commands, file symlinks or directory junctions
could escape the lexical capsule root, and tests duplicated the production
platform/layout rules. It also found an error-contract gap where unknown-user
expansion could leak `RuntimeError`. The repair moves all layout identities into
production, canonicalizes the root and files, rejects resolved files outside the
canonical authority, distinguishes omission from explicit `None`, and guards
both user expansion and strict resolution behind actionable `ConfigError`.

Independent follow-up reproduced real Windows file-symlink and directory-junction
escape rejection and found no unresolved critical, high, or medium issue. Ten
focused real-filesystem tests, the 340-test provider suite, the 82-test control
suite, Ruff, formatting, scoped type checking, and diff checks pass without
fakes, mocks, stubs, patches, monkeypatches, skips, or expected failures.

S09 proves canonical path identity, ownership, presence, and armed no-fallback
behavior. It deliberately makes no readiness or successful-launch claim.
Executable-mode and runnable-artifact certification remains assigned to S14,
which precedes S16 desktop-profile activation.

## `W01 P02 S10` component-manifest contract review

Status: PASS

The A2A package now owns one versioned desktop component-manifest authority and
exports its byte-exact Draft 2020-12 schema at a stable installed resource path.
The contract binds the component identity to the A2A distribution asset, admits
only the five approved target triples and exact four-asset closure, pins CPython
3.13, Node.js 22, and ACP 0.59.0, and gives the gateway and standalone MCP
surfaces distinct schema-visible discriminators. Asset digests describe the
immutable source artifact bytes; later SBOM and dashboard release-set contracts
remain responsible for installed-tree and composite-release integrity.

Initial review found crossed entrypoint kinds could pass schema validation, the
schema was absent from the built wheel, component and distribution versions
could disagree, the API range admitted versions the production router does not
implement, and command segments were not portable across Windows. The repair
introduced typed entrypoints, a schema-visible `v1` API enum, production identity
binding, stable wheel inclusion, and one shared runtime/schema portability
policy. Follow-up review found and repaired the legacy Windows device spellings
`COM¹`/`²`/`³` and `LPT¹`/`²`/`³`.

Independent final review found no unresolved critical, high, or medium issue.
It reproduced 111 focused production-model and Draft 2020-12 tests, the real
working-tree wheel build and isolated installed-resource read, Ruff checking,
Ruff formatting, and scoped type checking. The tests import production code and
use no fake, mock, stub, patch, monkeypatch, skip, expected failure, or mirrored
business logic. S11 remains explicitly open until the emitter consumes these
typed authorities and genuine immutable artifacts.

## `W01 P02 S11` pinned component-manifest emitter review

Status: PASS

The emitter now treats the exact A2A wheel as the sole authority for component
name, version, MIT license expression, console entrypoints, Alembic migration
range, and A2A source-artifact digest. It copies and hashes the wheel once into
a bounded private snapshot, then reads only that snapshot. The other three
assets and both dependency locks remain explicit immutable source-artifact byte
inputs; S13 and S14 retain real runtime acquisition, licensing, SBOM, and
installed-tree integrity.

Initial review found four high-severity provenance/evidence defects: identity
could come from an unrelated distribution, duplicate console scripts collapsed
silently, source-digest semantics were ambiguous, and positive tests fabricated
distribution metadata. It also found producer-specific JSON bytes, unbounded
pre-I/O work, and leaked validation failures. The first repair moved identity
and entrypoint parsing into the real wheel, defined canonical JSON v1, and used
real-wheel evidence.

Adversarial follow-up then reproduced split `.dist-info` authority, unsafe
Windows migration names and alternate data streams, raw migration exceptions,
special-device hashing, late string validation, an independent digest-algorithm
override, and stale license evidence. The final repair binds one root-level
`.dist-info` identity, derives `License-Expression: MIT`, rejects traversal,
devices, ADS, overlong/deep/case-colliding paths, requires regular files at
preflight and descriptor time, normalizes expected failures, and validates
wheel metadata through the production contract before migration materialization
or non-A2A hashing. It also restored and verified the S10 schema force-include
after a concurrent worktree edit removed it.

Independent final review found no unresolved critical, high, or medium issue.
It reproduced 137 focused contract/emitter tests plus the five-test clean
dependency-closure build/install gate, for 142 passes. Ruff checking, Ruff
formatting, scoped type checking, and lock consistency pass. A fresh 608,058-byte
wheel has 235 entries, contains the installed schema resource, one matching
`.dist-info` authority, MIT metadata, both required scripts, and 11 migration
files, while excluding desktop tests. The tests use production code, real wheel
bytes, real locks, and real package migrations without fake, mock, stub, patch,
monkeypatch, skip, expected failure, or mirrored emitter logic.

At S11 closure, S12 remained open because its candidate certification gate
required a separate whole-file architecture review and independent adversarial
verdict. The following section records that later review and repair.

## `W01 P02 S12` clean-wheel component-certification review

Status: PASS

The initial candidate did not meet the architecture boundary even though its
tests passed. It built from the shared dirty checkout, treated the host Node.js
24 executable as a Node.js 22 source artifact, treated a virtual-environment
interpreter and one checkout ACP JavaScript file as complete runtime sources,
and required the local fixture digest to differ from the emitted manifest. Its
fixture-local pin helper also mirrored dashboard rejection logic that does not
yet exist in production.

The repaired gate captures one exact Git commit object, builds the wheel from
that clean archive, and inspects the resulting immutable artifact. It proves the
exact production preset inventory, package-owned migrations, one installed
component-schema resource, standardized Name/version/MIT metadata, and complete
test and certification-preset exclusion. Both the repository schema snapshot
and packaged schema bytes equal the production Pydantic exporter.

The A2A-owned dashboard-shaped JSON is now explicitly `fixture_only`. It binds
only the component name and version to real wheel metadata and validates the
A2A-owned target and digest vocabulary. It does not claim that its digest names
a current emitted manifest, that it is a complete release set, or that it proves
dashboard rejection policy. Real target artifacts and emitted manifests remain
owned by A2A S13 through S15. The dashboard-owned release-set schema, parser, and
producer-consumer proof remain dashboard S04, S06, and S145.

Independent final review found no unresolved critical, high, or medium issue.
It reproduced three focused tests and 145 integrated contract, emitter,
dependency-closure, and component-certification tests. Ruff checking, Ruff
formatting, scoped type checking, lock consistency, and diff hygiene pass. The
tests import production component identity, target, digest, and schema
authorities and use no fake, mock, stub, patch, monkeypatch, skip, expected
failure, or mirrored dashboard consumer logic.

## `W01 P03 S13` deterministic capsule-builder review

Status: REVISION REQUIRED

The builder's static checks and command-line entrypoint pass, and its eleven
service tests collect. Independent review nevertheless found four high-severity
contract failures and one medium-severity evidence gap. S13 must remain open
until these findings are repaired and reviewed. Work begun for S14 does not by
itself close an S13 defect.

### s13-determinism-evidence-contradiction | high | The recorded proof cannot match the manifest contract

Type: release evidence. The record says wheel timestamp bytes and the outer ZIP
change between builds while canonical manifest bytes remain identical. The
manifest includes the exact wheel digest, so changed wheel bytes must change
the canonical manifest. The builder does not set a stable source epoch, and its
test checks canonical bytes rather than complete archive identity. Reproduce
the two-build evidence, bind every nondeterministic input, and require the
claimed artifact boundary to be byte-identical before restoring the claim.

### s13-malformed-digest-fails-open | high | Invalid pins disable verification

Type: supply-chain integrity. Input loading checks only that a digest key is
present. Acquisition verifies bytes only when that value already matches the
expected lowercase SHA-256 grammar. A typo or placeholder therefore accepts
cached or downloaded bytes without verification. A direct real-file probe
reproduced this behavior with `not-a-digest`. Reject invalid digests before any
cache lookup or network access, then compare every acquired byte stream.

### s13-mixed-source-snapshot | high | One capsule can combine HEAD with dirty worktree facts

Type: provenance integrity. The wheel is built from `git archive HEAD`, while
the builder, pin descriptor, exported Python lock, and both dependency-lock
digests come from the live worktree and environment. Build every input from one
exported commit snapshot, or fail closed on index and worktree drift and bind
the commit identity explicitly.

### s13-offline-closure-incomplete | high | The capsule omits transitive runtime payloads

Type: product contract. The capsule carries runtime source archives, the root
A2A wheel, one ACP tarball, and a Python lock recipe. It does not carry the
Python dependency wheelhouse or ACP's transitive npm closure. The artifact
therefore cannot satisfy the ADR's offline-after-install base closure. Assemble
and verify the complete target-native dependency payload before closing S13.

### s13-checkout-free-evidence-incomplete | medium | Locks, licensing, and SBOM cannot be reverified from the artifact

Type: verification adequacy. The manifest hashes checkout lock files that are
not shipped, while the shipped Python lock is not the manifest's bound lock
input. License values are descriptor strings rather than evidence derived from
the acquired artifacts, and no SBOM is present. Ship and digest the actual
closure authorities, validate licensing evidence, and emit the required SBOM
so S14 can verify the capsule without a checkout.

## `W01 P03 S14` standalone capsule-verifier review

Status: REVISION REQUIRED

The verifier detects missing fixed entries, changed root-asset bytes, and
canonical-manifest inconsistency. Independent review found that this is an
internal-consistency check, not the checkout-free closure verifier claimed by
S14. Five high-severity and two medium-severity findings remain open.

### s14-false-closure-certification | high | Root asset names are accepted as an installable offline closure

Type: product contract. Verification does not inspect runtime target identity
or require the Python and ACP transitive payloads missing from S13. A manifest
labeled for Windows can bind another target's runtime archives and still pass.
Require target-native structure and the complete installable dependency payload
before reporting target closure.

### s14-lock-identity-unverified | high | Manifest lock digests cannot be checked from the capsule

Type: provenance integrity. The verifier never checks the manifest's `uv.lock`
or `package-lock.json` identities. Those files are absent, and the shipped
Python lock is not bound by the manifest. Ship the authoritative locks, bind
their bytes, and reject missing, stale, malformed, or mismatched closure state.

### s14-manifest-claims-not-rederived | high | Target, entrypoints, and licenses are trusted assertions

Type: verification adequacy. The command has no expected-target input and only
schema-validates entrypoint and license fields copied from the manifest. It
does not derive those facts from acquired runtime, wheel, and npm artifacts.
Add an explicit target expectation and artifact-derived checks for every claim.

### s14-sbom-incomplete | high | The emitted inventory omits material dependency evidence

Type: supply-chain evidence. The generated inventory contains four top-level
claims and Python package names and versions. It omits Python artifact hashes,
licenses and relationships, all Node and ACP transitive components, and a
standard authenticated SBOM identity. Generate the inventory from the complete
verified closure and validate its schema and digest.

### s14-checkout-free-proof-missing | high | Every test executes through the source checkout

Type: test adequacy. Tests launch the repository script with `uv run` from the
repository root, importing checkout modules and dependencies. Copy or install
the independently pinned verifier and capsule into an isolated directory and
prove verification succeeds with no repository files available.

### s14-archive-ambiguity-unbounded | medium | Duplicate members and resource exhaustion are unchecked

Type: input safety. Converting ZIP names to a set hides duplicate members, and
the verifier applies no entry-count, expanded-size, per-entry-size, or
compression-ratio bounds before whole-entry reads. Reuse the bounded,
duplicate-safe archive discipline from the manifest reader.

### s14-rejection-matrix-incomplete | medium | Explicit failure contracts lack durable tests

Type: test adequacy. Negative coverage omits wrong target, stale lock identity,
malformed lock structure, schema and canonical tampering, entrypoint and license
mismatch, duplicate archive members, resource bounds, and absent transitive
closure. Add real-byte rejection cases for each contract before closing S14.

## `W01 P03 S15` capsule-publication workflow review

Status: REVISION REQUIRED

Full action pinning, concurrency, timeouts, and the five target triples are
sound. Actionlint and independent review found four high-severity publication
blockers and two medium-severity permission and documentation findings.

### s15-intel-macos-runner-invalid | high | The five-target matrix cannot schedule

Type: automation correctness. Actionlint rejects `macos-13` as an unknown
hosted-runner label, so the Intel macOS leg cannot run. Status: resolved by
selecting `macos-15-intel`; Actionlint accepts the complete workflow.

### s15-clean-runner-environment-missing | high | Build scripts run before dependencies are installed

Type: automation correctness. Jobs install uv and CPython, then call
`uv run --no-sync` without creating or synchronizing the project environment.
The scripts require Click, Pydantic, JSON Schema support, and the A2A package.
Status: resolved by synchronizing the locked tooling environment before build
and running each script with frozen no-sync semantics.

### s15-release-gate-bypasses-product-ci | high | Tag publication can ship failed capsule contracts

Type: release safety. The publish job depended only on the capsule matrix. It
was not gated on canonical CI or resolution of the open S13 and S14 findings,
so it could publish an incomplete artifact that passed only internal
self-consistency checks. Status: resolved by removing tag-triggered release
publication. The remaining workflow is manual artifact evidence; release
publication must be added only after repaired capsule certification passes.

### s15-artifact-identity-not-digest-stamped | high | Published assets lack an external immutable binding

Type: supply-chain integrity. Artifact and release names contained only the
target. No outer ZIP digest or checksum asset was published. Status: resolved
for the manual artifact workflow by computing the final archive SHA-256,
including it in the artifact name, and uploading a checksum file beside the
capsule. A future release workflow must preserve this binding.

### s15-workflow-permissions-too-broad | medium | Build jobs inherit release write authority

Type: automation security. Workflow-level `contents: write` applies to all five
build jobs even though they only read source and upload artifacts. Status:
resolved by defaulting the workflow to `contents: read` and granting
`contents: write` only to the publish job.

### s15-release-notes-overstate-artifact | medium | Publication text claims determinism and offline closure

Type: documentation accuracy. Release notes called the ZIP deterministic and
said it contained the locked dependency closure. S13 records differing archive
bytes and ships only a root wheel plus a lock recipe. Status: resolved by
removing release publication and its unsupported notes.

## Uncommitted capsule-foundation candidate review

Status: REVISION REQUIRED; candidate files remain uncommitted.

The candidate descriptor and archive primitives pass Ruff, formatting, Ty,
lock consistency, and 19 real-file tests. They are not safe to preserve as a
standalone foundation commit until the following findings are repaired.

### capsule-tar-unselected-expansion-unbounded | medium | Compressed members outside the selected root bypass effective bounds

Type: input safety. Gzip and XZ tar projection enumerates members before
enforcing meaningful decompression bounds, then counts only members selected
under the declared archive root. A large unselected compressed member can
consume unbounded decompression time and resources while bypassing the stated
expanded-size limit. Bound the complete decompressed stream and every member,
including unselected members, before projection.

### capsule-projection-parent-symlink-race | medium | A parent swap can redirect file materialization outside staging

Type: filesystem safety. Destination containment is checked during preflight,
but later directory creation, temporary-file placement, and final hard-linking
resolve paths again. A concurrent parent replacement with a symbolic link can
redirect writes outside the staging root. Use descriptor-relative,
no-follow filesystem operations or revalidate opened parent identities through
the final link, and add a real race-oriented rejection test.

### capsule-zstd-window-unit | high | The configured decompressor window is effectively two tebibytes

Type: resource safety. The candidate passes a byte-valued two-gibibyte constant
to the Zstandard API's kibibyte-valued `max_window_size` parameter. Gzip and XZ
tar grammars also enumerate the complete decompressed archive before enforcing
the later member limits. Correct the unit and bound every compressed tar byte
before full archive indexing.

### capsule-installed-evidence-invalid | high | Invalid and duplicate installed-file claims are accepted

Type: integrity evidence. `ProjectedFile`, `deterministic_tree_digest`, and the
installed-tree inventory accept duplicate paths, malformed digests, negative
sizes, and invalid modes. A real production-function probe emitted a digest for
two identical invalid records. Validate every record and reject portable path
collisions before any evidence is serialized or hashed.

### capsule-output-identity-race | high | The returned archive digest may describe replacement bytes

Type: artifact integrity. The archive writer closes its output path and reopens
that pathname to calculate the returned SHA-256. A replacement between those
operations can detach the digest from the file object that was written. Hash
the same open descriptor and retain stable file identity through publication.

### capsule-output-promotion-race | high | Failure cleanup can delete another creator's output

Type: filesystem safety. The writer creates the final path directly. If another
creator wins the no-overwrite race, the generic failure handler can unlink that
other output; an interruption can also strand a partial final archive. Write a
private temporary file, flush it, atomically promote it without overwrite, and
remove only paths created by the current invocation.

### capsule-projection-not-transactional | medium | A failed later member leaves earlier files behind

Type: filesystem safety. Member writes are atomic individually, but an archive
failure after the first successful member leaves a partial destination tree.
Retry then fails against the no-overwrite rule. Roll back every path created by
the projection or require and enforce a disposable private subtree.

### capsule-windows-junction-boundary | medium | Link checks do not cover Windows junctions

Type: cross-platform safety. Staging-root and candidate-tree checks use symbolic
link predicates only. Reject junction and reparse-point directory authorities
where the platform exposes them, and revalidate destination parents at the
final materialization boundary.

### capsule-descriptor-is-not-provenance | medium | Exact metadata is not a trusted source catalog

Type: provenance integrity. The descriptor accepts any credential-free HTTPS
URL and caller-supplied target, archive, license, and evidence strings. It does
not derive GNU versus musl identity or bind the tuple to qualified PBS, Node,
or ACP release authorities. Keep the type explicitly metadata-only until a
reviewed catalog validates the exact target tuple.

### capsule-acp-inventory-blob-only | medium | ACP inventory claims are not semantically reconciled

Type: dependency closure. The verifier proves only the declared inventory
blob's size and SHA-256. It does not parse the package list, reconcile the
declared count, prove the selected target SDK version and SRI against
`package-lock.json`, or verify the installed inventory. Rename the boundary
honestly or add semantic package-lock reconciliation before using it as closure
evidence.

### capsule-public-input-errors-leak | medium | Invalid projector input can escape the typed error contract

Type: API safety. The public generic source dataclass is unvalidated. Invalid
archive-root data can escape as a raw validation exception instead of the
declared capsule assembly error. Validate public arguments before archive work
and normalize failures to the typed boundary.

### capsule-build-decoder-runtime-dependency | medium | Build-only decoding expands every product installation

Type: dependency hygiene. The candidate declares Zstandard in mandatory product
dependencies even though it exists to read release-build PBS archives. Keep the
decoder behind a lazy build authority or document and certify why its native
wheel belongs in the immutable runtime closure.

### capsule-foundation-maintainability | medium | The module and rejection matrix exceed a reviewable boundary

Type: maintainability and test adequacy. The candidate module is 1,029 lines.
Its default real-byte tests are valuable but omit compressed-tar exhaustion,
projection rollback, invalid and duplicate evidence, raced final output,
junctions, semantic ACP inventory, and Unicode-normalized collisions. Split
archive projection from evidence/publication and add the missing rejection
cases before preserving this foundation.

## Uncommitted capsule-foundation corrective disposition

Status: REVISION REQUIRED; no foundation commit is approved and `W01 P03 S13`,
`S14`, and `S15` remain open.

This disposition reviews the candidate snapshot whose `capsule.py` SHA-256 is
`45cf3363cda89ffaecf8616dce2c0e5f38ca299d468b03f47bd32ed06207deff` and whose
`capsule_evidence.py` SHA-256 is
`162d16fb08798be11284daede8b9ee1f17c9e29a74ebcb781276890f4420ac76`.
The focused real-file suite reports 37 passing tests and the scoped Ruff,
format, and Ty gates pass. Those gates do not resolve the filesystem and
product-closure findings below.

### Corrected finding: `capsule-zstd-window-unit`

The original high-severity premise was incorrect for locked
`zstandard==0.25.0`. Both installed backends pass `max_window_size` to libzstd
as bytes even though upstream Python-facing documentation describes
kibibytes. The old two-gibibyte argument therefore imposed a two-gibibyte cap,
not a two-tebibyte cap. The candidate now uses an explicit 128 MiB byte limit,
and a valid frame advertising a 256 MiB window is rejected. This finding is
resolved as a resource-bound repair and retained here to correct the audit
record.

### Repairs verified in the reviewed snapshot

- Compressed tar streams are bounded before archive indexing; XZ uses a 128
  MiB decoder-memory limit and Zstandard uses the verified 128 MiB byte limit.
- ZIP central-directory bytes and entry count are preflighted before
  `ZipFile`, installed-file evidence is validated and collision checked, and
  evidence iterable consumption stops at 80,001 records.
- Archive hashing uses the same open descriptor, member creation uses
  no-follow exclusive creation, and the archive writer requests ZIP64-capable
  local headers.
- Public input failures are normalized to `CapsuleAssemblyError`, Windows
  link-like authorities include junctions and reparse points, the Zstandard
  decoder remains a lazy tooling dependency, and archive I/O is split behind
  an acyclic private module.
- Current `os.open` to `os.fdopen` paths retain descriptor sentinels and close
  on failure. `_relative_directory_descriptor` also closes a newly opened
  descriptor if `fstat` or validation fails. The prior descriptor-leak finding
  is resolved in this snapshot.

### capsule-directory-publication-can-replace | high | POSIX projection promotion is not exclusive

Type: filesystem correctness. `project_archive` checks that the destination is
absent and then calls ordinary `os.rename`. On POSIX that operation can replace
a concurrently created empty destination directory. The public refusal-to-
overwrite contract is therefore false. Use a target-native exclusive rename
authority and fail closed when the platform or filesystem cannot provide it;
the check-then-rename sequence is not an acceptable fallback.

### capsule-failed-projection-residue-unbounded | high | Rejected archives leave complete private trees

Type: resource safety. The previous stat-then-`rmtree` cleanup could delete a
swapped replacement and was correctly removed, but the replacement behavior
leaves every randomized `.vaultspec-projection-*` tree after failure. The tests
now explicitly accept those trees. A late rejection can retain up to the
multi-gibibyte expansion bound, and repeated failures accumulate without a
bounded quarantine or owning cleanup authority. Define and enforce an
exclusive parent/quarantine contract or leave cleanup to a caller-owned outer
temporary generation whose removal is proven. Do not describe permanent
residue as transactional rollback.

### capsule-windows-cross-process-lease-contamination | high | Process-local filtering cannot protect the source snapshot

Type: determinism and concurrency. The Windows directory lease creates visible
`.vaultspec-authority-*.lease` files inside the capsule source and filters only
the names registered in the current process. A real two-process probe against
one source tree made both independent archive writers fail, while the in-
process thread test passed. Another process's lease can be scanned as payload
or disappear during emission. Replace visible sentinel files with a native
directory-handle authority and add a real subprocess concurrency gate; a
process-local set cannot certify release determinism.

### capsule-file-publication-path-authority | high | Linux publication discards the leased parent descriptor

Type: filesystem safety. The Linux `renameat2(RENAME_NOREPLACE)` candidate uses
`AT_FDCWD` and absolute paths even though the output directory is already
leased by descriptor. A parent rename or replacement can therefore invalidate
the checked authority before the native call. Use the opened source and
destination directory descriptors with relative names and revalidate the
published identity through that authority. Fail closed for unsupported symbols,
flags, filesystems, and cross-device publication.

### capsule-success-temporary-residue | medium | Hard-link publication retains duplicate archives

Type: operational resource safety. On macOS and on Linux without usable
`renameat2`, the archive publisher falls back to a no-replace hard link and
never removes the private source name. The test permits one quarantine beside
every successful output. Repeated successful builds therefore retain duplicate
full-size capsule archives. Either adopt a platform-native consuming exclusive
rename or make an owning outer temporary directory responsible for the source
name and prove its bounded cleanup.

### capsule-zip64-policy-ambiguous | medium | Per-entry ZIP64 passes a central-directory-only rejection rule

Type: archive contract. Canonical ZIP64 end records are rejected, but a valid
small archive using a ZIP64 local header and ordinary end record passes. State
whether only ZIP64 central directories are unsupported or all ZIP64 grammar is
forbidden, then add positive and negative real-byte cases matching that policy.

### capsule-zip-comment-eocd-limitation | low | EOCD signatures in comments can reject valid archives

Type: compatibility. The preflight inherits CPython's end-record search
limitation: an ordinary comment passes, while some valid comments containing an
EOCD signature are rejected. Keep this as a documented controlled-input limit
unless the parser is replaced.

### Product-closure blockers unchanged

The exact metadata descriptor is still not a trusted PBS, Node, or ACP source
catalog. ACP inventory remains a digest-bound blob rather than a semantically
reconciled package-lock and installed-tree inventory. Windows CRT
redistribution and servicing provenance still require qualified confirmation,
and the root ACP package's Anthropic SDK dependency still requires qualified
redistribution authority or an upstream grant. Intel macOS still requires a
target-native locked `cryptography==49.0.0` build. No target cohort has produced
the required native install, compile, relocation, entrypoint, tree-mutation,
license, and CycloneDX evidence. Ordinary implementation approval does not
resolve those legal or target-native evidence gates.

### Disposition

Do not stage or commit the capsule foundation and do not restore S13-S15
completion markers. The next admissible implementation must first choose and
document one enforceable ownership model: native exclusive directory and file
publication with descriptor-relative authorities on every target, or an outer
caller-owned temporary generation whose cleanup and activation boundaries are
the transaction. After that choice, require Windows cross-process and native
Linux/macOS no-replace tests before independent formal review.

## Corrective review after the unsafe certification commit

Status: SAFETY PASS FOR THE PINNED WORKING SNAPSHOT; PRODUCT READINESS FAILS.
`W01 P03 S13`, `S14`, and `S15` remain open, and no release or tag publication
is approved.

Commit `9b78c164` recorded an implementation-and-documentation certification
before the required review gates were satisfied. Later commits now descend from
it, so this audit does not rewrite shared history. The commit remains unsuitable
as product evidence. This disposition applies only to the uncommitted corrective
snapshot with these SHA-256 identities:

- `_filesystem_authority.py`:
  `9977638f53664b9e8e4298e731aa4d8cf6185fefe9248d90939643b498cf91fc`
- `capsule.py`:
  `dc3c80c13487f5e51059237be01c279552345fce2b410bc8e8724b40ba9d2e62`
- `capsule_evidence.py`:
  `bf67d40d4f3bd793733cf0aad4c1e9c2ecc3a796533eae58d918c3c1a737a2a6`
- `test_capsule_archives.py`:
  `89b2d1ece32ac277175600a31cb4bb19a691b1eb9706ebeab4396cf38ed1ad70`
- `test_capsule_publication_races.py`:
  `20337f281149d0ccd23135a6c8acbea74726f74660bd37cd712a9596b461adb5`

### Safety findings resolved in the working snapshot

- Windows publishes the exact held file or directory handle relative to the
  leased destination through `NtSetInformationFile` with no replacement.
- POSIX member materialization creates and opens descendants relative to the
  continuously leased quarantine descriptor with mandatory `O_DIRECTORY` and
  `O_NOFOLLOW`; unsupported capability fails closed.
- Source-tree enumeration consumes at most the remaining global entry budget
  plus one before sorting or collecting metadata.
- Failed POSIX projections clear through the held quarantine descriptor,
  identity-check the empty name beneath the leased parent, and reclaim the
  empty slot descriptor-relatively. The unavoidable same-user empty-name swap
  remains inside the documented exclusive-parent-mutation precondition.
- Named archive staging is unbuffered. Exceptional exit truncates the exact
  still-open file descriptor to zero before `fsync` and close, so at most 16
  zero-length named slots can remain. Successful publication and anonymous
  Linux staging are not truncated.
- Typed overwrite refusal is preserved under both simultaneous and delayed
  publisher startup. Tests continue to use production imports and real files
  and processes without mocks, patches, skips, or expected failures.

The final safety review found no unresolved critical, high, or medium safety
finding for those exact production hashes. Hash-pinned Windows evidence reports
42 focused artifact/capsule tests and 219 complete desktop tests passing. Ruff
format/check, Ty, the lock check, and diff checks pass. Isolated WSL CPython
3.13 resource tests report three passes for bounded enumeration, exact-file
truncation, and failed-projection slot reclamation.

### Product readiness remains blocked

Named POSIX file publication and every POSIX directory publication currently
fail with `ENOSYS` because native rename APIs re-resolve a mutable source name.
Linux archive publication therefore works only when anonymous `O_TMPFILE` plus
descriptor-bound `linkat` is available; Linux directory projection and macOS
archive and directory publication cannot complete. The cross-process directory
race test still requires one real winner and one collision loser on every
supported target; it does not accept `ENOSYS` as success.

The governing architecture already assigns release-set receipt, activation,
rollback, and final visibility to the dashboard-owned immutable generation.
The next implementation must expose and prove an A2A writer/projector contract
for a caller-owned unpublished generation, then make the dashboard activate
only the complete five-target cohort. Do not reintroduce name-bound inner
publication or weaken target-native success tests to close this gap.

Target-native macOS evidence, both Linux release architectures, the Intel
macOS `cryptography==49.0.0` build, Windows CRT redistribution and servicing
provenance, and qualified authority for the root ACP package's Anthropic SDK
dependency remain unresolved. General implementation approval does not satisfy
those target-native or redistribution gates.

## Capsule-foundation corrective implementation review

Status: IMPLEMENTED AND INDEPENDENTLY APPROVED AS A FOUNDATION. This supersedes
the revision-required disposition above for the reviewed source snapshot. It
does not close ``W01 P03 S13``, ``S14``, or ``S15`` and does not satisfy the
product-closure evidence listed above.

The corrective pass replaces pathname-based publication and cleanup with a
shared native filesystem-authority layer. Windows uses non-link-like directory
handles that deny rename/delete races and publishes the exact open file or
directory handle with a no-replace rename. Linux archive publication uses an
anonymous ``O_TMPFILE`` and descriptor-bound ``linkat``. POSIX directory
projection and hosts without an identity-bound primitive fail closed.

Projection staging claims one of 64 fixed directories by atomic exclusive
creation. Failed bytes are cleared through a live lease to the owned directory
inode, so cleanup cannot follow a swapped parent entry; an empty bounded slot
can remain for explicit caller-owned maintenance. Windows archive staging uses
16 fixed ``CREATE_NEW`` slots, while successful Linux staging is anonymous and
leaves no source residue. Source discovery begins under the root lease, uses
descriptor-relative no-follow traversal on POSIX, and holds native
per-directory Windows authority without visible sentinel files.

The ZIP policy is explicit: ZIP64 end records and central-directory sentinels
are unsupported, while bounded ZIP64 local headers with an ordinary central
directory are accepted. Positive and negative real-byte tests preserve that
distinction. The end-of-central-directory signature-in-comment limitation
remains a queued low compatibility constraint for controlled inputs.

Validation reports 40 focused artifact/capsule tests and 188 complete desktop
tests passing. The focused matrix includes real cross-process archive and
directory publishers, source and parent churn, late projection failure,
compressed-stream exhaustion, decoder memory limits, ZIP grammar bounds,
evidence collisions, and deterministic bytes. Ruff, format, and Ty gates pass.
Independent review found no remaining high- or medium-severity foundation
blocker.

The prior directory-publication replacement, projection residue, visible
Windows lease, descriptor-discarding publication, successful temporary residue,
cleanup race, and quarantine-capacity findings are resolved. Descriptor
metadata and ACP inventory semantics remain intentionally scoped: they are
exact caller-supplied metadata and opaque digest-bound evidence, not a qualified
source catalog or semantic dependency closure. Target-native install,
relocation, license, CycloneDX, and redistribution evidence remain required
before a target capsule or release workflow can be called complete.

### capsule-publication-docstring-drift | low | Docstrings described obsolete randomized staging semantics

Type: documentation accuracy. Status: resolved after the final independent
review. The public projector and archive-writer docstrings now describe fixed
Windows slots, anonymous Linux file staging, native no-replace publication,
fail-closed unsupported hosts, and the bounded quarantine model.

## Capsule-foundation corrective re-review

Status: REVISED AFTER CONTRADICTORY IMPLEMENTATION EVIDENCE. The historical
approval above is retained because it records the review that occurred, but its
POSIX premise was inaccurate: the reviewed implementation identity-checked a
named source and then renamed that name, leaving a same-user check-to-rename
swap interval. The current correction restores the contract the approval
claimed: Windows publishes the exact held handle, Linux may publish an
anonymous ``O_TMPFILE`` through descriptor-bound ``linkat``, and named POSIX
files plus POSIX directories fail closed.

### capsule-posix-publication-not-identity-bound | high | Named sources could be swapped after validation

Type: filesystem authority and publication safety. Status: resolved in the
corrective pass. Named POSIX file and directory publication now raises
``ENOSYS`` before any name-based rename. POSIX tests require the destination to
remain absent and the owned projection quarantine to remain bounded; Windows
retains exact-handle no-replace publication.

### active-run-feature-selector-unindexed | medium | Feature-only discovery lacked a matching index

Type: query scalability. Status: resolved in the corrective pass. The schema
and migration now provide the ``is_active, feature_tag, created_at DESC, id
DESC`` index, and the real 100,000-row query-plan test covers the feature-only
selector as well as workspace-plus-feature discovery.

### gateway-and-migration-api-docs-missing | medium | New operator surfaces lacked Sphinx references

Type: user documentation. Status: resolved in the corrective pass. The module
reference now registers the authentication, transaction, and migration modules
and their public objects with Sphinx roles. The operator guide documents bearer
reuse, public health behavior, tokenless fail-closed behavior, and the internal
one-time desktop migration command.

### corrective-history-deleted | medium | Rolling audit approval was removed instead of superseded

Type: audit governance. Status: resolved in the corrective pass. The historical
review is restored verbatim and this re-review appends the contradictory
evidence and revised disposition rather than rewriting history.

### snapshot-and-discovery-api-docs-missing | medium | Later public modules were absent from the API registry

Type: user documentation. Status: resolved after formal re-review. The Sphinx
module reference now registers the desktop consistency-group snapshot models
and functions plus the bounded active-run discovery projection. The operator
guide explains quiescence, descriptor visibility, interrupted-restore markers,
viewer rebinding, selector bounds, and the authoritative per-run follow-up.

### real-corpus-tests-used-skip | low | Enrolled-corpus integration tests bypassed a missing prerequisite

Type: test policy. Status: resolved after formal re-review. The three real-rule
corpus tests now fail with an enrollment instruction when the required synced
corpus is absent; they no longer use ``pytest.skip``.

### provider-credential-cleanup-timeout | low | One pre-existing provider cleanup test is timing-sensitive

Type: test reliability. Status: open follow-up. A broad changed-file review run
observed ``test_turn_failure_after_build_cleans_credential_home`` time out once
instead of reaching its expected prompt ``RuntimeError``; the edited assertion
in that file is unrelated. Keep this queued for provider-process teardown
diagnosis if the canonical isolated gate reproduces it.

### desktop-vault-hygiene-warnings | low | Existing annotations and feature index remain noisy

Type: audit hygiene. Status: open follow-up. ``vault check all`` is structurally
clean but still reports template annotations, execution-record whitespace, and
a stale ``desktop-product-profile`` feature index. These warnings do not alter
the capsule safety disposition and remain visible for the next curation pass.

## `W02.P06.S26` mutable-store manifest review

Formal review of commit ``901da93f`` required revisions. The focused tests
passed, but the exported manifest does not satisfy the approved store
schema-version and single-authority contract. Step ``S26`` is reopened.

### s26-schema-version-absent | high | The checkpoint store binds an authority label but no semantic version

Type: contract completeness. ``MutableStore`` carries ``kind``, ``derivable``,
and ``schema_authority`` only. ``checkpointer-schema`` is a label, not a
version. Add a bounded semantic schema version for every store. Derive the
primary value from the packaged Alembic head. Define and enforce a project-owned
checkpoint schema version against the real required schema. Never use SQLite's
mutable ``PRAGMA schema_version`` cookie as release metadata.

### s26-membership-authority-duplicated | high | Contract and snapshot modules independently declare the store closure

Type: architecture ownership. ``snapshot.consistency_group_members`` claims
single authority, but ``contract.DESKTOP_CONSISTENCY_GROUP`` repeats both store
kinds and both non-derivable values. The reconciliation test then mirrors the
enum translation. Make ``snapshot.consistency_group_members`` the only
production declaration. Make runtime store setup and manifest generation
consume it.

### s26-minor-version-compatibility-broken | high | Required 1.1 data contradicts the directional parser rule

Type: versioned compatibility. A valid 1.0 manifest lacks the required
``consistency_group`` field, yet ``contract_versions_compatible("1.0",
"1.1")`` still claims a 1.1 consumer can read it. Increment the major contract
version, or make the 1.1 parser accept valid 1.0 manifests. Reject updater
operations that require ``consistency_group`` when the manifest lacks it.

### s26-generated-schema-underconstrained | high | Dashboard schema validation can accept incomplete or duplicate membership

Type: cross-repository validation. Pydantic rejects missing and duplicate store
kinds, but the exported JSON Schema Draft 2020-12 definition permits arrays
containing one or two items. Require exactly one primary and one checkpoint
store with unique ``kind`` values. Prove both invalid cases fail through the
real validator.

### s26-derivability-unproved | high | A Boolean can authorize omission without reconstruction evidence

Type: integrity contract. Any candidate manifest can set ``derivable=true``
without naming a reconstruction authority or proof. Constrain every current
member to ``derivable=false``. Before permitting ``true``, replace the Boolean
with a tagged object that identifies the reconstruction mechanism and carries a
size-limited proof reference.

## Architecture-owner disposition after outer-generation mapping

Status: INNER PUBLICATION SAFETY PASS; END-TO-END PRODUCT ACTIVATION FAIL.
This is the latest disposition. Historical implementation-approval sections
above describe earlier review snapshots and do not close producer Steps
``W01.P03.S13`` through ``S15``, authorize a release, or establish that a
dashboard receipt can safely activate the current output.

The pinned inner-publication snapshot remains independently acceptable for its
narrow filesystem-safety claim. The reviewed production hashes are
``29360075558E8961DBF13B91E22EFACFA34B5151A9E4873EF8944FEE2504FD78`` for
``_capsule_archive_io.py``,
``9977638F53664B9E8E4298E731AA4D8CF6185FEFE9248D90939643B498CF91FC`` for
``_filesystem_authority.py``,
``DC3C80C13487F5E51059237BE01C279552345FCE2B410BC8E8724B40BA9D2E62`` for
``capsule.py``, and
``BF67D40D4F3BD793733CF0AAD4C1E9C2ECC3A796533EAE58D918C3C1A737A2A6`` for
``capsule_evidence.py``. The race contract hash is
``20337F281149D0CCD23135A6C8ACBEA74726F74660BD37CD712A9596B461ADB5``.
It contains no POSIX ``ENOSYS`` acceptance branch: POSIX directory publication
fails the test because the test requires exactly one real winner, one
no-replace loser, and the winner's bytes.

The accepted architecture already provides the portable completion path. The
dashboard creates a final-name generation that remains unpublished because no
active receipt selects it. A2A claims one absent prefix and writes exclusively
through continuously leased descriptor or handle authority, returning
deterministic evidence without an inner rename. A failure poisons the complete
unpublished generation; A2A does not perform name-based partial cleanup. The
dashboard verifies the complete generation and makes it visible only by
committing a complete active receipt. No new ADR is required because both
accepted provisioning records already assign release-set receipt, activation,
and rollback authority to the dashboard.

The cross-repository code audit found that the dashboard cannot yet serve as
that visibility transaction. Unreceipted generation directories are inert:
production start derives a generation only from ``receipt.active_generation``
and no production consumer scans the generations directory. However:

- ``LifecycleController::active_receipt`` accepts parsed ``Staged`` and
  ``RollingBack`` records instead of requiring an active receipt.
- ``Receipt::persist`` uses a predictable process-identifier temporary name,
  path-based write and rename, and no file or directory durability barrier.
  It also stores candidate interruption state at the active receipt path.
- The receipt does not bind the dashboard build, complete release-set manifest
  digest, component-lock digest, or installed-generation file digest table.
- Gateway start reads ``component.lock`` from the candidate generation itself
  and verifies manifest claims, but it does not establish a dashboard-trusted
  lock identity or verify every installed byte against the receipt-bound
  release set.

The canonical plans now expose these findings instead of preserving false
completion. A2A Steps ``S13``, ``S14``, and ``S15`` are open; new Steps ``S94``
through ``S97`` own the direct unpublished-generation projector, exact-file ZIP
writer, real process tests, and child-directory authority. Dashboard Steps
``S08``, ``S11``, and ``S16`` are reopened; new Steps ``S162`` through ``S165``
own generation identity, inertness, receipt-bound installed-byte verification,
and start refusal. Self-install ``S51`` and product-build ``S64`` now require
final-name unpublished generations and receipt-only activation without a POSIX
tree rename.

Commit ``9b78c16479951838033d5318a624099f841c5bbd`` remains unsuitable as release
evidence because it recorded the foundation before this end-to-end contract
was reviewed. No target artifact, tag, installer, or release may be published
from it. Target-native macOS and Linux evidence, Intel macOS cryptography,
Windows C runtime redistribution and servicing provenance, qualified ACP and
Anthropic SDK redistribution authority, and the immutable five-target cohort
remain independent blockers.

## `W01.P03.S97` unpublished child-authority review

Status: PASS AFTER REVISION.

The first S97 review rejected an impossible identity claim. POSIX `mkdirat`
does not return a descriptor, and a real `renameat2(RENAME_EXCHANGE)` probe
proved that a prepared directory could replace the newly created child before
`openat`; matching the opened descriptor to the current name did not prove it
was the inode created by that invocation. The plan and implementation now state
the achievable product invariant instead of hiding that gap.

The accepted primitive atomically requires an absent child name, acquires a
no-follow lease of the current child before any write, requires that exact
leased child to be empty, and performs no cleanup or publication on failure.
POSIX enumerates the held descriptor directly. Windows brackets enumeration
with held-handle and named-path identity validation. A pre-lease substitution
can only poison an unpublished generation; it cannot select one. Complete
generation verification and the dashboard's active receipt remain the sole
visibility boundary.

Independent re-review found no critical, high, or medium finding. Windows
reported six focused passes and WSL CPython 3.13 reported ten focused and
POSIX-regression passes. Ruff, Ty, formatting, and the production-importing
real-file/process test policy passed. The reviewed hashes are
``6B5ED61237001BFE127B67153C7644F12C037B37FF8A07EE159E2C13C2A7A245``
for `_filesystem_authority.py` and
``5626ACB0AD81929D47185A6B111AFABA7F270B3B7AED342EA948BA2BD0932E5F``
for `test_unpublished_generation.py`.

This closes only S97. S94 must keep writes under the leased authority; S96 must
exercise the complete competing-process and substitution matrix; S14 must
verify the full generation; dashboard receipt-bound installed-byte verification
must pass before activation. Target-native and legal/provenance blockers remain
unchanged, and no release is authorized.
