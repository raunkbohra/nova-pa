"""
Email Tool — Gmail integration.
Read, search, draft, and send emails.
"""

import logging
from typing import Optional, List
import base64
from email.mime.text import MIMEText
import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

# Google Gmail API endpoint
GMAIL_API_URL = "https://www.googleapis.com/gmail/v1"


class EmailTool(BaseTool):
    """Tool for managing Gmail"""

    def __init__(self, session=None):
        self.session = session
        self._access_token = None

    @property
    def name(self) -> str:
        return "email"

    @property
    def description(self) -> str:
        return """Manage Raunak's Gmail inbox.
Read, search, draft, and send emails.

Examples:
- "Show me my unread emails"
- "Search for emails from Sequoia"
- "What did Raj say in his last email?"
- "Draft a reply to Amit"
- "Send this email: [text]"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "search", "read", "draft", "send", "delete", "triage"],
                    "description": "Action: 'list' emails, 'search' by query, 'read' a specific email, 'draft' a new message, 'send' an email, 'delete' an email, or 'triage' to prioritize inbox"
                },
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'from:raj@example.com', 'subject:meeting', 'is:unread')"
                },
                "email_id": {
                    "type": "string",
                    "description": "Email ID to read (required for read action)"
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email address (required for draft/send)"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject (required for draft/send)"
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (required for draft/send)"
                },
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID to reply to (optional for draft/send)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of emails to return (default 10)"
                },
                "permanent": {
                    "type": "boolean",
                    "description": "For delete action: if true, permanently deletes (unrecoverable). Default false moves to Trash."
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """Execute email operation"""
        try:
            # Ensure we have an access token
            if not await self._ensure_token():
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error="Could not authenticate with Gmail API"
                )
            
            if action == "list":
                return await self._list_emails(**kwargs)
            elif action == "search":
                return await self._search_emails(**kwargs)
            elif action == "read":
                return await self._read_email(**kwargs)
            elif action == "draft":
                return await self._draft_email(**kwargs)
            elif action == "send":
                return await self._send_email(**kwargs)
            elif action == "delete":
                return await self._delete_email(**kwargs)
            elif action == "triage":
                return await self._triage_inbox(**kwargs)
            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Unknown action: {action}"
                )
        except Exception as e:
            logger.error(f"Email tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _ensure_token(self) -> bool:
        """Load and refresh Google OAuth token from file"""
        try:
            import json
            import os
            token_file = settings.google_token_file
            if not os.path.exists(token_file):
                logger.error(f"Google token file not found: {token_file}")
                return False

            with open(token_file) as f:
                token_data = json.load(f)

            creds = Credentials.from_authorized_user_info(token_data)

            if not creds.valid and creds.refresh_token:
                import asyncio
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, creds.refresh, Request())
                updated = json.loads(creds.to_json())
                with open(token_file, "w") as f:
                    json.dump(updated, f)

            self._access_token = creds.token
            return True
        except Exception as e:
            logger.error(f"Failed to load Google token: {e}")
            return False

    async def _list_emails(self, limit: int = 10, **kwargs) -> ToolResult:
        """List recent emails from inbox"""
        try:
            params = {
                "q": "in:inbox",
                "maxResults": min(limit, 10)
            }
            
            result = await self._call_api("GET", "/users/me/messages", params=params)
            
            if not result.get("messages"):
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={
                        "emails": [],
                        "count": 0
                    }
                )
            
            emails = []
            for msg in result["messages"][:limit]:
                email_data = await self._get_message_preview(msg["id"])
                if email_data:
                    emails.append(email_data)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "emails": emails,
                    "count": len(emails)
                }
            )
        except Exception as e:
            logger.error(f"Failed to list emails: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _search_emails(self, query: str = None, limit: int = 10, **kwargs) -> ToolResult:
        """Search emails by query"""
        if not query:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Query is required to search emails"
            )
        
        try:
            params = {
                "q": query,
                "maxResults": min(limit, 10)
            }
            
            result = await self._call_api("GET", "/users/me/messages", params=params)
            
            if not result.get("messages"):
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={
                        "query": query,
                        "emails": [],
                        "count": 0
                    }
                )
            
            emails = []
            for msg in result["messages"][:limit]:
                email_data = await self._get_message_preview(msg["id"])
                if email_data:
                    emails.append(email_data)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "query": query,
                    "emails": emails,
                    "count": len(emails)
                }
            )
        except Exception as e:
            logger.error(f"Failed to search emails: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _read_email(self, email_id: str = None, **kwargs) -> ToolResult:
        """Read full email content"""
        if not email_id:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Email ID is required"
            )
        
        try:
            msg = await self._call_api("GET", f"/users/me/messages/{email_id}")
            
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            
            body_text = ""
            if "parts" in msg["payload"]:
                for part in msg["payload"]["parts"]:
                    if part.get("mimeType") == "text/plain":
                        data = part.get("body", {}).get("data")
                        if data:
                            body_text = base64.urlsafe_b64decode(data).decode("utf-8")
                            break
            else:
                data = msg["payload"].get("body", {}).get("data")
                if data:
                    body_text = base64.urlsafe_b64decode(data).decode("utf-8")
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "email_id": email_id,
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "body": body_text[:1000],  # First 1000 chars
                    "thread_id": msg.get("threadId")
                }
            )
        except Exception as e:
            logger.error(f"Failed to read email: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _draft_email(self, to: str = None, subject: str = None,
                          body: str = None, thread_id: str = None, **kwargs) -> ToolResult:
        """Create a draft email"""
        if not to:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="To address is required"
            )
        
        if not subject:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Subject is required"
            )
        
        if not body:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Body is required"
            )
        
        try:
            # Create MIME message
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            
            draft_body = {
                "message": {
                    "raw": raw_message
                }
            }
            
            if thread_id:
                draft_body["message"]["threadId"] = thread_id
            
            result = await self._call_api("POST", "/users/me/drafts", json=draft_body)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "drafted",
                    "draft_id": result.get("id"),
                    "to": to,
                    "subject": subject,
                    "preview": body[:100]
                }
            )
        except Exception as e:
            logger.error(f"Failed to draft email: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _send_email(self, to: str = None, subject: str = None,
                         body: str = None, thread_id: str = None, **kwargs) -> ToolResult:
        """Send an email"""
        if not to:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="To address is required"
            )
        
        if not subject:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Subject is required"
            )
        
        if not body:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Body is required"
            )
        
        try:
            # Create MIME message
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            
            send_body = {
                "raw": raw_message
            }
            
            if thread_id:
                send_body["threadId"] = thread_id
            
            result = await self._call_api("POST", "/users/me/messages/send", json=send_body)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "sent",
                    "message_id": result.get("id"),
                    "to": to,
                    "subject": subject
                }
            )
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _delete_email(self, email_id: str = None, permanent: bool = False, **kwargs) -> ToolResult:
        """Move email to trash or permanently delete it"""
        if not email_id:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="email_id is required to delete an email"
            )

        try:
            if permanent:
                await self._call_api("DELETE", f"/users/me/messages/{email_id}")
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={"status": "permanently deleted", "email_id": email_id}
                )
            else:
                await self._call_api("POST", f"/users/me/messages/{email_id}/trash")
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={"status": "moved to trash", "email_id": email_id}
                )
        except Exception as e:
            logger.error(f"Failed to delete email: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _get_message_preview(self, message_id: str) -> Optional[dict]:
        """Get preview of a message"""
        try:
            msg = await self._call_api("GET", f"/users/me/messages/{message_id}", params={"format": "metadata"})
            
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            
            return {
                "email_id": message_id,
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
                "thread_id": msg.get("threadId")
            }
        except Exception as e:
            logger.error(f"Failed to get message preview: {e}")
            return None

    async def _triage_inbox(self, limit: int = 20, **kwargs) -> ToolResult:
        """Fetch unread emails and score/sort by priority"""
        try:
            params = {"q": "is:unread in:inbox", "maxResults": min(limit, 20)}
            result = await self._call_api("GET", "/users/me/messages", params=params)

            if not result.get("messages"):
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={"emails": [], "count": 0, "summary": "Inbox is clear."}
                )

            # Keywords that bump priority
            URGENT_SENDERS = ["sequoia", "matrix", "accel", "investor", "vc", "fund",
                               "partner", "founder", "ceo", "cto", "md@", "gp@"]
            URGENT_SUBJECTS = ["investment", "term sheet", "funding", "offer", "urgent",
                                "contract", "deal", "closing", "revenue", "partnership"]
            LOW_SENDERS = ["noreply", "no-reply", "newsletter", "notifications@",
                           "mailer", "donotreply", "digest", "alerts@", "support@"]
            LOW_SUBJECTS = ["unsubscribe", "newsletter", "weekly digest", "monthly update",
                             "promotion", "sale", "offer", "% off", "coupon"]

            def _score(from_addr: str, subject: str) -> tuple[int, str]:
                f = from_addr.lower()
                s = subject.lower()
                if any(k in f for k in URGENT_SENDERS) or any(k in s for k in URGENT_SUBJECTS):
                    return 3, "🔴 Urgent"
                if any(k in f for k in LOW_SENDERS) or any(k in s for k in LOW_SUBJECTS):
                    return 1, "⚪ Low"
                return 2, "🟡 Normal"

            emails = []
            for msg in result["messages"]:
                preview = await self._get_message_preview(msg["id"])
                if not preview:
                    continue
                score, label = _score(preview.get("from", ""), preview.get("subject", ""))
                preview["priority"] = label
                preview["_score"] = score
                emails.append(preview)

            emails.sort(key=lambda e: e["_score"], reverse=True)
            for e in emails:
                del e["_score"]

            urgent = sum(1 for e in emails if "Urgent" in e["priority"])
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "emails": emails,
                    "count": len(emails),
                    "urgent_count": urgent,
                    "summary": f"{len(emails)} unread — {urgent} urgent"
                }
            )
        except Exception as e:
            logger.error(f"Failed to triage inbox: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))

    async def _call_api(self, method: str, path: str, params=None, json=None):
        """Call Gmail API with OAuth token"""
        url = f"{GMAIL_API_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=15.0
            )
            if response.status_code == 204:
                return {}
            response.raise_for_status()
            return response.json()
