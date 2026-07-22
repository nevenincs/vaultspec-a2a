---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W04.P11` summary

Phase P11 delivered whole-tree process ownership: a bounded drain gate wired
into run admission and every production stop path, terminal-boundary token
release, and operating-system containment (Windows job objects, POSIX
sessions and process groups) for the desktop worker, every run-owned
provider root, and their terminal and bridge descendants, proven by an
integrated real-descendant certification. All eleven Steps (S56 through S62
and the interposed S89 through S92 hardening rows) are closed; independent
review's two high findings were remediated and one medium bound was
documented honestly, with the remaining medium folded into the admission
phase that owns the affected path.

- Modified: `src/vaultspec_a2a/api/app.py`,
  `src/vaultspec_a2a/api/routes/gateway.py`,
  `src/vaultspec_a2a/api/routes/admin.py`,
  `src/vaultspec_a2a/worker/executor.py`,
  `src/vaultspec_a2a/control/worker_management.py`,
  `src/vaultspec_a2a/providers/_subprocess.py`,
  `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`,
  `src/vaultspec_a2a/utils/process.py`
- Created: `src/vaultspec_a2a/control/drain.py`,
  `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`

## Description

The drain gate atomically closes admission, tracks active runs, and reports
truthful quiescence; run starts are refused while draining, and after review
remediation the lifespan shutdown and the authenticated administrative stop
both close admission before any process stops. Token release moved to the
terminal boundary: actor tokens survive input-required pauses and are
released exactly once on terminal outcomes. A single containment authority
wraps every owned root — the desktop worker and each run-owned provider
tree — in a kill-on-close job object or a new session and process group
before descendant work, with bounded, discovery-free termination. The audit
rows found and fixed one real gap (terminal children escaped containment on
the POSIX path) and locked the three specification-only bridge modules with
regression assertions proving no launch spec escapes the owning provider
group. The integrated certification drives real spawned trees through the
real seams and proves containment before work and whole-tree reaping on
graceful and forced paths. The Windows window between spawn and job
assignment was judged structurally unclosable through the standard library
and is documented precisely at the assignment seam; the POSIX containment
path is correct by construction but unexercised on this host and awaits
continuous-integration coverage.

## Tests

Nine hundred thirty tests across the api, control, worker, providers, and
utils suites and the four-leg owned-process-tree certification are green
with real child processes, real job objects, real kills, and no
monkeypatching, skips, or expected failures beyond the established
in-process mock provider at the uninstalled-external-CLI seam. Review
remediation scrubbed audit-lock coordinates from three test docstrings and
added a deterministic administrative-stop drain test. The run-start
admission-release guarantee on unexpected failure is owned by the admission
phase together with its certification.
