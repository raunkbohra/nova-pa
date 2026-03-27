"""
Claude Opus 4.6 Agentic Loop with Adaptive Thinking.
Handles message processing, tool calls, and conversation management.
"""

import logging
import re
from typing import Optional, List
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.memory import (
    save_message, get_messages, get_context, set_context,
    save_external_message, get_external_thread
)
from app.tools import get_claude_tools, get_tool

logger = logging.getLogger(__name__)

# Initialize Anthropic async client
client = AsyncAnthropic(api_key=settings.anthropic_api_key)

# Maximum iterations to prevent infinite loops
MAX_ITERATIONS = 10

# System prompt for Commander Mode
COMMANDER_SYSTEM = """You are NOVA, Raunk Bohra's executive assistant.

Your role: Help Raunk manage his work efficiently. You have access to his calendar, email, notes, reminders, and can research topics via web search.

Personality:
- Direct, efficient, zero fluff
- Smart about what matters to Raunk
- Proactive with suggestions when relevant
- Honest about what you can and can't do

Commands you understand:
- "What's on today?" → Calendar summary
- "Brief me on my 3pm" → Meeting details + research on attendees
- "Save a note: [content]" → Add to second brain with optional tags
- "Search my notes: [query]" → Find notes by keyword
- "Remind me [when] to [task]" → Set reminder
- "Schedule [person], find time [duration] [when]" → Calendar booking
- "Reply to [email/message]" → Draft response
- "Delete email from [person]" → Use email tool: first search to get the email_id, then call delete action with that email_id
- "Research [topic]" → Web search
- "What's the weather?" → Current weather + forecast
- "Latest news on [topic]" → News headlines
- "Send [person] a WhatsApp: [message]" → MUST call send_whatsapp tool with phone + message
- "Message [number] saying [text]" → MUST call send_whatsapp tool immediately
- "Help me with [task]" → General assistance

Rules:
- Keep responses concise unless Raunk asks for details
- Use NPT (Asia/Kathmandu, UTC+5:45) timezone by default — Raunk is based in Nepal
- Always confirm before taking irreversible actions
- If you can't do something, explain why clearly
- CRITICAL: When asked to send a WhatsApp/message to a number, you MUST call the send_whatsapp tool. Never reply with text saying you sent it — actually call the tool."""

# System prompt for Receptionist Mode
RECEPTIONIST_SYSTEM = """You are NOVA, Raunk Bohra's executive assistant.

Your role: Handle external contacts professionally and intelligently.

You have a few key responsibilities:
1. Greet callers warmly and professionally
2. Qualify the contact (name, company, purpose)
3. Make smart decisions about routing them

Decision framework:
- STRONG signal (investor, client, known partner) → Auto-book meeting
- UNCLEAR (might be relevant) → Ping Raunk for approval
- SPAM/IRRELEVANT (vendor, cold pitch) → Politely decline, don't ping

Special cases:
- VIP numbers skip all qualification (auto-book immediately)
- "URGENT" or "Emergency" messages → Always ping Raunk immediately
- "Just tell Raunk..." → Relay the message + confirm delivery
- Known repeat contacts → Greet by name, no re-qualification

What you never reveal:
- Raunk's personal phone or email
- His calendar details beyond "available/busy"
- Private conversation history
- Any personal information

Be warm, professional, and genuinely helpful."""


class Agent:
    """Claude-powered agent for NOVA"""

    def __init__(self):
        self.conversation_history: List[dict] = []
        self.max_iterations = MAX_ITERATIONS

    async def process_commander_message(self, message: str, session: AsyncSession) -> str:
        """
        Process message in Commander Mode (Raunk's personal assistant).

        Returns: Response text to send back to Raunk
        """
        logger.info(f"Processing Commander message: {message[:100]}")

        # Load Raunak context
        raunak_info = await get_context(session, "raunak_info")

        # Build system prompt with context
        system = COMMANDER_SYSTEM
        if raunak_info:
            system += f"\n\nContext about Raunk:\n{raunak_info}"

        # Get recent message history
        recent_messages = await get_messages(session, limit=settings.max_conversation_history)

        # Convert to Claude format
        messages = []
        for msg in recent_messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # Add current message
        messages.append({
            "role": "user",
            "content": message
        })

        # Save to history
        await save_message(session, "user", message)

        # Call Claude with adaptive thinking
        response = await self._call_claude(
            system=system,
            messages=messages,
            tools=get_claude_tools(),
            is_commander=True
        )

        # Save response
        await save_message(session, "assistant", response)

        return response

    async def process_receptionist_message(self, phone: str, message: str,
                                          session: AsyncSession) -> str:
        """
        Process message in Receptionist Mode (external contact).

        Returns: Response text to send to the contact
        """
        logger.info(f"Processing Receptionist message from {phone}: {message[:100]}")

        # Get thread history
        thread = await get_external_thread(session, phone)

        # Convert to Claude format
        messages = []
        for msg in thread:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # Add current message
        messages.append({
            "role": "user",
            "content": message
        })

        # Save to thread
        await save_external_message(session, phone, "user", message)

        # Call Claude
        response = await self._call_claude(
            system=RECEPTIONIST_SYSTEM,
            messages=messages,
            tools=None,  # Receptionist doesn't have tool access
            is_commander=False
        )

        # Save response
        await save_external_message(session, phone, "assistant", response)

        return response

    # Keywords that indicate Raunk wants NOVA to take an action via a tool
    _ACTION_PATTERNS = re.compile(
        r"\b(send|message|text|whatsapp|remind|schedule|book|add|save|note|search|research|email|reply|delete|trash|remove)\b",
        re.IGNORECASE
    )

    def _should_force_tool(self, messages: List[dict]) -> bool:
        """Return True if the last user message is clearly an action request."""
        for msg in reversed(messages):
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                return bool(self._ACTION_PATTERNS.search(msg["content"]))
        return False

    async def _call_claude(self, system: str, messages: List[dict],
                         tools: Optional[List[dict]] = None,
                         is_commander: bool = False) -> str:
        """
        Call Claude with tool use support.

        Returns: Final text response
        """
        iteration = 0
        # Force tool use on first iteration for action requests so Haiku
        # doesn't hallucinate a "Done!" text reply instead of calling the tool.
        force_tool_first = is_commander and tools and self._should_force_tool(messages)

        while iteration < self.max_iterations:
            iteration += 1
            logger.debug(f"Claude iteration {iteration}")

            # Build request
            request_kwargs = {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4096,
                "system": system,
                "messages": messages,
            }

            if tools:
                request_kwargs["tools"] = tools
                # On the first iteration of an action request, require a tool call
                if force_tool_first and iteration == 1:
                    request_kwargs["tool_choice"] = {"type": "any"}
                    logger.debug("Forcing tool_choice=any on first iteration")

            # Call Claude
            response = await client.messages.create(**request_kwargs)

            # Process response
            text_blocks = []
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text_blocks.append(block.text)
                elif block.type == "tool_use" and is_commander:
                    tool_calls.append(block)

            # If no tool calls, return text and done
            if not tool_calls:
                final_text = "\n".join(text_blocks).strip()
                logger.debug(f"Claude response (final): {final_text[:100]}")
                return final_text

            # Process tool calls
            logger.debug(f"Processing {len(tool_calls)} tool calls")

            # Add assistant response to messages
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Execute tools and collect results
            tool_results = []
            for tool_call in tool_calls:
                tool = get_tool(tool_call.name)
                if not tool:
                    logger.warning(f"Unknown tool: {tool_call.name}")
                    continue

                try:
                    result = await tool.execute(**tool_call.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": str(result.data) if result.success else f"Error: {result.error}"
                    })
                except Exception as e:
                    logger.error(f"Tool execution error: {e}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": f"Error: {str(e)}"
                    })

            # Add tool results to messages
            messages.append({
                "role": "user",
                "content": tool_results
            })

        # Max iterations reached
        logger.warning(f"Max iterations ({self.max_iterations}) reached")
        return "I've been thinking about this for a while. Could you rephrase your request?"
