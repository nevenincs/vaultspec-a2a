"""Continuous DB population daemon for Mock LLM testing.

This script runs as the `mock-seeder` Docker entrypoint, utilizing APScheduler
to dispatch predefined Mock LLM team topologies. The execution trajectories 
are written to `.vault/a2a.sqlite`, serving as a saturated datastream for UI testing.
"""

import asyncio
import logging
import random
import signal
from datetime import UTC, datetime
from typing import cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from lib.core.config import settings
from lib.core.team_config import discover_team_preset_ids, load_team_config, load_agent_config, AgentConfigNotFoundError
from lib.utils.trace import print_trace_summary

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
    from lib.database.crud import ThreadStatus, create_thread, update_thread_status
    from lib.core.graph import compile_team_graph
    
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
                agent_configs=cast(list, agent_configs),
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

            logger.info("Triggering LangGraph execution...")
            async for event in graph.astream(inputs, config, stream_mode="values"):
                pass 

            async with session_factory() as db:
                await update_thread_status(db, thread_id, ThreadStatus.COMPLETED)
                await db.commit()
            
            print_trace_summary(thread_id)
            logger.info("Successfully seeded thread: %s", thread_id)

    except Exception as e:
        logger.exception("Graph execution failed for %s", preset_id)
        async with session_factory() as db:
            await update_thread_status(db, thread_id, ThreadStatus.FAILED)
            await db.commit()


async def run_daemon() -> None:
    """Initialize APScheduler and begin the dispatch loop."""
    from lib.database import run_migrations
    from lib.database.session import close_db, get_session_factory, init_db

    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    await run_migrations(settings.database_url)
    
    engine = await init_db(db_path)
    logger.info("Mock Seeder Daemon connected to database: %s", db_path)
    session_factory = get_session_factory()

    mock_presets = [tid for tid in discover_team_preset_ids() if tid.startswith("mock-")]
    if not mock_presets:
        logger.error("No mock presets discovered! Exiting.")
        return
        
    loop = asyncio.get_running_loop()

    def dispatch_job():
        """APScheduler hook that randomly selects a preset to run dynamically."""
        preset = random.choice(mock_presets)
        # APScheduler invokes synchronous context for add_job functions, 
        # so we spawn the async payload backwards onto the running loop
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(execute_mock_team(db_path, session_factory, preset))
        )
        
        # Reschedule next execution uniformly between 15-45 seconds
        next_interval = random.randint(15, 45)
        logger.info("Next seed scheduled in %s seconds.", next_interval)
        scheduler.reschedule_job('seed_job', trigger=IntervalTrigger(seconds=next_interval))

    # Initial trigger kicks off immediately
    scheduler.add_job(dispatch_job, IntervalTrigger(seconds=5), id='seed_job')
    scheduler.start()
    
    logger.info("Mock Seeder APScheduler started. Starting Uvicorn health endpoint...")
    
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)
    
    # Run the server and wait for shutdown
    await server.serve()
    
    try:
        await shutdown_event.wait()
    finally:
        logger.info("Shutting down Mock Seeder Daemon...")
        scheduler.shutdown()
        await close_db()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    asyncio.run(run_daemon())
