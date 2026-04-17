"""LoopMessage iMessage service for ORBIT.

Drop-in replacement for sendblue.py — exposes the same async send_message()
signature and returns the same result dict shape so the API layer can switch
providers via a single env var (TEXTING_PROVIDER).

LoopMessage API:
- Host: https://server.loopmessage.com
- Auth: single `Authorization` header with the API key (LoopMessage
  issues only one credential per account; no separate secret key).
- Send endpoint: POST /api/v1/message/send/
- Body: recipient (E.164 or email), text, sender_name (UUID),
  attachments (array of URLs), optional status_callback.
- Docs: https://docs-legacy.loopmessage.com/imessage-conversation-api/send-message

Webhook payload shape (inbound + status) uses `alert_type` to discriminate
event kinds. Status callback URL must be able to parse LoopMessage-shaped
payloads, so we point it at the unified LoopMessage webhook endpoint rather
than the Sendblue status-callback route (which reads Sendblue field names).
"""
import os
import re
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────
LOOPMESSAGE_API_KEY = os.getenv("LOOPMESSAGE_API_KEY", "")
LOOPMESSAGE_SENDER_ID = os.getenv("LOOPMESSAGE_SENDER_ID", "")
LOOPMESSAGE_FROM_NUMBER = os.getenv("LOOPMESSAGE_FROM_NUMBER", "")
LOOPMESSAGE_BASE_URL = "https://server.loopmessage.com"
LOOPMESSAGE_STATUS_CALLBACK = os.getenv(
    "LOOPMESSAGE_STATUS_CALLBACK",
    "https://better-choice-api.onrender.com/api/texting/webhook"
)


# ── Phone normalization (identical contract to sendblue) ───────────

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) > 10:
        return f"+{digits}"
    return ""


def phones_match(phone_a: str, phone_b: str) -> bool:
    return normalize_phone(phone_a) == normalize_phone(phone_b) and normalize_phone(phone_a) != ""


# ── Send message ────────────────────────────────────────────────────

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
    """Send an iMessage via LoopMessage.

    Returns a dict matching sendblue.send_message shape:
      {success, message_handle, status, service, was_downgraded}
    so callers (API layer, schedulers) do not need to change.
    """
    to_e164 = normalize_phone(to_number)
    if not to_e164:
        return {"success": False, "error": f"Invalid phone number: {to_number}"}

    if not LOOPMESSAGE_API_KEY:
        return {"success": False, "error": "LOOPMESSAGE_API_KEY not configured"}
    if not LOOPMESSAGE_SENDER_ID:
        return {"success": False, "error": "LOOPMESSAGE_SENDER_ID not configured"}

    payload: dict = {
        "recipient": to_e164,
        "text": content or "",
        "sender_name": LOOPMESSAGE_SENDER_ID,
        "status_callback": LOOPMESSAGE_STATUS_CALLBACK,
    }
    if media_url:
        # LoopMessage accepts attachments as an array of URLs (max 3).
        payload["attachments"] = [media_url]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LOOPMESSAGE_BASE_URL}/api/v1/message/send/",
                json=payload,
                headers={
                    "Authorization": LOOPMESSAGE_API_KEY,
                    "Content-Type": "application/json",
                },
            )
            try:
                data = resp.json()
            except Exception:
                data = {}

            if resp.status_code == 200 and data.get("success"):
                # LoopMessage returns message_id (UUID); normalize to message_handle
                message_handle = (
                    data.get("message_id")
                    or data.get("messageId")
                    or data.get("message_handle")
                    or ""
                )
                # LoopMessage accepted = queued for delivery. Final state
                # arrives via webhook (message_sent / message_failed).
                status = "QUEUED"

                logger.info(
                    "LoopMessage sent: to=%s handle=%s",
                    to_e164, message_handle
                )

                if db:
                    _log_message(
                        db=db, direction="outbound", phone_number=to_e164,
                        from_number=LOOPMESSAGE_FROM_NUMBER or (from_number or ""),
                        content=content, media_url=media_url,
                        message_handle=message_handle, status=status,
                        service="loopmessage",
                        customer_id=customer_id, context=context, sent_by=sent_by,
                    )

                return {
                    "success": True,
                    "message_handle": message_handle,
                    "status": status,
                    "service": "loopmessage",
                    "was_downgraded": False,  # LoopMessage is iMessage-only
                }
            else:
                # Failure paths: 400/402/5xx, or 200 with success=false.
                # The `message` field from LoopMessage is informational-only
                # per their docs — map their `code` to a human-readable hint.
                error_code = data.get("code")
                error_msg = (
                    data.get("message")
                    or data.get("error_message")
                    or data.get("error")
                    or _loopmessage_error_hint(error_code)
                    or f"HTTP {resp.status_code}"
                )
                logger.error(
                    "LoopMessage send failed: http=%s code=%s msg=%s",
                    resp.status_code, error_code, error_msg
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "error_code": error_code,
                    "status_code": resp.status_code,
                }

    except Exception as e:
        logger.error("LoopMessage send error: %s", e)
        return {"success": False, "error": str(e)}


# ── Error code → human hint ────────────────────────────────────────

_LOOPMESSAGE_ERROR_HINTS = {
    100: "Bad request",
    110: "Missing credentials in request",
    120: "One or more required parameters missing",
    125: "Authorization key invalid or missing (LOOPMESSAGE_API_KEY)",
    130: "Secret key invalid or missing (LoopMessage no longer requires this for your account)",
    140: "No text in request",
    150: "No recipient in request",
    160: "Invalid recipient",
    170: "Invalid recipient email",
    180: "Invalid recipient phone number",
    190: "Phone number is not mobile",
    210: "Sender name not specified",
    220: "Invalid sender name",
    230: "Internal error using the sender name",
    240: "Sender name not activated or unpaid",
    270: "Recipient has blocked messages",
    300: "Dedicated sender name required for this message type",
    330: "Rate-limited — too many messages to dormant recipients (Apple suspension risk)",
    400: "No credits remaining on LoopMessage balance",
    500: "LoopMessage account suspended",
    510: "LoopMessage account blocked",
    530: "LoopMessage account suspended due to debt",
    540: "No active purchased sender name",
    545: "Sender name suspended by Apple",
    550: "Recipient must be added as sandbox contact (or sender not upgraded)",
    560: "Recipient must initiate the conversation first",
    570: "API method deprecated",
}


def _loopmessage_error_hint(code) -> Optional[str]:
    """Return a human-readable description for a LoopMessage error code."""
    if code is None:
        return None
    try:
        return _LOOPMESSAGE_ERROR_HINTS.get(int(code))
    except (TypeError, ValueError):
        return None


# ── Bulk send ───────────────────────────────────────────────────────

async def send_bulk(
    messages: list[dict],
    db: Optional[Session] = None,
    context: Optional[str] = None,
) -> dict:
    results, sent, failed = [], 0, 0
    for msg in messages:
        result = await send_message(
            to_number=msg["to_number"], content=msg["content"],
            media_url=msg.get("media_url"), db=db,
            customer_id=msg.get("customer_id"), context=context,
            sent_by=msg.get("sent_by"),
        )
        results.append(result)
        if result.get("success"): sent += 1
        else: failed += 1
    return {"sent": sent, "failed": failed, "results": results}


# ── Customer matching (identical logic — shared table `customers`) ──

def match_customer_by_phone(db: Session, phone: str) -> Optional[dict]:
    from app.models.customer import Customer
    from app.models.sale import Sale

    normalized = normalize_phone(phone)
    if not normalized:
        return None
    digits_10 = normalized[-10:]

    customer = db.query(Customer).filter(
        (Customer.phone.ilike(f"%{digits_10}%")) |
        (Customer.mobile_phone.ilike(f"%{digits_10}%"))
    ).first()
    if customer:
        return {
            "customer_id": customer.id, "name": customer.full_name or "",
            "email": customer.email or "", "phone": customer.phone or customer.mobile_phone or "",
            "source": "customers",
        }

    sale = db.query(Sale).filter(
        Sale.client_phone.ilike(f"%{digits_10}%")
    ).order_by(Sale.created_at.desc()).first()
    if sale:
        return {
            "customer_id": None, "name": sale.client_name or "",
            "email": sale.client_email or "", "phone": sale.client_phone or "",
            "sale_id": sale.id, "source": "sales",
        }
    return None


# ── Message logging (writes to the same text_messages table) ───────

def _log_message(db, direction, phone_number, content=None, from_number=None,
                 media_url=None, message_handle=None, status=None, service=None,
                 customer_id=None, context=None, sent_by=None, raw_payload=None) -> Optional[int]:
    try:
        from sqlalchemy import text
        result = db.execute(
            text("""
                INSERT INTO text_messages
                (direction, phone_number, from_number, content, media_url,
                 message_handle, status, service, customer_id, context, sent_by,
                 raw_payload, created_at, updated_at)
                VALUES
                (:direction, :phone_number, :from_number, :content, :media_url,
                 :message_handle, :status, :service, :customer_id, :context, :sent_by,
                 :raw_payload, NOW(), NOW())
                RETURNING id
            """),
            {"direction": direction, "phone_number": phone_number,
             "from_number": from_number or "", "content": content or "",
             "media_url": media_url or "", "message_handle": message_handle or "",
             "status": status or "", "service": service or "loopmessage",
             "customer_id": customer_id, "context": context or "",
             "sent_by": sent_by or "",
             "raw_payload": str(raw_payload) if raw_payload else None}
        )
        db.commit()
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error("Failed to log text message: %s", e)
        db.rollback()
        return None


def update_message_status(db, message_handle, status, error_code=None, was_downgraded=None, service=None):
    try:
        from sqlalchemy import text
        updates = ["status = :status", "updated_at = NOW()"]
        params = {"message_handle": message_handle, "status": status}
        if error_code:
            updates.append("error_code = :error_code"); params["error_code"] = error_code
        if was_downgraded is not None:
            updates.append("was_downgraded = :was_downgraded"); params["was_downgraded"] = was_downgraded
        if service:
            updates.append("service = :service"); params["service"] = service
        db.execute(
            text(f"UPDATE text_messages SET {', '.join(updates)} WHERE message_handle = :message_handle"),
            params
        )
        db.commit()
    except Exception as e:
        logger.error("Failed to update message status: %s", e)
        db.rollback()


# ── Conversation history (shared table) ────────────────────────────

def get_conversation(db, phone, limit=50):
    from sqlalchemy import text
    digits_10 = normalize_phone(phone)[-10:] if normalize_phone(phone) else ""
    if not digits_10: return []
    try:
        rows = db.execute(text("""
            SELECT id, direction, phone_number, from_number, content, media_url,
                   message_handle, status, service, customer_id, context, sent_by,
                   was_downgraded, error_code, created_at
            FROM text_messages WHERE phone_number LIKE :pattern
            ORDER BY created_at DESC LIMIT :limit
        """), {"pattern": f"%{digits_10}%", "limit": limit}).fetchall()
        return [{
            "id": r[0], "direction": r[1], "phone_number": r[2], "from_number": r[3],
            "content": r[4], "media_url": r[5], "message_handle": r[6], "status": r[7],
            "service": r[8], "customer_id": r[9], "context": r[10], "sent_by": r[11],
            "was_downgraded": r[12], "error_code": r[13],
            "created_at": r[14].isoformat() if r[14] else None,
        } for r in rows]
    except Exception as e:
        logger.error("Failed to get conversation: %s", e)
        return []


# ── Inbound webhook payload normalizer ─────────────────────────────

def parse_inbound_webhook(payload: dict) -> dict:
    """Map a LoopMessage inbound webhook into the shape our API handler expects.

    LoopMessage sends (per docs):
      alert_type: "message_inbound" | "message_sent" | "message_failed" | "message_reaction" | etc.
      message_id: UUID
      text: string
      recipient: E.164 (the contact who sent — our "from")
      sender_name: sender UUID (our sender)
      from_number / passthrough: varies
      attachments: list of URLs

    We return a dict keyed the way app.api.texting's webhook handler reads it.
    """
    alert_type = payload.get("alert_type", "")
    return {
        "alert_type": alert_type,
        "from_number": payload.get("recipient") or payload.get("from") or payload.get("from_number", ""),
        "to_number": payload.get("sender_name") or payload.get("to_number", ""),
        "content": payload.get("text") or payload.get("content", ""),
        "media_url": (payload.get("attachments") or [""])[0] if payload.get("attachments") else "",
        "message_handle": payload.get("message_id") or payload.get("message_handle", ""),
        "service": "loopmessage",
    }
