set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

product_cli := "uv run --no-sync --frozen --no-default-groups vaultspec-a2a"

# Show product passthrough recipes.
help:
    @just --list dev::product

# Pass arguments directly to the product CLI.
cli *ARGS:
    {{ product_cli }} {{ ARGS }}

# Report gateway health through the product CLI.
doctor *ARGS:
    {{ product_cli }} doctor {{ ARGS }}

# List product team presets.
presets *ARGS:
    {{ product_cli }} presets {{ ARGS }}

# Start, inspect, or cancel runs through the product CLI.
run *ARGS:
    {{ product_cli }} run {{ ARGS }}

# Provision or verify an agent workspace through the product CLI.
workspace *ARGS:
    {{ product_cli }} workspace {{ ARGS }}

# Start the standalone product MCP server.
mcp TRANSPORT="stdio" *ARGS:
    uv run --no-sync --frozen --no-default-groups vaultspec-a2a-mcp --transport {{ TRANSPORT }} {{ ARGS }}
