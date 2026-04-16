"""LoopMessage iMessage service for ORBIT.

Drop-in replacement for sendblue.py — exposes the same async send_message()
signature and returns the same result dict shape so the API layer can switch
providers via a single env var (TEXTING_PROVIDER).

LoopMessage NEW API (not legacy server.loopmessage.com):
- Host: https://a.loopmessage.com
- Auth: single `Authorization` header (no Loop-Secret-Key)
- Send endpoint: POST /api/v1/message/send/
- Params: contact (E.164), text, sender (UUID), attachments (list of URLs)
- Docs: https://docs.loopmessage.com

Webhook payload shape (inbound + status) documented at:
https://docs.loopmessage.com/imessage-conversation-api/webhooks
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
LOOPMESSAGE_BASE_URL = "https://a.loopmessage.com"
LOOPMESSAGE_STATUS_CALLBACK = os.getenv(
    "LOOPMESSAGE_STATUS_CALLBACK",
    "https://better-choice-api.onrender.com/api/sendblue/status-callback"
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
        "contact": to_e164,
        "text": content or "",
        "sender": LOOPMESSAGE_SENDER_ID,
        "status_callback": LOOPMESSAGE_STATUS_CALLBACK,
    }
    if media_url:
        # LoopMessage accepts attachments as a list of URLs
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

            if resp.status_code in (200, 201, 202) and data.get("success"):
                # LoopMessage returns message_id (UUID); normalize to message_handle
                message_handle = (
                    data.get("message_id")
                    or data.get("messageId")
                    or data.get("message_handle")
                    or ""
                )
                # LoopMessage is iMessage-native; treat accepted as QUEUED
                status = data.get("status") or "QUEUED"

                logger.info(
                    "LoopMessage sent: to=%s handle=%s status=%s",
                    to_e164, message_handle, status
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
                error_msg = (
                    data.get("message")
                    or data.get("error_message")
                    or data.get("error")
                    or f"HTTP {resp.status_code}"
                )
                error_code = data.get("code")
                logger.error(
                    "LoopMessage send failed: %s code=%s — %s",
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

    We return a dict keyed the way app.api.sendblue.inbound_webhook reads it.
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
