"""
Notes Tool — Raunk's second brain with full-text search.
Save, retrieve, search notes with tags.
"""

import logging
from typing import List
from app.tools.base import BaseTool, ToolResult
from app.memory import save_note, search_notes
import app.memory as _db

logger = logging.getLogger(__name__)


class NotesTool(BaseTool):
    """Tool for managing notes and second brain"""

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "notes"

    @property
    def description(self) -> str:
        return """Manage Raunk's second brain. Save, search, and retrieve notes with tags.

Examples:
- "Note: Series A target ₹5Cr, timeline Q3"
- "What did I note about Project Alpha?"
- "Save to notes: meeting with Raj - discussed expansion"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "search"],
                    "description": "Action to perform: 'save' a new note or 'search' existing notes"
                },
                "title": {
                    "type": "string",
                    "description": "Title of the note (required for save, optional for search)"
                },
                "content": {
                    "type": "string",
                    "description": "Content of the note (required for save)"
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (optional for save, e.g., 'investment,timeline')"
                },
                "query": {
                    "type": "string",
                    "description": "Search query to find notes (required for search, e.g., 'Project Alpha' or 'investment')"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """Execute notes operation"""
        try:
            if action == "save":
                return await self._save_note(**kwargs)
            elif action == "search":
                return await self._search_notes(**kwargs)
            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Unknown action: {action}"
                )
        except Exception as e:
            logger.error(f"Notes tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _save_note(self, title: str = None, content: str = None,
                        tags: str = None, **kwargs) -> ToolResult:
        """Save a new note"""
        if not content:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Content is required to save a note"
            )

        # If no title provided, use first 50 chars of content
        if not title:
            title = content[:50] + ("..." if len(content) > 50 else "")

        async with _db.AsyncSessionLocal() as session:
            note = await save_note(session, title, content, tags)

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "status": "saved",
                "note_id": note.id,
                "title": note.title,
                "tags": note.tags or "none"
            }
        )

    async def _search_notes(self, query: str = None, **kwargs) -> ToolResult:
        """Search notes by query"""
        if not query:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Query is required to search notes"
            )

        async with _db.AsyncSessionLocal() as session:
            notes = await search_notes(session, query)

        if not notes:
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "query": query,
                    "results": [],
                    "count": 0,
                    "message": f"No notes found matching '{query}'"
                }
            )

        results = []
        for note in notes[:10]:  # Limit to 10 results
            results.append({
                "id": note.id,
                "title": note.title,
                "content": note.content[:200] + ("..." if len(note.content) > 200 else ""),
                "tags": note.tags or "none",
                "created": note.created_at.isoformat() if note.created_at else None
            })

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "query": query,
                "results": results,
                "count": len(results)
            }
        )
