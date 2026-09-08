set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Every probe below is one call into `dev/doctor`, which implements each check
# ONCE in stdlib-only Python. These recipes previously carried paired
# `[windows]`/`[unix]` bodies - including two separate semver comparators, one
# in PowerShell's `[Version]` type and one in `awk` - so which answer you got
# depended on which platform you were standing on.
doctor := "uv run --no-sync --frozen --no-default-groups --group tooling python -m dev.doctor"

# Show environment diagnosis recipes.
help:
    @just --list dev::doctor

# Diagnose required tools and report optional Docker support.
check:
    {{ doctor }} check

# Verify Just, uv, Node.js, and npm and report their resolved versions.
required:
    {{ doctor }} required

# Report Docker support without failing non-container workflows.
docker-optional:
    {{ doctor }} docker-optional

# Require Docker and Compose for container-specific recipes.
docker:
    {{ doctor }} docker
