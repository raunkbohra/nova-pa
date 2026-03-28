"""
Lending Tool — Track personal money lent and borrowed.
Maintains a running ledger: who owes Raunk, and who Raunk owes.
"""

import json
import logging
import os
from datetime import datetime, timezone, date as date_type, timedelta
from typing import Optional
from app.tools.base import BaseTool, ToolResult
import app.memory as _db
from app.memory import Base
from sqlalchemy import Column, Integer, String, Float, Text, Date, DateTime, func
from sqlalchemy.sql import select
import httpx

logger = logging.getLogger(__name__)


class LendingRecord(Base):
    """Personal lending/borrowing ledger"""
    __tablename__ = "lending_records"

    id = Column(Integer, primary_key=True)
    person = Column(String(255), nullable=False, index=True)   # normalized lowercase
    type = Column(String(10), nullable=False)                   # "lent" or "borrowed"
    amount = Column(Float, nullable=False)
    date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)  # NULL = outstanding
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LendingTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "lending"

    @property
    def description(self) -> str:
        return """Track personal money lent and borrowed — a personal ledger.

Actions:
- lend: Record money you gave to someone ("I lent Raj 5000")
- borrow: Record money you received from someone ("Amit gave me 2000")
- settle: Mark a debt as paid back ("Raj paid me back", "I paid Amit 1000")
- summary: See net balances per person — who owes you and who you owe
- history: Full transaction log, optionally filtered by person
- export: Create/update a Google Sheet with the full ledger and return its URL

Examples:
- "I lent Raj 5000" → lend(person="Raj", amount=5000)
- "Borrowed 2000 from Amit" → borrow(person="Amit", amount=2000)
- "Raj paid me back 3000" → settle(person="Raj", amount=3000)
- "Who owes me money?" → summary()
- "Show history with Raj" → history(person="Raj")
- "Export lending to Google Sheet" → export()
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["lend", "borrow", "settle", "summary", "history", "export"],
                    "description": "What to do: lend/borrow records a transaction, settle marks it paid, summary shows balances, history shows log, export syncs to Google Sheet"
                },
                "person": {
                    "type": "string",
                    "description": "Name of the person (required for lend/borrow/settle/history)"
                },
                "amount": {
                    "type": "number",
                    "description": "Amount in Rs. (required for lend/borrow; optional for settle to partially settle)"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional context (e.g. 'for dinner', 'advance salary')"
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional due date: 'YYYY-MM-DD'"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        # Ensure table exists
        async with _db.async_engine.begin() as conn:
            await conn.run_sync(LendingRecord.__table__.create, checkfirst=True)

        try:
            if action == "lend":
                return await self._record("lent", **kwargs)
            elif action == "borrow":
                return await self._record("borrowed", **kwargs)
            elif action == "settle":
                return await self._settle(**kwargs)
            elif action == "summary":
                return await self._summary()
            elif action == "history":
                return await self._history(**kwargs)
            elif action == "export":
                return await self._export_to_sheet()
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Lending tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _record(self, txn_type: str, person: str = None, amount: float = None,
                      notes: str = None, due_date: str = None, **kwargs) -> ToolResult:
        if not person:
            return ToolResult(tool_name=self.name, success=False, error="person is required")
        if amount is None or amount <= 0:
            return ToolResult(tool_name=self.name, success=False, error="amount is required and must be positive")

        parsed_due = None
        if due_date:
            try:
                parsed_due = date_type.fromisoformat(due_date)
            except ValueError:
                pass

        async with _db.AsyncSessionLocal() as session:
            session.add(LendingRecord(
                person=person.strip().lower(),
                type=txn_type,
                amount=amount,
                date=datetime.now(timezone.utc).date(),
                due_date=parsed_due,
                notes=notes,
            ))
            await session.commit()

        verb = "Lent" if txn_type == "lent" else "Borrowed"
        direction = "to" if txn_type == "lent" else "from"
        return ToolResult(tool_name=self.name, success=True, data={
            "message": f"{verb} Rs. {amount:,.0f} {direction} {person.title()}",
            "person": person.title(),
            "amount": amount,
            "type": txn_type,
        })

    async def _settle(self, person: str = None, amount: float = None,
                      notes: str = None, **kwargs) -> ToolResult:
        if not person:
            return ToolResult(tool_name=self.name, success=False, error="person is required to settle")

        person_key = person.strip().lower()
        now = datetime.now(timezone.utc)

        async with _db.AsyncSessionLocal() as session:
            # Get outstanding records for this person, oldest first
            stmt = (
                select(LendingRecord)
                .where(
                    LendingRecord.person == person_key,
                    LendingRecord.settled_at.is_(None)
                )
                .order_by(LendingRecord.date)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            if not records:
                return ToolResult(tool_name=self.name, success=False,
                                  error=f"No outstanding records found for {person.title()}")

            if amount is None:
                # Settle ALL outstanding records for this person
                settled_total = 0.0
                for rec in records:
                    rec.settled_at = now
                    if notes:
                        rec.notes = (rec.notes or "") + f" | settled: {notes}"
                    settled_total += rec.amount
                await session.commit()
                return ToolResult(tool_name=self.name, success=True, data={
                    "message": f"Settled all outstanding with {person.title()} (Rs. {settled_total:,.0f})",
                    "settled_count": len(records),
                    "settled_total": settled_total,
                })
            else:
                # Partial settle — mark oldest records until amount is covered
                remaining = amount
                settled_count = 0
                for rec in records:
                    if remaining <= 0:
                        break
                    rec.settled_at = now
                    if notes:
                        rec.notes = (rec.notes or "") + f" | settled: {notes}"
                    remaining -= rec.amount
                    settled_count += 1
                await session.commit()
                return ToolResult(tool_name=self.name, success=True, data={
                    "message": f"Settled Rs. {amount:,.0f} with {person.title()}",
                    "settled_count": settled_count,
                    "amount": amount,
                })

    async def _summary(self, **kwargs) -> ToolResult:
        async with _db.AsyncSessionLocal() as session:
            stmt = (
                select(
                    LendingRecord.person,
                    LendingRecord.type,
                    func.sum(LendingRecord.amount).label("total")
                )
                .where(LendingRecord.settled_at.is_(None))
                .group_by(LendingRecord.person, LendingRecord.type)
            )
            result = await session.execute(stmt)
            rows = result.all()

        # Aggregate: net per person (positive = they owe you, negative = you owe them)
        balances: dict[str, float] = {}
        for row in rows:
            person = row.person
            net = row.total if row.type == "lent" else -row.total
            balances[person] = balances.get(person, 0.0) + net

        owed_to_me = {p: v for p, v in balances.items() if v > 0}
        i_owe = {p: abs(v) for p, v in balances.items() if v < 0}
        total_owed_to_me = sum(owed_to_me.values())
        total_i_owe = sum(i_owe.values())

        return ToolResult(tool_name=self.name, success=True, data={
            "owed_to_me": {p.title(): v for p, v in owed_to_me.items()},
            "i_owe": {p.title(): v for p, v in i_owe.items()},
            "total_owed_to_me": total_owed_to_me,
            "total_i_owe": total_i_owe,
            "net_position": total_owed_to_me - total_i_owe,
        })

    async def _history(self, person: str = None, **kwargs) -> ToolResult:
        async with _db.AsyncSessionLocal() as session:
            stmt = select(LendingRecord).order_by(LendingRecord.date.desc())
            if person:
                stmt = stmt.where(LendingRecord.person == person.strip().lower())
            result = await session.execute(stmt)
            records = result.scalars().all()

        history = []
        for rec in records:
            history.append({
                "id": rec.id,
                "person": rec.person.title(),
                "type": rec.type,
                "amount": rec.amount,
                "date": str(rec.date),
                "due_date": str(rec.due_date) if rec.due_date else None,
                "settled": rec.settled_at is not None,
                "settled_at": rec.settled_at.strftime("%Y-%m-%d") if rec.settled_at else None,
                "notes": rec.notes,
            })

        return ToolResult(tool_name=self.name, success=True, data={
            "records": history,
            "count": len(history),
            "filter": person.title() if person else "all",
        })

    # ------------------------------------------------------------------
    # Google Sheets export
    # ------------------------------------------------------------------

    SHEETS_API = "https://sheets.googleapis.com/v4"
    DRIVE_API = "https://www.googleapis.com/drive/v3"
    SHEET_CONTEXT_KEY = "lending:sheet_id"  # persisted in nova_context

    async def _load_token(self) -> Optional[str]:
        """Load a valid Google OAuth access token (same pattern as drive_tool.py)."""
        from app.config import settings
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        try:
            token_file = settings.google_token_file
            if not os.path.exists(token_file):
                return None
            with open(token_file) as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data)
            if not creds.valid and creds.refresh_token:
                import asyncio
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, creds.refresh, Request())
                with open(token_file, "w") as f:
                    json.dump(json.loads(creds.to_json()), f)
            return creds.token
        except Exception as e:
            logger.error(f"Google token load failed: {e}")
            return None

    async def _sheets_request(self, token: str, method: str, url: str,
                               json_body=None, params=None) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers=headers,
                                        json=json_body, params=params, timeout=20.0)
            resp.raise_for_status()
            return resp.json()

    async def _export_to_sheet(self) -> ToolResult:
        token = await self._load_token()
        if not token:
            return ToolResult(tool_name=self.name, success=False,
                              error="Google auth failed — token missing or expired")

        # Fetch all records from DB
        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(LendingRecord).order_by(LendingRecord.date.desc())
            )
            records = result.scalars().all()
            saved_id = await _db.get_context(session, self.SHEET_CONTEXT_KEY)

        # Build rows: header + data
        header = ["#", "Person", "Type", "Amount (Rs.)", "Date", "Due Date",
                  "Status", "Settled On", "Notes"]
        rows = [header]
        for rec in records:
            rows.append([
                rec.id,
                rec.person.title(),
                "Lent →" if rec.type == "lent" else "← Borrowed",
                rec.amount,
                str(rec.date),
                str(rec.due_date) if rec.due_date else "",
                "Settled" if rec.settled_at else "Outstanding",
                rec.settled_at.strftime("%Y-%m-%d") if rec.settled_at else "",
                rec.notes or "",
            ])

        sheet_id = saved_id

        if sheet_id:
            # Verify the sheet still exists
            try:
                await self._sheets_request(
                    token, "GET",
                    f"{self.SHEETS_API}/spreadsheets/{sheet_id}",
                    params={"fields": "spreadsheetId"}
                )
            except Exception:
                sheet_id = None  # Sheet was deleted — create fresh

        if not sheet_id:
            # Create new spreadsheet
            body = {"properties": {"title": "NOVA — Personal Ledger"}}
            created = await self._sheets_request(
                token, "POST", f"{self.SHEETS_API}/spreadsheets", json_body=body
            )
            sheet_id = created["spreadsheetId"]

            # Persist the sheet ID so future exports reuse the same sheet
            async with _db.AsyncSessionLocal() as session:
                await _db.set_context(session, self.SHEET_CONTEXT_KEY, sheet_id)

        # Clear existing content then write fresh data
        await self._sheets_request(
            token, "POST",
            f"{self.SHEETS_API}/spreadsheets/{sheet_id}/values/Sheet1!A1:Z1000:clear"
        )
        await self._sheets_request(
            token, "PUT",
            f"{self.SHEETS_API}/spreadsheets/{sheet_id}/values/Sheet1!A1",
            params={"valueInputOption": "USER_ENTERED"},
            json_body={"values": rows}
        )

        # Bold the header row
        bold_request = {
            "requests": [{
                "repeatCell": {
                    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold"
                }
            }]
        }
        await self._sheets_request(
            token, "POST",
            f"{self.SHEETS_API}/spreadsheets/{sheet_id}:batchUpdate",
            json_body=bold_request
        )

        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        return ToolResult(tool_name=self.name, success=True, data={
            "message": f"Google Sheet updated with {len(records)} records",
            "url": url,
            "row_count": len(records),
            "sheet_id": sheet_id,
        })
