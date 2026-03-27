"""
Reminder Tool — Schedule recurring and one-time reminders.
Survives server restarts via APScheduler + PostgreSQL.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.base import BaseTool, ToolResult
from app.whatsapp import send_text
from app.config import settings

logger = logging.getLogger(__name__)

IST = timezone('Asia/Kolkata')

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None


def init_scheduler(database_url: str) -> AsyncIOScheduler:
    """Initialize APScheduler with PostgreSQL job store"""
    global _scheduler
    
    if _scheduler is not None:
        return _scheduler
    
    # SQLAlchemy job store
    jobstores = {
        'default': SQLAlchemyJobStore(url=database_url)
    }
    
    job_defaults = {
        'coalesce': True,
        'max_instances': 1
    }
    
    _scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults=job_defaults,
        timezone=IST
    )
    
    logger.info("APScheduler initialized with PostgreSQL job store")
    return _scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Get the global scheduler instance"""
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call init_scheduler first.")
    return _scheduler


class ReminderTool(BaseTool):
    """Tool for scheduling reminders"""

    def __init__(self, session: AsyncSession = None):
        self.session = session

    @property
    def name(self) -> str:
        return "reminder"

    @property
    def description(self) -> str:
        return """Schedule reminders to be notified at a specific time.

Examples:
- "Remind me in 10 minutes to check email"
- "Remind me tomorrow at 2pm IST to call Raj"
- "Remind me every Monday at 9am to prepare for week"
- "Remind me in 1 hour to drink water"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["schedule", "list", "cancel"],
                    "description": "Action: 'schedule' a new reminder, 'list' all reminders, or 'cancel' a reminder"
                },
                "message": {
                    "type": "string",
                    "description": "Reminder message (required for schedule)"
                },
                "when": {
                    "type": "string",
                    "description": "When to remind: '10 minutes', '2pm', 'tomorrow at 3pm', 'every Monday at 9am' (required for schedule)"
                },
                "reminder_id": {
                    "type": "string",
                    "description": "Reminder ID to cancel (required for cancel)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """Execute reminder operation"""
        try:
            if action == "schedule":
                return await self._schedule_reminder(**kwargs)
            elif action == "list":
                return await self._list_reminders()
            elif action == "cancel":
                return await self._cancel_reminder(**kwargs)
            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Unknown action: {action}"
                )
        except Exception as e:
            logger.error(f"Reminder tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _schedule_reminder(self, message: str = None, when: str = None,
                                 **kwargs) -> ToolResult:
        """Schedule a new reminder"""
        if not message:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Message is required to schedule a reminder"
            )
        
        if not when:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="When is required to schedule a reminder"
            )

        try:
            scheduler = get_scheduler()
            
            # Parse 'when' string and schedule job
            trigger, next_run = self._parse_when(when)
            
            job_id = f"reminder_{int(datetime.now().timestamp())}"
            
            scheduler.add_job(
                self._send_reminder,
                trigger=trigger,
                args=[message, job_id],
                id=job_id,
                replace_existing=False
            )
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "scheduled",
                    "reminder_id": job_id,
                    "message": message,
                    "when": when,
                    "next_run": next_run.isoformat() if next_run else "unknown"
                }
            )
        except Exception as e:
            logger.error(f"Failed to schedule reminder: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _list_reminders(self) -> ToolResult:
        """List all scheduled reminders"""
        try:
            scheduler = get_scheduler()
            jobs = scheduler.get_jobs()
            
            reminders = []
            for job in jobs:
                reminders.append({
                    "reminder_id": job.id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                })
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "reminders": reminders,
                    "count": len(reminders)
                }
            )
        except Exception as e:
            logger.error(f"Failed to list reminders: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _cancel_reminder(self, reminder_id: str = None, **kwargs) -> ToolResult:
        """Cancel a scheduled reminder"""
        if not reminder_id:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Reminder ID is required to cancel"
            )
        
        try:
            scheduler = get_scheduler()
            scheduler.remove_job(reminder_id)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "cancelled",
                    "reminder_id": reminder_id
                }
            )
        except Exception as e:
            logger.error(f"Failed to cancel reminder: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _send_reminder(self, message: str, job_id: str):
        """Send reminder via WhatsApp (called by scheduler)"""
        try:
            reminder_text = f"⏰ Reminder: {message}"
            await send_text(settings.raunak_phone, reminder_text)
            logger.info(f"Reminder sent: {job_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")

    def _parse_when(self, when: str) -> tuple:
        """Parse when string and return (trigger, next_run_time)"""
        when_lower = when.lower().strip()
        now = datetime.now(IST)
        
        # "in X minutes/hours"
        if when_lower.startswith("in "):
            parts = when_lower[3:].split()
            try:
                amount = int(parts[0])
                unit = parts[1].lower() if len(parts) > 1 else "minutes"
                
                if unit.startswith("minute"):
                    delta = timedelta(minutes=amount)
                elif unit.startswith("hour"):
                    delta = timedelta(hours=amount)
                elif unit.startswith("day"):
                    delta = timedelta(days=amount)
                else:
                    delta = timedelta(minutes=amount)
                
                run_time = now + delta
                from apscheduler.triggers.date import DateTrigger
                return DateTrigger(run_time=run_time), run_time
            except (ValueError, IndexError):
                raise ValueError(f"Could not parse time: {when}")
        
        # "tomorrow at HH:MM"
        if when_lower.startswith("tomorrow"):
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            
            if "at " in when_lower:
                time_part = when_lower.split("at ")[1].strip()
                try:
                    hour, minute = map(int, time_part.replace(":", " ").split())
                    tomorrow = tomorrow.replace(hour=hour, minute=minute)
                except:
                    raise ValueError(f"Could not parse time: {when}")
            
            from apscheduler.triggers.date import DateTrigger
            return DateTrigger(run_time=tomorrow), tomorrow
        
        # "HHpm/am" or "HH:MM"
        if "am" in when_lower or "pm" in when_lower or ":" in when_lower:
            # Simple 24h time or 12h with am/pm
            try:
                if "am" in when_lower or "pm" in when_lower:
                    time_obj = datetime.strptime(when_lower.replace("am", "").replace("pm", "").strip(), "%I:%M" if ":" in when_lower else "%I")
                    if "pm" in when_lower and time_obj.hour < 12:
                        time_obj = time_obj.replace(hour=time_obj.hour + 12)
                else:
                    time_obj = datetime.strptime(when_lower, "%H:%M" if ":" in when_lower else "%H")
                
                today_run = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
                
                # If time has passed today, schedule for tomorrow
                if today_run <= now:
                    today_run = (today_run + timedelta(days=1))
                
                from apscheduler.triggers.date import DateTrigger
                return DateTrigger(run_time=today_run), today_run
            except:
                raise ValueError(f"Could not parse time: {when}")
        
        # "every X day at HH:MM" (e.g., "every Monday at 9am")
        if "every " in when_lower:
            parts = when_lower.split("every ")[1]
            
            # Map day names to cron weekday numbers (0=Monday, 6=Sunday)
            day_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6
            }
            
            weekday = None
            hour, minute = 9, 0  # default 9am
            
            for day_name, day_num in day_map.items():
                if day_name in parts:
                    weekday = day_num
                    break
            
            if weekday is None:
                raise ValueError(f"Could not parse day: {when}")
            
            if "at " in parts:
                time_part = parts.split("at ")[1].strip()
                try:
                    if "pm" in time_part or "am" in time_part:
                        time_obj = datetime.strptime(time_part.replace("am", "").replace("pm", "").strip(), "%I:%M" if ":" in time_part else "%I")
                        if "pm" in time_part and time_obj.hour < 12:
                            time_obj = time_obj.replace(hour=time_obj.hour + 12)
                    else:
                        time_obj = datetime.strptime(time_part, "%H:%M" if ":" in time_part else "%H")
                    hour, minute = time_obj.hour, time_obj.minute
                except:
                    pass
            
            cron_trigger = CronTrigger(day_of_week=weekday, hour=hour, minute=minute, timezone=IST)
            next_run = cron_trigger.get_next_fire_time(None, now)
            return cron_trigger, next_run
        
        raise ValueError(f"Could not parse when: {when}")
