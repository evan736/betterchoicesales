"""Sendblue API routes — iMessage/SMS integration for ORBIT.

Endpoints:
- POST /api/sendblue/inbound         — Webhook for incoming messages
- POST /api/sendblue/status-callback  — Delivery status updates
- POST /api/sendblue/send             — Send a message (authenticated)
- POST /api/sendblue/send-bulk        — Bulk send (authenticated)
- GET  /api/sendblue/conversations    — List recent conversations
- GET  /api/sendblue/conversation/{phone} — Message thread for a number
- GET  /api/sendblue/messages         — All messages with filters
- GET  /api/sendblue/stats            — Dashboard stats
- POST /api/sendblue/test             — Send test message (admin only)

Webhook setup in Sendblue dashboard:
  Inbound: https://better-choice-api.onrender.com/api/sendblue/inbound
  Status:  (set per-message via status_callback param)
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.sendblue import (
    send_message,
    send_bulk,
    match_customer_by_phone,
    normalize_phone,
    _log_message,
    update_message_status,
    get_conversation,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sendblue", tags=["sendblue"])

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "betterchoiceins.com")
SENDBLUE_NOTIFY_EMAIL = os.getenv("SENDBLUE_NOTIFY_EMAIL", "evan@betterchoiceins.com")


# ── Pydantic models ────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    to_number: str
    content: str
    media_url: Optional[str] = None
    customer_id: Optional[int] = None
    context: Optional[str] = "manual"

class BulkSendRequest(BaseModel):
    messages: list[dict]  # Each: {to_number, content, media_url?, customer_id?}
    context: Optional[str] = "bulk"


# ── DB Migration ────────────────────────────────────────────────────

def run_sendblue_migration(engine=None):
    """Create text_messages table if it doesn't exist."""
    from app.core.database import engine as default_engine
    eng = engine or default_engine
    
    try:
        with eng.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS text_messages (
                    id SERIAL PRIMARY KEY,
                    direction VARCHAR(10) NOT NULL DEFAULT 'outbound',
                    phone_number VARCHAR(20) NOT NULL,
                    from_number VARCHAR(20) DEFAULT '',
                    content TEXT DEFAULT '',
                    media_url TEXT DEFAULT '',
                    message_handle VARCHAR(100) DEFAULT '',
                    status VARCHAR(20) DEFAULT '',
                    service VARCHAR(20) DEFAULT '',
                    customer_id INTEGER,
                    context VARCHAR(50) DEFAULT '',
                    sent_by VARCHAR(100) DEFAULT '',
                    was_downgraded BOOLEAN,
                    error_code VARCHAR(50),
                    error_message TEXT,
                    raw_payload TEXT,
                    read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_text_messages_phone ON text_messages(phone_number)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_text_messages_handle ON text_messages(message_handle)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_text_messages_customer ON text_messages(customer_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_text_messages_direction ON text_messages(direction)
            """))
            conn.commit()
            logger.info("text_messages table ready")
        
        # Voice notes table
        with eng.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS voice_notes (
                    id SERIAL PRIMARY KEY,
                    note_id VARCHAR(20) NOT NULL UNIQUE,
                    caf_data BYTEA NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_voice_notes_note_id ON voice_notes(note_id)
            """))
            conn.commit()
            logger.info("voice_notes table ready")
    except Exception as e:
        logger.warning(f"Sendblue migration: {e}")


# ── 1. INBOUND WEBHOOK ─────────────────────────────────────────────

@router.post("/inbound")
async def inbound_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive inbound messages from Sendblue.
    
    Sendblue POSTs JSON with: content, from_number, to_number, number,
    message_handle, date_sent, media_url, service, etc.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON"}
    
    from_number = payload.get("from_number", "") or payload.get("number", "")
    content = payload.get("content", "")
    media_url = payload.get("media_url", "")
    message_handle = payload.get("message_handle", "")
    service = payload.get("service", "")
    to_number = payload.get("to_number", "") or payload.get("sendblue_number", "")
    
    logger.info("Inbound text from %s: %s (service=%s)", from_number, content[:100], service)
    
    # Match to customer
    customer_match = match_customer_by_phone(db, from_number)
    customer_id = customer_match.get("customer_id") if customer_match else None
    customer_name = customer_match.get("name", "Unknown") if customer_match else "Unknown"
    
    # Log to DB
    msg_id = _log_message(
        db=db, direction="inbound", phone_number=from_number,
        from_number=from_number, content=content, media_url=media_url,
        message_handle=message_handle, status="RECEIVED", service=service or "sendblue",
        customer_id=customer_id, context="inbound_webhook", raw_payload=payload,
    )
    
    # Send email notification to Evan
    _send_inbound_notification(
        from_number=from_number, content=content,
        customer_name=customer_name, customer_match=customer_match,
        media_url=media_url, service=service or "sendblue",
    )
    
    # Post to office chat
    _post_to_office_chat(db=db, from_number=from_number, content=content, customer_name=customer_name)
    
    return {"status": "ok", "message_id": msg_id, "customer_match": customer_name}


# ── 2. STATUS CALLBACK ─────────────────────────────────────────────

@router.post("/status-callback")
async def status_callback(request: Request, db: Session = Depends(get_db)):
    """Receive delivery status updates from Sendblue.
    
    Statuses: REGISTERED → PENDING → QUEUED → ACCEPTED → SENT → DELIVERED
    Or: ERROR / DECLINED
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error"}
    
    message_handle = payload.get("message_handle", "")
    status = payload.get("status", "")
    error_code = payload.get("error_code")
    was_downgraded = payload.get("was_downgraded")
    service = payload.get("service")
    
    if message_handle and status:
        update_message_status(
            db=db,
            message_handle=message_handle,
            status=status,
            error_code=str(error_code) if error_code else None,
            was_downgraded=was_downgraded,
            service=service,
        )
    
    # Log errors
    if status in ("ERROR", "DECLINED"):
        error_msg = payload.get("error_message", "")
        logger.error(
            "Sendblue delivery failed: handle=%s status=%s error=%s",
            message_handle, status, error_msg
        )
        # Update error_message in DB too
        try:
            db.execute(
                text("UPDATE text_messages SET error_message = :msg WHERE message_handle = :handle"),
                {"msg": error_msg, "handle": message_handle}
            )
            db.commit()
        except Exception:
            pass
    
    return {"status": "ok"}


# ── 3. SEND MESSAGE (Authenticated) ────────────────────────────────

@router.post("/send")
async def send_text(
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send an iMessage/SMS to a phone number."""
    result = await send_message(
        to_number=req.to_number,
        content=req.content,
        media_url=req.media_url,
        db=db,
        customer_id=req.customer_id,
        context=req.context or "manual",
        sent_by=current_user.full_name or current_user.username,
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Send failed"))
    
    return result


# ── 4. BULK SEND (Authenticated, admin/manager only) ───────────────

@router.post("/send-bulk")
async def send_text_bulk(
    req: BulkSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send messages to multiple recipients."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    
    # Inject sent_by into each message
    for msg in req.messages:
        msg["sent_by"] = current_user.full_name or current_user.username
    
    result = await send_bulk(
        messages=req.messages,
        db=db,
        context=req.context,
    )
    return result


# ── 5. CONVERSATIONS LIST ──────────────────────────────────────────

@router.get("/conversations")
def list_conversations(
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent text conversations grouped by phone number.
    
    Returns most recent message per phone number, with customer match info.
    """
    try:
        rows = db.execute(
            text("""
                WITH latest AS (
                    SELECT DISTINCT ON (phone_number)
                        id, direction, phone_number, content, status, service,
                        customer_id, created_at, was_downgraded, media_url
                    FROM text_messages
                    ORDER BY phone_number, created_at DESC
                )
                SELECT l.*, 
                    (SELECT COUNT(*) FROM text_messages t 
                     WHERE t.phone_number = l.phone_number AND t.read = FALSE AND t.direction = 'inbound') as unread_count,
                    (SELECT COUNT(*) FROM text_messages t 
                     WHERE t.phone_number = l.phone_number) as total_messages
                FROM latest l
                ORDER BY l.created_at DESC
                LIMIT :limit
            """),
            {"limit": limit}
        ).fetchall()
        
        conversations = []
        for r in rows:
            # Try to match customer
            customer_match = match_customer_by_phone(db, r[2])
            conversations.append({
                "phone_number": r[2],
                "last_message": {
                    "id": r[0],
                    "direction": r[1],
                    "content": r[3],
                    "status": r[4],
                    "service": r[5],
                    "created_at": r[8].isoformat() if r[8] else None,
                    "media_url": r[9] or None,
                },
                "customer_id": r[6],
                "customer_name": customer_match.get("name") if customer_match else None,
                "customer_email": customer_match.get("email") if customer_match else None,
                "unread_count": r[10],
                "total_messages": r[11],
            })
        
        return {"conversations": conversations, "total": len(conversations)}
        
    except Exception as e:
        logger.error("Failed to list conversations: %s", e)
        return {"conversations": [], "total": 0, "error": str(e)}


# ── 6. CONVERSATION THREAD ─────────────────────────────────────────

@router.get("/conversation/{phone}")
def get_conversation_thread(
    phone: str,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full message thread for a phone number."""
    messages = get_conversation(db, phone, limit)
    customer_match = match_customer_by_phone(db, phone)
    
    # Mark inbound messages as read
    normalized = normalize_phone(phone)
    if normalized:
        digits_10 = normalized[-10:]
        try:
            db.execute(
                text("""
                    UPDATE text_messages SET read = TRUE 
                    WHERE phone_number LIKE :pattern AND direction = 'inbound' AND read = FALSE
                """),
                {"pattern": f"%{digits_10}%"}
            )
            db.commit()
        except Exception:
            pass
    
    return {
        "phone": phone,
        "normalized": normalized,
        "customer": customer_match,
        "messages": list(reversed(messages)),  # Chronological order
        "total": len(messages),
    }


# ── 7. ALL MESSAGES (with filters) ─────────────────────────────────

@router.get("/messages")
def list_messages(
    direction: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    context: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all messages with optional filters."""
    conditions = []
    params = {"limit": limit, "offset": offset}
    
    if direction:
        conditions.append("direction = :direction")
        params["direction"] = direction
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if context:
        conditions.append("context = :context")
        params["context"] = context
    if search:
        conditions.append("(content ILIKE :search OR phone_number ILIKE :search)")
        params["search"] = f"%{search}%"
    
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    try:
        rows = db.execute(
            text(f"""
                SELECT id, direction, phone_number, from_number, content, media_url,
                       message_handle, status, service, customer_id, context, sent_by,
                       was_downgraded, error_code, error_message, read, created_at
                FROM text_messages
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params
        ).fetchall()
        
        count_row = db.execute(
            text(f"SELECT COUNT(*) FROM text_messages {where}"),
            params
        ).fetchone()
        
        return {
            "messages": [
                {
                    "id": r[0], "direction": r[1], "phone_number": r[2],
                    "from_number": r[3], "content": r[4], "media_url": r[5],
                    "message_handle": r[6], "status": r[7], "service": r[8],
                    "customer_id": r[9], "context": r[10], "sent_by": r[11],
                    "was_downgraded": r[12], "error_code": r[13], 
                    "error_message": r[14], "read": r[15],
                    "created_at": r[16].isoformat() if r[16] else None,
                }
                for r in rows
            ],
            "total": count_row[0] if count_row else 0,
        }
    except Exception as e:
        logger.error("Failed to list messages: %s", e)
        return {"messages": [], "total": 0, "error": str(e)}


# ── 8. STATS ────────────────────────────────────────────────────────

@router.get("/stats")
def sendblue_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dashboard stats for texting."""
    try:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        stats = {}
        
        # Total messages
        row = db.execute(text("SELECT COUNT(*) FROM text_messages")).fetchone()
        stats["total_messages"] = row[0] if row else 0
        
        # By direction
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE direction='outbound'")).fetchone()
        stats["total_sent"] = row[0] if row else 0
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE direction='inbound'")).fetchone()
        stats["total_received"] = row[0] if row else 0
        
        # Today
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE created_at >= :today"), {"today": today}).fetchone()
        stats["today"] = row[0] if row else 0
        
        # This week
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE created_at >= :week"), {"week": week_ago}).fetchone()
        stats["this_week"] = row[0] if row else 0
        
        # Unread inbound
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE direction='inbound' AND read=FALSE")).fetchone()
        stats["unread"] = row[0] if row else 0
        
        # Delivery stats (outbound only)
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE direction='outbound' AND status='DELIVERED'")).fetchone()
        stats["delivered"] = row[0] if row else 0
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE direction='outbound' AND status IN ('ERROR','DECLINED')")).fetchone()
        stats["failed"] = row[0] if row else 0
        
        # iMessage vs SMS breakdown
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE service ILIKE '%imessage%'")).fetchone()
        stats["imessage_count"] = row[0] if row else 0
        row = db.execute(text("SELECT COUNT(*) FROM text_messages WHERE service ILIKE '%sms%'")).fetchone()
        stats["sms_count"] = row[0] if row else 0
        
        # By context
        ctx_rows = db.execute(text("""
            SELECT context, COUNT(*) FROM text_messages 
            WHERE context != '' 
            GROUP BY context ORDER BY COUNT(*) DESC LIMIT 10
        """)).fetchall()
        stats["by_context"] = {r[0]: r[1] for r in ctx_rows}
        
        return stats
        
    except Exception as e:
        logger.error("Failed to get sendblue stats: %s", e)
        return {"error": str(e)}


# ── 9. TEST ENDPOINT (Admin only) ──────────────────────────────────

@router.post("/test")
async def test_send(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a test message to confirm Sendblue integration works."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    from_number = os.getenv("SENDBLUE_FROM_NUMBER", "")
    if not from_number:
        return {"success": False, "error": "SENDBLUE_FROM_NUMBER not set. Set it in Render env vars."}
    
    result = await send_message(
        to_number="+18479085665",
        content="✅ ORBIT Sendblue test — iMessage integration is working!",
        db=db,
        context="test",
        sent_by="system",
    )
    return result


# ── 10. MARK READ ──────────────────────────────────────────────────

@router.post("/messages/{message_id}/read")
def mark_message_read(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a single message as read."""
    try:
        db.execute(
            text("UPDATE text_messages SET read = TRUE WHERE id = :id"),
            {"id": message_id}
        )
        db.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 11. VOICE NOTE ─────────────────────────────────────────────────

from fastapi import UploadFile, File, Form

@router.post("/voice-note")
async def send_voice_note(
    to_number: str = Form(...),
    audio: UploadFile = File(...),
    customer_id: Optional[int] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record and send a voice memo via iMessage.
    
    Accepts any audio format (webm, mp3, wav, m4a, ogg) — converts to .caf
    via ffmpeg, stores in DB, serves via public URL for Sendblue to fetch.
    
    Sendblue delivers .caf files as native iMessage voice notes (inline playable).
    """
    import subprocess
    import tempfile
    import uuid
    import base64
    
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")
    
    # Determine input format from filename or content type
    ext = "webm"
    if audio.filename:
        ext = audio.filename.rsplit(".", 1)[-1].lower() if "." in audio.filename else "webm"
    elif audio.content_type:
        ct_map = {"audio/webm": "webm", "audio/mp3": "mp3", "audio/mpeg": "mp3",
                  "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a",
                  "audio/ogg": "ogg", "audio/x-m4a": "m4a"}
        ext = ct_map.get(audio.content_type, "webm")
    
    # Convert to .caf using ffmpeg
    note_id = str(uuid.uuid4())[:12]
    
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as inp:
        inp.write(audio_bytes)
        inp_path = inp.name
    
    out_path = f"/tmp/{note_id}.caf"
    
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", inp_path, "-acodec", "opus", "-b:a", "24k", "-y", out_path],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            logger.error("ffmpeg conversion failed: %s", result.stderr.decode()[:500])
            raise HTTPException(status_code=500, detail="Audio conversion failed")
        
        with open(out_path, "rb") as f:
            caf_bytes = f.read()
        
    finally:
        import os as _os
        try: _os.unlink(inp_path)
        except: pass
        try: _os.unlink(out_path)
        except: pass
    
    # Store .caf in database as BYTEA so it survives Render deploys
    try:
        caf_b64 = base64.b64encode(caf_bytes).decode()
        db.execute(
            text("""
                INSERT INTO voice_notes (id, note_id, caf_data, created_at)
                VALUES (DEFAULT, :note_id, decode(:caf_b64, 'base64'), NOW())
            """),
            {"note_id": note_id, "caf_b64": caf_b64}
        )
        db.commit()
    except Exception as e:
        logger.error("Failed to store voice note: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to store voice note")
    
    # Public URL that Sendblue will fetch
    caf_url = f"https://better-choice-api.onrender.com/api/sendblue/voice-note/{note_id}.caf"
    
    # Send via Sendblue as media_url
    result = await send_message(
        to_number=to_number,
        content="",
        media_url=caf_url,
        db=db,
        customer_id=customer_id,
        context="voice_note",
        sent_by=current_user.full_name or current_user.username,
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Send failed"))
    
    return {**result, "voice_note_url": caf_url}


@router.get("/voice-note/{note_id}.caf")
def serve_voice_note(note_id: str, db: Session = Depends(get_db)):
    """Serve a .caf voice note file — public endpoint for Sendblue to fetch."""
    from fastapi.responses import Response
    
    try:
        row = db.execute(
            text("SELECT caf_data FROM voice_notes WHERE note_id = :note_id"),
            {"note_id": note_id}
        ).fetchone()
        
        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="Voice note not found")
        
        return Response(
            content=bytes(row[0]),
            media_type="audio/x-caf",
            headers={
                "Content-Disposition": f"inline; filename={note_id}.caf",
                "Cache-Control": "public, max-age=86400",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to serve voice note: %s", e)
        raise HTTPException(status_code=500, detail="Failed to serve voice note")


# ── HELPERS ─────────────────────────────────────────────────────────

def _send_inbound_notification(
    from_number: str,
    content: str,
    customer_name: str,
    customer_match: Optional[dict],
    media_url: str = "",
    service: str = "",
):
    """Email notification to Evan when an inbound text arrives."""
    if not MAILGUN_API_KEY:
        return
    
    import httpx as _httpx
    
    customer_info = ""
    if customer_match:
        customer_info = f"""
        <tr><td style="padding:4px 12px;color:#94a3b8;font-size:13px;">Customer</td>
            <td style="padding:4px 12px;color:#e2e8f0;font-size:13px;font-weight:600;">{customer_match.get('name','Unknown')}</td></tr>
        <tr><td style="padding:4px 12px;color:#94a3b8;font-size:13px;">Email</td>
            <td style="padding:4px 12px;color:#e2e8f0;font-size:13px;">{customer_match.get('email','')}</td></tr>
        """
    
    media_block = ""
    if media_url:
        media_block = f"""
        <div style="margin-top:12px;padding:12px;background:#1e293b;border-radius:8px;">
            <p style="margin:0 0 8px;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Attachment</p>
            <a href="{media_url}" style="color:#38bdf8;font-size:13px;">View Media</a>
        </div>
        """
    
    html = f"""<!DOCTYPE html><html><body style="margin:0;padding:20px;background:#0f172a;font-family:Arial,sans-serif;">
    <div style="max-width:500px;margin:0 auto;background:#1a2744;border-radius:12px;overflow:hidden;border:1px solid rgba(56,189,248,0.2);">
        <div style="background:linear-gradient(135deg,#0ea5e9,#2563eb);padding:16px 20px;">
            <h2 style="margin:0;color:white;font-size:16px;">💬 Inbound Text Message</h2>
            <p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:12px;">via {service or 'Sendblue'}</p>
        </div>
        <div style="padding:20px;">
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:4px 12px;color:#94a3b8;font-size:13px;">From</td>
                    <td style="padding:4px 12px;color:#e2e8f0;font-size:13px;font-weight:600;">{from_number}</td></tr>
                {customer_info}
            </table>
            <div style="margin-top:16px;padding:16px;background:#0f172a;border-radius:8px;border-left:3px solid #38bdf8;">
                <p style="margin:0;color:#e2e8f0;font-size:14px;line-height:1.6;white-space:pre-wrap;">{content or '(No text content)'}</p>
            </div>
            {media_block}
            <div style="margin-top:16px;text-align:center;">
                <a href="https://orbit.betterchoiceins.com/texting" 
                   style="display:inline-block;background:#2563eb;color:white;padding:10px 24px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;">
                    Reply in ORBIT
                </a>
            </div>
        </div>
    </div>
    </body></html>"""
    
    try:
        _httpx.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={
                "from": f"ORBIT Texting <noreply@{MAILGUN_DOMAIN}>",
                "to": SENDBLUE_NOTIFY_EMAIL,
                "subject": f"💬 Text from {customer_name} ({from_number})",
                "html": html,
            },
        )
        logger.info("Inbound text notification sent to %s", SENDBLUE_NOTIFY_EMAIL)
    except Exception as e:
        logger.error("Failed to send inbound text notification: %s", e)


def _post_to_office_chat(
    db: Session,
    from_number: str,
    content: str,
    customer_name: str,
):
    """Post inbound text notification to the #general office chat channel."""
    try:
        # Find general channel
        row = db.execute(
            text("SELECT id FROM chat_channels WHERE name = 'general' AND channel_type = 'public' LIMIT 1")
        ).fetchone()
        
        if not row:
            return
        
        channel_id = row[0]
        
        # Find system user (or admin)
        user_row = db.execute(
            text("SELECT id FROM users WHERE username = 'admin' LIMIT 1")
        ).fetchone()
        
        if not user_row:
            return
        
        sender_label = customer_name if customer_name != "Unknown" else from_number
        chat_content = f"💬 **Inbound text from {sender_label}** ({from_number}):\n{content[:300]}"
        
        db.execute(
            text("""
                INSERT INTO chat_messages (channel_id, user_id, content, created_at)
                VALUES (:channel_id, :user_id, :content, NOW())
            """),
            {"channel_id": channel_id, "user_id": user_row[0], "content": chat_content}
        )
        db.commit()
        
    except Exception as e:
        logger.warning("Failed to post inbound text to chat: %s", e)


# ── HEALTH ──────────────────────────────────────────────────────────

@router.get("/health")
def sendblue_health():
    """Check Sendblue configuration."""
    from_number = os.getenv("SENDBLUE_FROM_NUMBER", "")
    api_key = os.getenv("SENDBLUE_API_KEY", "")
    api_secret = os.getenv("SENDBLUE_API_SECRET", "")
    
    return {
        "status": "ok" if (api_key and api_secret) else "missing_credentials",
        "provider": "sendblue",
        "from_number": from_number or "NOT SET",
        "api_key_set": bool(api_key),
        "api_secret_set": bool(api_secret),
        "inbound_webhook": "https://better-choice-api.onrender.com/api/sendblue/inbound",
        "status_callback": "https://better-choice-api.onrender.com/api/sendblue/status-callback",
    }
