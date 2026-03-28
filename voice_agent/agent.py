"""
NOVA Voice Agent — Answers phone calls using Vobiz + LiveKit + Claude.
Runs as a separate service alongside the WhatsApp bot.
Shares the same PostgreSQL database and knowledge base.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

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
# Claude LLM adapter for LiveKit (wraps Anthropic API into LiveKit's LLM interface)
# ---------------------------------------------------------------------------

class ClaudeLLM(llm.LLM):
    """Adapter that lets LiveKit's VoicePipelineAgent use Claude as the LLM."""

    def __init__(self):
        super().__init__()
        self._client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def chat(self, *, chat_ctx: llm.ChatContext, **kwargs):
        return ClaudeLLMStream(self._client, chat_ctx)


class ClaudeLLMStream(llm.LLMStream):
    """Streaming adapter for Claude responses."""

    def __init__(self, client: AsyncAnthropic, chat_ctx: llm.ChatContext):
        super().__init__(chat_ctx=chat_ctx)
        self._client = client
        self._chat_ctx = chat_ctx

    async def _run(self):
        # Convert LiveKit chat context to Claude messages format
        messages = []
        system_text = ""

        for msg in self._chat_ctx.messages:
            if msg.role == "system":
                system_text = msg.content
            elif msg.role in ("user", "assistant"):
                messages.append({"role": msg.role, "content": msg.content})

        if not messages:
            messages = [{"role": "user", "content": "Hello"}]

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
# System prompt — same personality as WhatsApp NOVA, adapted for voice
# ---------------------------------------------------------------------------

VOICE_SYSTEM = """You are NOVA, Raunk Bohra's voice assistant answering phone calls on his behalf.

You are speaking on the phone — keep responses SHORT (1-3 sentences max). People don't want to listen to long paragraphs.

Your personality:
- Warm, professional, direct
- Sound natural — use contractions, casual phrasing
- Never say "as an AI" or "I'm an AI assistant"

If the caller is:
- A known contact/friend → be warm, ask how they're doing
- A potential business contact → be professional, qualify them
- Unknown → introduce yourself: "Hi, this is NOVA, Raunk's assistant. How can I help?"

What you can do:
- Take messages for Raunk
- Share Raunk's general availability (busy/available, not exact calendar)
- Answer basic questions about iwishbag (Raunk's fashion e-commerce company)
- Transfer urgent calls to Raunk

What you should NOT do:
- Share Raunk's personal phone number or email
- Give out specific calendar details
- Make commitments on Raunk's behalf
- Share any private or financial information

If the caller asks to speak to Raunk directly, say: "Let me check if Raunk is available. Can I get your name and what this is regarding?" Then take a message.

Remember: You're on a PHONE CALL. Be conversational, not robotic. Keep it brief."""


# ---------------------------------------------------------------------------
# Agent entrypoint
# ---------------------------------------------------------------------------

def prewarm(proc: JobProcess):
    """Prewarm VAD model for faster call pickup."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Called when a phone call connects to the agent."""

    logger.info(f"Call connected: room={ctx.room.name}")

    # Wait for the caller to connect
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    logger.info(f"Caller connected: {participant.identity}")

    # STT: Groq Whisper (OpenAI-compatible endpoint)
    stt = lk_openai.STT.with_groq(
        model="whisper-large-v3-turbo",
        language="en",
    )

    # TTS: Use Cartesia (fast, natural voice) or fall back to gTTS
    tts_api_key = os.environ.get("CARTESIA_API_KEY")
    if tts_api_key:
        tts = cartesia.TTS(voice="248be419-c632-4f23-adf1-5324ed7dbf1d")  # British Lady
    else:
        # Fall back to OpenAI TTS via Groq or basic
        tts = lk_openai.TTS(
            model="tts-1",
            voice="nova",
        )

    # LLM: Claude
    claude_llm = ClaudeLLM()

    # Build the voice pipeline
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=stt,
        llm=claude_llm,
        tts=tts,
        chat_ctx=llm.ChatContext().append(
            role="system",
            text=VOICE_SYSTEM,
        ),
        # Allow interruption (caller can speak while NOVA is talking)
        allow_interruptions=True,
        # Shorter silence threshold for natural phone conversation
        min_endpointing_delay=0.5,
    )

    agent.start(ctx.room, participant)

    # Greet the caller
    await agent.say("Hi, this is NOVA, Raunk's assistant. How can I help?")


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
