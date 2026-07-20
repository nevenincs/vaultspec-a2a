set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show environment diagnosis recipes.
help:
    @just --list dev::doctor

# Diagnose required tools and report optional Docker support.
check: required docker-optional

# Verify Just, uv, Node.js, and npm and report their resolved versions.
[windows]
required:
    @& { $required = [Version]"1.31.0"; $raw = (& just --version); $match = [Regex]::Match($raw, "\d+\.\d+\.\d+"); if (-not $match.Success) { Write-Error "Could not parse the installed Just version. Required: just >= $required. Install from https://just.systems/man/en/packages.html"; exit 1 }; $current = [Version]$match.Value; if ($current -lt $required) { Write-Error "just $current is too old. Required: just >= $required for native modules. Install from https://just.systems/man/en/packages.html"; exit 1 }; Write-Host "$raw (requirement satisfied: >= $required)" }
    @if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Error "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"; exit 1 }; uv --version
    @& { if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Error "Node.js is required for the project-pinned ACP runtime. Install the version declared in .node-version from https://nodejs.org/"; exit 1 }; node scripts/check_node_version.mjs; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Write-Error "npm is required to restore package-lock.json."; exit 1 }; npm --version }

# Verify Just, uv, Node.js, and npm and report their resolved versions.
[unix]
required:
    @required="1.31.0"; raw="$(just --version)"; current="$(printf '%s\n' "$raw" | awk 'match($0, /[0-9]+\.[0-9]+\.[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"; if [ -z "$current" ]; then echo "Could not parse the installed Just version. Required: just >= $required. Install from https://just.systems/man/en/packages.html" >&2; exit 1; fi; if ! awk -v current="$current" -v required="$required" 'BEGIN { split(current, c, "."); split(required, r, "."); for (i = 1; i <= 3; i++) { if ((c[i] + 0) > (r[i] + 0)) exit 0; if ((c[i] + 0) < (r[i] + 0)) exit 1 } exit 0 }'; then echo "just $current is too old. Required: just >= $required for native modules. Install from https://just.systems/man/en/packages.html" >&2; exit 1; fi; printf '%s (requirement satisfied: >= %s)\n' "$raw" "$required"
    @if ! command -v uv >/dev/null 2>&1; then echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; fi; uv --version
    @if ! command -v node >/dev/null 2>&1; then echo "Node.js is required for the project-pinned ACP runtime. Install the version declared in .node-version from https://nodejs.org/" >&2; exit 1; fi; node scripts/check_node_version.mjs; if ! command -v npm >/dev/null 2>&1; then echo "npm is required to restore package-lock.json." >&2; exit 1; fi; npm --version

# Report Docker support without failing non-container workflows.
[windows]
docker-optional:
    @if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Warning "Docker is not installed. It is required only for container build and stack recipes: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 0 }; docker --version; if ($LASTEXITCODE -ne 0) { Write-Warning "Docker is unavailable. Install or repair Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 0 }; docker compose version; if ($LASTEXITCODE -ne 0) { Write-Warning "Docker Compose is unavailable. Install or repair Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 0 }

# Require Docker and Compose for container-specific recipes.
[windows]
docker:
    @if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Error "Docker with Compose is required for this recipe. Install Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 1 }; docker --version; if ($LASTEXITCODE -ne 0) { Write-Error "Docker is required for this recipe. Install or repair Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 1 }; docker compose version; if ($LASTEXITCODE -ne 0) { Write-Error "Docker Compose is required for this recipe. Install or repair Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"; exit 1 }

# Report Docker support without failing non-container workflows.
[unix]
docker-optional:
    @if ! command -v docker >/dev/null 2>&1; then echo "Docker is not installed. It is required only for container build and stack recipes: https://docs.docker.com/engine/install/" >&2; exit 0; fi; if ! docker --version; then echo "Docker is unavailable. Install or repair Docker Engine: https://docs.docker.com/engine/install/" >&2; exit 0; fi; if ! docker compose version; then echo "Docker Compose is unavailable. Install the Compose plugin: https://docs.docker.com/compose/install/" >&2; exit 0; fi

# Require Docker and Compose for container-specific recipes.
[unix]
docker:
    @if ! command -v docker >/dev/null 2>&1; then echo "Docker with Compose is required for this recipe. Install Docker Engine: https://docs.docker.com/engine/install/" >&2; exit 1; fi; if ! docker --version; then echo "Docker is required for this recipe. Install or repair Docker Engine: https://docs.docker.com/engine/install/" >&2; exit 1; fi; if ! docker compose version; then echo "Docker Compose is required for this recipe. Install the Compose plugin: https://docs.docker.com/compose/install/" >&2; exit 1; fi
