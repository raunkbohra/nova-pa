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
                    "description": "Namespaced key e.g. 'pref:meetings', 'goal:revenue', 'person:raj' (required for remember/forget)"
                },
                "value": {
                    "type": "string",
                    "description": "The fact to remember, max ~200 chars (required for remember)"
                },
                "pattern": {
                    "type": "string",
                    "description": "Key prefix to search e.g. 'person:' returns all person entries, or full key for exact lookup (required for recall)"
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
                                      data={"results": {}, "count": 0,
                                            "message": f"No memory found for '{pattern}'"})
                return ToolResult(tool_name=self.name, success=True,
                                  data={"results": {pattern: value}, "count": 1})
            else:
                # Prefix search
                from sqlalchemy.sql import select
                from app.memory import NovaContext
                stmt = select(NovaContext).where(
                    NovaContext.key.like(f"{pattern.rstrip(':')}:%")
                )
                result = await session.execute(stmt)
                rows = {row.key: row.value for row in result.scalars().all()}
                return ToolResult(tool_name=self.name, success=True,
                                  data={"results": rows, "count": len(rows)})

    async def _forget(self, key: str = None, **kwargs) -> ToolResult:
        if not key:
            return ToolResult(tool_name=self.name, success=False, error="key is required")
        async with _db.AsyncSessionLocal() as session:
            from sqlalchemy import delete
            from app.memory import NovaContext
            await session.execute(delete(NovaContext).where(NovaContext.key == key))
            await session.commit()
        return ToolResult(tool_name=self.name, success=True, data={"deleted": key})
