set working-directory := "../.."

# Every recipe here is a passthrough to `dev/toolchain.py`, which states the
# exact flag set for each profile once. These are the recipes whose PURPOSE is
# to change the environment, so - unlike every gate - the commands behind them
# deliberately do not carry `uv run --no-sync`.
#
# The dispatcher itself must still run from an environment that exists, which is
# why it goes through the already-resolved tooling profile.

dev := "uv run --no-sync --frozen --no-default-groups --group tooling python -m dev"

# Show dependency-profile recipes.
help:
    @just --list dev::deps

# Resolve the base runtime profile from the project lock.
base:
    {{ dev }} deps base

# Resolve the server runtime profile from the project lock.
server:
    {{ dev }} deps server

# Resolve the RAG runtime profile from the project lock without provisioning models.
rag:
    {{ dev }} deps rag

# Resolve the repository tooling profile from the project lock.
tooling:
    uv sync --locked --no-default-groups --group tooling

# Restore the project-pinned ACP runtime from the npm lock.
node:
    {{ dev }} deps node

# Resolve every runtime extra plus the composed all dependency group.
all:
    {{ dev }} deps all

# Verify that project metadata and the lock agree without changing either.
check:
    {{ dev }} deps check

# Regenerate the lockfile.
lock:
    {{ dev }} deps lock

# Regenerate the lockfile at the newest allowed versions.
upgrade:
    {{ dev }} deps upgrade
