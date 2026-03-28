"""
Google Tasks Tool — Manage Raunk's Google Tasks lists.
Uses existing Google OAuth token (tasks scope).
"""

import logging
import json
import os
from typing import Optional
from datetime import datetime
from pytz import timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import httpx
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

TASKS_API = "https://tasks.googleapis.com/tasks/v1"
NPT = timezone('Asia/Kathmandu')


class TasksTool(BaseTool):

    def __init__(self):
        self._access_token: Optional[str] = None

    @property
    def name(self) -> str:
        return "tasks"

    @property
    def description(self) -> str:
        return """Manage Raunk's Google Tasks — list, add, and complete tasks.

Actions:
- list: Show all pending tasks (optionally from a specific list)
- add: Add a new task with optional due date
- complete: Mark a task as done

Examples:
- "Show my tasks" → list()
- "Add task: follow up with Raj" → add(title="Follow up with Raj")
- "Add task due tomorrow: prepare pitch deck" → add(title="Prepare pitch deck", due="tomorrow")
- "Done with the Raj task" → complete(task_id="...")
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "complete"],
                    "description": "'list' shows tasks, 'add' creates a task, 'complete' marks done"
                },
                "title": {
                    "type": "string",
                    "description": "Task title (required for add)"
                },
                "due": {
                    "type": "string",
                    "description": "Due date: 'today', 'tomorrow', 'YYYY-MM-DD' (optional for add)"
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID to complete (required for complete)"
                },
                "list_id": {
                    "type": "string",
                    "description": "Task list ID (defaults to primary @default list)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        if not await self._load_token():
            return ToolResult(tool_name=self.name, success=False,
                              error="Google auth failed — token missing or expired")
        try:
            if action == "list":
                return await self._list_tasks(**kwargs)
            elif action == "add":
                return await self._add_task(**kwargs)
            elif action == "complete":
                return await self._complete_task(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Tasks tool error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _load_token(self) -> bool:
        try:
            token_file = settings.google_token_file
            if not os.path.exists(token_file):
                return False
            with open(token_file) as f:
                token_data = json.load(f)
            creds = Credentials.from_authorized_user_info(token_data)
            if not creds.valid and creds.refresh_token:
                import asyncio
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, creds.refresh, Request())
                with open(token_file, "w") as f:
                    json.dump(json.loads(creds.to_json()), f)
            self._access_token = creds.token
            return bool(self._access_token)
        except Exception as e:
            logger.error(f"Tasks token load failed: {e}")
            return False

    async def _api(self, method: str, path: str, params=None, json_body=None) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{TASKS_API}{path}",
                                        headers=headers, params=params,
                                        json=json_body, timeout=15.0)
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()

    async def _list_tasks(self, list_id: str = "@default", **kwargs) -> ToolResult:
        data = await self._api("GET", f"/lists/{list_id}/tasks", params={
            "showCompleted": False,
            "showHidden": False,
            "maxResults": 20,
        })
        items = data.get("items", [])

        tasks = []
        for t in items:
            due = t.get("due", "")[:10] if t.get("due") else None
            tasks.append({
                "id": t["id"],
                "title": t.get("title", ""),
                "due": due,
                "notes": t.get("notes", ""),
                "status": t.get("status", ""),
            })

        return ToolResult(tool_name=self.name, success=True,
                          data={"tasks": tasks, "count": len(tasks)})

    async def _add_task(self, title: str = None, due: str = None,
                        list_id: str = "@default", **kwargs) -> ToolResult:
        if not title:
            return ToolResult(tool_name=self.name, success=False, error="title is required")

        body = {"title": title}

        if due:
            from datetime import date, timedelta
            today = datetime.now(NPT).date()
            if due.lower() == "today":
                d = today
            elif due.lower() == "tomorrow":
                d = today + timedelta(days=1)
            else:
                try:
                    d = date.fromisoformat(due)
                except ValueError:
                    d = today
            # Google Tasks uses RFC3339 with midnight UTC for due dates
            body["due"] = f"{d.isoformat()}T00:00:00.000Z"

        data = await self._api("POST", f"/lists/{list_id}/tasks", json_body=body)
        return ToolResult(tool_name=self.name, success=True,
                          data={"created": data.get("title"), "id": data.get("id"),
                                "due": data.get("due", "")[:10] if data.get("due") else None})

    async def _complete_task(self, task_id: str = None, list_id: str = "@default", **kwargs) -> ToolResult:
        if not task_id:
            return ToolResult(tool_name=self.name, success=False, error="task_id is required")
        await self._api("PATCH", f"/lists/{list_id}/tasks/{task_id}",
                        json_body={"status": "completed"})
        return ToolResult(tool_name=self.name, success=True, data={"completed": task_id})
