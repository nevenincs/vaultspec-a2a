---
title: Database Schema Fragility and Migration Engine
source: vaultspec-a2a research session
relevance: 10
---

# Database Schema Fragility and Migration Engine

## Executive Summary
This document investigates the current state of database persistence in `vaultspec-a2a`. The research conclusively proves that the current persistence layer lacks any safe schema evolution mechanics, relying instead on raw and error-prone SQL patches within application boot code.

## Empirical Codebase Findings

1. **The Core Defect in `init_db`:**
   At `Y:/code/vaultspec-a2a-worktrees/main/lib/database/session.py` (specifically within the `init_db` function), table creation is executed via:
   ```python
   await conn.run_sync(Base.metadata.create_all)
   ```
   This SQLAlchemy convenience method is designed *exclusively* for initial blank-slate application bootstrapping. It generates `CREATE TABLE` statements for non-existent tables but fundamentally ignores structural changes (added/removed columns, indexing, constraints) for existing tables.

2. **The Fragile Workaround:**
   Because `create_all` cannot evolve an existing SQLite file, past developers inserted manual schema definitions via raw `ALTER TABLE` commands wrapped in suppressing `try/except` blocks (e.g., adding `team_preset` to `threads` on line 192 of `session.py`).
   This is an architectural anti-pattern because:
   - There is no version history or linear directed acyclic graph (DAG) of migrations.
   - Booting older or branching versions of the codebase against the same SQLite file can instantly corrupt schema bounds.
   - It cannot safely execute complex migrations (e.g., SQLite table rewrites requiring temp-tables for constraint alterations).

3. **Absence of Standard Tooling:**
   A full repository search confirms that:
   - `alembic` is entirely absent from `pyproject.toml`.
   - The directory `lib/database/migrations` does not exist.
   - There are no `alembic.ini` or `env.py` configurations available in the project tree to intercept the `aiosqlite` connection strings.

## Resolution Strategy

The orchestrator must immediately decouple schema layout logic from application runtime logic (`init_db`) by adopting **Alembic**. 

### Implementation Path
1. **Dependency Injection:** Introduce `alembic>=1.13.0` into the `uv` toolchain / `pyproject.toml`.
2. **Environment Configuration:** Generate `lib/database/alembic.ini` and a custom `env.py` configured to import the async `get_engine()` from `session.py` and the declarative base (`Base.metadata`) from `models.py`.
3. **Establish Baseline:** Cut a `001_initial_schema.py` migration using `alembic revision --autogenerate` mapping to the currently live `threads`, `artifacts`, `permission_log`, and `token_usage` tables.
4. **Boot Refactor:** Excise all raw `ALTER TABLE` commands and `Base.metadata.create_all` instructions from `init_db()`. In their place, the backend application should either invoke an Alembic programmatic upgrade context on start, or strictly delegate DB prep to an orchestration CLI command (`uv run alembic upgrade head`).

### Related Architecture Decisions
This research is formalized in **ADR-029: Database Migration Framework**. It runs parallel to **ADR-028: Universal Rule Propagation** due to their simultaneous implementation batch.
