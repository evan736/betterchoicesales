"""Twilio SMS service for ORBIT — provider module for the Texting UI.

Drop-in replacement for loopmessage.py — exposes the same async send_message()
signature and re-exports the provider-agnostic helpers (phone normalization,
customer matching, message logging, conversation history) from loopmessage.py
so the API layer and schedulers do not need to change.
"""
import os
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.services.loopmessage import (
    normalize_phone,
    phones_match,
    match_customer_by_phone,
    _log_message,
    update_message_status,
    get_conversation,
    send_bulk,
)

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_NUMBER = os.getenv("TWILIO_SMS_NUMBER", "+16305267478")
TWILIO_STATUS_CALLBACK = os.getenv(
    "TWILIO_STATUS_CALLBACK",
    "https://better-choice-api.onrender.com/api/texting/status-callback",
)
TWILIO_API_URL = (
    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    if TWILIO_ACCOUNT_SID else ""
)


async def send_message(
    to_number: str,
    content: str,
    media_url: Optional[str] = None,
    from_number: Optional[str] = None,
    db: Optional[Session] = None,
    customer_id: Optional[int] = None,
    context: Optional[str] = None,
    sent_by: Optional[str] = None,
) -> dict:
    """Send an SMS via Twilio. Mirrors the loopmessage.send_message contract."""
    to_e164 = normalize_phone(to_number)
    if not to_e164:
        return {"success": False, "error": f"Invalid phone number: {to_number}"}
    if not TWILIO_ACCOUNT_SID:
        return {"success": False, "error": "TWILIO_ACCOUNT_SID not configured"}
    if not TWILIO_AUTH_TOKEN:
        return {"success": False, "error": "TWILIO_AUTH_TOKEN not configured"}
    if not TWILIO_SMS_NUMBER:
        return {"success": False, "error": "TWILIO_SMS_NUMBER not configured"}

    form_data: dict = {
        "From": from_number or TWILIO_SMS_NUMBER,
        "To": to_e164,
        "Body": (content or "")[:1600],
        "StatusCallback": TWILIO_STATUS_CALLBACK,
    }
    if media_url:
        form_data["MediaUrl"] = media_url

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                TWILIO_API_URL,
                data=form_data,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            )
            try:
                data = resp.json()
            except Exception:
                data = {}

            if resp.status_code in (200, 201):
                message_handle = data.get("sid", "")
                status = (data.get("status") or "QUEUED").upper()
                logger.info(
                    "Twilio SMS sent: to=%s sid=%s status=%s",
                    to_e164, message_handle, status,
                )
                if db:
                    _log_message(
                        db=db,
                        direction="outbound",
                        phone_number=to_e164,
                        from_number=form_data["From"],
                        content=content,
                        media_url=media_url,
                        message_handle=message_handle,
                        status=status,
                        service="twilio",
                        customer_id=customer_id,
                        context=context,
                        sent_by=sent_by,
                    )
                return {
                    "success": True,
                    "message_handle": message_handle,
                    "status": status,
                    "service": "twilio",
                    "was_downgraded": False,
                }
            else:
                error_code = data.get("code")
                error_msg = (
                    data.get("message")
                    or data.get("error_message")
                    or f"HTTP {resp.status_code}"
                )
                logger.error(
                    "Twilio SMS send failed: http=%s code=%s msg=%s",
                    resp.status_code, error_code, error_msg,
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "error_code": error_code,
                    "status_code": resp.status_code,
                }
    except Exception as e:
        logger.error("Twilio SMS send error: %s", e)
        return {"success": False, "error": str(e)}


def parse_inbound_webhook(payload: dict) -> dict:
    """Map Twilio inbound SMS webhook (form-encoded) to the shape api/texting.py expects."""
    num_media = 0
    try:
        num_media = int(payload.get("NumMedia", "0") or 0)
    except (TypeError, ValueError):
        num_media = 0
    media_url = payload.get("MediaUrl0", "") if num_media > 0 else ""
    return {
        "alert_type": "message_inbound",
        "from_number": payload.get("From", ""),
        "to_number": payload.get("To", ""),
        "content": payload.get("Body", ""),
        "media_url": media_url,
        "message_handle": payload.get("MessageSid", ""),
        "service": "twilio",
    }


_TWILIO_STATUS_MAP = {
    "queued": "QUEUED",
    "accepted": "QUEUED",
    "sending": "QUEUED",
    "sent": "SENT",
    "delivered": "DELIVERED",
    "undelivered": "ERROR",
    "failed": "ERROR",
    "canceled": "ERROR",
    "receiving": "RECEIVED",
    "received": "RECEIVED",
    "read": "READ",
}


def parse_status_callback(payload: dict) -> dict:
    """Map Twilio delivery status callback (form-encoded) to our normalized shape."""
    twilio_status = (payload.get("MessageStatus") or "").lower()
    normalized = _TWILIO_STATUS_MAP.get(twilio_status, twilio_status.upper())
    return {
        "message_handle": payload.get("MessageSid", ""),
        "status": normalized,
        "error_code": payload.get("ErrorCode") or None,
        "error_message": payload.get("ErrorMessage") or "",
        "service": "twilio",
    }
