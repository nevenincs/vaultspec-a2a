set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

dev := "docker compose --project-name vaultspec-a2a-dev -f service/docker-compose.dev.yml"
integration := "docker compose --project-name vaultspec-a2a-integration -f service/docker-compose.integration.yml"
database := "docker compose --project-name vaultspec-a2a-database -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml"
prod := "docker compose --project-name vaultspec-a2a-prod -f service/docker-compose.prod.yml"
infrastructure := "docker compose --project-name vaultspec-a2a-infrastructure -f service/docker-compose.integration.yml"

# Show bounded Docker Compose stack recipes.
help:
    @just --list dev::stack

# Validate the development stack configuration.
dev-config:
    just dev doctor docker
    {{ dev }} config

# Start the development stack.
dev-up:
    just dev doctor docker
    {{ dev }} up -d --build --wait

# Stop and remove the development stack.
dev-down:
    just dev doctor docker
    {{ dev }} down --remove-orphans

# Show development stack status.
dev-status:
    just dev doctor docker
    {{ dev }} ps

# Validate the deterministic integration stack configuration.
integration-config:
    just dev doctor docker
    {{ integration }} config

# Start the deterministic integration stack.
integration-up:
    just dev doctor docker
    {{ integration }} up -d --build --wait

# Stop and remove the deterministic integration stack.
integration-down:
    just dev doctor docker
    {{ integration }} down --remove-orphans

# Show deterministic integration stack status.
integration-status:
    just dev doctor docker
    {{ integration }} ps

# Validate the PostgreSQL-backed stack configuration.
database-config:
    just dev doctor docker
    {{ database }} config

# Start only the PostgreSQL service in its isolated Compose project.
database-up:
    just dev doctor docker
    {{ database }} up -d --wait postgres

# Stop and remove the isolated PostgreSQL Compose project.
database-down:
    just dev doctor docker
    {{ database }} down --remove-orphans

# Show PostgreSQL stack status.
database-status:
    just dev doctor docker
    {{ database }} ps

# Validate the production stack configuration.
prod-config:
    just dev doctor docker
    {{ prod }} config

# Start the production stack.
prod-up:
    just dev doctor docker
    {{ prod }} up -d --build --wait

# Stop and remove the production stack.
prod-down:
    just dev doctor docker
    {{ prod }} down --remove-orphans

# Show production stack status.
prod-status:
    just dev doctor docker
    {{ prod }} ps

# Validate the integration file used by the isolated infrastructure project.
infrastructure-config:
    just dev doctor docker
    {{ infrastructure }} config

# Start only Jaeger in its isolated infrastructure Compose project.
infrastructure-up:
    just dev doctor docker
    {{ infrastructure }} up -d --wait jaeger

# Stop and remove the isolated infrastructure Compose project.
infrastructure-down:
    just dev doctor docker
    {{ infrastructure }} down --remove-orphans

# Show infrastructure stack status.
infrastructure-status:
    just dev doctor docker
    {{ infrastructure }} ps
