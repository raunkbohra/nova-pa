"""
Proactive Jobs — NOVA initiates on triggers rather than waiting to be asked.
All functions are module-level async for APScheduler SQLAlchemy job store serialization.

Jobs:
  - _check_unanswered_emails: Daily 10am NPT — emails 48hrs+ unread
  - _post_meeting_followup: Every 30 min — meetings that just ended
  - _contact_checkins: Monday 9am NPT — contacts not heard from in 14+ days
  - _end_of_day_wrap: Daily 8pm NPT — full day summary
  - _weekly_review: Monday 8am NPT — week recap + goals + sales
  - _check_sales_pace: Daily 6pm NPT — alert if behind daily target
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from pytz import timezone

logger = logging.getLogger(__name__)

NPT = timezone('Asia/Kathmandu')

# Job IDs for main.py registration
JOB_UNANSWERED_EMAILS = "proactive_unanswered_emails"
JOB_POST_MEETING = "proactive_post_meeting"
JOB_CONTACT_CHECKINS = "proactive_contact_checkins"
JOB_EOD_WRAP = "proactive_eod_wrap"
JOB_WEEKLY_REVIEW = "proactive_weekly_review"
JOB_SALES_PACE = "proactive_sales_pace"
JOB_MONTHLY_REPORT = "proactive_monthly_report"
JOB_PRE_MEETING = "proactive_pre_meeting"


async def _check_unanswered_emails():
    """
    Daily 10am NPT — find emails 48hrs+ unread and ping Raunk.
    Only sends if there are actionable emails (investors, clients, partners).
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.email_tool import EmailTool

    logger.info("Proactive: checking unanswered emails...")

    try:
        email = EmailTool()
        result = await email.execute(
            action="search",
            query="is:inbox is:unread older_than:2d",
            limit=10
        )

        if not result.success or not result.data.get("emails"):
            logger.info("Proactive: no old unread emails found")
            return

        emails = result.data["emails"]

        # Filter to priority senders
        priority_keywords = ["investor", "client", "partner", "board", "vc", "fund", "angel"]
        priority_emails = []
        for em in emails:
            sender = (em.get("from", "") + em.get("subject", "")).lower()
            if any(kw in sender for kw in priority_keywords):
                priority_emails.append(em)

        # Fall back to all unread if no priority ones found
        to_show = priority_emails[:3] if priority_emails else emails[:3]

        if not to_show:
            return

        lines = [f"📧 *{len(to_show)} email(s) need your attention (48hrs+):*"]
        for em in to_show:
            sender = em.get("from", "Unknown")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            subject = em.get("subject", "(no subject)")
            lines.append(f"• {sender} — {subject}")

        await send_text(settings.raunak_phone, "\n".join(lines))
        logger.info(f"Proactive: sent unanswered email alert ({len(to_show)} emails)")

    except Exception as e:
        logger.error(f"Proactive unanswered emails error: {e}")


async def _post_meeting_followup():
    """
    Every 30 min — find meetings that ended in the last 30 minutes and prompt follow-up.
    Skips all-day events (no 'T' in datetime string).
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool

    logger.info("Proactive: checking post-meeting follow-ups...")

    try:
        cal = CalendarTool()
        result = await cal.execute(action="list", limit=20)

        if not result.success or not result.data.get("events"):
            return

        now = datetime.now(NPT)
        window_start = now - timedelta(minutes=30)

        for event in result.data["events"]:
            end_str = event.get("end", "")
            title = event.get("title", "Untitled")

            # Skip all-day events
            if not end_str or "T" not in end_str:
                continue

            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(NPT)
            except Exception:
                continue

            # Check if it ended in the last 30 minutes
            if window_start <= end_dt <= now:
                msg = (
                    f"📅 *{title}* just ended.\n"
                    f"Want me to send a follow-up email or log any notes?"
                )
                await send_text(settings.raunak_phone, msg)
                logger.info(f"Proactive: sent post-meeting prompt for '{title}'")

    except Exception as e:
        logger.error(f"Proactive post-meeting error: {e}")


async def _contact_checkins():
    """
    Monday 9am NPT — contacts not heard from in 14+ days.
    Prioritises VIP contacts, max 5.
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.memory import AsyncSessionLocal
    from sqlalchemy.sql import select
    from sqlalchemy import func
    from app.memory import Contact
    import app.memory as _db

    logger.info("Proactive: checking contact check-ins...")

    try:
        cutoff = datetime.now(dt_timezone.utc) - timedelta(days=14)

        async with _db.AsyncSessionLocal() as session:
            stmt = (
                select(Contact)
                .where(Contact.is_blocked == False)  # noqa: E712
                .where(
                    func.coalesce(Contact.last_seen, Contact.first_seen) < cutoff
                )
                .order_by(
                    Contact.is_vip.desc(),
                    func.coalesce(Contact.last_seen, Contact.first_seen).asc()
                )
                .limit(5)
            )
            result = await session.execute(stmt)
            stale_contacts = result.scalars().all()

        if not stale_contacts:
            logger.info("Proactive: no stale contacts")
            return

        names = []
        for c in stale_contacts:
            label = c.name or c.phone
            if c.is_vip:
                label += " ⭐"
            names.append(f"• {label}")

        msg = "👥 *Haven't heard from these contacts in 2+ weeks:*\n"
        msg += "\n".join(names)
        msg += "\n\nWant me to reach out to any of them?"

        await send_text(settings.raunak_phone, msg)
        logger.info(f"Proactive: sent contact check-in for {len(stale_contacts)} contacts")

    except Exception as e:
        logger.error(f"Proactive contact check-ins error: {e}")


async def _end_of_day_wrap():
    """
    Daily 8pm NPT — summary of the day: meetings done, sales logged, tomorrow's reminders.
    Omits sections that have no data — no empty pings.
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool
    from app.tools.reminder_tool import ReminderTool
    import app.memory as _db
    from app.memory import get_sales_summary

    logger.info("Generating end-of-day wrap...")

    now = datetime.now(NPT)
    date_str = now.strftime("%A, %b %d")
    sections = [f"🌙 *End of Day — {date_str}*\n"]
    has_content = False

    # --- Calendar: completed events today ---
    try:
        cal = CalendarTool()
        result = await cal.execute(action="list", limit=20)
        if result.success and result.data.get("events"):
            done_events = []
            for e in result.data["events"]:
                end_str = e.get("end", "")
                if not end_str or "T" not in end_str:
                    continue
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(NPT)
                    if end_dt.date() == now.date() and end_dt <= now:
                        start_str = e.get("start", "")
                        if "T" in start_str:
                            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(NPT)
                            time_label = start_dt.strftime("%I:%M%p").lstrip("0")
                        else:
                            time_label = "all-day"
                        done_events.append(f"• {time_label} — {e.get('title', 'Untitled')}")
                except Exception:
                    continue

            if done_events:
                sections.append("✅ *DONE TODAY*")
                sections.extend(done_events)
                sections.append("")
                has_content = True
    except Exception as e:
        logger.warning(f"EOD wrap: calendar error: {e}")

    # --- Sales: today's entry ---
    try:
        async with _db.AsyncSessionLocal() as session:
            sales = await get_sales_summary(session, "today")
        if sales["total_revenue"] > 0:
            rev = sales["total_revenue"]
            orders = sales["total_orders"]
            # Daily pace needed for 30L month
            import calendar as cal_lib
            days_in_month = cal_lib.monthrange(now.year, now.month)[1]
            daily_target = 3_000_000 / days_in_month
            sections.append("📊 *SALES TODAY*")
            sections.append(f"• Revenue: Rs. {rev:,.0f} | Orders: {orders}")
            sections.append(f"• Target pace: Rs. {daily_target:,.0f}/day")
            sections.append("")
            has_content = True
        else:
            sections.append("📊 *SALES TODAY*\n• No sales data logged yet — want to add it?")
            sections.append("")
            has_content = True
    except Exception as e:
        logger.warning(f"EOD wrap: sales error: {e}")

    # --- Reminders: due tomorrow ---
    try:
        reminder = ReminderTool()
        result = await reminder.execute(action="list")
        if result.success and result.data.get("reminders"):
            tomorrow = (now + timedelta(days=1)).date()
            tomorrow_reminders = []
            for r in result.data["reminders"]:
                run_time = r.get("next_run_time", "")
                if run_time:
                    try:
                        rt = datetime.fromisoformat(run_time.replace("Z", "+00:00")).astimezone(NPT)
                        if rt.date() == tomorrow:
                            time_label = rt.strftime("%I:%M%p").lstrip("0")
                            tomorrow_reminders.append(f"• {time_label} — {r.get('name', 'Reminder')}")
                    except Exception:
                        continue

            if tomorrow_reminders:
                sections.append("⏰ *TOMORROW*")
                sections.extend(tomorrow_reminders)
                sections.append("")
                has_content = True
    except Exception as e:
        logger.warning(f"EOD wrap: reminders error: {e}")

    if not has_content:
        logger.info("EOD wrap: nothing to report, skipping")
        return

    message = "\n".join(sections).rstrip()
    await send_text(settings.raunak_phone, message)
    logger.info("End-of-day wrap sent.")


async def _weekly_review():
    """
    Monday 8am NPT — weekly recap: last week's sales, this week's calendar highlights,
    and a summary of active goals from memory.
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool
    import app.memory as _db
    from app.memory import get_sales_summary, get_all_context

    logger.info("Generating weekly review...")

    now = datetime.now(NPT)
    sections = [f"📋 *Weekly Review — {now.strftime('%b %d, %Y')}*\n"]
    has_content = False

    # --- Last week's sales ---
    try:
        async with _db.AsyncSessionLocal() as session:
            sales = await get_sales_summary(session, "last_7_days")
        rev = sales["total_revenue"]
        orders = sales["total_orders"]
        days = sales["days_logged"]
        if rev > 0:
            target_week = 3_000_000 / 4.33  # ~30L / 4.33 weeks
            pct = rev / target_week * 100
            sections.append("📊 *LAST 7 DAYS — iwishbag*")
            sections.append(f"• Revenue: Rs. {rev:,.0f} ({pct:.0f}% of weekly target)")
            sections.append(f"• Orders: {orders} | Days logged: {days}/7")
            sections.append(f"• Daily avg: Rs. {sales['daily_average']:,.0f}")
            sections.append("")
            has_content = True
    except Exception as e:
        logger.warning(f"Weekly review: sales error: {e}")

    # --- This week's calendar ---
    try:
        cal = CalendarTool()
        result = await cal.execute(action="list", time_range="this_week", limit=10)
        if result.success and result.data.get("events"):
            events = result.data["events"]
            timed = [e for e in events if "T" in e.get("start", "")]
            if timed:
                sections.append("📅 *THIS WEEK*")
                for e in timed[:5]:
                    start_str = e.get("start", "")
                    try:
                        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(NPT)
                        label = dt.strftime("%a %d %b, %I:%M%p").lstrip("0")
                    except Exception:
                        label = start_str[:10]
                    sections.append(f"• {label} — {e.get('title', 'Untitled')}")
                sections.append("")
                has_content = True
    except Exception as e:
        logger.warning(f"Weekly review: calendar error: {e}")

    # --- Active goals from memory ---
    try:
        async with _db.AsyncSessionLocal() as session:
            ctx = await get_all_context(session)
        goals = {k: v for k, v in ctx.items() if k.startswith("goal:")}
        if goals:
            sections.append("🎯 *ACTIVE GOALS*")
            for k, v in goals.items():
                label = k.replace("goal:", "").replace("_", " ").title()
                sections.append(f"• {label}: {v}")
            sections.append("")
            has_content = True
    except Exception as e:
        logger.warning(f"Weekly review: memory error: {e}")

    if not has_content:
        logger.info("Weekly review: nothing to report, skipping")
        return

    message = "\n".join(sections).rstrip()
    await send_text(settings.raunak_phone, message)
    logger.info("Weekly review sent.")


async def _check_sales_pace():
    """
    Daily 6pm NPT — if today's sales haven't been logged OR revenue is below
    the daily target pace, send an alert.
    """
    from app.whatsapp import send_text
    from app.config import settings
    import app.memory as _db
    from app.memory import get_sales_summary

    logger.info("Proactive: checking sales pace...")

    try:
        import calendar as cal_lib
        now = datetime.now(NPT)
        days_in_month = cal_lib.monthrange(now.year, now.month)[1]
        daily_target = 3_000_000 / days_in_month

        async with _db.AsyncSessionLocal() as session:
            today = await get_sales_summary(session, "today")

        revenue_today = today["total_revenue"]

        if revenue_today == 0:
            msg = (
                f"📊 *Sales check — {now.strftime('%b %d')}*\n"
                f"No sales logged yet today.\n"
                f"Daily target: Rs. {daily_target:,.0f} — want to log today's figures?"
            )
            await send_text(settings.raunak_phone, msg)
            logger.info("Proactive: sent sales reminder (no data)")
        elif revenue_today < daily_target * 0.7:
            pct = revenue_today / daily_target * 100
            gap = daily_target - revenue_today
            msg = (
                f"📊 *Sales alert — {now.strftime('%b %d')}*\n"
                f"• Today: Rs. {revenue_today:,.0f} ({pct:.0f}% of target)\n"
                f"• Gap: Rs. {gap:,.0f} below daily pace\n"
                f"• Monthly target: Rs. 30L"
            )
            await send_text(settings.raunak_phone, msg)
            logger.info(f"Proactive: sent sales pace alert ({pct:.0f}% of target)")
        else:
            logger.info(f"Proactive: sales pace OK (Rs. {revenue_today:,.0f})")

    except Exception as e:
        logger.error(f"Proactive sales pace error: {e}")


async def _monthly_sales_report():
    """
    1st of each month, 9am NPT — full last-month sales report vs 30L target.
    """
    from app.whatsapp import send_text
    from app.config import settings
    import app.memory as _db
    from app.memory import get_sales_summary, get_sales_trend

    logger.info("Generating monthly sales report...")

    try:
        async with _db.AsyncSessionLocal() as session:
            last_month = await get_sales_summary(session, "last_30_days")
            trend = await get_sales_trend(session, "last_30_days", "this_month")

        rev = last_month["total_revenue"]
        orders = last_month["total_orders"]
        days = last_month["days_logged"]
        avg = last_month["daily_average"]
        target = 3_000_000
        pct = rev / target * 100

        now = datetime.now(NPT)
        month_name = (now.replace(day=1) - __import__('datetime').timedelta(days=1)).strftime("%B %Y")

        status = "✅" if rev >= target else ("⚠️" if rev >= target * 0.7 else "❌")

        msg = (
            f"📊 *Monthly Report — {month_name}*\n\n"
            f"{status} *Revenue: Rs. {rev:,.0f}* ({pct:.1f}% of 30L target)\n"
            f"• Orders: {orders}\n"
            f"• Days logged: {days}/30\n"
            f"• Daily average: Rs. {avg:,.0f}\n"
            f"• Target: Rs. {target:,.0f}\n"
            f"• Gap: Rs. {abs(target - rev):,.0f} {'above' if rev >= target else 'below'} target"
        )

        await send_text(settings.raunak_phone, msg)
        logger.info("Monthly sales report sent.")

    except Exception as e:
        logger.error(f"Monthly report error: {e}")


async def _pre_meeting_prep():
    """
    Every 30 min — find meetings starting in the next 30 minutes and send prep context.
    Skips all-day events and meetings already pinged (tracked via memory key).
    """
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool
    from app.tools.perplexity_tool import PerplexityTool
    import app.memory as _db
    from app.memory import get_context, set_context

    logger.info("Proactive: checking pre-meeting prep...")

    try:
        cal = CalendarTool()
        result = await cal.execute(action="list", limit=10)
        if not result.success or not result.data.get("events"):
            return

        now = datetime.now(NPT)
        window_end = now + timedelta(minutes=35)
        window_start = now + timedelta(minutes=5)  # don't ping if already started

        for event in result.data["events"]:
            start_str = event.get("start", "")
            title = event.get("title", "Untitled")

            if not start_str or "T" not in start_str:
                continue

            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(NPT)
            except Exception:
                continue

            if not (window_start <= start_dt <= window_end):
                continue

            # Check if already prepped for this event
            event_id = event.get("id", start_str)
            mem_key = f"context:prepped_{event_id}"
            async with _db.AsyncSessionLocal() as session:
                already_prepped = await get_context(session, mem_key)

            if already_prepped:
                continue

            # Build prep message
            time_label = start_dt.strftime("%I:%M%p").lstrip("0")
            mins_away = int((start_dt - now).total_seconds() / 60)
            lines = [f"📅 *{title}* in {mins_away} min ({time_label})\n"]

            # Research attendees/topic if meaningful title
            skip_words = {"lunch", "break", "block", "focus", "personal", "hold"}
            if not any(w in title.lower() for w in skip_words) and len(title) > 4:
                try:
                    perplexity = PerplexityTool()
                    research = await perplexity.execute(
                        action="search",
                        query=f"Who is {title} and what should I know before a meeting with them? Brief background.",
                    )
                    if research.success and research.data.get("answer"):
                        answer = research.data["answer"][:400]
                        lines.append(f"*Background:*\n{answer}")
                except Exception:
                    pass

            description = event.get("description", "")
            if description:
                lines.append(f"\n*Agenda:* {description[:200]}")

            lines.append("\nWant me to pull anything else?")

            await send_text(settings.raunak_phone, "\n".join(lines))

            # Mark as prepped so we don't repeat
            async with _db.AsyncSessionLocal() as session:
                await set_context(session, mem_key, "1")

            logger.info(f"Proactive: sent pre-meeting prep for '{title}'")

    except Exception as e:
        logger.error(f"Proactive pre-meeting error: {e}")
