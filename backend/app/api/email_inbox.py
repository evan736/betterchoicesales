"""Email Inbox API — shared inbox, inbound routing, AI drafts, thread management."""
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


# ══════════════════════════════════════════════════════════════════════
# MAILGUN INBOUND WEBHOOK — receives all incoming email
# ══════════════════════════════════════════════════════════════════════

@router.post("/inbound")
async def inbound_email(request: Request):
    """Mailgun inbound webhook — receives parsed emails."""
    try:
        form = await request.form()
        
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
    """List email threads with filters."""
    q = db.query(EmailThread)
    
    if mailbox:
        q = q.filter(EmailThread.mailbox == mailbox)
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
        from_email = "service@betterchoiceins.com"
    
    from_str = f"{current_user.full_name} <{from_email}>"
    
    # Reply to the original sender
    to_email = thread.from_email
    to_name = thread.from_name or ""
    cc_list = [e.strip() for e in cc_emails.split(",") if e.strip()] if cc_emails else []
    
    # Get last message for In-Reply-To
    last_msg = db.query(EmailMessage).filter(
        EmailMessage.thread_id == thread_id
    ).order_by(desc(EmailMessage.created_at)).first()
    
    # Build HTML
    html_body = body.replace('\n', '<br>')
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden;">
      <div style="background: #1e40af; padding: 20px 28px;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
          <td style="color: #ffffff; font-size: 17px; font-weight: 700; letter-spacing: 0.3px;">Better Choice Insurance Group</td>
        </tr></table>
      </div>
      <div style="padding: 28px; color: #1f2937; font-size: 14px; line-height: 1.75; background: #ffffff;">
        {html_body}
      </div>
      <div style="padding: 18px 28px; border-top: 1px solid #e5e7eb; background: #f9fafb;">
        <p style="margin: 0 0 2px 0; font-weight: 600; color: #1f2937; font-size: 13px;">{current_user.full_name}</p>
        <p style="margin: 0; color: #6b7280; font-size: 12px;">Better Choice Insurance Group</p>
        <p style="margin: 0; color: #6b7280; font-size: 12px;">(847) 908-5665 · {from_email}</p>
      </div>
    </div>
    """
    
    # Save attachments
    att_info = []
    mg_files = []
    for att in attachments:
        content = att.file.read()
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
# AI DRAFT
# ══════════════════════════════════════════════════════════════════════

@router.post("/threads/{thread_id}/ai-draft")
def generate_ai_draft(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate an AI-suggested reply for a thread."""
    import requests as http_requests
    
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
    
    prompt = f"""You are a helpful insurance agency assistant at Better Choice Insurance Group. 
Draft a professional, friendly reply to the customer's latest email.

Keep it concise (2-4 paragraphs max). Be warm but professional. 
If you need information you don't have, note what you'd need to look up.
Don't include a subject line — just the body text.
Sign off as the agent's name will be added automatically.
{customer_context}

Email thread:
{conversation_text}

Draft a reply:"""

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
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        draft = data["content"][0]["text"] if data.get("content") else ""
        
        # Save draft to the latest inbound message
        last_inbound = None
        for msg in reversed(messages):
            if msg.direction == "inbound":
                last_inbound = msg
                break
        if last_inbound:
            last_inbound.ai_draft = draft
            last_inbound.ai_draft_generated_at = datetime.utcnow()
            db.commit()
        
        return {"draft": draft}
    except Exception as e:
        logger.error(f"AI draft generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI draft failed: {str(e)}")


# ══════════════════════════════════════════════════════════════════════
# INBOX STATS
# ══════════════════════════════════════════════════════════════════════

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
    
    # Create catch-all route for @betterchoiceins.com
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
# HELPERS
# ══════════════════════════════════════════════════════════════════════

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
    """Determine which mailbox based on recipient addresses."""
    for email in recipients:
        local = email.split("@")[0].lower()
        if local == "service":
            return "service"
        # Check if it matches a user's email prefix
        if "@betterchoiceins.com" in email.lower():
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
