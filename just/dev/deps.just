set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Resolve the base runtime profile from the project lock.
base:
    uv sync --locked --no-default-groups

# Resolve the server runtime profile from the project lock.
server:
    uv sync --locked --no-default-groups --extra server

# Resolve the RAG runtime profile from the project lock without provisioning models.
rag:
    uv sync --locked --no-default-groups --extra rag

# Resolve the repository tooling profile from the project lock.
tooling:
    uv sync --locked --no-default-groups --group tooling

# Resolve every runtime extra plus the composed all dependency group.
all:
    uv sync --locked --no-default-groups --all-extras --group all

# Verify that project metadata and the lock agree without changing either.
check:
    uv lock --check
