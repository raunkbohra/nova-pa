"""
WhatsApp Tool — Send messages to any WhatsApp number.
Allows NOVA to message Raunk's contacts on his behalf.
"""

import logging
import re
from app.tools.base import BaseTool, ToolResult
from app.whatsapp import send_text

logger = logging.getLogger(__name__)


class WhatsAppTool(BaseTool):
    """Tool for sending WhatsApp messages to contacts"""

    @property
    def name(self) -> str:
        return "send_whatsapp"

    @property
    def description(self) -> str:
        return """Send a WhatsApp message to any phone number on Raunk's behalf.

Examples:
- "Send Rinni a message saying I love her" (with phone +9779823377223)
- "Message Raj that the meeting is postponed" (with phone +91XXXXXXXXXX)
- "Tell my wife I'll be 30 min late"

Note: Only works if the recipient has WhatsApp and has messaged this number before,
OR for the first message, send a template-style short greeting.
        """

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "Recipient phone number in E.164 format (e.g. +9779823377223 or +919XXXXXXXXX)"
                },
                "message": {
                    "type": "string",
                    "description": "Message text to send"
                }
            },
            "required": ["phone", "message"]
        }

    async def execute(self, phone: str, message: str, **kwargs) -> ToolResult:
        """Send a WhatsApp message to the given number"""
        # Normalize phone — strip spaces, ensure + prefix
        phone = phone.strip().replace(" ", "")
        if not phone.startswith("+"):
            phone = "+" + phone

        if not re.match(r"^\+\d{7,15}$", phone):
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Invalid phone number format: {phone}. Use E.164 format like +9779823377223"
            )

        success = await send_text(phone, message)

        if success:
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "status": "sent",
                    "to": phone,
                    "preview": message[:100]
                }
            )
        else:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to send message to {phone}. The recipient may need to message NOVA first to open a conversation window."
            )
