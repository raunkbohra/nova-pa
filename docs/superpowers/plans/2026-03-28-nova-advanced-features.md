# NOVA Advanced Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent memory, structured sales tracking, and 4 proactive scheduled jobs to NOVA.

**Architecture:** Three independent systems sharing the existing PostgreSQL DB, APScheduler, and tool registry. Memory uses the existing `NovaContext` key-value table with namespaced keys. Sales adds a new `SalesData` table. Proactivity adds 4 APScheduler CronTrigger jobs in a new `app/proactive.py` module.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, APScheduler 3.x, PostgreSQL, Claude Haiku 4.5, pytz

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/memory.py` | Modify | Add `SalesData` model + `Float`/`Date` imports; add `save_sales`, `get_sales_summary`, `get_sales_trend`, `get_all_context` |
| `app/tools/memory_tool.py` | Create | `memory` tool — `remember`, `recall`, `forget` |
| `app/tools/sales_tool.py` | Create | `sales` tool — `log`, `summary`, `trend` |
| `app/tools/__init__.py` | Modify | Register `MemoryTool` and `SalesTool` |
| `app/agent.py` | Modify | Updated system prompt; replace single `raunak_info` inject with full multi-key context |
| `app/proactive.py` | Create | 4 proactive job functions: unanswered emails, post-meeting, contact check-ins, EOD wrap |
| `main.py` | Modify | Register 4 proactive APScheduler jobs at startup |

---

## Task 1: SalesData model + DB helpers

**Files:**
- Modify: `app/memory.py`

- [ ] **Step 1: Add `Float` and `Date` to SQLAlchemy imports**

In `app/memory.py`, change line 6-9:
```python
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float, Date, Index,
    create_engine, event, text, func
)
```

- [ ] **Step 2: Add `SalesData` model after `NovaContext` class (around line 84)**

```python
class SalesData(Base):
    """Daily iwishbag sales entries"""
    __tablename__ = "sales_data"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    revenue = Column(Float, nullable=False, default=0.0)
    orders = Column(Integer, nullable=False, default=0)
    quotes = Column(Integer, nullable=True)
    cogs = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 3: Add `save_sales` helper at end of CRUD section**

```python
async def save_sales(session: AsyncSession, date_str: str, revenue: float,
                     orders: int, quotes: int = None, cogs: float = None,
                     notes: str = None):
    """Save or update a daily sales entry (upsert by date)"""
    from datetime import date as date_type
    import re

    # Parse date: "yesterday", "today", "YYYY-MM-DD", "Mar 26", "March 26"
    today = datetime.now(timezone.utc).date()
    if date_str.lower() == "today":
        entry_date = today
    elif date_str.lower() == "yesterday":
        from datetime import timedelta
        entry_date = today - timedelta(days=1)
    else:
        try:
            entry_date = date_type.fromisoformat(date_str)
        except ValueError:
            # Try "Mar 26" / "March 26" formats
            for fmt in ("%b %d", "%B %d", "%b %d %Y", "%B %d %Y"):
                try:
                    parsed = datetime.strptime(date_str.strip(), fmt)
                    entry_date = parsed.replace(year=today.year).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Cannot parse date: {date_str}")

    stmt = select(SalesData).where(SalesData.date == entry_date)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.revenue = revenue
        existing.orders = orders
        if quotes is not None:
            existing.quotes = quotes
        if cogs is not None:
            existing.cogs = cogs
        if notes is not None:
            existing.notes = notes
    else:
        session.add(SalesData(
            date=entry_date, revenue=revenue, orders=orders,
            quotes=quotes, cogs=cogs, notes=notes
        ))

    await session.commit()
    return entry_date
```

- [ ] **Step 4: Add `get_sales_summary` helper**

```python
MONTHLY_TARGET = 3_000_000  # Rs. 30L

async def get_sales_summary(session: AsyncSession, period: str = "this_month") -> dict:
    """Return aggregated sales stats for a period vs 30L/month target"""
    from datetime import date, timedelta
    today = datetime.now(timezone.utc).date()

    if period == "today":
        start, end = today, today
    elif period == "yesterday":
        start = end = today - timedelta(days=1)
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif period == "last_7_days":
        start = today - timedelta(days=6)
        end = today
    elif period == "this_month":
        start = today.replace(day=1)
        end = today
    elif period == "last_30_days":
        start = today - timedelta(days=29)
        end = today
    else:
        start = today.replace(day=1)
        end = today

    stmt = select(
        func.sum(SalesData.revenue).label("total_revenue"),
        func.sum(SalesData.orders).label("total_orders"),
        func.sum(SalesData.cogs).label("total_cogs"),
        func.count(SalesData.id).label("days_logged"),
    ).where(SalesData.date.between(start, end))

    row = (await session.execute(stmt)).one()
    total_revenue = row.total_revenue or 0.0
    days_in_period = (end - start).days + 1

    # Month-to-date target progress
    days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day
    expected_by_today = (MONTHLY_TARGET / days_in_month) * today.day
    pct_of_target = (total_revenue / MONTHLY_TARGET * 100) if period == "this_month" else None

    return {
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_revenue": total_revenue,
        "total_orders": row.total_orders or 0,
        "total_cogs": row.total_cogs or 0.0,
        "days_logged": row.days_logged or 0,
        "daily_average": total_revenue / days_in_period if days_in_period > 0 else 0,
        "monthly_target": MONTHLY_TARGET,
        "pct_of_target": round(pct_of_target, 1) if pct_of_target is not None else None,
        "on_track": total_revenue >= expected_by_today if period == "this_month" else None,
    }
```

- [ ] **Step 5: Add `get_sales_trend` helper**

```python
async def get_sales_trend(session: AsyncSession, period_a: str, period_b: str) -> dict:
    """Compare two periods side by side"""
    summary_a = await get_sales_summary(session, period_a)
    summary_b = await get_sales_summary(session, period_b)

    rev_a = summary_a["total_revenue"]
    rev_b = summary_b["total_revenue"]
    pct_change = ((rev_a - rev_b) / rev_b * 100) if rev_b > 0 else None

    return {
        "period_a": summary_a,
        "period_b": summary_b,
        "revenue_change_pct": round(pct_change, 1) if pct_change is not None else None,
        "orders_change": summary_a["total_orders"] - summary_b["total_orders"],
    }
```

- [ ] **Step 6: Add `get_all_context` helper**

```python
async def get_all_context(session: AsyncSession) -> dict:
    """Return all NovaContext rows as {key: value} dict"""
    stmt = select(NovaContext)
    result = await session.execute(stmt)
    return {row.key: row.value for row in result.scalars().all()}
```

- [ ] **Step 7: Commit**

```bash
git add app/memory.py
git commit -m "feat: SalesData model + sales/context DB helpers"
```

---

## Task 2: Memory tool

**Files:**
- Create: `app/tools/memory_tool.py`

- [ ] **Step 1: Create the file**

```python
"""
Memory Tool — Persistent facts about Raunk: preferences, goals, people, projects.
Keys are namespaced: pref:, goal:, person:, project:, context:
"""

import logging
from app.tools.base import BaseTool, ToolResult
from app.memory import set_context, get_context
import app.memory as _db

logger = logging.getLogger(__name__)


class MemoryTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return """Remember, recall, or forget facts about Raunk — preferences, goals, people, projects.

Key naming convention:
- pref:meeting_times     → "Prefers mornings, avoids Fridays"
- goal:revenue_target    → "30L/month from iwishbag by Q3 2026"
- person:raj_sharma      → "Investor, Kathmandu, discussing Series A"
- project:iwishbag       → "E-commerce bags, target 30L/month"
- context:general        → General facts

Examples:
- Learn "Raunk prefers 9am meetings" → remember(key="pref:meetings", value="Prefers 9am, avoids Fridays")
- Learn "Raj is an investor" → remember(key="person:raj", value="Investor from Kathmandu, met March 2026")
- Recall all people → recall(pattern="person:")
- Recall a goal → recall(pattern="goal:revenue_target")
- Forget outdated fact → forget(key="project:old_project")
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["remember", "recall", "forget"],
                    "description": "'remember' saves a fact, 'recall' retrieves facts, 'forget' deletes a fact"
                },
                "key": {
                    "type": "string",
                    "description": "Namespaced key, e.g. 'pref:meetings', 'goal:revenue', 'person:raj' (required for remember/forget)"
                },
                "value": {
                    "type": "string",
                    "description": "The fact to remember, max ~200 chars (required for remember)"
                },
                "pattern": {
                    "type": "string",
                    "description": "Key prefix to search, e.g. 'person:' returns all person entries, or full key for exact lookup (required for recall)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "remember":
                return await self._remember(**kwargs)
            elif action == "recall":
                return await self._recall(**kwargs)
            elif action == "forget":
                return await self._forget(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Memory tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _remember(self, key: str = None, value: str = None, **kwargs) -> ToolResult:
        if not key:
            return ToolResult(tool_name=self.name, success=False, error="key is required")
        if not value:
            return ToolResult(tool_name=self.name, success=False, error="value is required")

        async with _db.AsyncSessionLocal() as session:
            await set_context(session, key, value)

        return ToolResult(tool_name=self.name, success=True, data={"saved": key, "value": value})

    async def _recall(self, pattern: str = None, **kwargs) -> ToolResult:
        if not pattern:
            return ToolResult(tool_name=self.name, success=False, error="pattern is required")

        async with _db.AsyncSessionLocal() as session:
            if ":" in pattern and not pattern.endswith(":"):
                # Exact key lookup
                value = await get_context(session, pattern)
                if value is None:
                    return ToolResult(tool_name=self.name, success=True,
                                      data={"results": {}, "count": 0, "message": f"No memory found for '{pattern}'"})
                return ToolResult(tool_name=self.name, success=True,
                                  data={"results": {pattern: value}, "count": 1})
            else:
                # Prefix search
                from sqlalchemy.sql import select
                from app.memory import NovaContext
                stmt = select(NovaContext).where(NovaContext.key.like(f"{pattern.rstrip(':')}:%"))
                result = await session.execute(stmt)
                rows = {row.key: row.value for row in result.scalars().all()}
                return ToolResult(tool_name=self.name, success=True,
                                  data={"results": rows, "count": len(rows)})

    async def _forget(self, key: str = None, **kwargs) -> ToolResult:
        if not key:
            return ToolResult(tool_name=self.name, success=False, error="key is required")

        async with _db.AsyncSessionLocal() as session:
            from sqlalchemy.sql import select, delete
            from app.memory import NovaContext
            await session.execute(delete(NovaContext).where(NovaContext.key == key))
            await session.commit()

        return ToolResult(tool_name=self.name, success=True, data={"deleted": key})
```

- [ ] **Step 2: Commit**

```bash
git add app/tools/memory_tool.py
git commit -m "feat: memory tool — remember/recall/forget with namespaced keys"
```

---

## Task 3: Sales tool

**Files:**
- Create: `app/tools/sales_tool.py`

- [ ] **Step 1: Create the file**

```python
"""
Sales Tool — Log and analyse iwishbag daily sales data.
Raunk pastes sales figures; NOVA calls this to store and query them.
"""

import logging
from app.tools.base import BaseTool, ToolResult
from app.memory import save_sales, get_sales_summary, get_sales_trend, MONTHLY_TARGET
import app.memory as _db

logger = logging.getLogger(__name__)


class SalesTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "sales"

    @property
    def description(self) -> str:
        return """Log and analyse iwishbag daily sales data. Monthly target: Rs. 30L.

Examples:
- User pastes "Revenue Rs. 50.6K, Orders 5, COGS Rs. 2.6K" → log(date="yesterday", revenue=50600, orders=5, cogs=2600)
- "How are sales this month?" → summary(period="this_month")
- "Compare this week vs last week" → trend(period_a="this_week", period_b="last_week")

Always call log() when user shares sales figures. Numbers in Rs. — convert K to full (50.6K = 50600).
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["log", "summary", "trend"],
                    "description": "'log' saves a day's data, 'summary' queries a period, 'trend' compares two periods"
                },
                "date": {
                    "type": "string",
                    "description": "For log: 'today', 'yesterday', 'YYYY-MM-DD', or 'Mar 26' (required for log)"
                },
                "revenue": {
                    "type": "number",
                    "description": "Revenue in Rs. — convert K notation (50.6K → 50600) (required for log)"
                },
                "orders": {
                    "type": "integer",
                    "description": "Number of orders (required for log)"
                },
                "quotes": {
                    "type": "integer",
                    "description": "Number of quotes (optional for log)"
                },
                "cogs": {
                    "type": "number",
                    "description": "Cost of goods sold in Rs. (optional for log)"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes for the day (optional for log)"
                },
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_week", "last_7_days", "this_month", "last_30_days"],
                    "description": "Period to query (required for summary)"
                },
                "period_a": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_week", "last_7_days", "this_month", "last_30_days"],
                    "description": "First period to compare (required for trend)"
                },
                "period_b": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_week", "last_7_days", "this_month", "last_30_days"],
                    "description": "Second period to compare (required for trend)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "log":
                return await self._log(**kwargs)
            elif action == "summary":
                return await self._summary(**kwargs)
            elif action == "trend":
                return await self._trend(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Sales tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _log(self, date: str = None, revenue: float = None, orders: int = None,
                   quotes: int = None, cogs: float = None, notes: str = None, **kwargs) -> ToolResult:
        if not date:
            return ToolResult(tool_name=self.name, success=False, error="date is required")
        if revenue is None:
            return ToolResult(tool_name=self.name, success=False, error="revenue is required")
        if orders is None:
            return ToolResult(tool_name=self.name, success=False, error="orders is required")

        async with _db.AsyncSessionLocal() as session:
            entry_date = await save_sales(session, date, revenue, orders, quotes, cogs, notes)

        return ToolResult(tool_name=self.name, success=True, data={
            "status": "logged",
            "date": str(entry_date),
            "revenue": f"Rs. {revenue:,.0f}",
            "orders": orders,
        })

    async def _summary(self, period: str = "this_month", **kwargs) -> ToolResult:
        async with _db.AsyncSessionLocal() as session:
            stats = await get_sales_summary(session, period)

        if stats["days_logged"] == 0:
            return ToolResult(tool_name=self.name, success=True,
                              data={"message": f"No sales data logged for {period} yet."})

        return ToolResult(tool_name=self.name, success=True, data=stats)

    async def _trend(self, period_a: str = None, period_b: str = None, **kwargs) -> ToolResult:
        if not period_a or not period_b:
            return ToolResult(tool_name=self.name, success=False,
                              error="Both period_a and period_b are required")

        async with _db.AsyncSessionLocal() as session:
            trend = await get_sales_trend(session, period_a, period_b)

        return ToolResult(tool_name=self.name, success=True, data=trend)
```

- [ ] **Step 2: Commit**

```bash
git add app/tools/sales_tool.py
git commit -m "feat: sales tool — log/summary/trend for iwishbag daily data"
```

---

## Task 4: Register tools

**Files:**
- Modify: `app/tools/__init__.py`

- [ ] **Step 1: Add imports and registrations**

Add after the existing WhatsAppTool/ContactsTool lines:
```python
from app.tools.memory_tool import MemoryTool
from app.tools.sales_tool import SalesTool
```

And at the bottom:
```python
register_tool(MemoryTool())
register_tool(SalesTool())
```

- [ ] **Step 2: Commit**

```bash
git add app/tools/__init__.py
git commit -m "feat: register memory and sales tools"
```

---

## Task 5: Update agent — system prompt + dynamic context injection

**Files:**
- Modify: `app/agent.py`

- [ ] **Step 1: Update imports — add `get_all_context`**

Change the memory import line:
```python
from app.memory import (
    save_message, get_messages, get_context, set_context,
    save_external_message, get_external_thread, save_usage, get_all_context
)
```

- [ ] **Step 2: Update COMMANDER_SYSTEM prompt**

Replace the current `COMMANDER_SYSTEM` string with:
```python
COMMANDER_SYSTEM = """You are NOVA, Raunk Bohra's executive assistant.

Your role: Help Raunk manage his work efficiently. You have access to his calendar, email, notes, reminders, sales data, memory, and can research topics via web search.

Personality:
- Direct, efficient, zero fluff
- Smart about what matters to Raunk
- Proactive with suggestions when relevant
- Honest about what you can and can't do

Commands you understand:
- "What's on today?" → Calendar summary
- "Brief me on my 3pm" → Meeting details + research on attendees
- "Save a note: [content]" → Add to second brain with optional tags
- "Search my notes: [query]" → Find notes by keyword
- "Remind me [when] to [task]" → Set reminder
- "Schedule [person], find time [duration] [when]" → Calendar booking
- "Reply to [email/message]" → Draft response
- "Delete email from [person]" → Use email tool: first search to get the email_id, then call delete action with that email_id
- "Research [topic]" → Web search
- "What's the weather?" → Current weather + forecast
- "Latest news on [topic]" → News headlines
- "Send [person] a WhatsApp: [message]" → MUST call send_whatsapp tool with phone + message
- "Message [number] saying [text]" → MUST call send_whatsapp tool immediately
- "How are sales?" → Use sales tool summary action
- "Who messaged?" → Use check_contacts tool
- "How much API cost?" → Use api_cost tool

Memory rules (CRITICAL):
- When Raunk tells you a preference → call memory(remember, key="pref:<topic>", value="...")
- When Raunk states a goal or target → call memory(remember, key="goal:<topic>", value="...")
- When you learn something important about a person → call memory(remember, key="person:<name>", value="...")
- When a project status changes → call memory(remember, key="project:<name>", value="...")
- Before answering questions about people/goals/projects → call memory(recall, pattern="person:") or relevant prefix

Sales rules:
- When Raunk pastes or shares sales figures → IMMEDIATELY call sales(log, ...) to store them
- Convert K notation: 50.6K = 50600, 2.6K = 2600
- Monthly target is Rs. 30,00,000 (30L)

Rules:
- Keep responses concise unless Raunk asks for details
- Use NPT (Asia/Kathmandu, UTC+5:45) timezone by default — Raunk is based in Nepal
- Always confirm before taking irreversible actions
- If you can't do something, explain why clearly
- CRITICAL: When asked to send a WhatsApp/message to a number, you MUST call the send_whatsapp tool. Never reply with text saying you sent it — actually call the tool."""
```

- [ ] **Step 3: Replace single `raunak_info` injection with full multi-key context**

Find this block in `process_commander_message` (around line 105):
```python
        # Load Raunak context
        raunak_info = await get_context(session, "raunak_info")

        # Build system prompt with context
        system = COMMANDER_SYSTEM
        if raunak_info:
            system += f"\n\nContext about Raunk:\n{raunak_info}"
```

Replace with:
```python
        # Load all persistent memory keys
        all_context = await get_all_context(session)

        # Build system prompt with structured context
        system = COMMANDER_SYSTEM
        if all_context:
            context_lines = [f"  {k}: {v}" for k, v in sorted(all_context.items())]
            system += "\n\nWhat I know about Raunk:\n" + "\n".join(context_lines)
```

- [ ] **Step 4: Add `log`, `summarize`, `trend`, `remember`, `recall`, `forget` to `_ACTION_PATTERNS`**

Find:
```python
        r"\b(send|message|text|whatsapp|remind|schedule|book|add|save|note|search|research|email|reply|delete|trash|remove)\b",
```

Replace with:
```python
        r"\b(send|message|text|whatsapp|remind|schedule|book|add|save|note|search|research|email|reply|delete|trash|remove|log|sales|revenue|orders|remember|recall|forget)\b",
```

- [ ] **Step 5: Commit**

```bash
git add app/agent.py
git commit -m "feat: agent — dynamic multi-key context injection + memory/sales instructions"
```

---

## Task 6: Proactive jobs module

**Files:**
- Create: `app/proactive.py`

- [ ] **Step 1: Create the file**

```python
"""
Proactive jobs — NOVA initiates on 4 scheduled triggers.
All functions are module-level async for APScheduler SQLAlchemy job store serialization.

Jobs registered in main.py:
  proactive_unanswered_emails  — daily 10:00am NPT
  proactive_post_meeting       — every 30 minutes
  proactive_contact_checkins   — Monday 09:00am NPT
  proactive_eod_wrap           — daily 20:00 NPT
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

NPT = None  # Lazy-loaded to avoid import-time issues


def _get_npt():
    global NPT
    if NPT is None:
        from pytz import timezone as tz
        NPT = tz('Asia/Kathmandu')
    return NPT


# ---------------------------------------------------------------------------
# Job 1: Unanswered email check — daily 10am NPT
# ---------------------------------------------------------------------------

async def _check_unanswered_emails():
    """Scan inbox for emails >48hrs old with no reply. Send WhatsApp nudge if any found."""
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.email_tool import EmailTool

    logger.info("Proactive: checking unanswered emails...")
    try:
        email = EmailTool()
        if not await email._ensure_token():
            logger.warning("Proactive emails: could not authenticate Gmail")
            return

        result = await email._search_emails(query="is:inbox is:unread older_than:2d", limit=5)
        if not result.success or not result.data.get("emails"):
            logger.info("Proactive emails: nothing unanswered")
            return

        emails = result.data["emails"]
        lines = []
        for e in emails[:3]:
            sender = e.get("from", "Unknown")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            lines.append(f"• {sender} — {e.get('subject', '(no subject)')}")

        msg = f"📧 *{len(emails)} email(s) need your attention (48hrs+):*\n" + "\n".join(lines)
        await send_text(settings.raunak_phone, msg)
        logger.info(f"Proactive: sent unanswered email nudge ({len(emails)} emails)")
    except Exception as e:
        logger.error(f"Proactive unanswered emails error: {e}")


# ---------------------------------------------------------------------------
# Job 2: Post-meeting follow-up — every 30 minutes
# ---------------------------------------------------------------------------

async def _post_meeting_followup():
    """Check for timed calendar events that ended in last 30min. Prompt for follow-up."""
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool

    logger.info("Proactive: checking for recently ended meetings...")
    try:
        cal = CalendarTool()
        if not await cal._ensure_token():
            logger.warning("Proactive meetings: could not authenticate Calendar")
            return

        result = await cal._list_events(time_range="today")
        if not result.success or not result.data.get("events"):
            return

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=31)

        for event in result.data["events"]:
            end_str = event.get("end", "")
            # All-day events have date-only strings (no "T") — skip them
            if not end_str or "T" not in end_str:
                continue
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if window_start <= end_dt <= now:
                    title = event.get("title", "Meeting")
                    msg = f"📅 *{title}* just ended.\nWant me to send a follow-up or log notes?"
                    await send_text(settings.raunak_phone, msg)
                    logger.info(f"Proactive: post-meeting nudge sent for '{title}'")
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Proactive post-meeting error: {e}")


# ---------------------------------------------------------------------------
# Job 3: Contact check-ins — Monday 9am NPT
# ---------------------------------------------------------------------------

async def _contact_checkins():
    """Find VIP/important contacts not heard from in 14+ days. Send WhatsApp list."""
    from app.whatsapp import send_text
    from app.config import settings
    from sqlalchemy.sql import select
    from app.memory import Contact
    import app.memory as _db

    logger.info("Proactive: checking stale contacts...")
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)

        async with _db.AsyncSessionLocal() as session:
            from sqlalchemy import func as sqlfunc
            last_activity = sqlfunc.coalesce(Contact.last_seen, Contact.first_seen)
            stmt = (
                select(Contact)
                .where(
                    Contact.is_blocked == False,
                    last_activity < cutoff
                )
                .order_by(Contact.is_vip.desc(), last_activity.asc())
                .limit(5)
            )
            result = await session.execute(stmt)
            contacts = result.scalars().all()

        if not contacts:
            logger.info("Proactive: no stale contacts")
            return

        lines = []
        for c in contacts:
            name = c.name or c.phone
            last = c.last_seen.strftime("%b %d") if c.last_seen else "unknown"
            vip = " ⭐" if c.is_vip else ""
            lines.append(f"• {name}{vip} — last seen {last}")

        msg = "👥 *Haven't heard from these contacts in 2+ weeks:*\n" + "\n".join(lines)
        msg += "\n\nWant me to reach out to any of them?"
        await send_text(settings.raunak_phone, msg)
        logger.info(f"Proactive: sent contact check-in nudge ({len(contacts)} contacts)")
    except Exception as e:
        logger.error(f"Proactive contact checkins error: {e}")


# ---------------------------------------------------------------------------
# Job 4: End-of-day wrap — daily 8pm NPT
# ---------------------------------------------------------------------------

async def _end_of_day_wrap():
    """Evening summary: completed calendar events, today's sales, tomorrow's reminders."""
    from app.whatsapp import send_text
    from app.config import settings
    from app.tools.calendar_tool import CalendarTool
    from app.memory import get_sales_summary, MONTHLY_TARGET
    import app.memory as _db

    logger.info("Proactive: generating end-of-day wrap...")
    npt = _get_npt()
    today_str = datetime.now(npt).strftime("%A, %b %d")
    sections = [f"🌙 *End of Day — {today_str}*\n"]

    # --- Today's calendar ---
    try:
        cal = CalendarTool()
        if await cal._ensure_token():
            result = await cal._list_events(time_range="today")
            if result.success and result.data.get("events"):
                events = result.data["events"]
                timed = [e for e in events if e.get("start") and "T" in e.get("start", "")]
                if timed:
                    sections.append("✅ *TODAY'S MEETINGS*")
                    for e in timed:
                        try:
                            dt = datetime.fromisoformat(
                                e["start"].replace("Z", "+00:00")
                            ).astimezone(npt)
                            time_str = dt.strftime("%I:%M%p").lstrip("0")
                        except Exception:
                            time_str = e.get("start", "")
                        sections.append(f"• {time_str} — {e.get('title', 'Event')}")
                    sections.append("")
    except Exception as ex:
        logger.warning(f"EOD wrap: calendar error: {ex}")

    # --- Today's sales ---
    try:
        async with _db.AsyncSessionLocal() as session:
            stats = await get_sales_summary(session, "today")
        if stats.get("days_logged", 0) > 0:
            rev = stats["total_revenue"]
            orders = stats["total_orders"]
            daily_target = MONTHLY_TARGET / 30
            pct = rev / daily_target * 100
            sections.append("📊 *TODAY'S SALES*")
            sections.append(f"• Revenue: Rs. {rev:,.0f} ({pct:.0f}% of daily target)")
            sections.append(f"• Orders: {orders}")
            sections.append("")
        else:
            sections.append("📊 *SALES*\n• No data logged today yet\n")
    except Exception as ex:
        logger.warning(f"EOD wrap: sales error: {ex}")

    sections.append("Have a great evening, Raunk! 🙏")
    await send_text(settings.raunak_phone, "\n".join(sections))
    logger.info("Proactive: end-of-day wrap sent.")
```

- [ ] **Step 2: Commit**

```bash
git add app/proactive.py
git commit -m "feat: proactive jobs — unanswered emails, post-meeting, contact checkins, EOD wrap"
```

---

## Task 7: Register proactive jobs in main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add imports**

After the existing briefing import line:
```python
from app.proactive import (
    _check_unanswered_emails,
    _post_meeting_followup,
    _contact_checkins,
    _end_of_day_wrap,
)
```

- [ ] **Step 2: Register the 4 jobs in the lifespan startup block**

After the existing `logger.info("✅ Morning briefing scheduled...")` line, add:
```python
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler.add_job(
        _check_unanswered_emails,
        CronTrigger(hour=10, minute=0, timezone=timezone('Asia/Kathmandu')),
        id="proactive_unanswered_emails",
        replace_existing=True,
    )
    scheduler.add_job(
        _post_meeting_followup,
        IntervalTrigger(minutes=30),
        id="proactive_post_meeting",
        replace_existing=True,
    )
    scheduler.add_job(
        _contact_checkins,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=timezone('Asia/Kathmandu')),
        id="proactive_contact_checkins",
        replace_existing=True,
    )
    scheduler.add_job(
        _end_of_day_wrap,
        CronTrigger(hour=20, minute=0, timezone=timezone('Asia/Kathmandu')),
        id="proactive_eod_wrap",
        replace_existing=True,
    )
    logger.info("✅ Proactive jobs registered (emails 10am, post-meeting 30min, checkins Mon 9am, EOD 8pm)")
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: register 4 proactive APScheduler jobs in main.py"
```

---

## Task 8: Deploy and verify

- [ ] **Step 1: Push and deploy**

```bash
bash scripts/deploy.sh
```

Expected: `nova` process restarts, status `online`.

- [ ] **Step 2: Check startup logs for all jobs**

```bash
ssh nova-vps "pm2 logs nova --lines 30 --nostream"
```

Expected lines in logs:
```
✅ Morning briefing scheduled for 7:00am NPT daily
✅ Proactive jobs registered (emails 10am, post-meeting 30min, checkins Mon 9am, EOD 8pm)
```

- [ ] **Step 3: Test memory tool — tell NOVA a preference**

Send WhatsApp: *"I prefer 9am meetings, avoid Fridays"*
Expected: NOVA calls `memory(remember, key="pref:meetings", value=...)` and confirms.

Verify in DB:
```bash
ssh nova-vps "cd nova-pa && python -c \"
import asyncio
from app.memory import init_db, get_all_context, AsyncSessionLocal
from app.config import settings
async def check():
    await init_db(settings.database_url)
    async with AsyncSessionLocal() as s:
        ctx = await get_all_context(s)
        print(ctx)
asyncio.run(check())
\""
```

Expected: dict containing `pref:meetings` key.

- [ ] **Step 4: Test sales tool — paste sales data**

Send WhatsApp: *"Yesterday: Revenue Rs. 80K, Orders 8, COGS Rs. 4K"*
Expected: NOVA calls `sales(log, date="yesterday", revenue=80000, orders=8, cogs=4000)` and confirms.

Then ask: *"How are sales this month?"*
Expected: NOVA returns summary with revenue total and % of 30L target.

- [ ] **Step 5: Test EOD wrap manually**

```bash
ssh nova-vps "cd nova-pa && python -c \"
import asyncio
from app.proactive import _end_of_day_wrap
asyncio.run(_end_of_day_wrap())
\""
```

Expected: WhatsApp message received within 5 seconds.

- [ ] **Step 6: Test unanswered emails manually**

```bash
ssh nova-vps "cd nova-pa && python -c \"
import asyncio
from app.proactive import _check_unanswered_emails
asyncio.run(_check_unanswered_emails())
\""
```

Expected: Either WhatsApp nudge (if old unread emails exist) or silent (nothing to report).

- [ ] **Step 7: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: post-deploy fixes"
bash scripts/deploy.sh
```
