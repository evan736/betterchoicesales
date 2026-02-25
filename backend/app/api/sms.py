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

BCI_OFFICE_NUMBER = "+16305280941"  # Main MIA/Retell number for reference in replies


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
    <Message>This number is not monitored for text messages. For assistance, please call Better Choice Insurance Group at (630) 528-0941 or visit betterchoiceins.com</Message>
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
            f"If you need immediate assistance, please call us at (630) 528-0941."
        )
    elif request_type == "policy_change":
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"Better Choice Insurance Group here — we received your policy change request"
            f"{' for your ' + carrier + ' policy' if carrier else ''}. "
            f"Our service team will process this and follow up with you. "
            f"Questions? Call us at (630) 528-0941."
        )
    elif request_type == "document_request":
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"Better Choice Insurance Group here — we received your document request. "
            f"Our team will email your documents shortly. "
            f"Questions? Call us at (630) 528-0941."
        )
    else:
        body = (
            f"Hi{' ' + first_name if first_name else ''}! "
            f"This is Better Choice Insurance Group. We received your message and "
            f"a member of our team will follow up with you shortly. "
            f"Need immediate help? Call (630) 528-0941."
        )

    return send_sms(caller_phone, body)


# ── 3. CANCELLATION ALERT SMS TO STAFF ─────────────────────────────

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
