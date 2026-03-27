"""
Meta Cloud API helpers for sending/receiving WhatsApp messages.
Wrapper around Meta's graph.facebook.com REST API.
"""

import httpx
import logging
import json
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

META_API_URL = "https://graph.facebook.com/v18.0"


# ============================================================================
# Send Message
# ============================================================================

async def send_text(phone: str, message: str) -> bool:
    """
    Send text message via Meta Cloud API.

    Args:
        phone: Recipient phone in E.164 format (+919XXXXXXXXX)
        message: Text message to send

    Returns:
        True if sent successfully, False otherwise
    """
    url = f"{META_API_URL}/{settings.meta_phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {
            "body": message
        }
    }

    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()

            result = response.json()
            msg_id = result.get("messages", [{}])[0].get("id")
            logger.info(f"Text sent to {phone}, msg_id={msg_id}")
            return True

    except httpx.HTTPError as e:
        logger.error(f"Failed to send text to {phone}: {e}")
        return False


async def send_audio(phone: str, audio_data) -> bool:
    """
    Send audio message via Meta Cloud API.

    Args:
        phone: Recipient phone in E.164 format
        audio_data: Either URL (str) to audio file or raw audio bytes

    Returns:
        True if sent successfully, False otherwise
    """
    url = f"{META_API_URL}/{settings.meta_phone_number_id}/messages"

    # If audio_data is bytes, we'd need to upload to Meta first
    # For now, assume URL or use local upload
    if isinstance(audio_data, bytes):
        # TODO: Upload to Meta servers and get URL
        # For now, return False (not implemented)
        logger.warning("Direct bytes upload not yet implemented, use URL instead")
        return False
    
    audio_url = audio_data  # Assume it's a URL string

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "audio",
        "audio": {
            "link": audio_url
        }
    }

    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()

            result = response.json()
            msg_id = result.get("messages", [{}])[0].get("id")
            logger.info(f"Audio sent to {phone}, msg_id={msg_id}")
            return True

    except httpx.HTTPError as e:
        logger.error(f"Failed to send audio to {phone}: {e}")
        return False


# ============================================================================
# Download Media
# ============================================================================

async def download_media(media_id: str) -> Optional[bytes]:
    """
    Download media from Meta servers.

    Args:
        media_id: Media ID returned in webhook message

    Returns:
        Media bytes, or None if download failed
    """
    url = f"{META_API_URL}/{media_id}"

    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
    }

    try:
        async with httpx.AsyncClient() as client:
            # First, get the media URL
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()

            media_data = response.json()
            media_url = media_data.get("url")

            if not media_url:
                logger.error(f"No URL in media response: {media_data}")
                return None

            # Then download the actual media
            media_response = await client.get(media_url, timeout=30.0)
            media_response.raise_for_status()

            logger.info(f"Media downloaded: {media_id}, size={len(media_response.content)}")
            return media_response.content

    except httpx.HTTPError as e:
        logger.error(f"Failed to download media {media_id}: {e}")
        return None


# ============================================================================
# Parse Webhook Payload
# ============================================================================

def parse_message_payload(message: dict, metadata: dict) -> dict:
    """
    Parse incoming message from Meta webhook.

    Args:
        message: Message object from webhook
        metadata: Metadata containing business account info

    Returns:
        Normalized message dict with extracted fields
    """
    from_phone = message.get("from")
    msg_id = message.get("id")
    msg_type = message.get("type")
    timestamp = int(message.get("timestamp", 0))

    parsed = {
        "phone": from_phone,
        "msg_id": msg_id,
        "type": msg_type,
        "timestamp": timestamp,
        "content": None,
        "media_id": None,
    }

    # Extract content based on message type
    if msg_type == "text":
        parsed["content"] = message.get("text", {}).get("body")

    elif msg_type == "audio":
        audio = message.get("audio", {})
        parsed["media_id"] = audio.get("id")
        parsed["mime_type"] = audio.get("mime_type")

    elif msg_type == "image":
        image = message.get("image", {})
        parsed["media_id"] = image.get("id")
        parsed["mime_type"] = image.get("mime_type")

    elif msg_type == "document":
        document = message.get("document", {})
        parsed["media_id"] = document.get("id")
        parsed["mime_type"] = document.get("mime_type")
        parsed["filename"] = document.get("filename")

    elif msg_type == "button":
        button = message.get("button", {})
        parsed["content"] = button.get("text")
        parsed["button_payload"] = button.get("payload")

    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        button_reply = interactive.get("button_reply", {})
        list_reply = interactive.get("list_reply", {})
        parsed["content"] = button_reply.get("title") or list_reply.get("title")

    return parsed
