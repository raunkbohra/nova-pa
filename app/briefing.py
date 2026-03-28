"""
Morning Briefing — Daily 7am summary for Raunk.
Pulls today's calendar, top unread emails, and Kathmandu weather.
Registered as a persistent APScheduler job in main.py.
"""

import logging
from datetime import datetime
from pytz import timezone

logger = logging.getLogger(__name__)

NPT = timezone('Asia/Kathmandu')
BRIEFING_JOB_ID = "morning_briefing"


async def _send_morning_briefing():
    """
    Module-level async function — required for APScheduler SQLAlchemy job store serialization.
    Called daily at 7am NPT.
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool
    from app.tools.email_tool import EmailTool
    from app.tools.weather_tool import WeatherTool

    logger.info("Generating morning briefing...")

    now = datetime.now(NPT)
    date_str = now.strftime("%A, %b %d")

    sections = [f"☀️ *Morning Briefing — {date_str}*\n"]

    # --- Calendar ---
    try:
        cal = CalendarTool()
        result = await cal.execute(action="list", limit=8)
        if result.success and result.data.get("events"):
            events = result.data["events"]
            sections.append("📅 *TODAY'S SCHEDULE*")
            for e in events:
                title = e.get("title", "Untitled")
                start = e.get("start", "")
                # Trim to just time portion if it's a datetime
                if "T" in start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(NPT)
                        start = dt.strftime("%I:%M%p").lstrip("0")
                    except Exception:
                        pass
                sections.append(f"• {start} — {title}")
        else:
            sections.append("📅 *TODAY'S SCHEDULE*\n• Nothing scheduled")
    except Exception as e:
        logger.warning(f"Briefing: calendar failed: {e}")
        sections.append("📅 *TODAY'S SCHEDULE*\n• (Could not load)")

    sections.append("")

    # --- Email ---
    try:
        email = EmailTool()
        result = await email.execute(action="search", query="is:unread in:inbox", limit=5)
        if result.success and result.data.get("emails"):
            emails = result.data["emails"]
            count = result.data.get("count", len(emails))
            sections.append(f"📧 *INBOX ({count} unread)*")
            for em in emails[:5]:
                sender = em.get("from", "Unknown")
                # Shorten "Name <email@domain>" to just Name
                if "<" in sender:
                    sender = sender.split("<")[0].strip().strip('"')
                subject = em.get("subject", "(no subject)")
                sections.append(f"• {sender} — {subject}")
        else:
            sections.append("📧 *INBOX*\n• No unread emails")
    except Exception as e:
        logger.warning(f"Briefing: email failed: {e}")
        sections.append("📧 *INBOX*\n• (Could not load)")

    sections.append("")

    # --- Weather ---
    try:
        weather = WeatherTool()
        result = await weather.execute(location="Kathmandu")
        if result.success and result.data:
            d = result.data
            temp = d.get("temperature", "?")
            desc = d.get("description", "").capitalize()
            sections.append(f"🌤 *KATHMANDU* — {temp}°C, {desc}")
        else:
            sections.append("🌤 *KATHMANDU* — (Could not load)")
    except Exception as e:
        logger.warning(f"Briefing: weather failed: {e}")

    sections.append("\nHave a great day, Raunk! 🙏")

    message = "\n".join(sections)

    await send_text(settings.raunak_phone, message)
    logger.info("Morning briefing sent.")
