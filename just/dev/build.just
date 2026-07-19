set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show artifact build and cleanup recipes.
help:
    @just --list dev::build

# Build the Python source distribution and wheel.
package:
    uv build --build-constraints build-constraints.txt

# Run documentation tests and build strict Sphinx HTML.
docs:
    uv run --isolated --locked --group docs --group dev python -m pytest docs/tests -q
    uv run --isolated --locked --group docs sphinx-build -n -W --keep-going -b html docs docs/_build/html

# Build local development container images.
docker:
    just dev doctor docker
    docker compose -f service/docker-compose.dev.yml build

# Build production gateway and worker container images.
docker-prod:
    just dev doctor docker
    docker build -t vaultspec-a2a-gateway -f service/docker/prod.Dockerfile --target gateway .
    docker build -t vaultspec-a2a-worker -f service/docker/prod.Dockerfile --target worker .

# Remove generated package, documentation, and Python cache artifacts.
clean:
    @& { $root = (Resolve-Path -LiteralPath ".").Path; $targets = @((Join-Path $root "dist"), (Join-Path $root "docs/_build")); $scanRoots = @("src", "tests", "docs") | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path -LiteralPath $_ }; $targets += @(Get-ChildItem -Path $scanRoots -Directory -Recurse -Filter "*.egg-info" -ErrorAction SilentlyContinue | ForEach-Object FullName); $targets += @(Get-ChildItem -Path $scanRoots -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object FullName); foreach ($target in ($targets | Select-Object -Unique)) { if (-not (Test-Path -LiteralPath $target)) { continue }; $resolved = (Resolve-Path -LiteralPath $target).Path; if (-not $resolved.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to remove path outside repository: $resolved" }; Remove-Item -LiteralPath $resolved -Recurse -Force }; Write-Host "Generated build artifacts removed."
