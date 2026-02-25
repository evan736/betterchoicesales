"""Email Inbox API — shared inbox, inbound routing, AI drafts, thread management."""
import hashlib
import hmac
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Form, UploadFile, File
from sqlalchemy import func, or_, and_, desc
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.email import EmailThread, EmailMessage, EmailRule
from app.models.customer import Customer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/email", tags=["email"])

ATTACHMENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "email-attachments")
os.makedirs(ATTACHMENT_DIR, exist_ok=True)


def _verify_mailgun_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify Mailgun webhook signature using HMAC-SHA256.
    See: https://documentation.mailgun.com/en/latest/user_manual.html#webhooks
    """
    if not settings.MAILGUN_API_KEY:
        logger.warning("No MAILGUN_API_KEY set — skipping signature verification")
        return True  # Can't verify without the key

    # Mailgun signs with the API key
    signing_key = settings.MAILGUN_API_KEY
    hmac_digest = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, hmac_digest)


# ══════════════════════════════════════════════════════════════════════
# MAILGUN INBOUND WEBHOOK — receives all incoming email
# ══════════════════════════════════════════════════════════════════════

@router.post("/inbound")
async def inbound_email(request: Request):
    """Mailgun inbound webhook — receives parsed emails."""
    try:
        form = await request.form()

        # ── Verify Mailgun signature ──
        mg_timestamp = form.get("timestamp", "")
        mg_token = form.get("token", "")
        mg_signature = form.get("signature", "")
        if mg_timestamp and mg_token and mg_signature:
            if not _verify_mailgun_signature(mg_token, mg_timestamp, mg_signature):
                logger.warning(f"⚠️ Mailgun signature verification FAILED — rejecting webhook")
                raise HTTPException(status_code=403, detail="Invalid signature")
        elif settings.MAILGUN_API_KEY:
            # Signature fields missing but we have an API key — log warning but allow
            # (some Mailgun route types don't include signature in form data)
            logger.warning("Mailgun webhook missing signature fields — allowing but this should be investigated")
        
        # Check for duplicate by Message-Id
        message_id = form.get("Message-Id", "")
        if message_id:
            from app.core.database import SessionLocal
            _check_db = SessionLocal()
            try:
                existing = _check_db.query(EmailMessage).filter(
                    EmailMessage.mailgun_message_id == message_id
                ).first()
                if existing:
                    logger.info(f"Duplicate inbound ignored: {message_id}")
                    return {"status": "duplicate", "message_id": message_id}
            finally:
                _check_db.close()
        
        from_raw = form.get("from", "")
        sender = form.get("sender", "")
        to_raw = form.get("To", form.get("to", ""))
        cc_raw = form.get("Cc", form.get("cc", ""))
        subject = form.get("subject", "(No Subject)")
        body_text = form.get("body-plain", "")
        body_html = form.get("body-html", "")
        message_id = form.get("Message-Id", "")
        in_reply_to = form.get("In-Reply-To", "")
        references = form.get("References", "")
        
        # Parse from
        from_name, from_email = _parse_email_address(from_raw or sender)
        
        # Parse recipients
        to_emails = _parse_email_list(to_raw)
        cc_emails = _parse_email_list(cc_raw)
        
        # Determine which mailbox this is for
        mailbox = _determine_mailbox(to_emails + cc_emails)
        
        # Save attachments
        att_info = []
        att_count = int(form.get("attachment-count", "0") or "0")
        for i in range(1, att_count + 1):
            att_file = form.get(f"attachment-{i}")
            if att_file and hasattr(att_file, 'filename'):
                ext = os.path.splitext(att_file.filename)[1] if att_file.filename else ""
                saved_name = f"{uuid.uuid4().hex}{ext}"
                saved_path = os.path.join(ATTACHMENT_DIR, saved_name)
                content = await att_file.read()
                with open(saved_path, "wb") as f:
                    f.write(content)
                att_info.append({
                    "filename": att_file.filename,
                    "path": f"/static/email-attachments/{saved_name}",
                    "size": len(content),
                    "content_type": att_file.content_type or "application/octet-stream",
                })
        
        # Get DB session
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            # Find or create thread
            thread = _find_or_create_thread(
                db, subject=subject, from_email=from_email, from_name=from_name,
                to_emails=to_emails, cc_emails=cc_emails, mailbox=mailbox,
                in_reply_to=in_reply_to, references=references,
            )
            
            # Create message
            msg = EmailMessage(
                thread_id=thread.id,
                direction="inbound",
                from_email=from_email,
                from_name=from_name,
                to_emails=to_emails,
                cc_emails=cc_emails,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                attachments=att_info,
                mailgun_message_id=message_id,
                in_reply_to=in_reply_to,
                references=references,
                read_by={},
            )
            db.add(msg)
            
            # Update thread
            thread.last_message_at = datetime.utcnow()
            if thread.status == "closed":
                thread.status = "open"  # Reopen on new inbound
            
            db.commit()
            db.refresh(msg)
            
            # Run rules asynchronously
            _apply_rules(db, thread, msg)
            
            # Try to link to customer
            _link_customer(db, thread, from_email)
            
            # Log to NowCerts
            _log_inbound_to_nowcerts(db, thread, msg)
            
            db.commit()
            
            logger.info(f"📥 Inbound email: {from_email} → {mailbox} | {subject[:60]}")
            return {"status": "ok", "thread_id": thread.id, "message_id": msg.id}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Inbound email processing failed: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


# ══════════════════════════════════════════════════════════════════════
# THREAD LIST / INBOX
# ══════════════════════════════════════════════════════════════════════

@router.get("/threads")
def list_threads(
    mailbox: Optional[str] = None,
    status: Optional[str] = None,
    assigned_to: Optional[int] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List email threads with filters. Enforces role-based mailbox access."""
    q = db.query(EmailThread)
    
    # ── Role-based access control ──
    is_admin = current_user.role.lower() in ("admin",)
    is_service = current_user.role.lower() in ("retention_specialist", "manager")
    user_mailbox = _user_to_mailbox(current_user)
    
    if mailbox:
        # Verify user can access this mailbox
        if not is_admin:
            if mailbox != "service" and mailbox != user_mailbox:
                raise HTTPException(status_code=403, detail="You don't have access to this mailbox")
        q = q.filter(EmailThread.mailbox == mailbox)
    else:
        # No mailbox filter → show only accessible mailboxes
        if is_admin:
            pass  # Admin sees everything
        else:
            # Producers/retention see service + their own mailbox
            q = q.filter(or_(
                EmailThread.mailbox == "service",
                EmailThread.mailbox == user_mailbox,
            ))
    
    if status:
        q = q.filter(EmailThread.status == status)
    else:
        q = q.filter(EmailThread.status != "closed")  # Default: hide closed
    if assigned_to is not None:
        if assigned_to == 0:
            q = q.filter(EmailThread.assigned_to_id.is_(None))  # Unassigned
        else:
            q = q.filter(EmailThread.assigned_to_id == assigned_to)
    if tag:
        q = q.filter(EmailThread.tags.contains([tag]))
    if search:
        q = q.filter(or_(
            EmailThread.subject.ilike(f"%{search}%"),
            EmailThread.from_email.ilike(f"%{search}%"),
            EmailThread.from_name.ilike(f"%{search}%"),
        ))
    
    total = q.count()
    threads = (
        q.order_by(desc(EmailThread.last_message_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    return {
        "threads": [_serialize_thread(t, current_user.id, db) for t in threads],
        "total": total,
        "page": page,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/threads/{thread_id}")
def get_thread(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a thread with all messages."""
    thread = db.query(EmailThread).filter(EmailThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    messages = (
        db.query(EmailMessage)
        .filter(EmailMessage.thread_id == thread_id)
        .order_by(EmailMessage.created_at)
        .all()
    )
    
    # Mark messages as read
    for msg in messages:
        if msg.direction == "inbound":
            read_by = msg.read_by or {}
            if str(current_user.id) not in read_by:
                read_by[str(current_user.id)] = datetime.utcnow().isoformat()
                msg.read_by = read_by
    db.commit()
    
    return {
        "thread": _serialize_thread(thread, current_user.id, db),
        "messages": [_serialize_message(m) for m in messages],
    }


# ══════════════════════════════════════════════════════════════════════
# THREAD ACTIONS
# ══════════════════════════════════════════════════════════════════════

@router.post("/threads/{thread_id}/assign")
def assign_thread(
    thread_id: int,
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign a thread to a user (or unassign with user_id=null)."""
    thread = db.query(EmailThread).filter(EmailThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    thread.assigned_to_id = user_id
    thread.assigned_at = datetime.utcnow() if user_id else None
    if user_id and thread.status == "open":
        thread.status = "assigned"
    db.commit()
    return {"status": "assigned", "assigned_to_id": user_id}


@router.post("/threads/{thread_id}/status")
def update_thread_status(
    thread_id: int,
    status: str = Form(...),
    snooze_until: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update thread status (open, assigned, snoozed, closed)."""
    thread = db.query(EmailThread).filter(EmailThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    thread.status = status
    if status == "snoozed" and snooze_until:
        thread.snoozed_until = datetime.fromisoformat(snooze_until)
    if status == "closed":
        thread.snoozed_until = None
    db.commit()
    return {"status": status}


@router.post("/threads/{thread_id}/tag")
def tag_thread(
    thread_id: int,
    tag: str = Form(...),
    action: str = Form("add"),  # "add" or "remove"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add or remove a tag from a thread."""
    thread = db.query(EmailThread).filter(EmailThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    tags = list(thread.tags or [])
    if action == "add" and tag not in tags:
        tags.append(tag)
    elif action == "remove" and tag in tags:
        tags.remove(tag)
    thread.tags = tags
    db.commit()
    return {"tags": tags}


# ══════════════════════════════════════════════════════════════════════
# SEND / REPLY
# ══════════════════════════════════════════════════════════════════════

@router.post("/threads/{thread_id}/reply")
def reply_to_thread(
    thread_id: int,
    body: str = Form(...),
    cc_emails: str = Form(""),
    send_as: str = Form("service"),
    close_after: bool = Form(False),
    attachments: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reply to a thread — sends email and saves message."""
    import requests as http_requests

    thread = db.query(EmailThread).filter(EmailThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")

    # Determine sender
    if send_as == "personal" and current_user.email:
        from_email = current_user.email
    else:
        from_email = f"service@{settings.MAILGUN_DOMAIN or 'mg.betterchoiceins.com'}"
    
    from_str = f"{current_user.full_name} <{from_email}>"
    
    # Reply to the original sender
    to_email = thread.from_email
    to_name = thread.from_name or ""
    cc_list = [e.strip() for e in cc_emails.split(",") if e.strip()] if cc_emails else []
    
    # Get last message for In-Reply-To
    last_msg = db.query(EmailMessage).filter(
        EmailMessage.thread_id == thread_id
    ).order_by(desc(EmailMessage.created_at)).first()
    
    # Build branded HTML
    html_body = body.replace('\n', '<br>')
    html = _build_branded_email(html_body, current_user.full_name, from_email)
    
    # Save attachments
    logger.info(f"📎 Reply: {len(attachments)} attachments received")
    att_info = []
    mg_files = []
    for att in attachments:
        content = att.file.read()
        logger.info(f"📎 File: {att.filename} ({len(content)} bytes, {att.content_type})")
        ext = os.path.splitext(att.filename)[1] if att.filename else ""
        saved_name = f"{uuid.uuid4().hex}{ext}"
        saved_path = os.path.join(ATTACHMENT_DIR, saved_name)
        with open(saved_path, "wb") as f:
            f.write(content)
        att_info.append({
            "filename": att.filename,
            "path": f"/static/email-attachments/{saved_name}",
            "size": len(content),
            "content_type": att.content_type or "application/octet-stream",
        })
        mg_files.append(("attachment", (att.filename, content, att.content_type or "application/octet-stream")))
    
    # Send via Mailgun
    data = {
        "from": from_str,
        "to": [f"{to_name} <{to_email}>" if to_name else to_email],
        "subject": f"Re: {thread.subject}" if not thread.subject.startswith("Re:") else thread.subject,
        "html": html,
        "h:Reply-To": from_email,
    }
    if cc_list:
        data["cc"] = cc_list
    if last_msg and last_msg.mailgun_message_id:
        data["h:In-Reply-To"] = last_msg.mailgun_message_id
        data["h:References"] = last_msg.mailgun_message_id
    
    resp = http_requests.post(
        f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data=data,
        files=mg_files if mg_files else None,
    )
    resp.raise_for_status()
    logger.info(f"📤 Mailgun reply response: {resp.status_code} {resp.json()} (files: {len(mg_files)})")
    
    # Save outbound message
    msg = EmailMessage(
        thread_id=thread.id,
        direction="outbound",
        from_email=from_email,
        from_name=current_user.full_name,
        to_emails=[to_email] + cc_list,
        cc_emails=cc_list,
        subject=data["subject"],
        body_text=body,
        body_html=html,
        attachments=att_info,
        sent_by_id=current_user.id,
        read_by={str(current_user.id): datetime.utcnow().isoformat()},
    )
    db.add(msg)
    
    thread.last_message_at = datetime.utcnow()
    if close_after:
        thread.status = "closed"
    
    db.commit()
    
    # Log to NowCerts
    _log_outbound_to_nowcerts(db, thread, msg, current_user)
    
    logger.info(f"📤 Reply sent: {from_email} → {to_email} | {thread.subject[:60]}")
    return {"status": "sent", "message_id": msg.id}


# ══════════════════════════════════════════════════════════════════════
# COMPOSE NEW EMAIL
# ══════════════════════════════════════════════════════════════════════

@router.post("/compose")
def compose_email(
    to_email: str = Form(...),
    to_name: str = Form(""),
    cc_emails: str = Form(""),
    subject: str = Form(...),
    body: str = Form(...),
    send_as: str = Form("service"),
    attachments: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compose and send a new email, creating a thread in the inbox."""
    import requests as http_requests

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")

    if not to_email or not subject or not body:
        raise HTTPException(status_code=400, detail="Recipient, subject, and body are required")

    # Determine sender
    if send_as == "personal" and current_user.email:
        from_email = current_user.email
    else:
        from_email = f"service@{settings.MAILGUN_DOMAIN or 'mg.betterchoiceins.com'}"

    from_str = f"{current_user.full_name} <{from_email}>"
    cc_list = [e.strip() for e in cc_emails.split(",") if e.strip()] if cc_emails else []

    # Build branded HTML
    html_body = body.replace('\n', '<br>')
    html = _build_branded_email(html_body, current_user.full_name, from_email)

    # Save attachments
    logger.info(f"📎 Compose: {len(attachments)} attachments received")
    att_info = []
    mg_files = []
    for att in attachments:
        content = att.file.read()
        logger.info(f"📎 File: {att.filename} ({len(content)} bytes, {att.content_type})")
        ext = os.path.splitext(att.filename)[1] if att.filename else ""
        saved_name = f"{uuid.uuid4().hex}{ext}"
        saved_path = os.path.join(ATTACHMENT_DIR, saved_name)
        with open(saved_path, "wb") as f:
            f.write(content)
        att_info.append({
            "filename": att.filename,
            "path": f"/static/email-attachments/{saved_name}",
            "size": len(content),
            "content_type": att.content_type or "application/octet-stream",
        })
        mg_files.append(("attachment", (att.filename, content, att.content_type or "application/octet-stream")))

    # Send via Mailgun
    data = {
        "from": from_str,
        "to": [f"{to_name} <{to_email}>" if to_name else to_email],
        "subject": subject,
        "html": html,
        "h:Reply-To": from_email,
    }
    if cc_list:
        data["cc"] = cc_list

    resp = http_requests.post(
        f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data=data,
        files=mg_files if mg_files else None,
    )
    resp.raise_for_status()
    mg_id = resp.json().get("id", "")

    # Determine mailbox for the thread (sender's mailbox)
    mailbox = _user_to_mailbox(current_user)

    # Try to link to a customer by recipient email
    customer = None
    try:
        from app.models.customer import Customer
        customer = db.query(Customer).filter(
            func.lower(Customer.email) == to_email.lower()
        ).first()
    except Exception:
        pass

    # Create thread
    thread = EmailThread(
        subject=subject,
        from_email=to_email,
        from_name=to_name or to_email.split("@")[0],
        mailbox=mailbox,
        status="closed",  # outbound-initiated threads start closed
        priority="normal",
        participants=[to_email, from_email] + cc_list,
        last_message_at=datetime.utcnow(),
        customer_id=customer.id if customer else None,
        customer_name=customer.display_name if customer else (to_name or None),
    )
    db.add(thread)
    db.flush()

    # Create outbound message
    msg = EmailMessage(
        thread_id=thread.id,
        direction="outbound",
        from_email=from_email,
        from_name=current_user.full_name,
        to_emails=[to_email] + cc_list,
        cc_emails=cc_list,
        subject=subject,
        body_text=body,
        body_html=html,
        attachments=att_info,
        mailgun_message_id=mg_id,
        sent_by_id=current_user.id,
        read_by={str(current_user.id): datetime.utcnow().isoformat()},
    )
    db.add(msg)
    db.commit()

    # Log to NowCerts
    _log_outbound_to_nowcerts(db, thread, msg, current_user)

    logger.info(f"📤 New email composed: {from_email} → {to_email} | {subject[:60]}")
    return {"status": "sent", "thread_id": thread.id, "message_id": msg.id, "to": to_email, "subject": subject}


# ══════════════════════════════════════════════════════════════════════
# AI DRAFT
# ══════════════════════════════════════════════════════════════════════

@router.post("/threads/{thread_id}/ai-draft")
def generate_ai_draft(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate an AI-suggested reply + action items for a thread."""
    import requests as http_requests
    import json as json_module
    
    thread = db.query(EmailThread).filter(EmailThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    messages = (
        db.query(EmailMessage)
        .filter(EmailMessage.thread_id == thread_id)
        .order_by(EmailMessage.created_at)
        .all()
    )
    
    # Build conversation context
    convo = []
    for msg in messages[-6:]:  # Last 6 messages for context
        direction = "Customer" if msg.direction == "inbound" else "Agent"
        body = (msg.body_text or "")[:800]
        convo.append(f"[{direction} — {msg.from_name or msg.from_email}]\n{body}")
    
    conversation_text = "\n\n---\n\n".join(convo)
    
    # Get customer context if available
    customer_context = ""
    if thread.customer_id:
        cust = db.query(Customer).filter(Customer.id == thread.customer_id).first()
        if cust:
            customer_context = f"\nCustomer: {cust.full_name}, Phone: {cust.phone or 'N/A'}, Email: {cust.email or 'N/A'}"
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="AI not configured")
    
    prompt = f"""You are an insurance agency assistant at Better Choice Insurance Group.
Analyze this email thread and provide TWO things:

1. A professional, friendly draft reply to the customer's latest email.
   - Keep it concise (2-4 paragraphs max). Be warm but professional.
   - If you need information you don't have, note what you'd need to look up.
   - Don't include a subject line — just the body text.
   - Don't include a sign-off — the agent's signature is added automatically.

2. A list of action items / next steps the agent should take based on this email.
   - Be specific: "Pull up policy #XYZ to check coverage", "Call customer to discuss renewal", etc.
   - Include any follow-ups, internal tasks, or things to verify.
   - Flag anything time-sensitive or urgent.
{customer_context}

Email thread:
{conversation_text}

Respond in this EXACT JSON format (no markdown, no backticks, just raw JSON):
{{"draft": "your draft reply text here", "action_items": ["action 1", "action 2", "action 3"], "urgency": "low|normal|high|urgent", "summary": "one-sentence summary of what the customer needs"}}"""

    try:
        resp = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["content"][0]["text"] if data.get("content") else ""
        
        # Parse JSON response
        try:
            # Strip any markdown fences if present
            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
            ai_result = json_module.loads(clean)
        except json_module.JSONDecodeError:
            # Fallback: treat entire response as draft
            ai_result = {
                "draft": raw_text,
                "action_items": [],
                "urgency": "normal",
                "summary": "",
            }
        
        draft = ai_result.get("draft", raw_text)
        action_items = ai_result.get("action_items", [])
        urgency = ai_result.get("urgency", "normal")
        summary = ai_result.get("summary", "")
        
        # Save draft to the latest inbound message
        last_inbound = None
        for msg in reversed(messages):
            if msg.direction == "inbound":
                last_inbound = msg
                break
        if last_inbound:
            last_inbound.ai_draft = draft
            last_inbound.ai_draft_generated_at = datetime.utcnow()
        
        # Save summary to thread
        thread.ai_summary = summary
        db.commit()
        
        return {
            "draft": draft,
            "action_items": action_items,
            "urgency": urgency,
            "summary": summary,
        }
    except Exception as e:
        logger.error(f"AI draft generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI draft failed: {str(e)}")


# ══════════════════════════════════════════════════════════════════════
# INBOX STATS
# ══════════════════════════════════════════════════════════════════════

@router.get("/mailboxes")
def get_accessible_mailboxes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get mailboxes the current user can access, with unread counts."""
    is_admin = current_user.role.lower() in ("admin",)
    user_mailbox = _user_to_mailbox(current_user)
    
    if is_admin:
        # Admin sees all mailboxes that have threads
        mailbox_rows = db.query(
            EmailThread.mailbox, func.count(EmailThread.id)
        ).filter(
            EmailThread.status != "closed"
        ).group_by(EmailThread.mailbox).all()
        
        mailboxes = []
        for mb, count in mailbox_rows:
            mailboxes.append({"mailbox": mb, "open_count": count})
        
        # Always include service even if empty
        if not any(m["mailbox"] == "service" for m in mailboxes):
            mailboxes.insert(0, {"mailbox": "service", "open_count": 0})
        
        # Get all employees for admin to see their mailboxes
        all_users = db.query(User).filter(User.is_active == True).all()
        for u in all_users:
            umbox = _user_to_mailbox(u)
            if umbox and not any(m["mailbox"] == umbox for m in mailboxes):
                mailboxes.append({"mailbox": umbox, "open_count": 0})
    else:
        # Regular users see service + their own
        mailboxes = []
        for mb in ["service", user_mailbox]:
            if not mb:
                continue
            count = db.query(func.count(EmailThread.id)).filter(
                EmailThread.mailbox == mb,
                EmailThread.status != "closed",
            ).scalar() or 0
            mailboxes.append({"mailbox": mb, "open_count": count})
    
    # Sort: service first, then alphabetical
    mailboxes.sort(key=lambda m: (0 if m["mailbox"] == "service" else 1, m["mailbox"]))
    
    return {
        "mailboxes": mailboxes,
        "is_admin": is_admin,
        "user_mailbox": user_mailbox,
        "can_assign_anyone": is_admin or current_user.role.lower() in ("retention_specialist", "manager"),
    }


@router.get("/stats")
def inbox_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get inbox statistics."""
    open_count = db.query(func.count(EmailThread.id)).filter(
        EmailThread.status.in_(["open", "assigned"])
    ).scalar() or 0
    
    unassigned = db.query(func.count(EmailThread.id)).filter(
        EmailThread.status == "open",
        EmailThread.assigned_to_id.is_(None),
    ).scalar() or 0
    
    my_assigned = db.query(func.count(EmailThread.id)).filter(
        EmailThread.assigned_to_id == current_user.id,
        EmailThread.status.in_(["open", "assigned"]),
    ).scalar() or 0
    
    snoozed = db.query(func.count(EmailThread.id)).filter(
        EmailThread.status == "snoozed",
    ).scalar() or 0
    
    closed_today = db.query(func.count(EmailThread.id)).filter(
        EmailThread.status == "closed",
        EmailThread.updated_at >= datetime.utcnow().replace(hour=0, minute=0, second=0),
    ).scalar() or 0
    
    # Unread count for current user
    unread_threads = 0
    open_threads = db.query(EmailThread).filter(
        EmailThread.status.in_(["open", "assigned"])
    ).all()
    for t in open_threads:
        last_msg = db.query(EmailMessage).filter(
            EmailMessage.thread_id == t.id,
            EmailMessage.direction == "inbound",
        ).order_by(desc(EmailMessage.created_at)).first()
        if last_msg:
            read_by = last_msg.read_by or {}
            if str(current_user.id) not in read_by:
                unread_threads += 1
    
    return {
        "open": open_count,
        "unassigned": unassigned,
        "my_assigned": my_assigned,
        "snoozed": snoozed,
        "closed_today": closed_today,
        "unread": unread_threads,
    }


# ══════════════════════════════════════════════════════════════════════
# RULES MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

@router.get("/rules")
def list_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    rules = db.query(EmailRule).order_by(EmailRule.priority).all()
    return [_serialize_rule(r) for r in rules]


@router.post("/rules")
def create_rule(
    request_body: dict = Depends(lambda request: request.json()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    rule = EmailRule(
        name=request_body.get("name", "New Rule"),
        conditions=request_body.get("conditions", []),
        match_mode=request_body.get("match_mode", "all"),
        actions=request_body.get("actions", []),
        priority=request_body.get("priority", 100),
        created_by_id=current_user.id,
    )
    db.add(rule)
    db.commit()
    return _serialize_rule(rule)


# ══════════════════════════════════════════════════════════════════════
# MAILGUN ROUTE SETUP — create/check inbound routes
# ══════════════════════════════════════════════════════════════════════

@router.get("/setup/check-routes")
def check_mailgun_routes(
    current_user: User = Depends(get_current_user),
):
    """Check existing Mailgun inbound routes."""
    import requests as http_requests
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if not settings.MAILGUN_API_KEY:
        raise HTTPException(status_code=500, detail="MAILGUN_API_KEY not configured")
    
    try:
        resp = http_requests.get(
            "https://api.mailgun.net/v3/routes",
            auth=("api", settings.MAILGUN_API_KEY),
            params={"limit": 50},
        )
        resp.raise_for_status()
        data = resp.json()
        routes = data.get("items", [])
        
        orbit_routes = []
        other_routes = []
        for r in routes:
            info = {
                "id": r.get("id"),
                "priority": r.get("priority"),
                "description": r.get("description", ""),
                "expression": r.get("expression", ""),
                "actions": r.get("actions", []),
                "created_at": r.get("created_at"),
            }
            if "orbit" in (r.get("description") or "").lower() or "/api/email/inbound" in str(r.get("actions", [])):
                orbit_routes.append(info)
            else:
                other_routes.append(info)
        
        return {
            "total_routes": len(routes),
            "orbit_routes": orbit_routes,
            "other_routes": other_routes,
            "mailgun_domain": settings.MAILGUN_DOMAIN,
            "webhook_url": "https://better-choice-api.onrender.com/api/email/inbound",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check routes: {str(e)}")


@router.post("/setup/create-route")
def create_mailgun_route(
    current_user: User = Depends(get_current_user),
):
    """Create the catch-all inbound route in Mailgun for ORBIT inbox."""
    import requests as http_requests
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")
    
    domain = settings.MAILGUN_DOMAIN
    webhook_url = "https://better-choice-api.onrender.com/api/email/inbound"
    
    # Create catch-all route for @mg.betterchoiceins.com (or configured domain)
    try:
        resp = http_requests.post(
            "https://api.mailgun.net/v3/routes",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "priority": 10,
                "description": "ORBIT Inbox — catch-all for betterchoiceins.com",
                "expression": f'match_recipient(".*@{domain}")',
                "action": [
                    f'forward("{webhook_url}")',
                    "stop()",
                ],
            },
        )
        resp.raise_for_status()
        route_data = resp.json()
        
        logger.info(f"Mailgun inbound route created: {route_data}")
        return {
            "status": "created",
            "route": route_data.get("route", {}),
            "domain": domain,
            "webhook_url": webhook_url,
            "expression": f'match_recipient(".*@{domain}")',
            "note": "All emails to *@" + domain + " will now be forwarded to ORBIT inbox.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create route: {str(e)}")


# ══════════════════════════════════════════════════════════════════════
# MAILGUN HISTORY SYNC
# ══════════════════════════════════════════════════════════════════════

@router.post("/setup/sync-history")
def sync_mailgun_history(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync sent/received email history from Mailgun Events API.
    Mailgun keeps events up to 30 days (paid). Stored message bodies for ~3 days.
    """
    import requests as http_requests
    
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")
    
    domain = settings.MAILGUN_DOMAIN
    begin = datetime.utcnow() - timedelta(days=min(days, 30))
    
    synced = 0
    skipped = 0
    errors = 0
    next_url = f"https://api.mailgun.net/v3/{domain}/events"
    params: dict = {
        "begin": begin.strftime("%a, %d %b %Y %H:%M:%S +0000"),
        "ascending": "yes",
        "limit": 100,
        "event": "stored OR accepted",
    }
    
    page = 0
    max_pages = 20
    
    while next_url and page < max_pages:
        try:
            resp = http_requests.get(
                next_url,
                auth=("api", settings.MAILGUN_API_KEY),
                params=params if page == 0 else None,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            
            for event in items:
                try:
                    r = _sync_event(db, event, domain)
                    if r == "synced":
                        synced += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Sync event error: {e}")
            
            db.commit()
            next_url = data.get("paging", {}).get("next")
            page += 1
        except Exception as e:
            logger.error(f"Events fetch failed page {page}: {e}")
            break
    
    return {"status": "complete", "synced": synced, "skipped": skipped, "errors": errors, "pages": page}


def _sync_event(db: Session, event: dict, domain: str) -> str:
    """Sync a single Mailgun event into ORBIT inbox."""
    headers = event.get("message", {}).get("headers", {})
    message_id = headers.get("message-id", "")
    if not message_id:
        return "skipped"
    
    # Duplicate check
    if db.query(EmailMessage).filter(EmailMessage.mailgun_message_id == message_id).first():
        return "skipped"
    
    timestamp = event.get("timestamp", 0)
    created_at = datetime.utcfromtimestamp(timestamp) if timestamp else datetime.utcnow()
    
    from_name, from_addr = _parse_email_address(headers.get("from", ""))
    to_list = _parse_email_list(headers.get("to", ""))
    subject = headers.get("subject", "(No Subject)")
    
    # Direction
    mg_domain = domain.lower()
    root_domain = mg_domain.replace("mg.", "") if mg_domain.startswith("mg.") else mg_domain
    is_outbound = any(from_addr.lower().endswith(f"@{d}") for d in [mg_domain, root_domain])
    direction = "outbound" if is_outbound else "inbound"
    mailbox = _determine_mailbox(to_list) if direction == "inbound" else "service"
    
    # Thread
    thread = _find_or_create_thread(
        db, subject=subject, from_email=from_addr, from_name=from_name,
        to_emails=to_list, cc_emails=[], mailbox=mailbox,
        in_reply_to="", references="",
    )
    
    # Try to retrieve stored message body
    body_text = ""
    storage_url = event.get("storage", {}).get("url", "") or event.get("message", {}).get("url", "")
    if storage_url:
        try:
            import requests as http_requests
            r = http_requests.get(storage_url, auth=("api", settings.MAILGUN_API_KEY),
                                  headers={"Accept": "application/json"}, timeout=10)
            if r.status_code == 200:
                stored = r.json()
                body_text = stored.get("body-plain", stored.get("stripped-text", ""))
        except Exception:
            pass
    
    msg = EmailMessage(
        thread_id=thread.id, direction=direction,
        from_email=from_addr, from_name=from_name,
        to_emails=to_list, cc_emails=[], subject=subject,
        body_text=body_text, body_html="", attachments=[],
        mailgun_message_id=message_id, read_by={}, created_at=created_at,
    )
    db.add(msg)
    
    if not thread.last_message_at or created_at > thread.last_message_at:
        thread.last_message_at = created_at
    if direction == "inbound":
        _link_customer(db, thread, from_addr)
    
    return "synced"

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _build_branded_email(body_html: str, sender_name: str, sender_email: str) -> str:
    """Build a branded Better Choice Insurance email with consistent design.
    
    Used by ALL outbound emails from ORBIT — replies, quick emails, automations.
    Matches the agency's brand: navy header, clean white body, professional footer.
    """
    app_url = "https://better-choice-api.onrender.com"
    logo_url = f"{app_url}/carrier-logos/bci_header_white.png"
    
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f4f5f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
<div style="max-width:600px; margin:0 auto; background:#ffffff;">

  <!-- Header -->
  <div style="background: linear-gradient(135deg, #1e3a6e 0%, #1e40af 100%); padding:24px 32px; text-align:center;">
    <img src="{logo_url}" alt="Better Choice Insurance Group" style="max-height:44px; width:auto; height:auto;" onerror="this.style.display='none';this.nextElementSibling.style.display='block';" />
    <div style="display:none; color:#ffffff; font-size:18px; font-weight:700; letter-spacing:0.5px;">
      Better Choice Insurance Group
    </div>
  </div>

  <!-- Body -->
  <div style="padding:28px 32px; color:#1f2937; font-size:14px; line-height:1.75;">
    {body_html}
  </div>

  <!-- Signature -->
  <div style="padding:20px 32px; border-top:1px solid #e5e7eb; background:#f9fafb;">
    <table cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td style="padding-right:16px; vertical-align:top;">
          <div style="width:48px; height:48px; border-radius:50%; background:linear-gradient(135deg, #1e3a6e, #1e40af); display:flex; align-items:center; justify-content:center;">
            <span style="color:#ffffff; font-size:16px; font-weight:700;">{sender_name[0] if sender_name else 'B'}</span>
          </div>
        </td>
        <td style="vertical-align:top;">
          <p style="margin:0 0 1px 0; font-weight:600; color:#1f2937; font-size:13px;">{sender_name}</p>
          <p style="margin:0 0 1px 0; color:#6b7280; font-size:11px;">Better Choice Insurance Group</p>
          <p style="margin:0; color:#6b7280; font-size:11px;">
            <a href="tel:+18479085665" style="color:#1e40af; text-decoration:none;">(847) 908-5665</a>
            &nbsp;·&nbsp;
            <a href="mailto:{sender_email}" style="color:#1e40af; text-decoration:none;">{sender_email}</a>
          </p>
        </td>
      </tr>
    </table>
  </div>

  <!-- Footer -->
  <div style="padding:16px 32px; background:#f4f5f7; border-top:1px solid #e5e7eb; text-align:center;">
    <p style="margin:0 0 4px 0; color:#9ca3af; font-size:10px;">
      Better Choice Insurance Group · 225 E Dundee Rd, Palatine, IL 60074
    </p>
    <p style="margin:0; color:#9ca3af; font-size:10px;">
      <a href="https://betterchoiceins.com" style="color:#6b7280; text-decoration:none;">betterchoiceins.com</a>
    </p>
  </div>

</div>
</body>
</html>"""


def _user_to_mailbox(user_obj) -> str:
    """Get mailbox name from user's email prefix (e.g. 'evan@betterchoiceins.com' → 'evan')."""
    if not user_obj:
        return ""
    email = getattr(user_obj, 'email', '') or ''
    if '@' in email:
        return email.split('@')[0].lower().strip()
    # Fallback to username
    username = getattr(user_obj, 'username', '') or ''
    return username.lower().replace(" ", ".").strip()


def _parse_email_address(raw: str) -> tuple:
    """Parse 'Name <email@example.com>' → (name, email)."""
    match = re.match(r'(.*?)\s*<(.+?)>', raw)
    if match:
        return match.group(1).strip().strip('"'), match.group(2).strip()
    return "", raw.strip()


def _parse_email_list(raw: str) -> list:
    """Parse comma-separated email list."""
    if not raw:
        return []
    addresses = []
    for part in raw.split(","):
        _, email = _parse_email_address(part.strip())
        if email and "@" in email:
            addresses.append(email.lower())
    return addresses


def _determine_mailbox(recipients: list) -> str:
    """Determine which mailbox based on recipient addresses.
    
    Matches emails to both mg.betterchoiceins.com (Mailgun subdomain)
    and betterchoiceins.com (agent emails forwarded via Mailgun).
    """
    mg_domain = (settings.MAILGUN_DOMAIN or "mg.betterchoiceins.com").lower()
    # Also match the root domain for agent emails
    root_domain = mg_domain.replace("mg.", "") if mg_domain.startswith("mg.") else mg_domain
    
    for email in recipients:
        email_lower = email.lower()
        local = email_lower.split("@")[0]
        domain = email_lower.split("@")[1] if "@" in email_lower else ""
        
        if local == "service":
            return "service"
        
        # Match @mg.betterchoiceins.com OR @betterchoiceins.com
        if domain in (mg_domain, root_domain):
            # Skip known non-inbox addresses
            if local in ("nonpay", "natgen", "inspection", "noreply", "no-reply"):
                continue
            return local
    
    return "service"  # Default


def _find_or_create_thread(
    db: Session, subject: str, from_email: str, from_name: str,
    to_emails: list, cc_emails: list, mailbox: str,
    in_reply_to: str = "", references: str = "",
) -> EmailThread:
    """Find existing thread by message references or create new one."""
    # Try to find by In-Reply-To
    if in_reply_to:
        existing_msg = db.query(EmailMessage).filter(
            EmailMessage.mailgun_message_id == in_reply_to
        ).first()
        if existing_msg:
            return db.query(EmailThread).filter(EmailThread.id == existing_msg.thread_id).first()
    
    # Try to find by references
    if references:
        for ref_id in references.strip().split():
            existing_msg = db.query(EmailMessage).filter(
                EmailMessage.mailgun_message_id == ref_id.strip()
            ).first()
            if existing_msg:
                return db.query(EmailThread).filter(EmailThread.id == existing_msg.thread_id).first()
    
    # Try to match by subject + sender (within 7 days)
    clean_subject = re.sub(r'^(Re:|Fwd?:)\s*', '', subject, flags=re.IGNORECASE).strip()
    week_ago = datetime.utcnow() - timedelta(days=7)
    existing = db.query(EmailThread).filter(
        EmailThread.from_email == from_email,
        or_(
            EmailThread.subject == subject,
            EmailThread.subject == clean_subject,
            EmailThread.subject == f"Re: {clean_subject}",
        ),
        EmailThread.created_at >= week_ago,
    ).order_by(desc(EmailThread.last_message_at)).first()
    if existing:
        return existing
    
    # Create new thread
    participants = [{"email": e, "type": "to"} for e in to_emails]
    participants += [{"email": e, "type": "cc"} for e in cc_emails]
    
    thread = EmailThread(
        subject=clean_subject or subject,
        mailbox=mailbox,
        status="open",
        from_email=from_email,
        from_name=from_name,
        participants=participants,
        last_message_at=datetime.utcnow(),
    )
    db.add(thread)
    db.flush()
    return thread


def _link_customer(db: Session, thread: EmailThread, from_email: str):
    """Try to link thread to a customer by email."""
    if thread.customer_id:
        return
    customer = db.query(Customer).filter(
        func.lower(Customer.email) == from_email.lower()
    ).first()
    if customer:
        thread.customer_id = customer.id


def _apply_rules(db: Session, thread: EmailThread, msg: EmailMessage):
    """Apply email rules to a new inbound message."""
    rules = db.query(EmailRule).filter(EmailRule.is_active == True).order_by(EmailRule.priority).all()
    
    for rule in rules:
        if _matches_rule(rule, thread, msg):
            _execute_actions(db, rule, thread, msg)


def _matches_rule(rule: EmailRule, thread: EmailThread, msg: EmailMessage) -> bool:
    """Check if a message matches rule conditions."""
    conditions = rule.conditions or []
    if not conditions:
        return False
    
    results = []
    for cond in conditions:
        field = cond.get("field", "")
        op = cond.get("operator", "contains")
        value = cond.get("value", "").lower()
        
        if field == "from":
            test = (msg.from_email or "").lower()
        elif field == "to":
            test = " ".join(msg.to_emails or []).lower()
        elif field == "subject":
            test = (msg.subject or "").lower()
        elif field == "body":
            test = (msg.body_text or "").lower()
        elif field == "mailbox":
            test = (thread.mailbox or "").lower()
        else:
            continue
        
        if op == "contains":
            results.append(value in test)
        elif op == "equals":
            results.append(test == value)
        elif op == "starts_with":
            results.append(test.startswith(value))
        elif op == "ends_with":
            results.append(test.endswith(value))
    
    if rule.match_mode == "any":
        return any(results)
    return all(results)


def _execute_actions(db: Session, rule: EmailRule, thread: EmailThread, msg: EmailMessage):
    """Execute rule actions on a thread."""
    for action in (rule.actions or []):
        act = action.get("action", "")
        params = action.get("params", {})
        
        if act == "assign":
            user_id = params.get("user_id")
            if user_id:
                thread.assigned_to_id = int(user_id)
                thread.assigned_at = datetime.utcnow()
                thread.status = "assigned"
        elif act == "tag":
            tag = params.get("tag")
            if tag:
                tags = list(thread.tags or [])
                if tag not in tags:
                    tags.append(tag)
                    thread.tags = tags
        elif act == "set_priority":
            thread.priority = params.get("priority", "normal")
        elif act == "close":
            thread.status = "closed"
        elif act == "move_mailbox":
            thread.mailbox = params.get("mailbox", thread.mailbox)
    
    logger.info(f"Rule '{rule.name}' applied to thread {thread.id}")


def _log_inbound_to_nowcerts(db: Session, thread: EmailThread, msg: EmailMessage):
    """Log inbound email to NowCerts if customer linked."""
    if not thread.customer_id:
        return
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if not nc or not nc.is_configured:
            return
        
        customer = db.query(Customer).filter(Customer.id == thread.customer_id).first()
        if not customer:
            return
        
        body_preview = (msg.body_text or "")[:300]
        att_names = [a.get("filename", "") for a in (msg.attachments or [])]
        
        note_lines = [
            f"Subject: {msg.subject}",
            f"From: {msg.from_name or msg.from_email} <{msg.from_email}>",
            f"To: {', '.join(msg.to_emails or [])}",
        ]
        if att_names:
            note_lines.append(f"Attachments: {', '.join(att_names)}")
        note_lines.append("")
        note_lines.append(body_preview + ("..." if len(msg.body_text or "") > 300 else ""))
        
        name_parts = (customer.full_name or "").split()
        nc.insert_note({
            "subject": f"📥 Received: {msg.subject or '(No Subject)'}",
            "insured_email": customer.email or msg.from_email,
            "insured_first_name": name_parts[0] if name_parts else "",
            "insured_last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
            "insured_database_id": str(customer.nowcerts_insured_id) if customer.nowcerts_insured_id else "",
            "type": "Email",
            "description": "\n".join(note_lines),
            "creator_name": "ORBIT (Inbound)",
        })
        msg.nowcerts_logged = True
        thread.nowcerts_logged = True
    except Exception as e:
        logger.error(f"NowCerts inbound log failed: {e}")


def _log_outbound_to_nowcerts(db: Session, thread: EmailThread, msg: EmailMessage, user: User):
    """Log outbound reply to NowCerts."""
    if not thread.customer_id:
        return
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if not nc or not nc.is_configured:
            return
        
        customer = db.query(Customer).filter(Customer.id == thread.customer_id).first()
        if not customer:
            return
        
        body_preview = (msg.body_text or "")[:300]
        att_names = [a.get("filename", "") for a in (msg.attachments or [])]
        
        note_lines = [
            f"Subject: {msg.subject}",
            f"From: {user.full_name} <{msg.from_email}>",
            f"To: {', '.join(msg.to_emails or [])}",
        ]
        if att_names:
            note_lines.append(f"Attachments: {', '.join(att_names)}")
        note_lines.append("")
        note_lines.append(body_preview + ("..." if len(msg.body_text or "") > 300 else ""))
        
        name_parts = (customer.full_name or "").split()
        nc.insert_note({
            "subject": f"📤 Sent: {msg.subject or '(No Subject)'}",
            "insured_email": customer.email or "",
            "insured_first_name": name_parts[0] if name_parts else "",
            "insured_last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
            "insured_database_id": str(customer.nowcerts_insured_id) if customer.nowcerts_insured_id else "",
            "type": "Email",
            "description": "\n".join(note_lines),
            "creator_name": f"ORBIT ({user.full_name})",
        })
        msg.nowcerts_logged = True
    except Exception as e:
        logger.error(f"NowCerts outbound log failed: {e}")


def _serialize_thread(thread: EmailThread, current_user_id: int, db: Session) -> dict:
    """Serialize thread for API response."""
    # Get message count and unread status
    msg_count = db.query(func.count(EmailMessage.id)).filter(
        EmailMessage.thread_id == thread.id
    ).scalar() or 0
    
    last_inbound = db.query(EmailMessage).filter(
        EmailMessage.thread_id == thread.id,
        EmailMessage.direction == "inbound",
    ).order_by(desc(EmailMessage.created_at)).first()
    
    is_unread = False
    if last_inbound:
        read_by = last_inbound.read_by or {}
        is_unread = str(current_user_id) not in read_by
    
    # Get preview from last message
    last_msg = db.query(EmailMessage).filter(
        EmailMessage.thread_id == thread.id
    ).order_by(desc(EmailMessage.created_at)).first()
    preview = ""
    if last_msg:
        preview = (last_msg.body_text or "")[:120]
    
    return {
        "id": thread.id,
        "subject": thread.subject,
        "mailbox": thread.mailbox,
        "status": thread.status,
        "priority": thread.priority,
        "from_email": thread.from_email,
        "from_name": thread.from_name,
        "assigned_to_id": thread.assigned_to_id,
        "assigned_to_name": thread.assigned_to.full_name if thread.assigned_to else None,
        "customer_id": thread.customer_id,
        "customer_name": thread.customer.full_name if thread.customer else None,
        "tags": thread.tags or [],
        "message_count": msg_count,
        "is_unread": is_unread,
        "preview": preview,
        "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "snoozed_until": thread.snoozed_until.isoformat() if thread.snoozed_until else None,
        "ai_summary": thread.ai_summary,
        "nowcerts_logged": thread.nowcerts_logged,
    }


def _serialize_message(msg: EmailMessage) -> dict:
    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "direction": msg.direction,
        "from_email": msg.from_email,
        "from_name": msg.from_name,
        "to_emails": msg.to_emails or [],
        "cc_emails": msg.cc_emails or [],
        "subject": msg.subject,
        "body_text": msg.body_text,
        "body_html": msg.body_html,
        "attachments": msg.attachments or [],
        "sent_by_id": msg.sent_by_id,
        "sent_by_name": msg.sent_by.full_name if msg.sent_by else None,
        "ai_draft": msg.ai_draft,
        "read_by": msg.read_by or {},
        "nowcerts_logged": msg.nowcerts_logged,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _serialize_rule(rule: EmailRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "is_active": rule.is_active,
        "priority": rule.priority,
        "conditions": rule.conditions or [],
        "match_mode": rule.match_mode,
        "actions": rule.actions or [],
    }
