"""
Contacts Tool — Browse external contacts who messaged NOVA.
List recent contacts or read a specific conversation thread.
"""

import logging
from app.tools.base import BaseTool, ToolResult
from app.memory import (
    get_recent_contacts, search_contact_by_name,
    get_external_thread, AsyncSessionLocal
)

logger = logging.getLogger(__name__)


class ContactsTool(BaseTool):
    """Tool for browsing external contacts and their conversations"""

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "check_contacts"

    @property
    def description(self) -> str:
        return """Check who has messaged NOVA and read their conversations.

Examples:
- "Who messaged me today?" → use action='recent'
- "Who has reached out recently?" → use action='recent'
- "Show me what John said" → use action='thread', name='John'
- "Read conversation with +91XXXXXXXXXX" → use action='thread', phone='+91XXXXXXXXXX'
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["recent", "thread"],
                    "description": "'recent' lists latest contacts, 'thread' reads full conversation with one contact"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of contacts to return for 'recent' action (default 10, max 20)"
                },
                "name": {
                    "type": "string",
                    "description": "Contact name to look up for 'thread' action (partial match supported)"
                },
                "phone": {
                    "type": "string",
                    "description": "Contact phone number in E.164 format for 'thread' action"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "recent":
                return await self._list_recent(**kwargs)
            elif action == "thread":
                return await self._read_thread(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Contacts tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _list_recent(self, limit: int = 10, **kwargs) -> ToolResult:
        limit = min(limit, 20)
        async with AsyncSessionLocal() as session:
            contacts = await get_recent_contacts(session, limit)

        if not contacts:
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={"contacts": [], "count": 0, "message": "No external contacts yet"}
            )

        results = []
        for c in contacts:
            last_active = c.last_seen or c.first_seen
            results.append({
                "name": c.name or "Unknown",
                "phone": c.phone,
                "company": c.company or "—",
                "purpose": c.purpose or "—",
                "vip": c.is_vip,
                "blocked": c.is_blocked,
                "last_active": last_active.strftime("%Y-%m-%d %H:%M UTC") if last_active else "unknown"
            })

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"contacts": results, "count": len(results)}
        )

    async def _read_thread(self, name: str = None, phone: str = None, **kwargs) -> ToolResult:
        if not name and not phone:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Provide either 'name' or 'phone' to read a thread"
            )

        async with AsyncSessionLocal() as session:
            if not phone and name:
                contact = await search_contact_by_name(session, name)
                if not contact:
                    return ToolResult(
                        tool_name=self.name,
                        success=True,
                        data={"message": f"No contact found matching '{name}'"}
                    )
                phone = contact.phone

            messages = await get_external_thread(session, phone)

        if not messages:
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={"phone": phone, "messages": [], "message": "No conversation found for this contact"}
            )

        thread = [
            {
                "role": m.role,
                "content": m.content,
                "time": m.created_at.strftime("%Y-%m-%d %H:%M UTC") if m.created_at else "unknown"
            }
            for m in messages
        ]

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"phone": phone, "messages": thread, "count": len(thread)}
        )
