"""
Expense Tool — Track business expenses for iwishbag P&L.
Separate from sales COGS — logs one-off costs like ads, logistics, salaries, etc.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from app.tools.base import BaseTool, ToolResult
import app.memory as _db
from sqlalchemy import Column, Integer, String, Float, Text, Date, DateTime, func
from sqlalchemy.sql import select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model — defined here, Base.metadata picked up on next init_db call
# ---------------------------------------------------------------------------

from app.memory import Base


class Expense(Base):
    """Business expense entries"""
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    category = Column(String(100), nullable=False)  # ads, logistics, salary, misc, etc.
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExpenseTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "expense"

    @property
    def description(self) -> str:
        return """Track iwishbag business expenses for P&L analysis.

Actions:
- log: Record an expense (ads, logistics, salary, misc, etc.)
- summary: Get total expenses for a period with breakdown by category
- profit: Calculate net profit = revenue - COGS - expenses for a period

Examples:
- "Spent Rs. 8K on Facebook ads today" → log(date="today", amount=8000, category="ads", description="Facebook ads")
- "What did I spend this month?" → summary(period="this_month")
- "What's my actual profit this month?" → profit(period="this_month")
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["log", "summary", "profit"],
                    "description": "'log' records expense, 'summary' shows breakdown, 'profit' shows net P&L"
                },
                "date": {
                    "type": "string",
                    "description": "Date: 'today', 'yesterday', 'YYYY-MM-DD' (required for log)"
                },
                "amount": {
                    "type": "number",
                    "description": "Amount in Rs. (required for log)"
                },
                "category": {
                    "type": "string",
                    "description": "Category: ads, logistics, salary, rent, misc, etc. (required for log)"
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of the expense"
                },
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_week", "last_7_days", "this_month", "last_30_days"],
                    "description": "Period for summary/profit (default: this_month)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        # Ensure table exists
        async with _db.async_engine.begin() as conn:
            await conn.run_sync(Expense.__table__.create, checkfirst=True)

        try:
            if action == "log":
                return await self._log(**kwargs)
            elif action == "summary":
                return await self._summary(**kwargs)
            elif action == "profit":
                return await self._profit(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Expense tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _log(self, date: str = None, amount: float = None, category: str = None,
                   description: str = None, **kwargs) -> ToolResult:
        if not date:
            return ToolResult(tool_name=self.name, success=False, error="date is required")
        if amount is None:
            return ToolResult(tool_name=self.name, success=False, error="amount is required")
        if not category:
            return ToolResult(tool_name=self.name, success=False, error="category is required")

        from datetime import date as date_type, timedelta
        today = datetime.now(timezone.utc).date()
        if date.lower() == "today":
            entry_date = today
        elif date.lower() == "yesterday":
            entry_date = today - timedelta(days=1)
        else:
            entry_date = date_type.fromisoformat(date)

        async with _db.AsyncSessionLocal() as session:
            session.add(Expense(
                date=entry_date,
                amount=amount,
                category=category.lower().strip(),
                description=description,
            ))
            await session.commit()

        return ToolResult(tool_name=self.name, success=True, data={
            "saved": str(entry_date), "amount": amount, "category": category
        })

    async def _summary(self, period: str = "this_month", **kwargs) -> ToolResult:
        start, end = self._date_range(period)
        async with _db.AsyncSessionLocal() as session:
            # Total
            total_row = (await session.execute(
                select(func.sum(Expense.amount).label("total"))
                .where(Expense.date.between(start, end))
            )).one()
            total = total_row.total or 0.0

            # By category
            cat_rows = (await session.execute(
                select(Expense.category, func.sum(Expense.amount).label("subtotal"))
                .where(Expense.date.between(start, end))
                .group_by(Expense.category)
                .order_by(func.sum(Expense.amount).desc())
            )).all()

        breakdown = {row.category: row.subtotal for row in cat_rows}
        return ToolResult(tool_name=self.name, success=True, data={
            "period": period, "total_expenses": total, "breakdown": breakdown
        })

    async def _profit(self, period: str = "this_month", **kwargs) -> ToolResult:
        from app.memory import get_sales_summary
        start, end = self._date_range(period)

        async with _db.AsyncSessionLocal() as session:
            sales = await get_sales_summary(session, period)
            expense_row = (await session.execute(
                select(func.sum(Expense.amount).label("total"))
                .where(Expense.date.between(start, end))
            )).one()

        revenue = sales["total_revenue"]
        cogs = sales["total_cogs"]
        expenses = expense_row.total or 0.0
        gross_profit = revenue - cogs
        net_profit = gross_profit - expenses
        net_margin = (net_profit / revenue * 100) if revenue > 0 else None

        return ToolResult(tool_name=self.name, success=True, data={
            "period": period,
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "expenses": expenses,
            "net_profit": net_profit,
            "net_margin_pct": round(net_margin, 1) if net_margin is not None else None,
        })

    @staticmethod
    def _date_range(period: str):
        from datetime import date, timedelta
        today = datetime.now(timezone.utc).date()
        if period == "today":
            return today, today
        elif period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        elif period == "this_week":
            return today - timedelta(days=today.weekday()), today
        elif period == "last_7_days":
            return today - timedelta(days=6), today
        elif period == "last_30_days":
            return today - timedelta(days=29), today
        else:  # this_month
            return today.replace(day=1), today
