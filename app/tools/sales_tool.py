"""
Sales Tool — Log and query iwishbag daily sales data.
Tracks revenue vs 30L/month target.
"""

import logging
from app.tools.base import BaseTool, ToolResult
import app.memory as _db
from app.memory import save_sales, get_sales_summary, get_sales_trend

logger = logging.getLogger(__name__)


class SalesTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "sales"

    @property
    def description(self) -> str:
        return """Log and query iwishbag daily sales data. Tracks revenue vs 30L/month target.

Actions:
- log: Save or update a sales entry for a date
- summary: Get aggregated stats for a period (today/this_week/this_month/last_7_days/last_30_days)
- trend: Compare two periods side by side

Examples:
- Log today's sales → log(date="today", revenue=52000, orders=18)
- Check this month → summary(period="this_month")
- Compare weeks → trend(period_a="this_week", period_b="last_week")
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["log", "summary", "trend"],
                    "description": "'log' saves a sales entry, 'summary' queries stats, 'trend' compares two periods"
                },
                "date": {
                    "type": "string",
                    "description": "Date for log action: 'today', 'yesterday', 'YYYY-MM-DD', or 'Mar 26'"
                },
                "revenue": {
                    "type": "number",
                    "description": "Revenue in Rs. (required for log)"
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
                    "description": "Free-text notes for the day (optional for log)"
                },
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_week", "last_7_days", "this_month", "last_30_days"],
                    "description": "Period for summary action"
                },
                "period_a": {
                    "type": "string",
                    "description": "First period for trend comparison (e.g. 'this_week')"
                },
                "period_b": {
                    "type": "string",
                    "description": "Second period for trend comparison (e.g. 'last_week')"
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
            "saved": str(entry_date),
            "revenue": revenue,
            "orders": orders,
            "quotes": quotes,
            "cogs": cogs,
        })

    async def _summary(self, period: str = "this_month", **kwargs) -> ToolResult:
        async with _db.AsyncSessionLocal() as session:
            data = await get_sales_summary(session, period)
        return ToolResult(tool_name=self.name, success=True, data=data)

    async def _trend(self, period_a: str = None, period_b: str = None, **kwargs) -> ToolResult:
        if not period_a or not period_b:
            return ToolResult(tool_name=self.name, success=False,
                              error="Both period_a and period_b are required")
        async with _db.AsyncSessionLocal() as session:
            data = await get_sales_trend(session, period_a, period_b)
        return ToolResult(tool_name=self.name, success=True, data=data)
