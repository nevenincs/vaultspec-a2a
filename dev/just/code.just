set working-directory := "../.."

# PLATFORM AGNOSTIC BY CONSTRUCTION. Every recipe below is a single command with
# no shell branching, no pipes, no conditionals, and no PowerShell-versus-sh
# dialect - so this module needs no `set windows-shell` and there is no second
# dialect of anything to maintain. All of the logic - target dispatch, step
# chaining, tool-or-Docker fallback, advisory-versus-gating exit codes - lives
# under `dev/`, whose dispatch core imports the standard library only.
#
# To change what a target runs, edit `dev/toolchain.py`. It is the single
# declarative source of truth for the whole toolchain. Run any verb with the
# target `help` for its full target list.

dev := "uv run --no-sync --frozen --no-default-groups --group tooling python -m dev"

# Show code validation and repair recipes.
help:
    @just --list dev::code

# Run gating static analysis; a finding fails the build.
lint target='all':
    {{ dev }} lint {{ target }}

# Apply every available formatter and automatic fix.
fix target='all':
    {{ dev }} fix {{ target }}

# Audit dependencies and code quality; only 'deps' gates.
audit target='all':
    {{ dev }} audit {{ target }}

# Rank the worst offenders across every code-health dimension; always exits 0.
health target='report':
    {{ dev }} health {{ target }}

# Run every read-only gate that holds the line today.
check:
    {{ dev }} lint all

# Run every gate including the unfinished burndowns; expected red.
check-strict:
    {{ dev }} lint strict

# Apply configured lint fixes and formatting explicitly.
repair:
    {{ dev }} fix python
