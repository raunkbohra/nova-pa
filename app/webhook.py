"""
FastAPI webhook server for Meta Cloud API (WhatsApp).
Handles incoming messages, verification, and health checks.
"""

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import logging
import json
from app.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="NOVA WhatsApp Assistant")


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "NOVA WhatsApp Assistant",
        "mode": "running"
    }


@app.get("/privacy")
async def privacy_policy():
    """Privacy policy"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 20px">
    <h1>NOVA Privacy Policy</h1>
    <p>NOVA is a private WhatsApp assistant for personal use by Raunak Bohra.</p>
    <p><strong>Data collected:</strong> WhatsApp messages sent to this assistant are processed to generate responses. Messages are stored on a private server and not shared with third parties.</p>
    <p><strong>Data retention:</strong> Conversation history is retained for context and can be deleted upon request.</p>
    <p><strong>Contact:</strong> raunkbohra@gmail.com</p>
    </body></html>
    """)


# ============================================================================
# Meta Webhook Verification
# ============================================================================

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = None,
    hub_challenge: str = None,
    hub_verify_token: str = None,
):
    """
    Verify webhook with Meta Cloud API.
    Meta sends a GET request during webhook setup.
    """
    if hub_mode != "subscribe":
        logger.warning(f"Invalid hub_mode: {hub_mode}")
        raise HTTPException(status_code=403, detail="Invalid hub_mode")

    if hub_verify_token != settings.meta_verify_token:
        logger.warning(f"Invalid verify token received")
        raise HTTPException(status_code=403, detail="Invalid verify token")

    logger.info("Webhook verified successfully")
    return int(hub_challenge)


# ============================================================================
# Incoming Messages
# ============================================================================

@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """
    Receive incoming messages from Meta Cloud API.
    Process asynchronously in background (return 200 immediately).
    """
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.debug(f"Received webhook: {json.dumps(body, indent=2)}")

    # Meta returns 200 OK immediately, process async in background
    background_tasks.add_task(_process_message, body)

    return JSONResponse({"status": "received"}, status_code=200)


async def _process_message(body: dict):
    """
    Background task to process incoming message.
    Runs after 200 OK is sent to Meta.
    """
    try:
        # Extract message details from Meta webhook payload
        # Structure: body -> entry -> changes -> value -> messages/statuses

        if body.get("object") != "whatsapp_business_account":
            logger.info(f"Non-WhatsApp object: {body.get('object')}")
            return

        entries = body.get("entry", [])
        if not entries:
            logger.info("No entries in webhook")
            return

        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                # Check for incoming messages
                messages = value.get("messages", [])
                if messages:
                    for msg in messages:
                        await _handle_incoming_message(msg, value)

                # Check for statuses (delivery, read confirmations)
                statuses = value.get("statuses", [])
                if statuses:
                    for status in statuses:
                        await _handle_status(status)

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)


async def _handle_incoming_message(msg: dict, metadata: dict):
    """
    Handle incoming WhatsApp message.
    Extract phone, message type, content, etc.
    Routes to Commander or Receptionist mode based on sender.
    """
    from app.agent import Agent
    from app.memory import AsyncSessionLocal
    from app.voice import handle_voice_note, handle_image
    from sqlalchemy.ext.asyncio import AsyncSession
    
    from_phone = msg.get("from")
    msg_id = msg.get("id")
    msg_type = msg.get("type")  # "text", "audio", "image", "document", "button", etc.
    timestamp = msg.get("timestamp")

    logger.info(f"Message from {from_phone} (type={msg_type}, id={msg_id})")

    try:
        # Extract message content based on type
        content = None
        is_voice = False
        
        if msg_type == "text":
            content = msg.get("text", {}).get("body", "")
        
        elif msg_type == "audio":
            # Voice note - transcribe it
            media = msg.get("audio", {})
            media_id = media.get("id")
            if media_id:
                content = await handle_voice_note(media_id)
                is_voice = True
                if content:
                    content = f"[Voice note transcribed] {content}"
                else:
                    content = "[Failed to transcribe voice note]"
        
        elif msg_type == "image":
            # Image - download and note it (Claude can analyze if provided)
            media = msg.get("image", {})
            media_id = media.get("id")
            caption = media.get("caption", "")
            if media_id:
                await handle_image(media_id)
            content = f"[Image received{': ' + caption if caption else ''}]"
        
        elif msg_type == "document":
            # Document
            media = msg.get("document", {})
            content = f"[Document received: {media.get('filename', 'unknown')}]"
        
        elif msg_type == "button":
            # Button response
            button = msg.get("button", {})
            content = button.get("text", "Button pressed")
        
        else:
            # Unsupported type
            logger.warning(f"Unsupported message type: {msg_type}")
            content = f"[Message type not supported: {msg_type}]"
        
        if not content:
            logger.warning(f"No content extracted from message {msg_id}")
            return
        
        # Determine mode: Commander vs Receptionist
        commander_phones = {settings.raunak_phone}
        if settings.raunak_phone2:
            commander_phones.add(settings.raunak_phone2.strip())
        is_commander = from_phone in commander_phones
        
        # Get database session and agent
        async with AsyncSessionLocal() as session:
            agent = Agent()
            
            # Process message through appropriate mode
            if is_commander:
                logger.info(f"Commander Mode: {from_phone}")
                response = await agent.process_commander_message(content, session)
            else:
                logger.info(f"Receptionist Mode: {from_phone}")
                response = await agent.process_receptionist_message(from_phone, content, session)
            
            # Send response back
            from app.whatsapp import send_text
            await send_text(from_phone, response)
    
    except Exception as e:
        logger.error(f"Error handling incoming message: {e}", exc_info=True)
        # Send error response
        from app.whatsapp import send_text
        await send_text(from_phone, "Sorry, I encountered an error processing your message. Please try again.")


async def _handle_status(status: dict):
    """
    Handle message status updates (delivery, read).
    """
    msg_id = status.get("id")
    recipient_id = status.get("recipient_id")
    status_value = status.get("status")  # "sent", "delivered", "read", "failed"
    errors = status.get("errors", [])

    if errors:
        logger.error(f"Message delivery FAILED: msg={msg_id}, to={recipient_id}, errors={errors}")
    else:
        logger.info(f"Message status: {status_value} → {recipient_id} (msg={msg_id})")


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        {"error": "Internal server error"},
        status_code=500
    )
