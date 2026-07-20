set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

procs := "uv run --no-sync --frozen --no-default-groups vaultspec-a2a procs"

# Show process-registry lifecycle recipes.
help:
    @just --list dev::service

# List every registered process and its liveness verdict.
list:
    {{ procs }} list

# Reserve and print the next free configured role port.
allocate ROLE:
    {{ procs }} allocate {{ ROLE }}

# Start one configured process role under the production registry.
up ROLE NAME *ARGS:
    {{ procs }} up {{ ROLE }} {{ NAME }} {{ ARGS }}

# Print the endpoint for one live registered process.
attach NAME:
    {{ procs }} attach {{ NAME }}

# Tree-kill one registered process through the production registry.
kill NAME:
    {{ procs }} kill {{ NAME }}

# Run the registered role's configured build command.
rebuild NAME:
    {{ procs }} rebuild {{ NAME }}

# Kill, rebuild, and restart one registered process on its recorded port.
rerun NAME:
    {{ procs }} rerun {{ NAME }}

# Restart one dead registered process on its recorded port.
resume NAME:
    {{ procs }} resume {{ NAME }}

# Kill and clear every stale or dead registry record.
reap:
    {{ procs }} reap

# Start a named development gateway through the production registry.
gateway-up NAME="dev" *ARGS:
    {{ procs }} up gateway-dev {{ NAME }} {{ ARGS }}

# Start a named development worker through the production registry.
worker-up NAME="dev" *ARGS:
    {{ procs }} up worker-dev {{ NAME }} {{ ARGS }}

# Start a named development engine with explicit serve, build, and data seats.
engine-up NAME REPO BUILD_REPO WORKSPACE *ARGS:
    {{ procs }} up engine-dev {{ NAME }} --repo {{ REPO }} --build-repo {{ BUILD_REPO }} --workspace {{ WORKSPACE }} {{ ARGS }}
