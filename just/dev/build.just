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
    uv run --no-sync --frozen --no-default-groups python -m vaultspec_a2a.cli.build_clean
