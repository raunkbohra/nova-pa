"""
NOVA WhatsApp Assistant - Entry Point

Run with: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Or: python -m uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from app.webhook import app
from app.config import settings
from app.memory import init_db, close_db
from app.tools.reminder_tool import init_scheduler

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Lifespan Events
# ============================================================================

@asynccontextmanager
async def lifespan(app):
    """
    Application startup and shutdown.
    Initialize database on startup, close on shutdown.
    """
    # Startup
    logger.info("🚀 NOVA starting up...")
    await init_db(settings.database_url)
    logger.info("✅ Database initialized")

    # APScheduler job store needs a sync DB URL (not asyncpg)
    sync_db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    scheduler = init_scheduler(sync_db_url)
    scheduler.start()
    logger.info("✅ Scheduler started")

    yield

    # Shutdown
    logger.info("🛑 NOVA shutting down...")
    scheduler.shutdown(wait=False)
    await close_db()
    logger.info("✅ Database closed")


# Attach lifespan to FastAPI app
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting NOVA on {settings.host}:{settings.port}")
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
