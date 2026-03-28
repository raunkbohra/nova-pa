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
from app.briefing import _send_morning_briefing, BRIEFING_JOB_ID
from app.proactive import (
    _check_unanswered_emails, _post_meeting_followup,
    _contact_checkins, _end_of_day_wrap,
    _weekly_review, _check_sales_pace,
    JOB_UNANSWERED_EMAILS, JOB_POST_MEETING, JOB_CONTACT_CHECKINS, JOB_EOD_WRAP,
    JOB_WEEKLY_REVIEW, JOB_SALES_PACE,
)

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

    # Register daily morning briefing at 7:00am NPT
    from apscheduler.triggers.cron import CronTrigger
    from pytz import timezone
    scheduler.add_job(
        _send_morning_briefing,
        CronTrigger(hour=7, minute=0, timezone=timezone('Asia/Kathmandu')),
        id=BRIEFING_JOB_ID,
        replace_existing=True,
    )
    logger.info("✅ Morning briefing scheduled for 7:00am NPT daily")

    # Unanswered emails — daily 10:00am NPT
    scheduler.add_job(
        _check_unanswered_emails,
        CronTrigger(hour=10, minute=0, timezone=timezone('Asia/Kathmandu')),
        id=JOB_UNANSWERED_EMAILS,
        replace_existing=True,
    )
    logger.info("✅ Unanswered email check scheduled for 10:00am NPT daily")

    # Post-meeting follow-up — every 30 minutes
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(
        _post_meeting_followup,
        IntervalTrigger(minutes=30),
        id=JOB_POST_MEETING,
        replace_existing=True,
    )
    logger.info("✅ Post-meeting follow-up scheduled every 30 minutes")

    # Contact check-ins — Monday 9:00am NPT
    scheduler.add_job(
        _contact_checkins,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=timezone('Asia/Kathmandu')),
        id=JOB_CONTACT_CHECKINS,
        replace_existing=True,
    )
    logger.info("✅ Contact check-ins scheduled for Monday 9:00am NPT")

    # End-of-day wrap — daily 8:00pm NPT
    scheduler.add_job(
        _end_of_day_wrap,
        CronTrigger(hour=20, minute=0, timezone=timezone('Asia/Kathmandu')),
        id=JOB_EOD_WRAP,
        replace_existing=True,
    )
    logger.info("✅ End-of-day wrap scheduled for 8:00pm NPT daily")

    # Weekly review — Monday 8:00am NPT
    scheduler.add_job(
        _weekly_review,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=timezone('Asia/Kathmandu')),
        id=JOB_WEEKLY_REVIEW,
        replace_existing=True,
    )
    logger.info("✅ Weekly review scheduled for Monday 8:00am NPT")

    # Sales pace alert — daily 6:00pm NPT
    scheduler.add_job(
        _check_sales_pace,
        CronTrigger(hour=18, minute=0, timezone=timezone('Asia/Kathmandu')),
        id=JOB_SALES_PACE,
        replace_existing=True,
    )
    logger.info("✅ Sales pace alert scheduled for 6:00pm NPT daily")

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
