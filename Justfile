# Requires just >= 1.31.0 for stable native modules.

set unstable := true
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := true

mod dev "dev/just/mod.just"

# The development toolchain's single entry point. Every gate, audit, and
# measurement below is one `python -m dev <verb> <target>` call whose behaviour
# is declared in `dev/toolchain.py`; nothing about WHAT a target runs lives in a
# justfile. Run `just <verb> help` for a verb's full target list.
dev := "uv run --no-sync --frozen --no-default-groups --group tooling python -m dev"

# Show the complete native command hierarchy.
default:
    @just --list --list-submodules

# Show the complete native command hierarchy.
help:
    @just --list --list-submodules

# ── Toolchain verbs ──────────────────────────────────────────────────────────
#
# The verbs split by CONSEQUENCE, not by tool:
#
#   lint    GATES.    Read-only, and a finding fails the build.
#   fix     MUTATES.  Everything automatically repairable, in one pass.
#   audit   Only `deps` gates. Every other target is advisory and exits 0 even
#           with findings, because each yields a lead to confirm.
#   test    GATES.
#   health  MEASURES. Always exits 0.
#
# Thresholds are published industry defaults, NOT calibrated to this tree's
# current worst offender. `just lint` therefore chains only the dimensions that
# hold that line today; `just lint strict` runs every dimension including the
# unfinished burndowns and is expected to be red. `just health` ranks the
# distance between the two.

# Run gating static analysis; a finding fails the build.
lint target='all':
    {{ dev }} lint {{ target }}

# Apply every available formatter and automatic fix.
fix target='all':
    {{ dev }} fix {{ target }}

# Audit dependencies and code quality; only 'deps' gates.
audit target='all':
    {{ dev }} audit {{ target }}

# Run the project test suites.
test target='unit':
    {{ dev }} test {{ target }}

# Rank the worst offenders across every code-health dimension; always exits 0.
health target='report':
    {{ dev }} health {{ target }}

# ── Aggregates ───────────────────────────────────────────────────────────────

# Run the current read-only local validation baseline.
ci:
    uv run --isolated --no-project python -m dev ci all

# Diagnose required tools and optional Docker support.
doctor:
    @just dev doctor check
