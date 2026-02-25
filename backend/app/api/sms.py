"""SMS routes for MIA AI Receptionist notifications.

Handles:
1. Inbound SMS auto-reply — "This number does not accept replies"
2. Post-call SMS confirmation — sent to callers after callback/message requests
3. Cancellation alert SMS — sent to BCI staff for urgent cancellation requests

Uses Twilio API directly. Number: (630) 526-7478 (SMS only, no voice).
"""
import os
import logging
from typing import Optional

import requests
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sms", tags=["sms"])

# Twilio config — loaded from environment variables
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_NUMBER = os.environ.get("TWILIO_SMS_NUMBER", "+16305267478")
TWILIO_API_URL = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"

BCI_OFFICE_NUMBER = "+18479085665"  # Main MIA/Retell number for reference in replies


# ── Helpers ─────────────────────────────────────────────────────────

def send_sms(to: str, body: str) -> dict:
    """Send an SMS via Twilio.

    Args:
        to: Phone number in E.164 format (+1XXXXXXXXXX)
        body: Message text (max 1600 chars, auto-splits into segments)

    Returns:
        {"success": True, "sid": "SM..."} or {"success": False, "error": "..."}
    """
    # Normalize to E.164 if not already
    digits = "".join(c for c in to if c.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    if not digits.startswith("1"):
        digits = "1" + digits
    to_number = f"+{digits}"

    try:
        resp = requests.post(
            TWILIO_API_URL,
            auth=(TWILIO_SID, TWILIO_AUTH),
            data={
                "From": TWILIO_SMS_NUMBER,
                "To": to_number,
                "Body": body[:1600],
            },
        )
        data = resp.json()
        if resp.status_code in (200, 201):
            logger.info("SMS sent to %s: sid=%s", to_number, data.get("sid"))
            return {"success": True, "sid": data.get("sid")}
        else:
            logger.error("SMS send failed: %s %s", resp.status_code, data.get("message"))
            return {"success": False, "error": data.get("message", str(resp.status_code))}
    except Exception as e:
        logger.error("SMS send error: %s", e)
        return {"success": False, "error": str(e)}


# ── 1. INBOUND SMS AUTO-REPLY ──────────────────────────────────────

@router.post("/inbound")
async def inbound_sms(request: Request):
    """Auto-reply to any inbound SMS with a 'not monitored' message.

    Twilio expects a TwiML response.
    """
    try:
        form = await request.form()
        from_number = form.get("From", "")
        body = form.get("Body", "")
        logger.info("Inbound SMS from %s: %s", from_number, body[:100])
    except Exception:
        pass

    # Return TwiML auto-reply
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>This number is not monitored for text messages. For assistance, please call Better Choice Insurance Group at (847) 908-5665.</Message>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


# ── 2. POST-CALL SMS CONFIRMATION ──────────────────────────────────

def send_post_call_sms(
    caller_phone: str,
    caller_name: str,
    request_type: str = "callback",
    carrier: str = "",
) -> dict:
    """Send a post-call SMS confirmation to the caller.

    Called from the post-call webhook when a callback or message was taken.
    """
    first_name = (caller_name or "").split()[0] if caller_name else ""

    if request_type == "callback":
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"This is Better Choice Insurance Group confirming we received your callback request. "
            f"A member of our team will reach out to you shortly. "
            f"If you need immediate assistance, please call us at (847) 908-5665."
        )
    elif request_type == "policy_change":
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"Better Choice Insurance Group here — we received your policy change request"
            f"{' for your ' + carrier + ' policy' if carrier else ''}. "
            f"Our service team will process this and follow up with you. "
            f"Questions? Call us at (847) 908-5665."
        )
    elif request_type == "document_request":
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"Better Choice Insurance Group here — we received your document request. "
            f"Our team will email your documents shortly. "
            f"Questions? Call us at (847) 908-5665."
        )
    else:
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"This is Better Choice Insurance Group. We received your message and "
            f"a member of our team will follow up with you shortly. "
            f"Need immediate help? Call (847) 908-5665."
        )

    return send_sms(caller_phone, body)


# ── 3. MID-CALL SMS (Retell Tool) ──────────────────────────────────

@router.post("/send-to-caller")
async def send_sms_to_caller(request: Request):
    """Send an SMS to the caller mid-call. Called by MIA as a Retell custom tool.

    Retell sends: {args: {caller_name, caller_phone, message_type, custom_message}, call: {...}}

    message_type options:
      - confirmation: "We received your request and our team will follow up shortly."
      - document_request: "We received your document request. Our team will email your documents shortly."
      - callback: "We received your callback request. A team member will reach out shortly."
      - policy_change: "We received your policy change request. Our team will process and follow up."
      - custom: Uses custom_message field
    """
    try:
        body = await request.json()
        args = body.get("args", {})
        call_info = body.get("call", {})

        caller_name = args.get("caller_name", "")
        caller_phone = args.get("caller_phone", call_info.get("from_number", ""))
        message_type = args.get("message_type", "confirmation")
        custom_message = args.get("custom_message", "")

        if not caller_phone:
            return {"result": "No phone number available to send SMS."}

        first_name = (caller_name or "").split()[0] if caller_name else ""
        greeting = f"Hi{' ' + first_name if first_name else ''}! "
        sign_off = " Questions? Call us at (847) 908-5665."

        messages = {
            "confirmation": (
                f"{greeting}This is Better Choice Insurance Group. "
                f"We received your request and our team will follow up with you shortly.{sign_off}"
            ),
            "callback": (
                f"{greeting}This is Better Choice Insurance Group confirming we received your callback request. "
                f"A member of our team will reach out to you shortly. "
                f"If you need immediate assistance, please call us at (847) 908-5665."
            ),
            "document_request": (
                f"{greeting}Better Choice Insurance Group here — we received your document request. "
                f"Our team will email your documents shortly.{sign_off}"
            ),
            "policy_change": (
                f"{greeting}Better Choice Insurance Group here — we received your policy change request. "
                f"Our service team will process this and follow up with you.{sign_off}"
            ),
        }

        if message_type == "custom" and custom_message:
            sms_body = custom_message[:1600]
        else:
            sms_body = messages.get(message_type, messages["confirmation"])

        result = send_sms(caller_phone, sms_body)

        if result.get("success"):
            logger.info("Mid-call SMS sent to %s (type=%s)", caller_phone, message_type)
            return {"result": f"Text message sent successfully to {caller_phone}."}
        else:
            logger.error("Mid-call SMS failed: %s", result.get("error"))
            return {"result": "I wasn't able to send the text message right now, but our team will follow up with you."}

    except Exception as e:
        logger.error("Mid-call SMS error: %s", e)
        return {"result": "I wasn't able to send the text message right now, but our team will follow up with you."}


# ── 4. CANCELLATION ALERT SMS TO STAFF ─────────────────────────────

def send_cancellation_alert_sms(
    caller_name: str,
    caller_phone: str,
    carrier: str = "",
    staff_numbers: list[str] | None = None,
) -> list[dict]:
    """Send urgent SMS to BCI staff when a cancellation request comes in.

    Called from the callback-request handler when urgency=urgent + CANCELLATION.
    """
    if staff_numbers is None:
        # Default: send to service team. Update these numbers as needed.
        staff_numbers = []  # Add BCI staff cell numbers here when ready

    if not staff_numbers:
        logger.info("No staff numbers configured for cancellation SMS alerts")
        return []

    body = (
        f"🔴 CANCELLATION ALERT\n"
        f"{caller_name} ({caller_phone})"
        f"{' — ' + carrier if carrier else ''}\n"
        f"Customer is requesting to cancel and is being transferred to the office NOW."
    )

    results = []
    for number in staff_numbers:
        result = send_sms(number, body)
        results.append({"number": number, **result})

    return results


# ── 4. HEALTH CHECK ────────────────────────────────────────────────

@router.get("/health")
async def sms_health():
    """SMS service health check."""
    return {
        "status": "ok",
        "sms_number": TWILIO_SMS_NUMBER,
        "provider": "twilio",
    }
