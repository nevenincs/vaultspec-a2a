set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show environment diagnosis recipes.
help:
    @just --list dev::doctor

# Diagnose required tools and report optional Docker support.
check: required docker-optional

# Verify Just and uv and report their resolved versions.
required:
    @& { $required = [Version]"1.31.0"; $raw = (& just --version); $match = [Regex]::Match($raw, "\d+\.\d+\.\d+"); if (-not $match.Success) { Write-Error "Could not parse the installed Just version. Required: just >= $required. Install from https://just.systems/man/en/packages.html"; exit 1 }; $current = [Version]$match.Value; if ($current -lt $required) { Write-Error "just $current is too old. Required: just >= $required for native modules. Install from https://just.systems/man/en/packages.html"; exit 1 }; Write-Host "$raw (requirement satisfied: >= $required)" }
    @if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Error "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"; exit 1 }; uv --version

# Report Docker support without failing non-container workflows.
docker-optional:
    @if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Warning "Docker is not installed. It is required only for container build and stack recipes: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 0 }; docker --version; docker compose version

# Require Docker and Compose for container-specific recipes.
docker:
    @if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Error "Docker with Compose is required for this recipe. Install Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 1 }; docker --version; docker compose version
