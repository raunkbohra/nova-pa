"""
NOVA Voice Agent — WebSocket-based, no LiveKit needed.
Vobiz streams audio directly to this server via WebSocket.

Architecture:
  Phone call → Vobiz → POST /voice/answer → XML <Connect><Stream>
  → Vobiz opens WebSocket to /voice/stream
  → Audio in (G.711 µ-law) → STT (Groq Whisper) → Claude → TTS → Audio out

Runs as a separate FastAPI service on port 8001.
"""

import os
import sys
import json
import base64
import struct
import asyncio
import logging
import io
import wave
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
import uvicorn
import httpx
from anthropic import AsyncAnthropic

logger = logging.getLogger("nova-voice")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = FastAPI(title="NOVA Voice Agent")

RAUNAK_PHONE = os.environ.get("RAUNAK_PHONE", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "")
VOICE_HOST = os.environ.get("VOICE_HOST", "")


# ---------------------------------------------------------------------------
# µ-law audio conversion helpers
# ---------------------------------------------------------------------------

ULAW_DECODE = []
for _i in range(256):
    _inv = ~_i & 0xFF
    _sign = -1 if (_inv & 0x80) else 1
    _exp = (_inv >> 4) & 0x07
    _man = _inv & 0x0F
    _sample = _sign * ((_man << 3) + 0x84) << _exp
    _sample -= _sign * 0x84
    ULAW_DECODE.append(max(-32768, min(32767, _sample)))


def _linear_to_ulaw(sample: int) -> int:
    BIAS = 0x84
    CLIP = 32635
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    if sample > CLIP:
        sample = CLIP
    sample += BIAS
    exponent = 7
    exp_mask = 0x4000
    while exponent > 0 and not (sample & exp_mask):
        exponent -= 1
        exp_mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


ULAW_ENCODE = [_linear_to_ulaw(i - 32768) for i in range(65536)]


def ulaw_to_pcm(ulaw_bytes: bytes) -> bytes:
    pcm = bytearray(len(ulaw_bytes) * 2)
    for i, b in enumerate(ulaw_bytes):
        struct.pack_into('<h', pcm, i * 2, ULAW_DECODE[b])
    return bytes(pcm)


def pcm_to_ulaw(pcm_bytes: bytes) -> bytes:
    result = bytearray(len(pcm_bytes) // 2)
    for i in range(0, len(pcm_bytes), 2):
        sample = struct.unpack_from('<h', pcm_bytes, i)[0]
        result[i // 2] = ULAW_ENCODE[sample + 32768]
    return bytes(result)


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Simple VAD — energy-based
# ---------------------------------------------------------------------------

def is_speech(pcm_bytes: bytes, threshold: int = 500) -> bool:
    if len(pcm_bytes) < 4:
        return False
    samples = struct.unpack(f'<{len(pcm_bytes)//2}h', pcm_bytes)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    return rms > threshold


# ---------------------------------------------------------------------------
# STT via Groq Whisper
# ---------------------------------------------------------------------------

async def transcribe(audio_wav: bytes) -> Optional[str]:
    if len(audio_wav) < 1000:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.wav", audio_wav, "audio/wav")},
                data={"model": "whisper-large-v3-turbo", "language": "en"},
            )
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            return text if text else None
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return None


# ---------------------------------------------------------------------------
# TTS via gTTS + ffmpeg
# ---------------------------------------------------------------------------

async def text_to_speech(text: str) -> Optional[bytes]:
    try:
        from gtts import gTTS
        import tempfile

        tts = gTTS(text=text, lang='en', tld='co.in')
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_buf.seek(0)

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_mp3:
            tmp_mp3.write(mp3_buf.read())
            tmp_mp3_path = tmp_mp3.name

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:
            tmp_wav_path = tmp_wav.name

        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y', '-i', tmp_mp3_path,
            '-ar', '8000', '-ac', '1', '-f', 'wav', tmp_wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        with open(tmp_wav_path, 'rb') as f:
            wav_data = f.read()

        pcm_data = wav_data[44:]
        ulaw_data = pcm_to_ulaw(pcm_data)

        os.unlink(tmp_mp3_path)
        os.unlink(tmp_wav_path)

        return ulaw_data
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return None


# ---------------------------------------------------------------------------
# Claude conversation
# ---------------------------------------------------------------------------

VOICE_SYSTEM = """You are NOVA, Raunk Bohra's voice assistant answering phone calls.

CRITICAL: Keep every response under 25 words. You're on a phone call — be brief.

Personality: warm, professional, direct. Use contractions. Never mention being AI.

About Raunk: Founder of iwishbag (fashion e-commerce), based in Nepal.

Flow:
1. Get caller's NAME and PURPOSE
2. For legitimate callers: take message, offer callback
3. For urgent: "I'm alerting Raunk right now"
4. For spam: politely decline

NEVER share: Raunk's phone, email, calendar, or finances."""


async def chat_with_claude(messages: list[dict]) -> str:
    try:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=VOICE_SYSTEM,
            messages=messages,
        )
        return resp.content[0].text
    except Exception as e:
        logger.error(f"Claude error: {e}")
        return "Sorry, I'm having trouble. Can you call back shortly?"


# ---------------------------------------------------------------------------
# WhatsApp helpers
# ---------------------------------------------------------------------------

async def ping_raunk(message: str):
    if not META_ACCESS_TOKEN or not RAUNAK_PHONE:
        return
    try:
        url = f"https://graph.facebook.com/v22.0/{META_PHONE_NUMBER_ID}/messages"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "messaging_product": "whatsapp",
                "to": RAUNAK_PHONE,
                "type": "text",
                "text": {"body": message}
            }, headers={
                "Authorization": f"Bearer {META_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            }, timeout=10.0)
    except Exception as e:
        logger.error(f"WhatsApp error: {e}")


async def send_call_summary(caller_phone: str, transcript: list[dict]):
    if len(transcript) < 2:
        return
    try:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        convo = "\n".join(
            f"{'Caller' if t['role']=='user' else 'NOVA'}: {t['text']}"
            for t in transcript
        )
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system="Summarize this phone call in 3-4 bullets for Raunk. Who called, what they wanted, action items. Very concise — WhatsApp message.",
            messages=[{"role": "user", "content": convo}],
        )
        summary = resp.content[0].text
        now = datetime.now(timezone.utc).strftime("%I:%M %p")
        await ping_raunk(f"📞 *Call Summary* ({now})\nFrom: {caller_phone}\n\n{summary}")
    except Exception as e:
        logger.error(f"Summary error: {e}")


async def save_caller_contact(caller_phone: str, transcript: list[dict]):
    if len(transcript) < 2:
        return
    try:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        caller_text = " ".join(t["text"] for t in transcript if t["role"] == "user")
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system='Extract: caller_name, company, purpose. Reply JSON only. null if unknown.',
            messages=[{"role": "user", "content": caller_text}],
        )
        info = json.loads(resp.content[0].text)
        from app.memory import init_db, get_or_create_contact, AsyncSessionLocal
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            await init_db(db_url)
            async with AsyncSessionLocal() as session:
                contact = await get_or_create_contact(
                    session, caller_phone,
                    info.get("caller_name"), info.get("company")
                )
                if info.get("purpose") and not contact.purpose:
                    contact.purpose = info["purpose"]
                    await session.commit()
            logger.info(f"Contact saved: {info.get('caller_name')} ({caller_phone})")
    except Exception as e:
        logger.error(f"Contact save error: {e}")


# ---------------------------------------------------------------------------
# Vobiz Webhooks
# ---------------------------------------------------------------------------

@app.post("/voice/answer")
async def voice_answer(request: Request):
    """Vobiz calls this when someone dials the number."""
    data = await request.form()
    call_uuid = data.get("CallUUID", "unknown")
    from_number = data.get("From", "unknown")
    logger.info(f"Incoming call: {from_number} (CallUUID={call_uuid})")

    ws_url = f"wss://{VOICE_HOST}/voice/stream"
    xml_response = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response>'
        f'<Connect><Stream url="{ws_url}" /></Connect>'
        '</Response>'
    )
    return Response(content=xml_response, media_type="application/xml")


@app.post("/voice/hangup")
async def voice_hangup(request: Request):
    """Vobiz calls this when the call ends."""
    data = await request.form()
    logger.info(f"Call ended: duration={data.get('Duration', '?')}s")
    return Response(content="OK", status_code=200)


# ---------------------------------------------------------------------------
# WebSocket Audio Handler
# ---------------------------------------------------------------------------

@app.websocket("/voice/stream")
async def voice_stream(ws: WebSocket):
    await ws.accept()
    logger.info("WebSocket connected")

    stream_sid = None
    caller_phone = "unknown"
    audio_buffer = bytearray()
    silence_frames = 0
    is_currently_speaking = False
    conversation: list[dict] = []
    transcript: list[dict] = []
    speech_frame_count = 0

    SILENCE_THRESHOLD = 25       # ~500ms at 20ms frames
    MIN_SPEECH_FRAMES = 5

    greeting_audio = await text_to_speech(
        "Hi, this is NOVA, Raunk's assistant. How can I help?"
    )

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                logger.info(f"Stream connected: {msg.get('protocol')}")

            elif event == "start":
                stream_sid = msg.get("streamSid")
                start_data = msg.get("start", {})
                caller_phone = start_data.get("customParameters", {}).get("from", "unknown")
                logger.info(f"Stream started: sid={stream_sid}")

                # Play greeting
                if greeting_audio and stream_sid:
                    chunk_size = 640
                    for i in range(0, len(greeting_audio), chunk_size):
                        chunk = greeting_audio[i:i + chunk_size]
                        await ws.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(chunk).decode()}
                        }))
                        await asyncio.sleep(0.08)

                transcript.append({
                    "role": "assistant",
                    "text": "Hi, this is NOVA, Raunk's assistant. How can I help?"
                })

            elif event == "media":
                payload = msg.get("media", {}).get("payload", "")
                ulaw_chunk = base64.b64decode(payload)
                pcm_chunk = ulaw_to_pcm(ulaw_chunk)

                if is_speech(pcm_chunk):
                    audio_buffer.extend(ulaw_chunk)
                    silence_frames = 0
                    speech_frame_count += 1
                    is_currently_speaking = True
                elif is_currently_speaking:
                    silence_frames += 1
                    audio_buffer.extend(ulaw_chunk)

                    if silence_frames >= SILENCE_THRESHOLD:
                        is_currently_speaking = False

                        if speech_frame_count >= MIN_SPEECH_FRAMES:
                            pcm_full = ulaw_to_pcm(bytes(audio_buffer))
                            wav_data = pcm_to_wav(pcm_full, sample_rate=8000)

                            text = await transcribe(wav_data)
                            if text and len(text) > 1:
                                logger.info(f"Caller: {text}")
                                transcript.append({"role": "user", "text": text})
                                conversation.append({"role": "user", "content": text})

                                # Urgent detection
                                urgent = ["urgent", "emergency", "asap", "immediately"]
                                if any(w in text.lower() for w in urgent):
                                    asyncio.create_task(ping_raunk(
                                        f"🚨 *Urgent call*\nFrom: {caller_phone}\n\"{text[:200]}\""
                                    ))

                                reply = await chat_with_claude(conversation)
                                logger.info(f"NOVA: {reply}")
                                conversation.append({"role": "assistant", "content": reply})
                                transcript.append({"role": "assistant", "text": reply})

                                reply_audio = await text_to_speech(reply)
                                if reply_audio and stream_sid:
                                    chunk_size = 640
                                    for i in range(0, len(reply_audio), chunk_size):
                                        chunk = reply_audio[i:i + chunk_size]
                                        await ws.send_text(json.dumps({
                                            "event": "media",
                                            "streamSid": stream_sid,
                                            "media": {
                                                "payload": base64.b64encode(chunk).decode()
                                            }
                                        }))
                                        await asyncio.sleep(0.08)

                        audio_buffer = bytearray()
                        silence_frames = 0
                        speech_frame_count = 0

            elif event == "stop":
                logger.info("Stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if len(transcript) >= 2:
            asyncio.create_task(send_call_summary(caller_phone, transcript))
            asyncio.create_task(save_caller_contact(caller_phone, transcript))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/voice/health")
async def health():
    return {"status": "ok", "service": "NOVA Voice Agent"}


if __name__ == "__main__":
    port = int(os.environ.get("VOICE_PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
