set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

rag_cli := "uv run --no-sync --frozen --no-default-groups --extra rag vaultspec-rag"

# Resolve locked RAG dependencies and enroll the workspace without external provisioning.
setup:
    uv sync --locked --no-default-groups --extra rag
    {{ rag_cli }} --version
    {{ rag_cli }} status

# Enroll RAG after its profile has already been synchronized; do not download models or Qdrant.
install:
    uv sync --locked --no-default-groups --extra rag
    {{ rag_cli }} --version
    {{ rag_cli }} status

# Preview non-provisioning workspace enrollment.
install-dry-run:
    {{ rag_cli }} install --mode dependency --no-mcp --no-provision --no-torch-config --yes --dry-run

# Deliberately refresh RAG inside its declared compatibility range.
upgrade:
    uv lock --upgrade-package vaultspec-rag
    uv sync --locked --no-default-groups --extra rag
    {{ rag_cli }} --version
    {{ rag_cli }} status
    uv lock --check

# Build or update both document and source indexes.
index:
    {{ rag_cli }} index --type all

# Preview source discovery without loading models or writing an index.
index-dry-run:
    {{ rag_cli }} index --type all --dry-run

# Report project index counts and storage state.
status:
    {{ rag_cli }} status

# Report installed dependency and live-service readiness independently.
service-doctor:
    {{ rag_cli }} server doctor

# Start the managed-Qdrant search service explicitly.
service-start:
    {{ rag_cli }} server start

# Start the local-store search service explicitly.
service-start-local:
    {{ rag_cli }} server start --local-only

# Stop the owned search service explicitly.
service-stop:
    {{ rag_cli }} server stop

# Report background search service state.
service-status:
    {{ rag_cli }} server status

# Show recent background service activity.
service-logs:
    {{ rag_cli }} server logs

# Explicitly download model files before first service use.
warmup:
    {{ rag_cli }} server warmup
