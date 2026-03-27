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
    """
    from_phone = msg.get("from")
    msg_id = msg.get("id")
    msg_type = msg.get("type")  # "text", "audio", "image", "document", "button", etc.
    timestamp = msg.get("timestamp")

    logger.info(f"Message from {from_phone} (type={msg_type}, id={msg_id})")

    # TODO: Route to mode router (Commander vs Receptionist)
    # TODO: Extract message content based on type
    # TODO: Pass to agent.py for Claude processing
    # TODO: Send response via whatsapp.py

    pass


async def _handle_status(status: dict):
    """
    Handle message status updates (delivery, read).
    """
    msg_id = status.get("id")
    recipient_id = status.get("recipient_id")
    status_value = status.get("status")  # "sent", "delivered", "read"

    logger.debug(f"Status update: msg={msg_id}, status={status_value}")

    # TODO: Update message status in database if needed
    pass


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
