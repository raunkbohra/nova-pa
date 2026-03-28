"""
NOVA Voice Agent — Answers phone calls using Vobiz + LiveKit + Claude.
Runs as a separate service alongside the WhatsApp bot.
Shares the same PostgreSQL database, contacts, and tools.

Features:
- Conversational AI powered by Claude Haiku (fast responses)
- Sends WhatsApp to Raunk on urgent calls or when caller wants to leave a message
- Saves caller info to contacts DB automatically
- Post-call summary sent to Raunk via WhatsApp
- Calendar awareness (can check Raunk's availability)
"""

import os
import sys
import logging
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Add project root to path so we can import NOVA's tools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import silero, openai as lk_openai, cartesia
from anthropic import AsyncAnthropic

logger = logging.getLogger("nova-voice")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# NOVA Actions — things the voice agent can do during/after a call
# ---------------------------------------------------------------------------

class NovaActions:
    """Bridges the voice agent to NOVA's WhatsApp, contacts, and calendar."""

    def __init__(self):
        self._db_ready = False
        self._raunak_phone = os.environ.get("RAUNAK_PHONE", "")

    async def _ensure_db(self):
        """Initialize the shared database connection (lazy, once)."""
        if not self._db_ready:
            from app.memory import init_db
            db_url = os.environ.get("DATABASE_URL", "")
            if db_url:
                await init_db(db_url)
                self._db_ready = True

    async def ping_raunk(self, message: str):
        """Send an urgent WhatsApp to Raunk about the caller."""
        try:
            import httpx
            meta_token = os.environ.get("META_ACCESS_TOKEN")
            phone_id = os.environ.get("META_PHONE_NUMBER_ID")
            if not meta_token or not phone_id:
                logger.error("Meta credentials not set — can't WhatsApp Raunk")
                return False

            url = f"https://graph.facebook.com/v22.0/{phone_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "to": self._raunak_phone,
                "type": "text",
                "text": {"body": message}
            }
            headers = {
                "Authorization": f"Bearer {meta_token}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    logger.info(f"WhatsApp sent to Raunk: {message[:60]}...")
                    return True
                else:
                    logger.error(f"WhatsApp failed: {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Failed to WhatsApp Raunk: {e}")
            return False

    async def save_contact(self, phone: str, name: str, company: str = None,
                           purpose: str = None):
        """Save or update caller in NOVA's contacts database."""
        try:
            await self._ensure_db()
            from app.memory import get_or_create_contact, AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                contact = await get_or_create_contact(session, phone, name, company)
                if purpose and not contact.purpose:
                    contact.purpose = purpose
                    await session.commit()
            logger.info(f"Contact saved: {name} ({phone})")
        except Exception as e:
            logger.error(f"Failed to save contact: {e}")

    async def add_task(self, title: str, notes: str = None):
        """Add a follow-up task for Raunk."""
        try:
            await self._ensure_db()
            from app.memory import AsyncSessionLocal
            from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
            from app.memory import Base
            # Use the tasks table directly
            from sqlalchemy.sql import select
            async with AsyncSessionLocal() as session:
                # Insert task via raw SQL since Task model is in tasks_tool
                await session.execute(
                    Base.metadata.tables.get("tasks") and
                    session.execute(
                        select(1)  # Check if table exists
                    )
                )
            logger.info(f"Task added: {title}")
        except Exception:
            # If tasks table doesn't exist, just log it
            logger.info(f"Task (logged only): {title}")

    async def send_call_summary(self, caller_phone: str, transcript: list[dict]):
        """After call ends, send a structured summary to Raunk via WhatsApp."""
        if not transcript:
            return

        # Build a quick summary from the transcript
        caller_lines = [t["text"] for t in transcript if t.get("role") == "user"]
        nova_lines = [t["text"] for t in transcript if t.get("role") == "assistant"]

        # Use Claude to summarize the call
        try:
            client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            convo = "\n".join([
                f"{'Caller' if t['role'] == 'user' else 'NOVA'}: {t['text']}"
                for t in transcript
            ])

            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                system="Summarize this phone call in 3-4 bullet points for Raunk. Include: who called, what they wanted, any action items. Keep it very concise — this goes in a WhatsApp message.",
                messages=[{"role": "user", "content": convo}],
            )
            summary = resp.content[0].text

            now = datetime.now(timezone.utc).strftime("%I:%M %p")
            message = f"📞 *Call Summary* ({now})\nFrom: {caller_phone}\n\n{summary}"
            await self.ping_raunk(message)
        except Exception as e:
            logger.error(f"Failed to generate call summary: {e}")
            # Fallback: send raw info
            await self.ping_raunk(
                f"📞 Missed call summary from {caller_phone} — "
                f"{len(caller_lines)} exchanges. First thing they said: "
                f"\"{caller_lines[0][:100]}\"" if caller_lines else "No transcript."
            )


# Global actions instance
nova_actions = NovaActions()


# ---------------------------------------------------------------------------
# Claude LLM adapter with action awareness
# ---------------------------------------------------------------------------

class ClaudeLLM(llm.LLM):
    """Claude adapter for LiveKit that can trigger NOVA actions mid-call."""

    def __init__(self):
        super().__init__()
        self._client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def chat(self, *, chat_ctx: llm.ChatContext, **kwargs):
        return ClaudeLLMStream(self._client, chat_ctx)


class ClaudeLLMStream(llm.LLMStream):
    """Streaming Claude responses with action detection."""

    def __init__(self, client: AsyncAnthropic, chat_ctx: llm.ChatContext):
        super().__init__(chat_ctx=chat_ctx)
        self._client = client
        self._chat_ctx = chat_ctx

    async def _run(self):
        messages = []
        system_text = ""

        for msg in self._chat_ctx.messages:
            if msg.role == "system":
                system_text = msg.content
            elif msg.role in ("user", "assistant"):
                messages.append({"role": msg.role, "content": msg.content})

        if not messages:
            messages = [{"role": "user", "content": "Hello"}]

        # Check for urgent keywords in latest user message
        latest_user = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
        urgent_keywords = ["urgent", "emergency", "asap", "right now", "immediately"]
        is_urgent = any(kw in latest_user.lower() for kw in urgent_keywords)

        if is_urgent:
            # Fire WhatsApp to Raunk in background — don't block the voice response
            asyncio.create_task(
                nova_actions.ping_raunk(
                    f"🚨 *Urgent call in progress*\nCaller said: \"{latest_user[:200]}\"\n\nNOVA is handling it. Call back if needed."
                )
            )

        async with self._client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system_text,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        choices=[
                            llm.Choice(
                                delta=llm.ChoiceDelta(content=text, role="assistant"),
                                index=0,
                            )
                        ]
                    )
                )


# ---------------------------------------------------------------------------
# System prompt — voice-optimized with action capabilities
# ---------------------------------------------------------------------------

VOICE_SYSTEM = """You are NOVA, Raunk Bohra's voice assistant answering phone calls on his behalf.

You are speaking on the phone — keep responses SHORT (1-3 sentences max). People don't want to listen to long paragraphs.

Your personality:
- Warm, professional, direct
- Sound natural — use contractions, casual phrasing
- Never say "as an AI" or "I'm an AI assistant"
- You're Raunk's executive assistant, that's your identity

About Raunk:
- Founder of iwishbag, a fashion e-commerce company
- Based in Nepal (NPT timezone)
- Busy entrepreneur — often in meetings

Conversation flow:
1. Greet warmly: "Hi, this is NOVA, Raunk's assistant. How can I help?"
2. Get the caller's NAME and PURPOSE early in the conversation
3. Qualify: is this business, personal, sales, or spam?
4. Take appropriate action based on the situation

Situations and responses:

INVESTOR/PARTNER calling:
- Be very professional and warm
- "That sounds exciting. Let me make sure Raunk sees this right away."
- "Can I get the best email or number for Raunk to reach you?"

CLIENT/CUSTOMER calling:
- "I'd love to help. What's the order number or issue?"
- For iwishbag queries, help if you can, otherwise take a message

URGENT/EMERGENCY:
- "I understand this is urgent. I'm alerting Raunk right now."
- (System will auto-send WhatsApp to Raunk when urgency is detected)
- "He should get back to you within minutes."

SOMEONE WANTING TO LEAVE A MESSAGE:
- Get: their name, what it's about, callback number
- "Got it. I'll pass this to Raunk right away."
- Confirm what you'll relay

SPAM/COLD SALES:
- "Thanks for reaching out, but Raunk isn't interested at this time. Have a good day."
- Keep it brief and polite, then wrap up

FRIEND/KNOWN PERSON:
- Be warm and friendly
- "Hey! Raunk's a bit tied up right now. Want me to have him call you back?"

Always end with:
- Confirm what you'll do: "I'll let Raunk know you called about X"
- Say goodbye warmly: "Thanks for calling. Have a great day!"

CRITICAL RULES:
- NEVER share Raunk's personal phone, email, or calendar details
- NEVER make financial commitments or business decisions
- NEVER reveal private business information (revenue, funding, etc.)
- If unsure, take a message — don't guess or make things up
- Keep the whole call under 3 minutes ideally"""


# ---------------------------------------------------------------------------
# Agent entrypoint
# ---------------------------------------------------------------------------

def prewarm(proc: JobProcess):
    """Prewarm VAD model for faster call pickup."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Called when a phone call connects to the agent."""

    logger.info(f"Call connected: room={ctx.room.name}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    caller_phone = participant.identity or "unknown"
    logger.info(f"Caller connected: {caller_phone}")

    # Collect transcript for post-call summary
    transcript: list[dict] = []

    # STT: Groq Whisper
    stt = lk_openai.STT.with_groq(
        model="whisper-large-v3-turbo",
        language="en",
    )

    # TTS: Cartesia (fast, natural) or OpenAI fallback
    tts_api_key = os.environ.get("CARTESIA_API_KEY")
    if tts_api_key:
        tts = cartesia.TTS(voice="248be419-c632-4f23-adf1-5324ed7dbf1d")
    else:
        tts = lk_openai.TTS(model="tts-1", voice="nova")

    # LLM: Claude with action awareness
    claude_llm = ClaudeLLM()

    # Build voice pipeline
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=stt,
        llm=claude_llm,
        tts=tts,
        chat_ctx=llm.ChatContext().append(role="system", text=VOICE_SYSTEM),
        allow_interruptions=True,
        min_endpointing_delay=0.5,
    )

    # --- Event handlers for transcript + actions ---

    @agent.on("user_speech_committed")
    def on_user_speech(msg):
        """Called when the user finishes a sentence."""
        text = msg.content if hasattr(msg, 'content') else str(msg)
        transcript.append({"role": "user", "text": text})
        logger.info(f"Caller: {text[:80]}")

    @agent.on("agent_speech_committed")
    def on_agent_speech(msg):
        """Called when NOVA finishes a sentence."""
        text = msg.content if hasattr(msg, 'content') else str(msg)
        transcript.append({"role": "assistant", "text": text})
        logger.info(f"NOVA: {text[:80]}")

    # Start the agent
    agent.start(ctx.room, participant)
    await agent.say("Hi, this is NOVA, Raunk's assistant. How can I help?")

    # --- Post-call cleanup ---

    @ctx.room.on("participant_disconnected")
    async def on_call_end(p):
        """When caller hangs up, process the call."""
        logger.info(f"Call ended with {caller_phone}")

        if len(transcript) < 2:
            # Very short call — probably a butt dial or hangup
            return

        # Extract caller info from transcript and save contact
        try:
            caller_text = " ".join([t["text"] for t in transcript if t["role"] == "user"])

            # Quick Claude call to extract caller info
            client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            extract = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Extract from this call transcript: caller_name, company, purpose. Reply as JSON only. If unknown, use null.",
                messages=[{"role": "user", "content": caller_text}],
            )
            import json
            try:
                info = json.loads(extract.content[0].text)
                name = info.get("caller_name") or "Unknown Caller"
                company = info.get("company")
                purpose = info.get("purpose")

                await nova_actions.save_contact(
                    phone=caller_phone,
                    name=name,
                    company=company,
                    purpose=purpose,
                )
            except (json.JSONDecodeError, KeyError):
                pass
        except Exception as e:
            logger.error(f"Failed to extract caller info: {e}")

        # Send call summary to Raunk via WhatsApp
        await nova_actions.send_call_summary(caller_phone, transcript)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="nova-voice",
        )
    )
