"""
Slash Commands — instant shortcuts that bypass the full AI loop for speed.

Supported commands:
  /help            — list all commands
  /brief           — trigger morning briefing now
  /tasks           — list pending Google Tasks
  /sales           — today's and this month's sales
  /remind <text>   — quick reminder (asks NOVA to set it)
  /memory          — dump all saved memory keys
  /cost            — API cost so far today
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_COMMANDS = {
    "/help": "show all slash commands",
    "/brief": "send morning briefing now",
    "/tasks": "list pending tasks",
    "/sales": "today + this month sales summary",
    "/remind": "set a quick reminder — e.g. /remind 3pm check orders",
    "/memory": "show everything NOVA remembers about you",
    "/cost": "API usage cost so far",
}


def is_slash_command(text: str) -> bool:
    """Return True if message starts with a known slash command."""
    lower = text.strip().lower()
    return any(lower == cmd or lower.startswith(cmd + " ") for cmd in _COMMANDS)


async def handle_slash_command(text: str) -> Optional[str]:
    """
    Execute a slash command and return the response string, or None if unrecognised.
    Fast path — no AI loop, no tool_choice overhead.
    """
    stripped = text.strip()
    lower = stripped.lower()

    # /help
    if lower == "/help":
        lines = ["*NOVA Slash Commands*\n"]
        for cmd, desc in _COMMANDS.items():
            lines.append(f"• `{cmd}` — {desc}")
        lines.append("\nOr just type naturally — NOVA understands plain language too.")
        return "\n".join(lines)

    # /brief — trigger morning briefing inline
    if lower == "/brief":
        try:
            from app.briefing import _send_morning_briefing
            await _send_morning_briefing()
            return None  # briefing sends its own message
        except Exception as e:
            logger.error(f"/brief error: {e}")
            return f"Couldn't send briefing: {e}"

    # /tasks
    if lower == "/tasks":
        try:
            from app.tools.tasks_tool import TasksTool
            result = await TasksTool().execute(action="list")
            if not result.success:
                return f"Couldn't load tasks: {result.error}"
            tasks = result.data.get("tasks", [])
            if not tasks:
                return "No pending tasks. ✅"
            lines = [f"*Tasks ({len(tasks)})*\n"]
            for t in tasks:
                due = f" — due {t['due']}" if t.get("due") else ""
                lines.append(f"• {t['title']}{due}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"/tasks error: {e}")
            return f"Couldn't load tasks: {e}"

    # /sales
    if lower == "/sales":
        try:
            import app.memory as _db
            from app.memory import get_sales_summary
            async with _db.AsyncSessionLocal() as session:
                today = await get_sales_summary(session, "today")
                month = await get_sales_summary(session, "this_month")

            lines = ["*Sales Summary*\n"]

            if today["total_revenue"] > 0:
                lines.append(f"*Today:* Rs. {today['total_revenue']:,.0f} | {today['total_orders']} orders")
                if today.get("margin_pct") is not None:
                    lines.append(f"  Margin: {today['margin_pct']}%")
            else:
                lines.append("*Today:* No data logged yet")

            lines.append("")
            rev = month["total_revenue"]
            pct = month.get("pct_of_target") or 0
            on_track = month.get("on_track")
            pace = "✅ on track" if on_track else "⚠️ behind pace"
            lines.append(f"*This month:* Rs. {rev:,.0f} ({pct}% of 30L) — {pace}")
            lines.append(f"  Orders: {month['total_orders']} | Avg/day: Rs. {month['daily_average']:,.0f}")
            if month.get("margin_pct") is not None:
                lines.append(f"  Gross margin: {month['margin_pct']}%")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"/sales error: {e}")
            return f"Couldn't load sales: {e}"

    # /memory
    if lower == "/memory":
        try:
            import app.memory as _db
            from app.memory import get_all_context
            async with _db.AsyncSessionLocal() as session:
                ctx = await get_all_context(session)
            if not ctx:
                return "No memories saved yet. Tell me something about yourself and I'll remember it."
            lines = [f"*Saved Memory ({len(ctx)} entries)*\n"]
            for k, v in sorted(ctx.items()):
                lines.append(f"• `{k}`: {v}")
            return "\n".join(lines)
        except Exception as e:
            return f"Couldn't load memory: {e}"

    # /cost
    if lower == "/cost":
        try:
            from app.tools.cost_tool import CostTool
            result = await CostTool().execute(days=30)
            if not result.success:
                return f"Couldn't load cost: {result.error}"
            d = result.data
            return (
                f"*API Cost (last 30 days)*\n"
                f"• Requests: {d.get('total_requests', 0):,}\n"
                f"• Tokens: {d.get('total_input', 0):,} in / {d.get('total_output', 0):,} out\n"
                f"• Est. cost: ${d.get('estimated_cost_usd', 0):.4f} USD"
            )
        except Exception as e:
            return f"Couldn't load cost: {e}"

    # /remind <text> — pass to NOVA as a natural language request
    if lower.startswith("/remind "):
        reminder_text = stripped[8:].strip()
        if not reminder_text:
            return "Usage: `/remind 3pm check iwishbag orders`"
        # Return None — let the caller pass this as a normal message to the agent
        return None

    return None
