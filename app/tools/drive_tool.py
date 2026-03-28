"""
Google Drive Tool — Search files, read Docs, and read Sheets.
Uses existing Google OAuth token (drive/documents/spreadsheets scopes).
"""

import logging
import json
import os
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import httpx
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

DRIVE_API = "https://www.googleapis.com/drive/v3"
DOCS_API = "https://docs.googleapis.com/v1"
SHEETS_API = "https://sheets.googleapis.com/v4"


class DriveTool(BaseTool):

    def __init__(self):
        self._access_token: Optional[str] = None

    @property
    def name(self) -> str:
        return "drive"

    @property
    def description(self) -> str:
        return """Access Raunk's Google Drive — search files, read Docs, read Sheets.

Actions:
- search: Find files by name or content query
- read_doc: Read a Google Doc by ID or URL
- read_sheet: Read a Google Sheet (returns first sheet rows)

Examples:
- "Find the iwishbag pitch deck" → search(query="iwishbag pitch deck")
- "Read that investor doc" → search then read_doc
- "Show me the sales spreadsheet" → search then read_sheet
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "read_doc", "read_sheet"],
                    "description": "'search' finds files, 'read_doc' reads a Google Doc, 'read_sheet' reads a Sheet"
                },
                "query": {
                    "type": "string",
                    "description": "Search query for finding files (required for search)"
                },
                "file_id": {
                    "type": "string",
                    "description": "Google Drive file ID or full URL (required for read_doc/read_sheet)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max files to return for search (default 5)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        if not await self._load_token():
            return ToolResult(tool_name=self.name, success=False,
                              error="Google auth failed — token missing or expired")
        try:
            if action == "search":
                return await self._search(**kwargs)
            elif action == "read_doc":
                return await self._read_doc(**kwargs)
            elif action == "read_sheet":
                return await self._read_sheet(**kwargs)
            else:
                return ToolResult(tool_name=self.name, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error(f"Drive tool error: {e}")
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
            logger.error(f"Drive token load failed: {e}")
            return False

    async def _api(self, method: str, url: str, params=None, json_body=None) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers=headers,
                                        params=params, json=json_body, timeout=20.0)
            resp.raise_for_status()
            return resp.json()

    async def _search(self, query: str = None, limit: int = 5, **kwargs) -> ToolResult:
        if not query:
            return ToolResult(tool_name=self.name, success=False, error="query is required")

        params = {
            "q": f"fullText contains '{query}' or name contains '{query}'",
            "pageSize": min(limit, 10),
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
            "orderBy": "modifiedTime desc",
        }
        data = await self._api("GET", f"{DRIVE_API}/files", params=params)
        files = data.get("files", [])

        results = []
        for f in files:
            mime = f.get("mimeType", "")
            kind = "Doc" if "document" in mime else "Sheet" if "spreadsheet" in mime else "File"
            results.append({
                "id": f["id"],
                "name": f["name"],
                "type": kind,
                "modified": f.get("modifiedTime", "")[:10],
                "url": f.get("webViewLink", ""),
            })

        return ToolResult(tool_name=self.name, success=True,
                          data={"files": results, "count": len(results)})

    async def _read_doc(self, file_id: str = None, **kwargs) -> ToolResult:
        if not file_id:
            return ToolResult(tool_name=self.name, success=False, error="file_id is required")

        # Strip URL to just the ID if a full URL was passed
        if "docs.google.com" in file_id or "drive.google.com" in file_id:
            import re
            match = re.search(r"/d/([a-zA-Z0-9_-]+)", file_id)
            if match:
                file_id = match.group(1)

        data = await self._api("GET", f"{DOCS_API}/documents/{file_id}")
        title = data.get("title", "Untitled")

        # Extract plain text from the document body
        text_parts = []
        for element in data.get("body", {}).get("content", []):
            para = element.get("paragraph")
            if not para:
                continue
            line = ""
            for el in para.get("elements", []):
                text_run = el.get("textRun")
                if text_run:
                    line += text_run.get("content", "")
            if line.strip():
                text_parts.append(line.rstrip("\n"))

        text = "\n".join(text_parts)
        # Truncate to ~4000 chars to keep context manageable
        if len(text) > 4000:
            text = text[:4000] + "\n\n[... truncated, document continues ...]"

        return ToolResult(tool_name=self.name, success=True,
                          data={"title": title, "content": text, "file_id": file_id})

    async def _read_sheet(self, file_id: str = None, **kwargs) -> ToolResult:
        if not file_id:
            return ToolResult(tool_name=self.name, success=False, error="file_id is required")

        if "spreadsheets.google.com" in file_id or "drive.google.com" in file_id:
            import re
            match = re.search(r"/d/([a-zA-Z0-9_-]+)", file_id)
            if match:
                file_id = match.group(1)

        # Get sheet metadata to find first sheet name
        meta = await self._api("GET", f"{SHEETS_API}/spreadsheets/{file_id}",
                                params={"fields": "properties,sheets.properties"})
        title = meta.get("properties", {}).get("title", "Untitled")
        sheets = meta.get("sheets", [])
        sheet_name = sheets[0]["properties"]["title"] if sheets else "Sheet1"

        # Read first 50 rows
        data = await self._api("GET",
                                f"{SHEETS_API}/spreadsheets/{file_id}/values/{sheet_name}!A1:Z50")
        rows = data.get("values", [])

        return ToolResult(tool_name=self.name, success=True,
                          data={"title": title, "sheet": sheet_name,
                                "rows": rows, "row_count": len(rows)})
