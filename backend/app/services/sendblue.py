"""Blooio iMessage/SMS service for ORBIT.

Handles:
- Outbound message sending via Blooio API (iMessage with RCS/SMS fallback)
- Inbound message processing from webhooks
- Customer matching by phone number
- Message logging to text_messages table
- Delivery status tracking

Blooio API docs: https://docs.blooio.com
Base URL: https://backend.blooio.com/v2/api
Auth: Bearer token
"""
import os
import re
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────
BLOOIO_API_KEY = os.getenv("BLOOIO_API_KEY", "")
BLOOIO_BASE_URL = "https://backend.blooio.com/v2/api"
BLOOIO_FROM_NUMBER = os.getenv("BLOOIO_FROM_NUMBER", "")

# Backward compat — also check old env var names
if not BLOOIO_API_KEY:
    BLOOIO_API_KEY = os.getenv("SENDBLUE_API_KEY", "")

SENDBLUE_NOTIFY_EMAIL = os.getenv("SENDBLUE_NOTIFY_EMAIL", "evan@betterchoiceins.com")


# ── Phone normalization ─────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Normalize any phone string to E.164 format (+1XXXXXXXXXX)."""
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
    """Compare two phone numbers after normalization."""
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
    """Send an iMessage/SMS via Blooio."""
    to_e164 = normalize_phone(to_number)
    if not to_e164:
        return {"success": False, "error": f"Invalid phone number: {to_number}"}

    if not BLOOIO_API_KEY:
        return {"success": False, "error": "Blooio API key not configured. Set BLOOIO_API_KEY env var."}

    body: dict = {}
    if content:
        body["text"] = content
    if media_url:
        body["attachments"] = [media_url]

    headers = {
        "Authorization": f"Bearer {BLOOIO_API_KEY}",
        "Content-Type": "application/json",
    }
    send_from = from_number or BLOOIO_FROM_NUMBER
    if send_from:
        headers["X-From-Number"] = normalize_phone(send_from)

    chat_id = urllib.parse.quote(to_e164, safe='')

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BLOOIO_BASE_URL}/chats/{chat_id}/messages",
                json=body,
                headers=headers,
            )
            data = resp.json()

            if resp.status_code in (200, 201, 202):
                message_id = data.get("message_id", "")
                status = data.get("status", "queued")

                logger.info("Blooio message sent: to=%s id=%s status=%s", to_e164, message_id, status)

                if db:
                    _log_message(
                        db=db, direction="outbound", phone_number=to_e164,
                        from_number=send_from or "", content=content, media_url=media_url,
                        message_handle=message_id, status=status, service="blooio",
                        customer_id=customer_id, context=context, sent_by=sent_by,
                    )

                return {"success": True, "message_id": message_id, "status": status}
            else:
                error_msg = data.get("error") or data.get("message") or str(resp.status_code)
                logger.error("Blooio send failed: %s — %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status_code": resp.status_code}

    except Exception as e:
        logger.error("Blooio send error: %s", e)
        return {"success": False, "error": str(e)}


# ── Bulk send ───────────────────────────────────────────────────────

async def send_bulk(messages: list[dict], db: Optional[Session] = None, context: Optional[str] = None) -> dict:
    """Send multiple messages."""
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


# ── Customer matching ───────────────────────────────────────────────

def match_customer_by_phone(db: Session, phone: str) -> Optional[dict]:
    """Find a customer by phone number."""
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


# ── Message logging ─────────────────────────────────────────────────

def _log_message(db, direction, phone_number, content=None, from_number=None,
                 media_url=None, message_handle=None, status=None, service=None,
                 customer_id=None, context=None, sent_by=None, raw_payload=None) -> Optional[int]:
    """Log a text message to the text_messages table."""
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
             "status": status or "", "service": service or "blooio",
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
    """Update a message's delivery status."""
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
        db.execute(text(f"UPDATE text_messages SET {', '.join(updates)} WHERE message_handle = :message_handle"), params)
        db.commit()
    except Exception as e:
        logger.error("Failed to update message status: %s", e)
        db.rollback()


# ── Conversation history ────────────────────────────────────────────

def get_conversation(db, phone, limit=50):
    """Get message thread for a phone number."""
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
