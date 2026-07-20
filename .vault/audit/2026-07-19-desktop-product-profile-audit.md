---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-20'
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

## `W02.P06.S26` corrective implementation review

Status: Local pass; dashboard activation blocked.

The corrective pass resolves all five earlier high-severity findings. Snapshot-owned
specifications now declare membership once. Runtime seating and manifest
generation consume that declaration. Contract ``2.0`` requires both stores,
``derivable=false``, authority pairs, and explicit schema versions.

The generated JSON Schema Draft 2020-12 definition now enforces exactly one
primary and one checkpoint store. It pins the primary version and migration
head to packaged Alembic head ``0008``. It pins checkpoint schema version
``1.0.0``. Real validator tests reject missing, duplicate, derivable, mismatched,
and foreign-version groups.

### s26-sdd-column-noop | high | Resolved

The earlier backfill queried a nonexistent ``channel_values`` SQL column and
treated that failure as success. The repair decodes real ``checkpoint`` blobs
through LangGraph's production serializer. It updates their nested
``channel_values`` mapping before the semantic marker is written. Real stored
legacy state proves one row is patched and remains readable afterward.

### s26-schema-object-identity-incomplete | high | Resolved

The first structural digest covered columns only. It could accept foreign
indexes and behavior-changing triggers. Version ``1.0.0`` now binds normalized
table DDL, automatic indexes, every additional SQLite object, column facts, and
primary-key positions. Real index and trigger mutations fail validation.

### s26-compatibility-split-writable-reads | medium | Resolved

Ordinary primary and checkpoint compatibility reads now use SQLite-enforced
read-only connections. Checkpoint identity and serialized state are validated
through one open database handle, closing the split-open replacement gap.

### s26-corrupt-store-diagnostics | medium | Resolved

Corrupt primary or checkpoint bytes previously escaped as bare SQLite database
errors. Compatibility now wraps both paths in ``SchemaCompatibilityError`` with
the store identity, supported version, and staged-migration remedy. Real corrupt
files prove the bounded diagnostic contract.

### s26-dashboard-consumer-ignores-contract-2 | high | Open external dependency

The dashboard ``CapsuleManifest`` still omits ``consistency_group`` and does not
gate ``contract_version``. Default Serde behavior discards the new safety field.
Dashboard ``S06`` owns the strict parser and verifier repair. Dashboard ``S145``
owns a real producer-consumer workflow. Dashboard ``S49`` must not implement
manifest-led snapshotting until ``S06`` and ``S145`` close.

### s26-producer-consumer-proof-absent | medium | Open external dependency

A2A proves real-wheel emission and standard JSON Schema validation locally.
The dashboard still constructs legacy fixture JSON. Dashboard ``S145`` must pass
the same emitted bytes through ``vaultspec-product`` and reject every invalid
membership, authority, derivability, version, and legacy-contract case.

The final local campaign passes 378 desktop and database tests plus four focused
CLI migration tests. Ruff, scoped type checking, schema equality, and diff
hygiene pass without mocks, fakes, patches, skips, or expected failures.

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

## Final gateway-handoff corrective review

Status: LOCAL SECURITY PASS AFTER THREE REVIEW/REMEDIATION ROUNDS;
TARGET POSIX FALLBACK EVIDENCE OPEN.

### gateway-handoff-link-redirection | high | Resolved

The final implementation review found that credential publication resolved the
final ``service.token`` component before opening its temporary output. A planted
file link could therefore redirect the write outside the A2A home and make the
discovery record accept that external path. The reader also repaired Windows
ACLs while performing its documented filesystem-only classification.

Credential publication now leases the exact parent directory, rejects any
link-like or non-regular destination, and creates the payload through a private
exclusive handle. Linux prefers an anonymous descriptor. Other POSIX filesystems
use an exclusive private name, no-replace hard-link publication, and an exact
opened-versus-published identity check before the source name is removed.
Windows publishes the exact held handle. The record references only the
canonical adjacent path. Reading opens the adjacent name under the leased parent
with no-follow semantics where available, compares the named and opened
identities, validates owner permissions without mutation, and revalidates
identity before returning the token. Real filesystem tests prove a planted link
cannot alter its target and that an untrusted credential's permissions remain
byte-for-byte unchanged through classification.

### gateway-handoff-windows-search-path | high | Resolved

The follow-up review found bare ``whoami.exe`` and ``icacls.exe`` launches that
could resolve from an attacker-controlled working directory. Production now
obtains the native Windows system directory through ``GetSystemDirectoryW`` and
launches both tools by their verified absolute System32 paths.

### gateway-handoff-explicit-broad-acl | high | Resolved

The first Windows validator rejected inherited ACEs but accepted an explicit
non-inheriting ``Everyone:F`` grant. The read path now enumerates the DACL through
native Windows security APIs and accepts exactly three non-inherited allow ACEs:
the current account, LocalSystem, and built-in administrators. A real Windows ACL
test adds explicit ``Everyone:F`` and proves classification returns no token
without repairing the file.

### gateway-handoff-private-at-creation | high | Resolved

The second follow-up found that a new Windows source file inherited its parent
DACL and briefly contained the bearer before ACL restriction. Publication now
restricts and natively verifies the exact parent-directory DACL before any
credential source is created or written. A broadly explicit or inherited
application home is normalized to the same
current user, LocalSystem, and administrators authority used by the final file.
Failure to establish and verify that exact private DACL fails closed. The real
Windows lifecycle test verifies the parent is private after publication.

### gateway-handoff-posix-publication-portability | high | Resolved

The first correction required Linux ``O_TMPFILE`` on every POSIX host. The
portable checked-hard-link fallback above preserves macOS and filesystems that
do not support anonymous temporary files while retaining no-replace publication
and exact post-publication identity validation.

### cli-configured-token-precedence | medium | Resolved

Loopback discovery previously overwrote an explicitly configured gateway token,
contradicting the CLI contract. Discovery is now consulted only when no token is
configured. A real child-process CLI test proves configured authority wins over
a conflicting fresh discovery credential.

### gateway-handoff-documentation-drift | medium | Resolved

Operator and API documentation no longer claim that ``service.json`` contains
the bearer or that absence of configuration normally yields ``503``. They now
describe generated per-process credentials, the adjacent owner-restricted handoff
file, secret-free discovery, and corrupted-state fail-closed behavior.

### sphinx-public-surface-coverage | medium | Resolved

The Sphinx module index now covers lifecycle discovery, checkpoint schema
identity, consistency-group store specifications, and the specification factory,
with cross-references to the relevant operator workflow. Strict nitpicky Sphinx
with warnings as errors passes.

### gateway-handoff-posix-fallback-target-proof | medium | Open evidence

The portable named-file fallback is statically reviewed but is not forced by the
Windows campaign, and ordinary Ubuntu filesystems select ``O_TMPFILE``. The
target-native macOS/Linux campaign must execute token publication on a filesystem
without anonymous temporary-file support and prove the no-replace hard-link plus
opened-versus-published identity checks. This is queued with the existing
target-native release evidence and does not weaken the Windows security result.

All implementation findings in this review pass are resolved. The explicit
target-proof gap above and independent release blockers listed earlier in this
audit remain open.

## `W01.P03.S94` direct unpublished-generation projection review

Status: PASS AFTER THREE REVIEW/REMEDIATION ROUNDS.

The accepted additive APIs take the caller's already-live generation authority,
require exclusive mutation authority while acquiring one absent prefix, snapshot
the exact trusted source before mutation, and keep both the generation and current
empty prefix child leased across planning and every member write. ZIP and tar share
the same bounded emitter and return the existing deterministic prefixed path, mode,
size, and SHA-256 evidence. The direct path contains no inner rename, cleanup,
publication, activation, or outer-generation lifecycle operation. A failure leaves
the unreceipted generation poisoned for complete verification and owner-side discard.

### direct-projector-legacy-api-regression | high | Resolved

The first concurrent implementation replaced the established `project_archive` and
`project_source_archive` signatures and later left their legacy quarantine helpers
undefined. Existing callers and competing-process tests failed. The final design is
additive: the direct APIs have explicit unpublished-generation names, while legacy
path-based staging and native no-replace publication retain their previous signatures
and behavior through the shared bounded emitter.

### direct-projector-public-surface | medium | Resolved

An intermediate revision omitted the new direct APIs from `capsule.__all__`. Both
archive and verified-source adapters are now explicitly exported without widening the
desktop package root.

### direct-projector-collision-classification | medium | Resolved

An existing-prefix `FileExistsError` was initially thrown through the source-snapshot
context manager and mislabeled as a snapshot failure. Snapshot ownership is now held
by a separate exit stack: trusted bytes are still validated before prefix mutation,
while collision refusal remains deterministic and the snapshot always closes.

### production-docstring-plan-metadata | high | Resolved

Editorial review rejected a public docstring that named a plan Step. Production text
now describes the absent-child authority contract without repository process metadata.

Independent final review reported no remaining critical, high, medium, or low finding
for source hash
``9DE4B05ABB637D40CB74E18C544A835E66C523C40E49A645E9EFAB3081883E47``.
The Windows desktop suite passed 235 tests; focused archive, publication-race, and
child-authority coverage passed 36 tests; and a real caller-leased ZIP probe proved
direct bytes, deterministic evidence paths, and collision preservation. Ruff,
formatting, Ty, and diff hygiene passed.

This closes only S94. S95 must add exact create-new archive writing, S96 must prove the
direct process and substitution matrix, and S14 must verify the complete generation.
Dashboard-owned final-name generation creation, installed-byte verification, durable
receipt selection, and the real producer-consumer workflow remain mandatory before
activation. Target-native and legal/provenance blockers remain unchanged, and no
release is authorized.

## `W01.P03.S95` exact final-name archive review

Status: PASS AFTER REVIEW AND PUBLIC-CONTRACT REVISION.

The accepted API consumes the caller's continuously live unpublished-generation
authority, claims one portable final archive name through exact create-new file
authority, shares the existing bounded deterministic emitter, hashes and revalidates
the held output, and performs no rename, cleanup, publication, activation, or outer
generation mutation. Late failure leaves the exact partial file inert for complete
generation verification to reject.

### exact-zip-public-name-omits-unpublished-boundary | medium | Resolved

The first public name omitted the safety-critical `unpublished` qualifier even though
failure deliberately retains a partial final-name file. The exported API is now
`write_deterministic_capsule_zip_into_unpublished_generation`, matching the direct
projector and preventing callers from mistaking it for a general publication helper.

### exact-zip-exclusive-mutation-precondition-omitted | high | Resolved

The first public contract accepted a live generation lease but did not state that the
caller must also retain exclusive mutation authority for the complete composition.
That omission made the no-replacement proof appear stronger than its actual boundary.
The final docstring now requires both the continuously live lease and caller-owned
exclusive mutation authority across the operation, while leaving publication and
activation with the outer generation lifecycle.

### exact-zip-type-contract-drift | medium | Resolved

Review found import and annotation drift while the shared emitter was being extracted.
The final source uses `Mapping` for the scanned directory-identity map and passes Ruff,
formatting, and Ty without an unused or missing type import.

### exact-zip-real-authority-proof | medium | Resolved

The initial S95 code had no focused caller-leased proof. Real production-importing
tests now write deterministic bytes at the final name, verify SHA-256 and ZIP members,
refuse a second create without changing the winner, and retain the claimed zero-byte
file after a real empty-source failure. Eight unpublished-generation tests and the
38-test focused archive/publication/build/verifier campaign pass; the complete desktop
suite passes 262 tests. Ruff, formatting, Ty, and diff hygiene pass for exact SHA-256
``B72C6B49947E2BBB449F114373BD229604DE2441FECCDBE77CE4FCD22A9DA35F``.
Independent technical and editorial reviewers reported no remaining finding for that
exact source state.

### step-record-plan-drift | high | Resolved

Editorial review found that the generated Step Record heading and scope no longer
matched the canonical S95 row, and that the plan omitted the production-importing test
file modified by the Step. The plan scope was reconciled through `vaultspec-core`, then
the Step Record was regenerated through its owning CLI before its authored body was
restored. Its machine-owned heading and two scope entries now exactly reflect S95.

### unrelated-gateway-note | medium | Resolved

An intermediate S95 record attributed a Windows gateway-handoff wording correction to
the archive writer. That unrelated note was removed; gateway-handoff review remains in
its owning audit trail.

### s95-type-contract-severity-downgraded | medium | Resolved

The first corrective audit recorded the missing `Mapping` contract as low even though
it had produced three Ruff `F821` failures and broken runtime type-hint resolution.
The original medium classification is restored above; no rationale supported the
downgrade.

This closes only S95. S96 process/substitution coverage, S14 complete-generation
verification, and dashboard-owned receipt selection remain open. Target-native and
legal/provenance blockers remain unchanged, and no release is authorized.

## Final active-run gateway and discovery review

Status: PASS; FINDINGS CLASSIFIED AND RESOLVED.

### active-run-id-path-safety | high | Resolved

Client run identifiers previously allowed route separators and leading punctuation,
making persisted identities unaddressable or ambiguous on per-run gateway routes.
One shared grammar now validates start requests and every status, stream, and cancel
path. Active discovery applies the same predicate in SQL before `LIMIT`, excluding
legacy invalid identifiers without consuming the bounded page. Real gateway tests
reject invalid values before persistence or dispatch and preserve valid dashboard ids.

### active-run-discovery-cross-dialect-bound | medium | Resolved

The path-safe database filter originally risked SQLite-specific SQL. The production
predicate uses SQLAlchemy's dialect-aware regular-expression operator; a direct
compile test proves SQLite `REGEXP` and PostgreSQL `~`, while the 100,000-row real
SQLite test saturates the active index with foreign selectors and still proves the
workspace/feature prefix and bounded limit are used.

### active-run-reservation-before-dispatch | high | Resolved

Worker dispatch previously crossed the external HTTP boundary before the client run
id was durably reserved. The service now commits the submitted row and ingest request
first. A real held worker response proves status and a concurrent replay observe one
durable reservation while only one dispatch is emitted; same-id races return the
winner rather than producing a duplicate or 500 response.

The gateway credential-separation, loopback-only exposure, invalid-legacy discovery,
and bounded-selector checks are covered by the same real production-process campaign.
No finding from this active-run review remains unqueued.

## `W01.P03.S96` direct-generation process and substitution review

Status: PASS AFTER MULTI-PLATFORM REVIEW AND REMEDIATION.

The final matrix uses only production imports, real files, real archive bytes, live
directory authorities, and spawned processes. Windows proves native handle behavior;
Linux under WSL proves descriptor-relative writes, real rename substitution, and the
intentional POSIX legacy refusal. The tests never use a fake, mock, stub, patch,
monkeypatch, `skip`, or `xfail`.

### direct-projector-permanent-coverage-gap | high | Resolved

The S94 direct projector initially had no permanent public-boundary test. S96 now
proves deterministic projection into separate generations, exact evidence, collision
preservation, path-only authority rejection, partial poison, cardinality refusal, and
substitution safety.

### legacy-posix-directory-test-drift | high | Resolved

Older portable-success and race tests contradicted the production contract that named
POSIX directory publication is not identity-bound. Portable success moved to the
direct projector, while the legacy race now requires POSIX refusal and no published
prefix. Windows retains its native one-winner expectation.

### direct-process-collision-gap | high | Resolved

Sequential collision checks did not prove the exact create-new boundary under process
competition. Distinct spawned contenders now race both a shared projection prefix and
one final ZIP name; each result identifies its contender, exactly one succeeds, and
the surviving bytes match that reported winner.

### direct-source-and-parent-substitution-gap | high | Resolved

Legacy thread churn did not prove the new authority lifetimes. Spawned processes now
attack the live generation name, a nested destination parent, the capsule source root,
the source-archive parent throughout snapshotting, and a late source file. Confirmed
substitution must fail with poison; an operating-system-blocked swap must produce the
complete trusted result. Outside sentinels and replacement bytes remain untouched.

### direct-partial-poison-proof-weak | medium | Resolved

The only direct writer failure had retained an empty file. A real late file replacement
now proves a non-empty exact-name ZIP remains inert after failure, while a corrupted
late projection member retains the already-written prefix member without cleanup.

### direct-evidence-and-authority-boundaries | medium | Resolved

The first matrix under-asserted archive evidence and omitted the direct writer's tree
bound. Both projection and archive evidence now independently match source path, size,
SHA-256, mode, ordering, and outer ZIP digest. Public calls reject path-only authority,
and real limit-plus-one archives and source trees leave bounded inert poison.

### swap-outcome-correlation-and-timing | high | Resolved

Early revisions allowed success or failure without binding it to whether a swap landed,
and the generation-name swap completed before the API call. Production-created path
and size barriers now force in-call attacks. Swapped and blocked outcomes are correlated
with failure or exact success, and source-parent churn continues until API completion.

### collision-provenance-and-limit-mirroring | medium | Resolved

Early contenders used indistinguishable payloads and one test copied the 80,000 limit
as a literal. Contenders now report identities and carry distinct bytes; boundary
inputs derive directly from the production constants instead of mirroring business
logic in tests.

### windows-symlink-capability-assumption | low | Resolved

Unconditional symlink creation depended on Windows developer privileges. File and
directory collisions remain universal, while link-like collision coverage runs on the
POSIX campaign where the capability is native and was exercised successfully.

### non-linux-posix-legacy-zip-drift | high | Resolved

Two legacy ZIP tests still required publication on macOS even though named POSIX file
publication deliberately fails closed. Portable deterministic success now uses the
direct writer. The legacy race retains Windows and Linux success but requires two
errors, no output, and only bounded zero-byte quarantines on non-Linux POSIX.

### stale-residue-and-unreachable-platform-assertions | low | Resolved

Review found a stale top-level quarantine glob after direct migration and an unreachable
POSIX branch after an earlier return. Each direct generation must now contain exactly
its final ZIP, and the remaining legacy branch expresses only its reachable host.

### transient-ready-state-flake | medium | Resolved

A full-suite run missed the worker's transient literal `ready` state and timed out even
though the worker had started. Readiness now accepts any non-empty worker status;
terminal outcomes remain gated by production-created path or size thresholds and are
still validated with process exit codes and final security assertions.

### legacy-churn-safe-collision-misclassified | medium | Resolved

A native Linux rerun showed that production can recreate the legacy output-parent name
between the attacker's rename and symlink. The harness treated the resulting
`FileExistsError` as a failure even though it means substitution was blocked. The helper
now classifies that exact collision as safe while retaining outside-sentinel, process,
authority, and residue assertions; three repeated Linux probes and the complete focused
Linux campaign pass.

### credential-tests-use-prohibited-skips | high | Open; queued as `W03.P08.S98`

The full desktop campaign exposed existing POSIX `skipif`, capability `skipif`, and
runtime `pytest.skip` branches in `test_credentials.py`, contrary to repository test
policy. This is not a capsule-authority defect. S98 now owns replacement with real
host-native assertions that never skip or xfail.

This closes only S96. S14 must verify complete unpublished generations, and dashboard
receipt-bound installed-byte verification and activation remain mandatory. The open
credential-test policy finding, target-native release evidence, and legal/provenance
gates continue to block release authorization. The final exact-source Windows desktop
campaign passed 290 tests with 26 deselected; its single pre-existing skip is the
credential-policy finding queued as S98 above.

## `W01.P03.S99` offline closure authority review

Status: PASS AFTER THREE FORMAL REVIEW ROUNDS; PHYSICAL EXTRACTION FOLLOW-UP OPEN.

S99 now defines canonical content-addressed authority for target-selected Python wheels,
ACP npm tarballs, their exact lock graphs, and their expected installed trees. The final
public loader cannot return the combined closure until both locks, every selected package
archive, every external license byte source, and every installed-license source join pass.
This remains candidate assembly input and grants no publication, receipt, activation, or
independent provenance authority.

### nominal-lock-and-target-selection | high | Resolved

The first inventory shape bound lock digests without proving the selected graph, roots,
target markers, nested npm installation identity, or one exact native SDK. Exact uv lock
and package-lock bytes are now parsed fail-closed, roots and reachability are explicit,
unreachable extras reject, nested package paths remain distinct, and excluded RAG and
Torch capabilities cannot enter the desktop closure.

### package-bytes-not-structurally-authoritative | high | Resolved

Early package records could describe arbitrary blobs. Real wheel and npm bytes now match
content-addressed SHA-256 identities, npm SHA-512 integrity, URL and version authority,
safe portable member paths, bounded expansion, archive identity, wheel `WHEEL` tags, and
complete `RECORD` hashes. Links, special members, traversal, collisions, encryption,
wrong identities, absent evidence, and compression bombs reject.

### installed-tree-authority-opaque | high | Resolved

The first closure descriptor did not bind the post-install result. Each closure now joins
one canonical content-addressed installed inventory containing sorted path, mode, size,
SHA-256, entrypoint, license, aggregate-size, file-count, and tree-digest facts. Descriptor
and inventory target, root, lock, source inventory, counts, size, and digest must all agree.

### installed-dashboard-domain-drift | high | Resolved

Review showed that NFC paths, per-closure 80,000-file bounds, unbounded combined license
counts, and duplicate license paths could create locally valid authority that the dashboard
must reject. Installed paths now use the dashboard segment grammar; Python plus ACP share
the dashboard-wide 80,000-file, 8 GiB, and 4,096-license bounds; cross-closure paths and
semantic license paths are unique; and component tokens plus canonical SPDX expressions
fit the dashboard schema.

### installed-license-source-join-absent | high | Resolved

Package-name coverage alone allowed arbitrary installed files to be relabelled as license
evidence. Every installed license now identifies one exact archive member or external
license source, carries the same canonical SPDX claim, and matches the verified source
digest. Every declared source is covered exactly once before the combined loader returns.

### real-wheel-license-metadata-unrepresentable | high | Resolved

Requiring `License-Expression` and one in-wheel license member made unavoidable locked
wheels impossible to represent. Version-aware handling now supports Metadata 2.4
`.dist-info/licenses` members, Metadata 2.1 direct and legacy license directories, and an
explicit curated SPDX fallback when the optional expression is absent. Deficient wheels
may bind separately supplied content-addressed external license bytes with an exact source
id, declared member, HTTPS provenance claim, size, SHA-256, and redistribution reference.
Missing, ambiguous, changed, or unreferenced external bytes reject.

### npm-semver-and-node-engine-drift | high | Resolved

The initial npm graph discarded dependency ranges and ignored `engines.node`. A partial
PEP 440 implementation then diverged from npm for prereleases, zero-major carets, partial
comparators, and short-circuited invalid OR branches. The accepted bounded evaluator
supports the stable forms mechanically present in the lock, rejects prerelease and
unsupported syntax before evaluation, evaluates every clause and token, and checks normal,
optional, peer, and Node-engine ranges. The pinned Node 22.17 runtime rejects incompatible
requirements. An independent differential checked 486 stable cases and all 183 real lock
edges against npm's bundled SemVer implementation with zero mismatches.

### wheel-runtime-and-platform-false-acceptance | high | Resolved

Compatibility originally accepted future CPython ABI tags, future macOS and manylinux
floors, native-ABI `any` wheels, and raw Linux tags with no glibc proof. The single wheel
compatibility authority now permits only CPython 3.13-compatible ABI forms, pure
`none-any`, target-native Windows and macOS tags within the recorded floor, and bounded
manylinux policies no newer than glibc 2.28. Raw Linux and future-floor inputs reject.

### exact-runtime-marker-drift | high | Resolved

Python markers originally used a nominal 3.13.0 environment instead of the descriptor's
exact 3.13.5 runtime. Lock reconciliation now receives the exact runtime release, validates
the `requires-python` contract, and evaluates patch-sensitive markers against that release.

### complete-verification-was-optional | medium | Resolved

Earlier callers could load lock-reconciled inventories without invoking package archive
and installed-license verification. The combined loader now performs the complete sequence
and returns the verified package results. A real-files test proves success with every byte
present and fail-closed behavior when one wheel disappears.

### duplicate-weaker-lock-and-wheel-apis | low | Resolved

Test-only path readers duplicated the production exact-lock snapshot path, and wheel
compatibility had a second public export. The weaker wrappers and duplicate export were
removed; production and tests use the exact byte APIs and single compatibility home.

### archive-preflight-snapshot-and-scanner-duplication | medium | Open; queued as `W01.P03.S100`

Package and capsule scanners still duplicate bounded path and member traversal. Expansion
ratio checks now occur before evidence reads, but ZIP central-directory preflight, fully
streamed member verification, and retention of the verified package snapshot through
extraction remain mandatory. S100 owns consolidation before S13 may extract package bytes.

### final-dashboard-tree-and-trusted-commit-join | medium | Open; assigned to `W01.P03.S13` and `W01.P03.S14`

Per-closure authority is only substrate. S13 must combine Python, ACP, CPython, Node, the
A2A distribution, and launcher files; reserve aggregate capacity for all of them; reject
cross-component collisions; and emit one dashboard `vaultspec-installed-tree-v1` bound to
the component manifest digest. The A2A source commit remains a candidate claim until the
dashboard independently joins it to the trusted component lock. S14 must verify the whole
unpublished generation without a source checkout.

The final exact-hash focused campaign passes 102 tests. The complete Windows desktop
campaign passes 384 tests with 26 deselected and the one pre-existing credential-policy
skip queued as S98. Ruff, formatting, Ty, and diff hygiene pass. Independent dashboard,
contract, and code-health reviewers found no S99 blocker; the sole carried medium finding
is assigned to S100 above. This closes only S99 and authorizes no release.

## `W01.P03.S100` shared archive authority review

Status: PASS AFTER THREE FORMAL REVIEW ROUNDS; ONE CONTROLLED-INPUT COMPATIBILITY
LIMITATION CARRIED.

S100 consolidates package, capsule, and manifest archive inspection behind one bounded
authority. ZIP central-directory and raw TAR controls are inspected before high-level
archive readers materialize members. Package verification can retain the exact regular
file snapshot through a scope-bound, read-only consume session, and the combined closure
loader exposes sequential retained handoffs for Python wheels, ACP packages, external
licenses, and the root A2A wheel. These are assembly prerequisites only; they grant no
publication, receipt, activation, provenance, or release authority.

### zip-preflight-trusted-high-level-parser-too-early | high | Resolved

Type: archive parser hardening. ZIP inputs previously reached `ZipFile` before independent
central-directory validation. The shared authority now scans EOCD and central-directory
records first, rejects multi-disk and ZIP64 overrides, reconciles the observed entry count,
and bounds central-directory bytes before the high-level parser opens the archive.

### forged-eocd-member-count-bypassed-cardinality | high | Resolved

Type: resource exhaustion. An EOCD count could understate real central-directory entries.
Preflight now counts every central record and requires exact agreement. Real forged-count
and 80,001-member regression inputs fail before extraction.

### wheel-record-verification-materialized-large-members | high | Resolved

Type: memory safety. Wheel `RECORD` verification could allocate a complete member even
when the archive-level bound permitted a very large file. Member digests are now streamed
in bounded chunks after `RECORD` syntax and size declarations pass.

### verified-evidence-did-not-retain-verified-bytes | high | Resolved

Type: authority lifetime and TOCTOU. Detached package evidence exposed a diagnostic path
that later consumers could reopen after replacement. Verification and consumption now
share an anonymous retained snapshot. Read views are scope-bound, read-only, non-nestable,
and invalid after scope exit; evidence is getter-only and cannot be rebound. Detached
verification remains evidence only and is explicitly not extraction authority.

### closure-handoff-reopened-unbound-package-and-license-paths | high | Resolved

Type: integration authority. The complete closure loader originally returned detached
evidence without a typed consume seam. It now retains the resolved input directory and
opens one reverified Python package, ACP package, external license, or root A2A wheel at a
time, comparing the full evidence object to the originally loaded result before yielding
the exact bytes. Sequential scopes avoid retaining thousands of handles.

### tar-control-records-had-no-cumulative-bound | high | Resolved

Type: resource exhaustion. Individually bounded PAX and GNU extension records could still
consume unbounded aggregate control bytes. Raw TAR preflight now charges every control
record against per-record and cumulative expanded-byte limits, rejects sparse forms, and
requires valid termination without non-zero trailing data.

### archive-snapshot-and-scanner-duplication | medium | Resolved

Type: duplicated code and contract drift. Package, capsule, and manifest paths carried
overlapping snapshot, path, collision, type, ratio, and aggregate-size logic. The shared
`_archive_authority` is now the single production home for retained regular-file snapshots,
ZIP/TAR member validation, central-directory preflight, raw TAR control inspection, and
bounded single-stream gzip decoding. Consumers retain only format-specific policy and
error normalization.

### zip-and-tar-cardinality-policy-was-accidentally-coupled | medium | Resolved

Type: contract correctness. Applying ZIP's non-ZIP64 ceiling to TAR narrowed the intended
TAR input domain. Ordinary ZIP remains capped at 65,534 entries, TAR at 100,000 entries,
and the final projected dashboard tree remains capped independently at 80,000 files.

### gzip-framing-boundary-lacked-persisted-evidence | medium | Resolved

Type: security regression coverage. A production-importing real-byte test now proves one
valid gzip member succeeds while raw trailing bytes and a concatenated second member fail.
The shared decoder also bounds expanded bytes and emits an anonymous retained payload.

### plan-metadata-leaked-into-delivered-code | high | Resolved

Type: architecture independence. Four production docstrings and one test name referred to
a plan Step instead of the product invariant. They now describe retained consume scopes in
product language; no plan identifier remains in the delivered implementation or tests.

### readonly-session-test-failed-the-type-gate | low | Resolved

Type: repository verification. The evidence-rebinding regression originally used an
incorrect type diagnostic suppression. It now attempts the runtime mutation through
`object.__setattr__`, still proves `AttributeError`, and passes the locked repository-wide
Ty gate without suppression.

### dead-and-duplicated-local-archive-branches | low | Resolved

Type: dead and duplicated code. Consolidation removed the duplicate local scanners,
snapshot wrappers, gzip paths, and an unreachable compressed-size check. The final diff
passes Ruff, formatting, Ty, and prohibited-test-pattern review.

### eocd-signature-inside-zip-comment | low | Carried; controlled input rejects safely

Type: compatibility. The independent EOCD search can identify a structurally plausible
signature embedded in a ZIP comment that CPython's `ZipFile` later cannot open. The public
boundary normalizes this as a safe archive rejection, so it is not a validation bypass or
resource-safety defect. Supporting that unusual controlled input would require replacing
or compensating for the runtime parser and is not required for desktop closure artifacts.

The final focused package, artifact, capsule, and manifest campaign passes 117 tests. The
complete desktop campaign passes 365 tests with the existing POSIX credential permission
skip already tracked separately. Ruff lint and formatting, locked repository-wide Ty,
diff hygiene, and the prohibited test-pattern scan pass. Three independent formal
reviewers matched all eight implementation/test SHA-256 identities and unanimously
approved with no remaining critical, high, medium, or low S100 blocker. This closes only
S100. Whole-generation assembly, verification, publication, trusted component-lock joins,
and dashboard receipt-bound activation remain mandatory under S13 through S15.

## `W01.P03.S101` retained capsule-input authority review

Status: PASS AFTER THREE FORMAL REVIEW ROUNDS; S13 REMAINS OPEN.

S101 establishes one exact-byte capability for assembly inputs. It does not publish a
generation, install the component tree, establish trusted dashboard component-lock
membership, or activate anything. Those duties remain queued under S102, S103, S13,
S14, and S15.

### complete-input-authority-not-retained | high | Resolved

Type: authority lifetime and TOCTOU. The first session retained the descriptor, locks,
and source artifacts but re-opened inventories, packages, and external licenses by
mutable cache paths. The final session retains every input class before yielding and
serves package and license access only from session-owned snapshots.

### path-capabilities-escaped-the-session | high | Resolved

Type: capability leakage. Public session properties exposed closure and artifact records
that contained reopenable paths. The session now exposes only immutable, path-free
inventory and package evidence, with every byte accessor guarded by the parent lifetime.

### descriptor-null-serialization-rejected-valid-target-neutral-sources | high | Resolved

Type: descriptor-v2 serialization contract. TOML omits null fields, while target-neutral
A2A and ACP sources had optional fields without model defaults. The descriptor model now
accepts omitted optional fields and the real TOML descriptor regression proves the
round-trip.

### retained-snapshot-cardinality-and-byte-budget-unbounded | medium | Resolved

Type: resource safety and availability. Retaining every logical input could consume
thousands of simultaneous temporary-file handles and unbounded temporary storage. The
session now deduplicates by verified digest and size, limits retained snapshots to 512 and
deduplicated bytes to 8 GiB, rejects declared overloads before closure work, and has real
count, byte, and duplicate-retention regressions.

### teardown-error-left-a-partially-unwound-session-active | medium | Resolved

Type: lifetime error state. A raw OS error while `ExitStack` unwound could consume cleanup
callbacks while leaving the session apparently usable. The lifecycle lock now makes
teardown terminal before callbacks run, normalizes supported cleanup errors, and a real
`os.close(-1)` regression proves that post-error access rejects.

### test-only-toml-writer-was-transitive | medium | Resolved

Type: dependency hygiene. Descriptor serialization tests imported `tomlkit` only because
the optional RAG environment happened to provide it. It is now an explicit tooling
dependency and isolated tooling import succeeds.

### session-to-manifest-and-license-matrix-was-incomplete | medium | Resolved

Type: real-behavior coverage. The final integration case mutates every descriptor, lock,
source, inventory, installed-inventory, Python package, ACP package, and both Python and
ACP external-license paths after session creation. It still emits the real built-wheel
manifest and reads the retained original bytes.

### direct-bound-api-input-normalization | low | Resolved

Type: public-boundary robustness. Invalid enum-like kinds, unhashable digests,
non-binary streams, and malformed descriptor digest identities now fail as domain errors
rather than leaking Python type errors.

Three independent final reviewers rechecked the exact frozen artifacts and approved with
no critical, high, medium, or low S101 finding. Focused verification passed 57 tests;
the complete desktop campaign passed 367 tests with the known POSIX credential-permission
skip. This closes only S101 and leaves S102 onward open.
