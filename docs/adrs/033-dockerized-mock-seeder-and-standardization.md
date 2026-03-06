# ADR 033: Dockerized Mock Data Seeder & Infrastructure Standardization

## Date
2026-03-05

## Status
Accepted

## Context
As part of expanding the Mock LLM features, we identified that manual CLI scripting (`run_mock_team.py`) is inadequate to saturate the local development UI with diverse, multi-agent data flows. The frontend requires a continuous, automated background layer that populates exactly the same LangGraph trace and SQLite execution patterns as real models—simulating successes, tool call failures, autonomous coordination, and human-in-the-loop interrupts.

Simultaneously, evaluating the integration of this "Mock Seeder" service exposed inconsistencies in our Docker landscape. Container builds are scattered between the root directory (`Dockerfile`, `Dockerfile.dev`) and the `docker/` subdirectory (`vidaimock.Dockerfile`). 

## Decision

### 1. Automated Mock Data Seeder
We will implement an automated mock data generation backend (`docker/mock_seeder.py`).
* **Behavior:** It will infinitely cycle through predefined mock team presets, invoking them against the local `init_db()` SQLAlchemy engine and `AsyncSqliteSaver` checkpointer.
* **Deployment:** This script will be wrapped in a dedicated `mock-seeder` Docker service, active in the local `docker-compose.dev.yml` stack, ensuring local DB saturation occurs automatically during `docker compose up`.

### 2. Docker Architecture Standardization
To clean up container sprawl, all `Dockerfile` definitions must be centralized within the `docker/` subdirectory.
* **Rename/Move** `Dockerfile.dev` -> `docker/dev.Dockerfile`
* **Rename/Move** `Dockerfile` -> `docker/prod.Dockerfile`
* **Target Isolation:** The `mock-seeder` container will be implemented as a new target inside `docker/dev.Dockerfile` (leveraging the existing Python uv-cache multi-stage base).
* **Compose Paths:** `docker-compose.dev.yml` and `docker-compose.prod.yml` must be updated to target these new relative paths (`build.dockerfile: docker/dev.Dockerfile`).

## Consequences
* **Positive:** Developers get instant, saturated UI timelines by simply starting Docker. Local setup is zero-touch.
* **Positive:** Improved repository hygiene. Root-level clutter is reduced, and container specifications are logically grouped in `docker/`.
* **Positive:** The `mock-seeder` shares the `python-base` image cache from the Dev Dockerfile, minimizing build times.
* **Negative:** Git history for the root Dockerfiles will detach upon renaming them into the `docker/` subfolder. 
