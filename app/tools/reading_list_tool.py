"""
Reading List Tool — Save URLs/articles to read later.
Raunk can paste links and NOVA saves them; he can list or summarize on demand.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from app.tools.base import BaseTool, ToolResult
import app.memory as _db
from app.memory import Base
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, func
from sqlalchemy.sql import select

logger = logging.getLogger(__name__)


class ReadingItem(Base):
    """Saved reading list items"""
    __tablename__ = "reading_list"

    id = Column(Integer, primary_key=True)
    url = Column(Text, nullable=False)
    title = Column(String(500), nullable=True)
    summary = Column(Text, nullable=True)
    tags = Column(String(255), nullable=True)
    read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReadingListTool(BaseTool):

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "reading_list"

    @property
    def description(self) -> str:
        return """Save URLs to read later, list them, or summarize a saved article.

Actions:
- save: Add a URL to the reading list
- list: Show unread items (optionally filtered by tag)
- summarize: Fetch and summarize a saved item
- mark_read: Mark an item as read

Examples:
- "Save this for later: https://..." → save(url="https://...")
- "What's on my reading list?" → list()
- "Summarize item 3 from my reading list" → summarize(item_id=3)
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "list", "summarize", "mark_read"],
                    "description": "Action to perform"
                },
                "url": {
                    "type": "string",
                    "description": "URL to save (required for save)"
                },
                "title": {
                    "type": "string",
                    "description": "Optional title override (for save)"
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags e.g. 'business,fundraising' (optional for save)"
                },
                "item_id": {
                    "type": "integer",
                    "description": "Reading list item ID (required for summarize/mark_read)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max items to return for list (default 10)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        # Ensure table exists
        async with _db.async_engine.begin() as conn:
            await conn.run_sync(ReadingItem.__table__.create, checkfirst=True)

        try:
            if action == "save":
                return await self._save(**kwargs)
            elif action == "list":
                return await self._list(**kwargs)
            elif action == "summarize":
                return await self._summarize(**kwargs)
            elif action == "mark_read":
                return await self._mark_read(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Reading list error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _save(self, url: str = None, title: str = None, tags: str = None, **kwargs) -> ToolResult:
        if not url:
            return ToolResult(tool_name=self.name, success=False, error="url is required")

        # Try to extract title from URL hostname if not provided
        if not title:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                title = parsed.hostname or url[:60]
            except Exception:
                title = url[:60]

        async with _db.AsyncSessionLocal() as session:
            item = ReadingItem(url=url, title=title, tags=tags)
            session.add(item)
            await session.commit()
            item_id = item.id

        return ToolResult(tool_name=self.name, success=True,
                          data={"saved": True, "id": item_id, "title": title})

    async def _list(self, limit: int = 10, tags: str = None, **kwargs) -> ToolResult:
        async with _db.AsyncSessionLocal() as session:
            stmt = select(ReadingItem).where(ReadingItem.read == False)  # noqa: E712
            if tags:
                stmt = stmt.where(ReadingItem.tags.ilike(f"%{tags}%"))
            stmt = stmt.order_by(ReadingItem.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            items = result.scalars().all()

        data = []
        for item in items:
            data.append({
                "id": item.id,
                "title": item.title or item.url[:60],
                "url": item.url,
                "tags": item.tags,
                "saved": item.created_at.strftime("%b %d") if item.created_at else "",
            })

        return ToolResult(tool_name=self.name, success=True,
                          data={"items": data, "count": len(data)})

    async def _summarize(self, item_id: int = None, **kwargs) -> ToolResult:
        if not item_id:
            return ToolResult(tool_name=self.name, success=False, error="item_id is required")

        async with _db.AsyncSessionLocal() as session:
            result = await session.execute(
                select(ReadingItem).where(ReadingItem.id == item_id)
            )
            item = result.scalar_one_or_none()

        if not item:
            return ToolResult(tool_name=self.name, success=False,
                              error=f"No reading list item with id {item_id}")

        # If already summarized, return cached
        if item.summary:
            return ToolResult(tool_name=self.name, success=True,
                              data={"title": item.title, "url": item.url, "summary": item.summary})

        # Fetch and summarize via Perplexity
        try:
            from app.tools.perplexity_tool import PerplexityTool
            result = await PerplexityTool().execute(
                action="search",
                query=f"Summarize the key points from this article: {item.url}"
            )
            summary = result.data.get("answer", "Could not summarize") if result.success else "Could not summarize"
        except Exception:
            summary = "Summarization failed — open the link to read it."

        # Cache the summary
        async with _db.AsyncSessionLocal() as session:
            db_item = (await session.execute(
                select(ReadingItem).where(ReadingItem.id == item_id)
            )).scalar_one_or_none()
            if db_item:
                db_item.summary = summary[:1000]
                await session.commit()

        return ToolResult(tool_name=self.name, success=True,
                          data={"title": item.title, "url": item.url, "summary": summary})

    async def _mark_read(self, item_id: int = None, **kwargs) -> ToolResult:
        if not item_id:
            return ToolResult(tool_name=self.name, success=False, error="item_id is required")

        async with _db.AsyncSessionLocal() as session:
            item = (await session.execute(
                select(ReadingItem).where(ReadingItem.id == item_id)
            )).scalar_one_or_none()
            if not item:
                return ToolResult(tool_name=self.name, success=False,
                                  error=f"No item with id {item_id}")
            item.read = True
            await session.commit()

        return ToolResult(tool_name=self.name, success=True, data={"marked_read": item_id})
