"""
Claude Opus 4.6 Agentic Loop with Adaptive Thinking.
Handles message processing, tool calls, and conversation management.
"""

import logging
import re
import json
from typing import Optional, List
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.memory import (
    save_message, get_messages, get_context, set_context,
    save_external_message, get_external_thread, save_usage, get_all_context
)
import app.memory as _db
from app.tools import get_claude_tools, get_tool, get_receptionist_tools

logger = logging.getLogger(__name__)

# Initialize Anthropic async client
client = AsyncAnthropic(api_key=settings.anthropic_api_key)

# Maximum iterations to prevent infinite loops
MAX_ITERATIONS = 10

# System prompt for Commander Mode (base — dynamic context appended at runtime)
COMMANDER_SYSTEM = """You are NOVA, Raunk Bohra's executive assistant.

Your role: Help Raunk manage his work efficiently. You have access to his calendar, email, notes, reminders, sales data, memory, Google Drive, and can research topics via web search.

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
- "Find [file] in Drive" → drive tool: search
- "Read that Google Doc / Sheet" → drive tool: read_doc or read_sheet
- "Show my tasks / add task / done with X" → tasks tool
- "Spent Rs. X on ads today" → expense tool: log
- "What's my actual profit this month?" → expense tool: profit
- "Save this for later: [url]" → reading_list tool: save
- "What's on my reading list?" → reading_list tool: list
- "Summarize reading list item [N]" → reading_list tool: summarize(item_id=N)
- "Triage my inbox" / "What needs attention in email?" → email tool: triage
- [Image sent] → analyze using vision, describe contents, flag action items
- [PDF/document sent] → analyze the document, summarise key points, flag deadlines and action items
- [Voice brain dump] → extract tasks, ideas, follow-ups, decisions — save them, then confirm what was extracted
- "I'm meeting X from Y in N mins" / "Brief me on my 3pm" → brief tool: meeting(name, company)
- "Who is [person]?" / "Research [company]" before a meeting → brief tool: person or company action
- "Explain [concept]" / "Teach me about [topic]" / "What is [business term]?" → give a sharp 5-point founder-focused explanation — no fluff, real-world examples, what it means for Raunk specifically
- /help /brief /tasks /sales /memory /cost → instant slash commands (no AI loop)

Sales (iwishbag):
- When Raunk pastes sales figures (revenue, orders), call sales tool with action=log
- "How are sales this month?" → sales tool with action=summary, period=this_month
- "Compare this week vs last week" → sales tool with action=trend
- Monthly target is Rs. 30L (3,000,000). Always show % of target when reporting sales.
- When COGS is available, show gross profit and margin % too.

URLs:
- When Raunk shares a URL to summarize, use the perplexity tool (action=search, query=url) or fetch the page and summarize.

Memory:
- When you learn a preference → memory tool: remember(key="pref:...", value="...")
- When you learn a goal/target → memory tool: remember(key="goal:...", value="...")
- When you learn about a person → memory tool: remember(key="person:...", value="...")
- When you learn a project update → memory tool: remember(key="project:...", value="...")
- "Remember that..." / "I prefer..." / "My goal is..." → auto-save to memory
- "What do you know about X?" → memory tool: recall(pattern="person:X")

Rules:
- Keep responses concise unless Raunk asks for details
- Use NPT (Asia/Kathmandu, UTC+5:45) timezone by default — Raunk is based in Nepal
- Always confirm before taking irreversible actions
- If you can't do something, explain why clearly
- CRITICAL: When asked to send a WhatsApp/message to a number, you MUST call the send_whatsapp tool. Never reply with text saying you sent it — actually call the tool.
- CRITICAL: If a tool returns ❌ FAILED or an error, tell Raunk the action FAILED. Never say "Done", "Sent", or "Scheduled" if the tool returned an error.
- CRITICAL: Never confirm an action happened unless the tool explicitly returned success."""

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
- "Just tell Raunk..." → call the send_whatsapp tool with Raunk's number and the verbatim message, then confirm delivery to the sender
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

    async def process_commander_message(self, message, session: AsyncSession) -> str:
        """
        Process message in Commander Mode (Raunk's personal assistant).
        `message` is either a str (text) or list (vision: [{type:image,...},{type:text,...}]).

        Returns: Response text to send back to Raunk
        """
        msg_preview = message[:100] if isinstance(message, str) else "[vision message]"
        logger.info(f"Processing Commander message: {msg_preview}")

        # Load all memory context (preferences, goals, people, projects)
        all_context = await get_all_context(session)

        # Build system prompt with dynamic memory context
        system = COMMANDER_SYSTEM
        if all_context:
            lines = [f"  {k}: {v}" for k, v in sorted(all_context.items())]
            system += "\n\nWhat you know about Raunk (from memory):\n" + "\n".join(lines)

        # Get recent message history
        recent_messages = await get_messages(session, limit=settings.max_conversation_history)

        # Convert to Claude format
        messages = []
        for msg in recent_messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # Add current message (str for text, list for vision)
        messages.append({
            "role": "user",
            "content": message
        })

        # Save to history — store vision messages as text summary
        msg_to_save = message if isinstance(message, str) else "[Image sent by Raunk]"
        await save_message(session, "user", msg_to_save)

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

        # Build system prompt with Raunk's relay number so Claude knows where to send
        system = RECEPTIONIST_SYSTEM + f"\n\nRaunk's WhatsApp number for relaying messages: {settings.raunak_phone}"

        # Call Claude with send_whatsapp tool so relay intent can actually be executed
        receptionist_tools = get_receptionist_tools() or None
        response = await self._call_claude(
            system=system,
            messages=messages,
            tools=receptionist_tools,
            is_commander=False
        )

        # Save response
        await save_external_message(session, phone, "assistant", response)

        # Auto-extract contact info from the conversation so far
        await self._extract_and_save_contact(phone, message, thread, session)

        return response

    async def _extract_and_save_contact(self, phone: str, latest_message: str,
                                         prior_thread, session: AsyncSession):
        """
        After each receptionist exchange, scan the full thread for name/company/purpose
        and update the Contact record + memory if new info is found.
        """
        from app.memory import get_or_create_contact, set_context

        # Build transcript from prior thread + latest message
        lines = [f"{m.role}: {m.content}" for m in prior_thread]
        lines.append(f"user: {latest_message}")
        transcript = "\n".join(lines[-10:])  # last 10 lines is enough

        extract_prompt = f"""Extract contact info from this WhatsApp conversation. Return ONLY a JSON object with these fields (null if not mentioned):
{{"name": "...", "company": "...", "purpose": "..."}}

Conversation:
{transcript}

JSON:"""

        try:
            extraction = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": extract_prompt}],
            )
            raw = extraction.content[0].text.strip()
            # Pull out JSON block
            import re as _re
            match = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if not match:
                return
            data = json.loads(match.group())
            name = data.get("name")
            company = data.get("company")
            purpose = data.get("purpose")

            if name or company or purpose:
                contact = await get_or_create_contact(session, phone, name=name, company=company)
                if purpose and not contact.purpose:
                    contact.purpose = purpose
                    await session.commit()
                # Also save to memory for NOVA's context in Commander mode
                if name:
                    key = f"person:{name.lower().replace(' ', '_')}"
                    value = f"Phone: {phone}"
                    if company:
                        value += f", Company: {company}"
                    if purpose:
                        value += f", Purpose: {purpose}"
                    await set_context(session, key, value)
                    logger.info(f"Auto-saved contact to memory: {key}")
        except Exception as e:
            logger.debug(f"Contact extraction failed (non-critical): {e}")

    # Keywords that indicate Raunk wants NOVA to take an action via a tool
    _ACTION_PATTERNS = re.compile(
        r"\b(send|message|text|whatsapp|wa|remind|schedule|book|add|save|note|search|research|email|reply|delete|trash|remove|log|sales|revenue|orders|remember|recall|forget|drive|doc|sheet|find|spreadsheet|task|tasks|done|complete|expense|spent|cost|profit|margin|triage|reading|read|summarize|tell|let|ping|inform|notify|contact|msg|lent|borrowed|borrow|loan|owe|owes|settle|paid back|gave me|lending|export|price|stock|crypto|bitcoin|btc|eth|ethereum|nifty|sensex|market|reliance|tcs|infosys|brief|meeting|explain|teach|who is|research)\b",
        re.IGNORECASE
    )

    # Patterns specifically indicating a WhatsApp send is needed
    _WHATSAPP_PATTERNS = re.compile(
        r"\b(send|message|text|whatsapp|wa|ping|tell|msg|inform|notify|let.*know)\b.*(\+\d{7,15}|raj|amit|priya|[a-z]+\s+a\s+(wa|whatsapp|message|msg))",
        re.IGNORECASE
    )

    def _get_last_user_text(self, messages: List[dict]) -> str:
        """Extract plain text from the last user message."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block.get("text", "")
        return ""

    def _should_force_tool(self, messages: List[dict]) -> bool:
        """Return True if the last user message is clearly an action request."""
        text = self._get_last_user_text(messages)
        return bool(self._ACTION_PATTERNS.search(text)) if text else False

    def _needs_whatsapp(self, messages: List[dict]) -> bool:
        """Return True if the request involves sending a WhatsApp message."""
        text = self._get_last_user_text(messages)
        if not text:
            return False
        # Explicit WhatsApp/message keywords
        whatsapp_words = re.compile(
            r"\b(whatsapp|wa|send.*message|message.*to|text.*to|ping|msg)\b", re.IGNORECASE
        )
        # Paired with a recipient indicator (phone number or "to [name]")
        recipient = re.compile(r"(\+\d{7,15}|\bto\s+\w+|\braj\b|\bamit\b)", re.IGNORECASE)
        return bool(whatsapp_words.search(text)) and bool(recipient.search(text))

    async def _call_claude(self, system: str, messages: List[dict],
                         tools: Optional[List[dict]] = None,
                         is_commander: bool = False) -> str:
        """
        Call Claude with tool use support.

        Returns: Final text response
        """
        iteration = 0
        total_input_tokens = 0
        total_output_tokens = 0
        # Force tool use on first iteration for action requests so Haiku
        # doesn't hallucinate a "Done!" text reply instead of calling the tool.
        force_tool_first = is_commander and tools and self._should_force_tool(messages)
        # Track if send_whatsapp has been called yet (to re-force if skipped)
        whatsapp_sent = False
        needs_whatsapp = is_commander and tools and self._needs_whatsapp(messages)

        if force_tool_first:
            logger.info(f"Force tool=any triggered for this request")
        if needs_whatsapp:
            logger.info(f"WhatsApp send detected — will enforce tool call")

        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"Claude iteration {iteration}/{self.max_iterations}")

            # Build request
            request_kwargs = {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4096,
                "system": system,
                "messages": messages,
            }

            if tools:
                request_kwargs["tools"] = tools
                if force_tool_first and iteration == 1:
                    request_kwargs["tool_choice"] = {"type": "any"}
                    logger.info("tool_choice=any on iteration 1")
                # If WhatsApp is needed but not yet sent, keep forcing on iteration 2
                elif needs_whatsapp and not whatsapp_sent and iteration == 2:
                    request_kwargs["tool_choice"] = {"type": "any"}
                    logger.info("tool_choice=any re-forced on iteration 2 (WhatsApp not yet sent)")

            # Call Claude
            response = await client.messages.create(**request_kwargs)
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Process response
            text_blocks = []
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text_blocks.append(block.text)
                elif block.type == "tool_use" and tools:
                    tool_calls.append(block)

            # If no tool calls, save usage and return
            if not tool_calls:
                final_text = "\n".join(text_blocks).strip()
                logger.info(f"Claude final response (no tool calls): {final_text[:120]}")
                try:
                    async with _db.AsyncSessionLocal() as session:
                        await save_usage(session, total_input_tokens, total_output_tokens)
                except Exception as e:
                    logger.warning(f"Failed to save usage: {e}")
                return final_text

            # Process tool calls
            tool_names = [tc.name for tc in tool_calls]
            logger.info(f"Tool calls: {tool_names}")

            # Add assistant response to messages
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Execute tools and collect results
            tool_results = []
            for tool_call in tool_calls:
                if tool_call.name == "send_whatsapp":
                    whatsapp_sent = True

                tool = get_tool(tool_call.name)
                if not tool:
                    logger.warning(f"Unknown tool: {tool_call.name}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": f"Error: Unknown tool '{tool_call.name}'"
                    })
                    continue

                try:
                    result = await tool.execute(**tool_call.input)
                    content = str(result.data) if result.success else f"❌ FAILED: {result.error}"
                    logger.info(f"Tool {tool_call.name} → {'OK' if result.success else 'FAILED'}: {content[:120]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": content
                    })
                except Exception as e:
                    logger.error(f"Tool execution error ({tool_call.name}): {e}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": f"❌ FAILED: {str(e)}"
                    })

            # Add tool results to messages
            if tool_results:
                messages.append({
                    "role": "user",
                    "content": tool_results
                })

        # Max iterations reached
        logger.warning(f"Max iterations ({self.max_iterations}) reached")
        return "I've been thinking about this for a while. Could you rephrase your request?"
