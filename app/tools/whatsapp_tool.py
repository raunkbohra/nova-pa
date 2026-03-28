"""
WhatsApp Tool — Send messages to any WhatsApp number.
Allows NOVA to message Raunk's contacts on his behalf.
Supports immediate send and scheduled (future) delivery.
"""

import logging
import re
import uuid
from app.tools.base import BaseTool, ToolResult
from app.whatsapp import send_text, send_template

logger = logging.getLogger(__name__)


async def _fire_scheduled_whatsapp(phone: str, message: str, job_id: str):
    """Module-level function required by APScheduler job store for scheduled delivery."""
    try:
        success, error_code = await send_text(phone, message)
        if not success and error_code == 131047:
            logger.info(f"24hr window expired for {phone}, falling back to template")
            await send_template(phone, message)
        elif not success:
            logger.error(f"Scheduled WhatsApp failed {job_id}: error_code={error_code}")
        else:
            logger.info(f"Scheduled WhatsApp fired: {job_id} → {phone}")
    except Exception as e:
        logger.error(f"Scheduled WhatsApp failed {job_id}: {e}")


class WhatsAppTool(BaseTool):
    """Tool for sending WhatsApp messages to contacts"""

    @property
    def name(self) -> str:
        return "send_whatsapp"

    @property
    def description(self) -> str:
        return """Send or schedule a WhatsApp message to any number on Raunk's behalf.

Actions:
- send (default): Send immediately (auto-falls back to template if 24hr window expired)
- schedule: Send at a future time
- template: Send an approved template directly, bypassing the 24hr window

Available templates:
- nova_intro: Introduce NOVA to someone new
- ping_contact: Generic ping / check-in
- followup_contact: Follow up on a previous conversation
- request_meeting: Request a meeting or call
- intro_contact: Cold outreach / first contact
- remind_meeting: Remind about an upcoming meeting
- confirm_meeting: Confirm a booked meeting
- after_meeting: Post-meeting follow-up
- catch_up: Reconnect with someone
- not_available: Politely decline / unavailable
- iwishbag_customer: iwishbag customer follow-up

Examples:
- "Message Raj the meeting is postponed" → send(phone="+91...", message="...")
- "Schedule a WA to Raj at 3pm saying call me" → schedule(phone="+91...", message="...", when="3pm")
- "Send nova_intro template to Dipu +1510..." → template(phone="+1510...", message="...", template_name="nova_intro", contact_name="Dipu")
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send", "schedule", "template"],
                    "description": "'send' delivers immediately (default), 'schedule' queues for future, 'template' sends an approved WhatsApp template directly (bypasses 24hr window)"
                },
                "phone": {
                    "type": "string",
                    "description": "Recipient phone in E.164 format (e.g. +9779823377223)"
                },
                "message": {
                    "type": "string",
                    "description": "Message text to send"
                },
                "when": {
                    "type": "string",
                    "description": "When to send (required for schedule): '3pm', 'tomorrow 9am', '2026-04-01 10:00'"
                },
                "contact_name": {
                    "type": "string",
                    "description": "Recipient's first name (used to personalise template messages)"
                },
                "template_name": {
                    "type": "string",
                    "enum": ["ping_contact", "followup_contact", "request_meeting", "nova_intro",
                             "remind_meeting", "confirm_meeting", "intro_contact", "after_meeting",
                             "not_available", "catch_up", "iwishbag_customer"],
                    "description": "Template to use (required for template action). Use nova_intro to introduce NOVA, ping_contact for generic ping, etc."
                }
            },
            "required": ["phone", "message"]
        }

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        phone = phone.strip().replace(" ", "")
        if not phone.startswith("+"):
            phone = "+" + phone
        return phone

    async def execute(self, phone: str, message: str, action: str = "send",
                      contact_name: str = "there", template_name: str = None, **kwargs) -> ToolResult:
        phone = self._normalize_phone(phone)
        if not re.match(r"^\+\d{7,15}$", phone):
            return ToolResult(tool_name=self.name, success=False,
                              error=f"Invalid phone: {phone}. Use E.164 like +9779823377223")

        if action == "schedule":
            return await self._schedule_message(phone, message, **kwargs)

        # Direct template send — skip free-form entirely
        if action == "template":
            ok = await send_template(phone, message, contact_name=contact_name,
                                     template_name=template_name)
            if ok:
                return ToolResult(tool_name=self.name, success=True, data={
                    "status": "sent_via_template",
                    "template": template_name or "auto-selected",
                    "to": phone,
                    "preview": message[:100],
                })
            return ToolResult(tool_name=self.name, success=False,
                              error=f"Template send failed to {phone}. Check template approval status.")

        # Immediate send — try free-form first (registers msg_id for webhook fallback)
        success, error_code = await send_text(phone, message, contact_name=contact_name)
        if success:
            return ToolResult(tool_name=self.name, success=True,
                              data={"status": "sent", "to": phone, "preview": message[:100]})

        # 24-hour window expired → fall back to approved template
        if error_code == 131047:
            logger.info(f"24hr window expired for {phone}, trying template fallback")
            template_ok = await send_template(phone, message, contact_name=contact_name)
            if template_ok:
                return ToolResult(tool_name=self.name, success=True, data={
                    "status": "sent_via_template",
                    "note": "24hr window expired — sent as approved template instead",
                    "to": phone,
                    "preview": message[:100],
                })
            return ToolResult(tool_name=self.name, success=False,
                              error=f"24hr window expired and template send also failed for {phone}.")

        return ToolResult(tool_name=self.name, success=False,
                          error=f"Failed to send to {phone} (error {error_code}). Recipient may need to message NOVA first.")

    async def _schedule_message(self, phone: str, message: str, when: str = None, **kwargs) -> ToolResult:
        if not when:
            return ToolResult(tool_name=self.name, success=False,
                              error="'when' is required for schedule action")
        try:
            from app.tools.reminder_tool import get_scheduler, ReminderTool
            from apscheduler.triggers.date import DateTrigger

            # Reuse ReminderTool's time parser
            trigger, run_time = ReminderTool()._parse_when(when)
            if not isinstance(trigger, DateTrigger):
                # For recurring patterns, use the next run time only
                from apscheduler.triggers.date import DateTrigger as DT
                trigger = DT(run_date=run_time)

            job_id = f"wa_sched_{uuid.uuid4().hex[:8]}"
            scheduler = get_scheduler()
            scheduler.add_job(
                _fire_scheduled_whatsapp,
                trigger=trigger,
                args=[phone, message, job_id],
                id=job_id,
                replace_existing=False,
            )
            return ToolResult(tool_name=self.name, success=True, data={
                "status": "scheduled",
                "to": phone,
                "send_at": run_time.strftime("%Y-%m-%d %H:%M NPT"),
                "preview": message[:100],
            })
        except Exception as e:
            logger.error(f"Schedule WhatsApp error: {e}")
            return ToolResult(tool_name=self.name, success=False, error=str(e))
