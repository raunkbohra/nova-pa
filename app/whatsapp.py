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

META_API_URL = "https://graph.facebook.com/v22.0"

# Tracks recent outbound messages so the delivery-failure webhook can retry
# with a template if error 131047 fires.
# { msg_id: {"phone": str, "message": str, "contact_name": str} }
_pending_delivery: dict[str, dict] = {}


# ============================================================================
# Send Message
# ============================================================================

async def send_text(phone: str, message: str, contact_name: str = "there") -> tuple[bool, int | None]:
    """
    Send text message via Meta Cloud API.

    Returns:
        (True, None) on success, (False, error_code) on failure.
        error_code 131047 means the 24-hour messaging window has expired.
    """
    url = f"{META_API_URL}/{settings.meta_phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)

            if response.status_code != 200:
                error_data = response.json()
                error_code = (
                    error_data.get("error", {}).get("code")
                    or error_data.get("error", {}).get("error_data", {}).get("details")
                )
                # Normalise to int if possible
                try:
                    error_code = int(error_code)
                except (TypeError, ValueError):
                    error_code = None
                logger.error(f"Meta API error sending to {phone}: {error_data}")
                return False, error_code

            result = response.json()
            msg_id = result.get("messages", [{}])[0].get("id")
            logger.info(f"Text sent to {phone}, msg_id={msg_id}")
            if msg_id:
                _pending_delivery[msg_id] = {"phone": phone, "message": message, "contact_name": contact_name}
            return True, None

    except httpx.HTTPError as e:
        logger.error(f"Failed to send text to {phone}: {e}")
        return False, None


# ============================================================================
# Template Messages
# ============================================================================

# Maps intent keywords → template name.
# Order matters: more specific matches first.
_TEMPLATE_ROUTING = [
    (["meeting", "reschedule", "confirm meeting", "booked"], "confirm_meeting"),
    (["remind", "reminder", "don't forget", "see you"], "remind_meeting"),
    (["after meeting", "post meeting", "follow up after", "great meeting"], "after_meeting"),
    (["introduce", "intro", "first time", "reaching out", "cold"], "intro_contact"),
    (["follow up", "followup", "following up", "checking in"], "followup_contact"),
    (["catch up", "catchup", "reconnect", "long time"], "catch_up"),
    (["not available", "busy", "unavailable", "can't meet", "cannot meet"], "not_available"),
    (["iwishbag", "bag", "order", "product", "customer"], "iwishbag_customer"),
    (["meet", "call", "schedule", "availability"], "request_meeting"),
    (["re-engage", "silent", "haven't heard", "introduce yourself"], "nova_intro"),
]
_DEFAULT_TEMPLATE = "ping_contact"

# Template component layouts — which variables each template's body expects.
# Format: list of body text variable values ({{1}}, {{2}}, ...)
# We fill them from the original message text.
_TEMPLATE_BODY_VARS: dict[str, list[str]] = {
    "ping_contact":       ["{name}", "{message}"],
    "followup_contact":   ["{name}", "{message}"],
    "request_meeting":    ["{name}", "{message}"],
    "nova_intro":         ["{name}"],
    "remind_meeting":     ["{name}", "{meeting_time}"],
    "confirm_meeting":    ["{name}", "{meeting_time}"],
    "intro_contact":      ["{name}"],
    "after_meeting":      ["{name}", "{message}"],
    "not_available":      ["{name}"],
    "catch_up":           ["{name}", "{message}"],
    "iwishbag_customer":  ["{name}", "{message}"],
}


def _pick_template(message: str) -> str:
    """Choose the best-matching template name based on message content."""
    lower = message.lower()
    for keywords, template_name in _TEMPLATE_ROUTING:
        if any(kw in lower for kw in keywords):
            return template_name
    return _DEFAULT_TEMPLATE


async def send_template(
    phone: str,
    message: str,
    contact_name: str = "there",
    template_name: str | None = None,
    meeting_time: str = "",
) -> bool:
    """
    Send an approved WhatsApp template message.

    Automatically selects the best template if template_name is not provided.
    Fills body variables from message text and contact_name.
    """
    if not template_name:
        template_name = _pick_template(message)

    url = f"{META_API_URL}/{settings.meta_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }

    # Build variable substitution list
    var_schema = _TEMPLATE_BODY_VARS.get(template_name, ["{name}", "{message}"])
    params = []
    for var in var_schema:
        if var == "{name}":
            params.append({"type": "text", "text": contact_name})
        elif var == "{message}":
            # Trim message to fit WhatsApp limits
            params.append({"type": "text", "text": message[:1000]})
        elif var == "{meeting_time}":
            params.append({"type": "text", "text": meeting_time or "our scheduled time"})

    components = []
    if params:
        components.append({"type": "body", "parameters": params})

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en_US"},
            "components": components,
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code != 200:
                logger.error(f"Template send failed ({template_name}) to {phone}: {response.text}")
                return False
            msg_id = response.json().get("messages", [{}])[0].get("id")
            logger.info(f"Template '{template_name}' sent to {phone}, msg_id={msg_id}")
            return True
    except httpx.HTTPError as e:
        logger.error(f"Template send error to {phone}: {e}")
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

            # Then download the actual media (requires auth header too)
            media_response = await client.get(media_url, headers=headers, timeout=30.0)
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
