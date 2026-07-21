---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S115'
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
     The S115 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Acquire every wheel tarball license blob and pinned source into the sha256-keyed content-addressed cache verifying each byte against its committed pin and failing closed on any digest mismatch and ## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_acquisition.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Acquire every wheel tarball license blob and pinned source into the sha256-keyed content-addressed cache verifying each byte against its committed pin and failing closed on any digest mismatch

## Scope

- `src/vaultspec_a2a/desktop/capsule_input_authoring.py`
- `src/vaultspec_a2a/desktop/tests/test_capsule_acquisition.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

- Add `acquire_artifact` to the input-authoring module: the sole network boundary that
  fetches one pinned byte source, verifies it against every supplied pin, and admits it
  into the content-addressed cache only after every pin matches.
- Stream the response into a temporary file under the cache root while computing both a
  sha256 and a sha512 digest and enforcing the declared size and a hard byte ceiling, so
  no artifact is ever held whole in memory and an over-long response fails during the
  stream.
- Verify fail-closed: a size, sha256, or sha512-SRI mismatch raises before any bytes are
  linked under a content address, and the temporary file is removed on any failure so a
  rejected artifact never lands in the cache.
- Key the cache by the verified sha256 even when only a sha512 integrity pin was supplied
  (the npm case), so a later consumer resolving the cache by sha256 receives exactly
  these bytes.
- Make acquisition idempotent: when a sha256 pin is known and the cache already holds a
  file at that content address whose bytes still verify, reuse it without re-fetching; a
  cached file whose bytes no longer match its own name is distrusted and re-acquired.
- Expose the byte source through an `open_stream` seam typed by a minimal `ByteReader`
  protocol, defaulting to a real HTTPS opener, so the verify, cache, and fail-closed
  logic is exercised against real byte streams offline while the real network path is
  proven by one service-marked test.
- Reject a non-HTTPS URL, a malformed sha256 pin, and an acquisition with no integrity
  pin at all.
- Add the offline test battery (content-address write, sha512-only pinning, each
  fail-closed branch, idempotent reuse, corrupted-cache re-acquisition, and the input
  guards) plus one service-marked test acquiring the real pinned launcher stub over the
  network and confirming its content address.

## Outcome

Acquisition is now a production authority: the capsule's verified-input chain has a real
producer for the cache the downstream session consumes. The module remains the only
component permitted network access, and it confines that access to one function behind
one HTTPS boundary. Every acquired byte is proven against its committed pin before it is
admitted under its content address, so the supply-chain trust root stays the committed,
human-reviewed pins and a mismatch can never enter the cache.

The service-marked test acquired the real pinned launcher stub over live HTTPS and
confirmed its bytes hash to the committed sha256 and land under that content address; the
offline battery proves the same verify, cache, idempotency, and fail-closed behaviour
against real byte streams without touching the network.

Gates on the four-target base: `ruff format` and `ruff check` clean across the desktop
package and the scripts tree, `ty check` clean on both touched files under the host
platform and `--python-platform linux`, and the full desktop suite at 512 passed with 4
deselected - the prior 502 plus the 10 offline acquisition cases, with the one
service-marked case deselected by default and separately proven green against the network.
The module stands at 392 lines, well within the size budget.

## Notes

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

- The `open_stream` seam is official module API, not a test shim: it takes a real byte
  source and defaults to a real HTTPS opener. The offline tests pass a real in-memory
  binary stream over real bytes through it, so the acquirer's logic runs against genuine
  streams with no mock or monkeypatch; the real socket transport is exercised by the
  service-marked test. Testing the verify/cache/fail-closed logic offline and the
  transport online is a deliberate division, not an avoidance of the network.
- The cache write is atomic: bytes stream to a per-process temporary name and are renamed
  into place only after every pin verifies, so a crashed or rejected acquisition leaves no
  half-written content address. Reusing an existing content address re-reads and re-hashes
  its bytes before trusting them rather than trusting the filename.
- Scope discipline: this Step adds acquisition only. It does not resolve closures (that is
  the reconciliation selection core it will later call), does not derive license identity,
  and does not emit inventories or a descriptor - those are the following Step and the
  build script. The acquirer is a generic pinned-source primitive that the closure
  resolution, the curated overrides, and the pinned toml sources will all feed.
- The service-marked test caches under the existing gitignored `dist/capsules/.cache`
  tree, matching the launcher step's convention, so repeated live runs do not re-download.
