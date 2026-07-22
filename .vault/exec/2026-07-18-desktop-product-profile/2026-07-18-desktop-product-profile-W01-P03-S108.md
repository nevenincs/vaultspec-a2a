---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S108'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Compose the Windows product launchers from the content-addressed console stub a relocatable launcher-dir shebang pinning the bundled interpreter and a deterministic epoch-stamped zip that pins the library root replacing the fail-loud Windows refusal and proving one composed launcher by live execution

## Scope

- `src/vaultspec_a2a/desktop/capsule_materializer.py`
- `scripts/desktop_capsule_inputs.toml`
- `src/vaultspec_a2a/desktop/tests/test_capsule_materializer.py`

## Description

- Declare the console-launcher stub donor as a content-addressed build input
  (`url`, `sha256`, `version`, `license`, plus the donated `member` and its own
  `member_sha256`) beside every other pinned download.
- Pin the donated member and its digest in the materializer, and add
  `extract_windows_launcher_stub`, which reads exactly that one member from the
  donor archive and content-addresses it; the donor's Python modules are never
  imported, so the donating library is neither a build- nor a run-time
  dependency.
- Add the Windows launcher composer: stub bytes, then one fixed ASCII shebang
  quoting the bundled interpreter addressed through the stub's own relocation
  token and carrying the isolated-mode flags, then a deterministic zip whose
  `__main__` walks back to the capsule root from its own location, exports the
  capsule root, pins the materialized library root at the head of the import
  path, and calls the contract console-script entrypoint.
- Replace the fail-loud Windows refusal with the generator: a Windows target now
  composes and writes the launcher pair 0755 through the same leased-descriptor
  write path as the POSIX pair, and refuses loudly when the stub bytes are
  absent or do not match the pinned digest.
- Extend the console-reference validator with an ASCII check, since both
  generators embed the reference verbatim in ASCII-encoded launcher content.
- Add real-behavior tests: declaration-to-code binding, three extraction
  fail-closed cases, six malformed-reference cases, composition shape and
  determinism against the real stub, byte-exact launcher-pair materialization
  in a real Windows-target capsule across two generations, and a live execution
  proof.

## Outcome

Verified stub input: donor
`https://files.pythonhosted.org/packages/02/08/9c41fb51ab5b43eb21674aff13df270e8ba6c4b29c8624e328dc7a9482af/distlib-0.4.3-py2.py3-none-any.whl`,
sha256 `4b0ce306c966eb73bc3a7b6abad017c556dadd92c44701562cd528ac7fde4d5b`
(470 628 bytes), license PSF-2.0; donated member `distlib/t64.exe`, sha256
`81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7`
(108 032 bytes). Both digests were computed here from the downloaded bytes
against the release index, not copied from a secondary source. The composition
format was read from the donor's own script-writing source, which builds every
Windows console executable as launcher plus shebang plus zip data, with the
simple shebang form `#!` plus executable plus interpreter arguments plus one
newline; the relocation token and its trailing separator, the quoted-executable
support, and the `.exe` requirement were confirmed against the stub binary's own
embedded parser strings.

Live execution proof (this Windows host, real composed executable, not a
simulation): a capsule tree was laid out under a path containing a space, the
interpreter subtree was junctioned to a real standalone Windows CPython (whose
layout matches the bundled one exactly: interpreter at the subtree root, no
`bin/` segment), and the composed 108 533-byte executable was run directly. It
exited 0 having reached the intended entrypoint, reporting argument passthrough
`["live", "proof"]`, import-path head equal to the capsule's own library root,
and the exported capsule root. An ambient import path injected through the
environment did not appear on the interpreter's search path, and no bytecode
cache was written into the capsule tree, so both isolated-mode flags took
effect through the shebang. This closes the sub-decision the decision record
carried as documentation-verified: the stub's relocation-token behavior, its
acceptance of a quoted executable and interpreter arguments, and the appended
zip's execution under isolated mode are now proven by execution.

What remains target-specific and unproven by this run: the bundled per-target
CPython bytes themselves (the interpreter subtree is a verbatim projection this
module never writes, and the host interpreter stood in for it through a
junction), and the full production dependency closure behind the two contract
console-script references. Neither is launcher-composition behavior.

Gates, all green: `ruff format` (3 files), `ruff check` over the desktop package
and the build scripts, `ty check` over the touched files on the host platform
and again with the platform pinned to linux, the two touched test modules
(19 passed, 3 deselected), the service-marked launcher tests (3 passed, 10
deselected), and the desktop package regression suite (441 passed, 3
deselected). The materializer module stands at 746 lines, within its bound.

## Notes

- The live-execution test found a real defect that byte-shape assertions alone
  would have missed: the zipapp's capsule-root walk was one parent short,
  because the launcher archive's `__main__` entry contributes a path segment of
  its own. The composed executable failed to import its entrypoint; the fix is
  the corrected parent count, and the live test is what proves it.
- Determinism required pinning two zip-entry fields the standard library
  defaults from the *building* host's platform and umask. Left unpinned, a
  launcher built on a POSIX release runner would not be byte-identical to one
  built on Windows despite identical inputs.
- The tests that need the real stub acquire it from its declared URL and are
  marked as service tests, matching how the capsule build certification already
  treats network-dependent inputs; the default suite stays offline and still
  covers every fail-closed path.
- Residual, raised for the queue: the donated stub bytes are redistributed
  inside each product launcher under a license whose notice-retention term is
  recorded only in the build-input declaration. Surfacing that notice inside the
  capsule would require a new reserved destination, which is outside this Step's
  scope and outside the unchanged launcher contract.
- Residual: a future Windows arm64 target needs its own stub member declared
  through this same mechanism; the pinned member is x86-64 only.
- Test scope grew beyond the Step row's declared files by one new test module
  dedicated to the Windows launcher, so the existing materializer test module
  keeps its closure-replay focus.
