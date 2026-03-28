"""
Voice module — Transcription (Whisper) and Text-to-Speech (gTTS).
Handles voice notes and audio responses.
"""

import logging
import io
from typing import Optional
import httpx
from app.config import settings
from app.whatsapp import download_media

logger = logging.getLogger(__name__)

# Whisper client — lazy init, prefers Groq (free) over OpenAI
_whisper_client = None
_whisper_backend = None  # "groq" or "openai"


def _get_whisper_client():
    global _whisper_client, _whisper_backend
    if _whisper_client is None:
        from openai import OpenAI
        if settings.groq_api_key:
            _whisper_client = OpenAI(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
            _whisper_backend = "groq"
            logger.info("Whisper backend: Groq (free)")
        elif settings.openai_api_key:
            _whisper_client = OpenAI(api_key=settings.openai_api_key)
            _whisper_backend = "openai"
            logger.info("Whisper backend: OpenAI")
        else:
            raise RuntimeError(
                "No transcription key set — add GROQ_API_KEY or OPENAI_API_KEY to .env"
            )
    return _whisper_client


async def transcribe_voice_note(media_id: str) -> Optional[str]:
    """
    Transcribe a WhatsApp voice note.
    Uses Groq Whisper if GROQ_API_KEY is set, falls back to OpenAI Whisper.
    """
    try:
        audio_data = await download_media(media_id)
        if not audio_data:
            logger.error(f"Failed to download media: {media_id}")
            return None

        audio_file = io.BytesIO(audio_data)
        audio_file.name = f"voice_{media_id}.ogg"

        client = _get_whisper_client()
        model = "whisper-large-v3-turbo" if _whisper_backend == "groq" else "whisper-1"

        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )

        text = transcript.text.strip()
        logger.info(f"Transcribed via {_whisper_backend}: {text[:80]}...")
        return text

    except Exception as e:
        logger.error(f"Failed to transcribe voice note: {e}")
        return None


async def synthesize_speech(text: str, language: str = "en") -> Optional[bytes]:
    """Stub — TTS not yet configured (needs audio hosting)."""
    return None


async def send_voice_response(phone: str, text: str, language: str = "en") -> bool:
    """
    Send a voice response to a WhatsApp user.
    
    Args:
        phone: Recipient phone number (E.164 format)
        text: Text to convert and send
        language: Language code for TTS
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if text is short enough to benefit from voice
        if len(text) > 500:
            logger.info(f"Text too long for voice response ({len(text)} chars), recommend text-only")
            return False
        
        # Synthesize speech
        audio_bytes = await synthesize_speech(text, language)
        
        if not audio_bytes:
            logger.error("Failed to synthesize speech")
            return False
        
        # TODO: For production, upload audio to S3/R2 and get public URL
        # For now, return False as we don't have a way to serve the audio
        # This will be implemented in Phase 6 (Deployment) with S3/R2 setup
        logger.warning("Voice response synthesis works, but URL hosting not yet configured")
        logger.info(f"Would send {len(audio_bytes)} bytes of audio to {phone}")
        return False
            
    except Exception as e:
        logger.error(f"Failed to send voice response: {e}")
        return False


async def handle_voice_note(media_id: str) -> Optional[str]:
    """
    Handle incoming voice note: transcribe and return text.
    
    Args:
        media_id: Meta-provided media ID
        
    Returns:
        Transcribed text or None
    """
    try:
        logger.info(f"Processing voice note: {media_id}")
        
        # Transcribe
        text = await transcribe_voice_note(media_id)
        
        if text:
            logger.info(f"Voice note transcribed: {text[:50]}...")
            return text
        else:
            logger.error("Failed to transcribe voice note")
            return None
            
    except Exception as e:
        logger.error(f"Error handling voice note: {e}")
        return None


async def handle_image(media_id: str) -> Optional[bytes]:
    """
    Handle incoming image: download and return bytes.
    Can be used by Claude for vision analysis.
    
    Args:
        media_id: Meta-provided media ID
        
    Returns:
        Image bytes or None
    """
    try:
        logger.info(f"Processing image: {media_id}")
        
        # Download image
        image_data = await download_media(media_id)
        
        if image_data:
            logger.info(f"Image downloaded: {len(image_data)} bytes")
            return image_data
        else:
            logger.error("Failed to download image")
            return None
            
    except Exception as e:
        logger.error(f"Error handling image: {e}")
        return None
