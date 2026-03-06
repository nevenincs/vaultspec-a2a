"""Continuous DB population daemon for Mock LLM testing.

This script runs as the `mock-seeder` Docker entrypoint, utilizing APScheduler
to dispatch predefined Mock LLM team topologies. The execution trajectories 
are written to `.vault/a2a.sqlite`, serving as a saturated datastream for UI testing.
"""

import asyncio
import logging
import os
import random
import signal
from datetime import UTC, datetime
from typing import cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from vaultspec_a2a.core.config import settings
from vaultspec_a2a.core.team_config import discover_team_preset_ids, load_team_config, load_agent_config, AgentConfigNotFoundError
from vaultspec_a2a.utils.trace import print_trace_summary

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Mock Seeder Health")
scheduler = AsyncIOScheduler()

@app.get("/health")
async def health():
    """Health check endpoint for Docker."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "presets_loaded": len(discover_team_preset_ids())
    }

shutdown_event = asyncio.Event()

def handle_shutdown(sig, frame):
    """Signal handler for graceful stop."""
    logger.info("Shutdown signal received, initiating graceful exit...")
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(shutdown_event.set)
    except RuntimeError:
        pass


async def execute_mock_team(db_path: str, session_factory, preset_id: str) -> None:
    """Core graphing routine executing a single chosen team configuration."""
    from vaultspec_a2a.database.crud import ThreadStatus, create_thread, update_thread_status
    from vaultspec_a2a.core.graph import compile_team_graph
    
    logger.info("==================================================")
    logger.info("SEEDING MOCK PRESET: %s", preset_id)
    logger.info("==================================================")

    try:
        team_config = load_team_config(preset_id)
    except Exception as e:
        logger.error("Preset %s not found in registry. Skipping. %s", preset_id, e)
        return

    agent_configs = {}
    for w in team_config.workers:
        try:
            agent_configs[w.agent_id] = load_agent_config(w.agent_id)
        except AgentConfigNotFoundError:
            logger.error("Failed to load agent %s for pristine %s. Skipping.", w.agent_id, preset_id)
            return

    supervisor_config = None
    if team_config.topology.type in ("star", "pipeline_loop"):
        try:
            supervisor_config = load_agent_config("vaultspec-supervisor")
        except AgentConfigNotFoundError:
            pass

    thread_id = f"mock-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    title = f"Mock: {team_config.display_name} ({thread_id[-4:]})"

    async with session_factory() as db:
        await create_thread(
            session=db,
            thread_id=thread_id,
            title=title,
            status=ThreadStatus.RUNNING,
            team_preset=preset_id,
            metadata='{"feature_tag": "mock-seeder"}',
        )
        await db.commit()

    try:
        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
            await checkpointer.setup()
            graph = compile_team_graph(
                team_config=team_config,
                agent_configs=agent_configs,
                supervisor_agent_config=supervisor_config,
                autonomous=True,
                checkpointer=checkpointer,
            )

            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "team_preset": preset_id,
                }
            }

            inputs = {
                "messages": [
                    ("user", f"Please execute the mock protocol for {preset_id}.")
                ]
            }

            logger.info("Triggering LangGraph execution for thread %s...", thread_id)
            async for _ in graph.astream(inputs, config, stream_mode="values"):
                if shutdown_event.is_set():
                    break
            
            async with session_factory() as db:
                await update_thread_status(db, thread_id, ThreadStatus.COMPLETED)
                await db.commit()
            
            logger.info("Successfully completed thread: %s", thread_id)

    except Exception:
        logger.exception("Graph execution failed for %s", preset_id)
        async with session_factory() as db:
            await update_thread_status(db, thread_id, ThreadStatus.FAILED)
            await db.commit()


async def loop_preset(db_path: str, session_factory, preset_id: str) -> None:
    """Infinite loop for a specific preset, ensuring it restarts after completion."""
    while not shutdown_event.is_set():
        # Jitter start to avoid thundering herd on startup
        await asyncio.sleep(random.uniform(2, 10))
        if shutdown_event.is_set():
            break
            
        await execute_mock_team(db_path, session_factory, preset_id)
        
        # Cooldown between runs of the same preset
        # ADR-M01: Slow down seeder to avoid LangSmith rate limits
        wait_seconds = random.randint(120, 300) 
        logger.info("Preset %s finished. Restarting in %s seconds.", preset_id, wait_seconds)

        
        # Sleep in chunks to allow faster shutdown
        for _ in range(wait_seconds):
            if shutdown_event.is_set():
                break
            await asyncio.sleep(1)


async def run_daemon() -> None:
    """Initialize DB and start concurrent looping tasks for each mock preset."""
    from vaultspec_a2a.database import run_migrations
    from vaultspec_a2a.database.session import close_db, get_session_factory, init_db

    # Enforce tracing state early — before any LangGraph/LangSmith imports fire.
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info("LangSmith tracing DISABLED for mock-seeder (set LANGSMITH_TRACING=true to enable)")
    else:
        logger.info("LangSmith tracing ENABLED for mock-seeder")

    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    await run_migrations(settings.database_url)
    
    await init_db(db_path)
    logger.info("Mock Seeder Daemon connected to database: %s", db_path)
    session_factory = get_session_factory()

    mock_presets = [tid for tid in discover_team_preset_ids() if tid.startswith("mock-")]
    if not mock_presets:
        logger.error("No mock presets discovered! Exiting.")
        return
        
    logger.info("Starting concurrent loops for %d mock presets...", len(mock_presets))
    
    # Spawn a dedicated loop task for every preset
    loop_tasks = [
        asyncio.create_task(loop_preset(db_path, session_factory, pid))
        for pid in mock_presets
    ]
    
    logger.info("Mock Seeder tasks started. Starting Uvicorn health endpoint...")
    
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)
    
    # Run the server. It will block until shutdown signal.
    # The loop_tasks continue running in the background.
    await server.serve()
    
    # On server exit (shutdown signal), wait for tasks to finish (which they will due to shutdown_event)
    logger.info("Shutting down Mock Seeder Daemon...")
    shutdown_event.set()
    await asyncio.gather(*loop_tasks, return_exceptions=True)
    await close_db()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    asyncio.run(run_daemon())
