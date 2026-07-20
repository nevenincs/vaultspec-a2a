# Requires just >= 1.31.0 for stable native modules.

set unstable := true
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := true

mod dev "just/dev/mod.just"

# Show the complete native command hierarchy.
default:
    @just --list --list-submodules

# Show the complete native command hierarchy.
help:
    @just --list --list-submodules

# Run the current read-only local validation baseline.
ci:
    uv sync --locked --no-default-groups --extra server --group all
    just dev deps node
    just dev code check
    just dev test unit

# Diagnose required tools and optional Docker support.
doctor:
    @just dev doctor check
