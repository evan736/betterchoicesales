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
from sqlalchemy import text as sqlalchemy_text
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
# Messaging Service SID — when set, sends route through the service
# (attaches A2P 10DLC campaign registration). Without this, sends use
# the raw From number which carriers treat as unregistered traffic and
# reject with error 30034 even when the campaign is approved. Default
# is BCI's Messaging Service from memory; can be overridden per-env.
TWILIO_MESSAGING_SERVICE_SID = os.getenv(
    "TWILIO_MESSAGING_SERVICE_SID", "MG4c93a3c802cc173fd7c8dc49da044fb0"
)
TWILIO_STATUS_CALLBACK = os.getenv(
    "TWILIO_STATUS_CALLBACK",
    "https://better-choice-api.onrender.com/api/texting/status-callback",
)
TWILIO_API_URL = (
    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    if TWILIO_ACCOUNT_SID else ""
)

# 10DLC compliance: the first outbound message to any recipient must carry
# opt-out language. ~26 chars so there's plenty of room in a single segment.
OPTOUT_FOOTER = "\n\nReply STOP to opt out."


def _apply_optout_footer_if_first_contact(
    db: Optional[Session], to_e164: str, content: str
) -> str:
    """Return content with opt-out footer appended if this is the first
    outbound message to this recipient.

    - No db → fail safe: append footer (compliance-first default).
    - Content already mentions STOP/opt out → don't duplicate.
    - Already sent to this number before → skip.
    """
    if not content:
        content = ""

    # Caller already included opt-out language — don't duplicate.
    lowered = content.lower()
    if "reply stop" in lowered or "stop to opt" in lowered or "text stop" in lowered:
        return content

    # Without a db session we can't check prior history; append footer to
    # stay compliant rather than risk an unmarked first-contact message.
    if db is None:
        return content + OPTOUT_FOOTER

    try:
        row = db.execute(
            sqlalchemy_text(
                "SELECT 1 FROM text_messages "
                "WHERE phone_number = :phone AND direction = 'outbound' "
                "LIMIT 1"
            ),
            {"phone": to_e164},
        ).fetchone()
        already_texted = row is not None
    except Exception as e:
        logger.warning("opt-out footer history check failed for %s: %s — appending footer", to_e164, e)
        return content + OPTOUT_FOOTER

    if already_texted:
        return content
    return content + OPTOUT_FOOTER


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

    # A2P 10DLC compliance: first message to any recipient must include opt-out
    # language. After at least one prior outbound to the same number, no need
    # to repeat. Skip if the caller explicitly already put STOP/opt-out wording
    # in their content (avoid duplication).
    body_text = _apply_optout_footer_if_first_contact(
        db=db, to_e164=to_e164, content=content or "",
    )

    form_data: dict = {
        "To": to_e164,
        "Body": body_text[:1600],
        "StatusCallback": TWILIO_STATUS_CALLBACK,
    }
    # Prefer Messaging Service when configured. This is required for A2P
    # 10DLC traffic — sends with raw 'From' bypass the campaign
    # registration and get rejected with error 30034 by US carriers.
    # The Messaging Service must have +16305267478 attached as a sender
    # AND be linked to the approved A2P campaign in Twilio Console.
    # An explicit from_number arg overrides (legacy callers, e.g. when
    # Evan wants to test from a specific number).
    if from_number:
        form_data["From"] = from_number
    elif TWILIO_MESSAGING_SERVICE_SID:
        form_data["MessagingServiceSid"] = TWILIO_MESSAGING_SERVICE_SID
    else:
        form_data["From"] = TWILIO_SMS_NUMBER

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
                        from_number=form_data.get("From") or TWILIO_SMS_NUMBER,
                        content=body_text,
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
                twilio_msg = (
                    data.get("message")
                    or data.get("error_message")
                    or f"HTTP {resp.status_code}"
                )

                # Friendlier surface messages for the common A2P 10DLC errors so
                # Evan / producers see an actionable toast instead of raw Twilio prose.
                friendly_msg = twilio_msg
                if str(error_code) == "30034":
                    friendly_msg = (
                        "A2P 10DLC: our number isn't linked to the approved campaign's "
                        "Messaging Service. Attach +16305267478 in Twilio Console → "
                        "Messaging → Services → Senders."
                    )
                elif str(error_code) == "30035":
                    friendly_msg = (
                        "A2P 10DLC campaign is still being configured by Twilio. "
                        "Wait up to 24 hours after approval and try again."
                    )
                elif str(error_code) == "21610":
                    friendly_msg = (
                        "Recipient replied STOP and is opted out. They must text "
                        "START to +16305267478 before we can message them again."
                    )

                logger.error(
                    "Twilio SMS send failed: http=%s code=%s msg=%s",
                    resp.status_code, error_code, twilio_msg,
                )

                # Persist the failure so Evan can audit it after the fact, not
                # just chase it through Render logs. The row makes the error
                # visible in the /api/texting/messages endpoint.
                if db:
                    try:
                        _log_message(
                            db=db,
                            direction="outbound",
                            phone_number=to_e164,
                            from_number=form_data.get("From") or TWILIO_SMS_NUMBER,
                            content=body_text,
                            media_url=media_url,
                            message_handle="",
                            status="ERROR",
                            service="twilio",
                            customer_id=customer_id,
                            context=context,
                            sent_by=sent_by,
                        )
                        db.execute(
                            sqlalchemy_text(
                                "UPDATE text_messages SET error_code = :code, error_message = :msg "
                                "WHERE id = (SELECT id FROM text_messages "
                                "WHERE phone_number = :phone AND status = 'ERROR' AND message_handle = '' "
                                "ORDER BY id DESC LIMIT 1)"
                            ),
                            {"code": str(error_code) if error_code else None,
                             "msg": twilio_msg, "phone": to_e164},
                        )
                        db.commit()
                    except Exception as log_err:
                        logger.error("Failed to persist Twilio error row: %s", log_err)

                return {
                    "success": False,
                    "error": friendly_msg,
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
