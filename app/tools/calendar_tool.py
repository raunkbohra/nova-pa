"""
Calendar Tool — Google Calendar integration.
Schedule, reschedule, cancel, and find free slots.
"""

import logging
from datetime import datetime, timedelta, time
from typing import Optional, List
from pytz import timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import httpx
from app.tools.base import BaseTool, ToolResult
from app.config import settings

logger = logging.getLogger(__name__)

IST = timezone('Asia/Kolkata')

# Google Calendar API endpoints
CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3"


class CalendarTool(BaseTool):
    """Tool for managing Google Calendar"""

    def __init__(self, session = None):
        self.session = session
        self._access_token = None

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return """Manage Raunak's Google Calendar.
Schedule, reschedule, cancel events, find free slots, list events.

Examples:
- "Schedule Raj for 30 min this Friday at 3pm"
- "What's free this week for 2 hours?"
- "Cancel my 2pm meeting today"
- "What's on my calendar today?"
- "Reschedule Raj's meeting to Monday at 10am"
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "cancel", "find_free", "get"],
                    "description": "Action: 'list' events, 'create' event, 'cancel' event, 'find_free' slots, or 'get' event details"
                },
                "start": {
                    "type": "string",
                    "description": "Event start time (ISO format or natural language, e.g., 'Friday 3pm', 'tomorrow at 10am')"
                },
                "end": {
                    "type": "string",
                    "description": "Event end time (ISO format or natural language)"
                },
                "title": {
                    "type": "string",
                    "description": "Event title (required for create)"
                },
                "description": {
                    "type": "string",
                    "description": "Event description (optional)"
                },
                "attendees": {
                    "type": "string",
                    "description": "Comma-separated email addresses of attendees (optional)"
                },
                "event_id": {
                    "type": "string",
                    "description": "Event ID to cancel or get (required for cancel/get)"
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration in minutes to find free slots for (required for find_free, default 30)"
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range to search (e.g., 'this week', 'next 7 days', default 'today')"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """Execute calendar operation"""
        try:
            # Ensure we have an access token
            if not await self._ensure_token():
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error="Could not authenticate with Google Calendar API"
                )
            
            if action == "list":
                return await self._list_events(**kwargs)
            elif action == "create":
                return await self._create_event(**kwargs)
            elif action == "cancel":
                return await self._cancel_event(**kwargs)
            elif action == "find_free":
                return await self._find_free_slots(**kwargs)
            elif action == "get":
                return await self._get_event(**kwargs)
            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Unknown action: {action}"
                )
        except Exception as e:
            logger.error(f"Calendar tool error: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _ensure_token(self) -> bool:
        """Ensure we have a valid Google API token"""
        # TODO: Load token from file and refresh if needed
        # For now, assume token is stored and available
        return True

    async def _list_events(self, time_range: str = "today", **kwargs) -> ToolResult:
        """List events in a time range"""
        try:
            start_dt, end_dt = self._parse_time_range(time_range)
            
            params = {
                "calendarId": "primary",
                "timeMin": start_dt.isoformat(),
                "timeMax": end_dt.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 10
            }
            
            events = await self._call_api("GET", "/events", params=params)
            
            if not events.get("items"):
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={
                        "time_range": time_range,
                        "events": [],
                        "count": 0
                    }
                )
            
            result_events = []
            for event in events["items"]:
                start = event["start"].get("dateTime") or event["start"].get("date")
                end = event["end"].get("dateTime") or event["end"].get("date")
                
                result_events.append({
                    "id": event["id"],
                    "title": event.get("summary", "No title"),
                    "start": start,
                    "end": end,
                    "description": event.get("description", "")
                })
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "time_range": time_range,
                    "events": result_events,
                    "count": len(result_events)
                }
            )
        except Exception as e:
            logger.error(f"Failed to list events: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _create_event(self, title: str = None, start: str = None,
                           end: str = None, description: str = None,
                           attendees: str = None, **kwargs) -> ToolResult:
        """Create a new calendar event"""
        if not title:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Title is required to create an event"
            )
        
        if not start:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Start time is required"
            )
        
        try:
            start_dt = self._parse_time(start)
            
            # Default end to 30 min after start if not specified
            if end:
                end_dt = self._parse_time(end)
            else:
                end_dt = start_dt + timedelta(minutes=30)
            
            event_body = {
                "summary": title,
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "Asia/Kolkata"
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "Asia/Kolkata"
                }
            }
            
            if description:
                event_body["description"] = description
            
            if attendees:
                attendee_list = [{"email": email.strip()} for email in attendees.split(",")]
                event_body["attendees"] = attendee_list
            
            result = await self._call_api("POST", "/events", json=event_body)
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "created",
                    "event_id": result.get("id"),
                    "title": title,
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "link": result.get("htmlLink")
                }
            )
        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _cancel_event(self, event_id: str = None, **kwargs) -> ToolResult:
        """Cancel (delete) an event"""
        if not event_id:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Event ID is required to cancel"
            )
        
        try:
            await self._call_api("DELETE", f"/events/{event_id}")
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "cancelled",
                    "event_id": event_id
                }
            )
        except Exception as e:
            logger.error(f"Failed to cancel event: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _find_free_slots(self, duration_minutes: int = 30,
                               time_range: str = "today", **kwargs) -> ToolResult:
        """Find free time slots in calendar"""
        try:
            start_dt, end_dt = self._parse_time_range(time_range)
            
            params = {
                "calendarId": "primary",
                "timeMin": start_dt.isoformat(),
                "timeMax": end_dt.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime"
            }
            
            events = await self._call_api("GET", "/events", params=params)
            
            # Build list of free slots
            free_slots = []
            current_time = start_dt
            
            for event in events.get("items", []):
                event_start = datetime.fromisoformat(
                    event["start"].get("dateTime") or event["start"].get("date")
                )
                event_end = datetime.fromisoformat(
                    event["end"].get("dateTime") or event["end"].get("date")
                )
                
                # Gap before event
                if (event_start - current_time).total_seconds() / 60 >= duration_minutes:
                    free_slots.append({
                        "start": current_time.isoformat(),
                        "end": event_start.isoformat(),
                        "duration_minutes": int((event_start - current_time).total_seconds() / 60)
                    })
                
                current_time = max(current_time, event_end)
            
            # Check for gap after last event
            if (end_dt - current_time).total_seconds() / 60 >= duration_minutes:
                free_slots.append({
                    "start": current_time.isoformat(),
                    "end": end_dt.isoformat(),
                    "duration_minutes": int((end_dt - current_time).total_seconds() / 60)
                })
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "time_range": time_range,
                    "duration_minutes": duration_minutes,
                    "free_slots": free_slots[:5],  # Return top 5
                    "count": len(free_slots)
                }
            )
        except Exception as e:
            logger.error(f"Failed to find free slots: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _get_event(self, event_id: str = None, **kwargs) -> ToolResult:
        """Get details of a specific event"""
        if not event_id:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Event ID is required"
            )
        
        try:
            event = await self._call_api("GET", f"/events/{event_id}")
            
            start = event["start"].get("dateTime") or event["start"].get("date")
            end = event["end"].get("dateTime") or event["end"].get("date")
            
            attendees = []
            for att in event.get("attendees", []):
                attendees.append({
                    "email": att.get("email"),
                    "response": att.get("responseStatus", "needsAction")
                })
            
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "id": event["id"],
                    "title": event.get("summary"),
                    "start": start,
                    "end": end,
                    "description": event.get("description", ""),
                    "attendees": attendees,
                    "link": event.get("htmlLink")
                }
            )
        except Exception as e:
            logger.error(f"Failed to get event: {e}")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(e)
            )

    async def _call_api(self, method: str, path: str, params=None, json=None):
        """Call Google Calendar API"""
        # TODO: Implement actual API call with auth
        # For now, return mock data
        logger.warning("Calendar API call not implemented - returning mock data")
        return {"items": []}

    def _parse_time(self, time_str: str) -> datetime:
        """Parse natural language time string to datetime"""
        time_lower = time_str.lower().strip()
        now = datetime.now(IST)
        
        # "HH:MM am/pm" or "Hpm/am"
        if "am" in time_lower or "pm" in time_lower:
            try:
                time_obj = datetime.strptime(time_lower.replace("am", "").replace("pm", "").strip(), "%I:%M" if ":" in time_lower else "%I")
                if "pm" in time_lower and time_obj.hour < 12:
                    time_obj = time_obj.replace(hour=time_obj.hour + 12)
                return now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
            except:
                pass
        
        # ISO format
        try:
            return datetime.fromisoformat(time_str).astimezone(IST)
        except:
            pass
        
        # Default to now + 1 hour
        return now + timedelta(hours=1)

    def _parse_time_range(self, time_range: str) -> tuple:
        """Parse time range string to (start, end) datetimes"""
        time_range_lower = time_range.lower().strip()
        now = datetime.now(IST)
        
        if time_range_lower == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif time_range_lower in ["this week", "week"]:
            # Monday of current week
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif time_range_lower in ["next 7 days", "7 days"]:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif time_range_lower in ["next 30 days", "30 days", "month"]:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=30)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        
        return start, end
