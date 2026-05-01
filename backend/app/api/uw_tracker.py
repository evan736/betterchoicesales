"""Underwriting Tracker API.

Endpoints:
  POST /api/uw/inbound              — Mailgun webhook for forwarded emails
  GET  /api/uw/items                — list with filters (status, assignee, due-soon)
  GET  /api/uw/items/{id}           — detail
  POST /api/uw/items/{id}/assign    — admin/manager picks assignee
  POST /api/uw/items/{id}/complete  — assignee marks done
  POST /api/uw/items/{id}/reopen    — undo complete
  POST /api/uw/items/{id}/dismiss   — soft-delete (e.g., spam/wrong-channel)
  PATCH /api/uw/items/{id}          — edit fields
  GET  /api/uw/items/{id}/attachment/{idx} — download/preview a PDF attachment
  GET  /api/uw/stats                — counts for dashboard widget
  POST /api/uw/items                — manual create (no email)
"""
import logging
import base64
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form, Response
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_, func
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.uw_item import UWItem, UWActivity
from app.services.uw_extraction import extract_uw_details, lookup_customer_by_policy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uw", tags=["uw-tracker"])


# ───────────────────────────────────────────────────────────────────────────
# Account premium helper — used in every UW notification email so Evan and
# the assignees can see how much business is at risk on this account.
# ───────────────────────────────────────────────────────────────────────────

def _account_total_premium(item: UWItem, premium_by_customer: Optional[dict] = None) -> Optional[float]:
    """Sum of premium across all active policies for this UW item's customer.

    Returns None when:
      - The UW item didn't match a customer (we can't compute account totals
        for an unmatched record)
      - The customer has no policies in the local DB yet (NowCerts sync may
        not have run, or this is a new prospect)

    The point of including this in UW emails is so the agent treating the
    request knows what the dollar exposure is. A $5k account with one home
    policy gets very different treatment than a $30k bundled commercial book.

    Performance: the list serializer calls this for every item. To avoid N+1
    queries when serializing 200 items, callers can pre-build a
    {customer_id: total_premium} dict via _bulk_premium_lookup() and pass
    it in. Without it, this falls back to a fresh per-call DB session
    (fine for single-item email contexts, expensive for list views).
    """
    if not item.customer_id:
        return None
    # Bulk-lookup path — used by list serializer
    if premium_by_customer is not None:
        return premium_by_customer.get(item.customer_id)
    # Single-call fallback — opens its own session
    try:
        from app.models.customer import CustomerPolicy
        from app.core.database import SessionLocal
        _db = SessionLocal()
        try:
            policies = (
                _db.query(CustomerPolicy)
                .filter(CustomerPolicy.customer_id == item.customer_id)
                .filter(or_(
                    CustomerPolicy.status.is_(None),
                    ~func.lower(CustomerPolicy.status).in_(
                        ["cancelled", "canceled", "expired", "lapsed", "non-renewed", "non renewed"]
                    ),
                ))
                .all()
            )
            if not policies:
                return None
            total = sum(float(p.premium or 0) for p in policies)
            return total if total > 0 else None
        finally:
            _db.close()
    except Exception as e:
        logger.debug(f"Could not compute account premium for UW item {item.id}: {e}")
        return None


def _bulk_premium_lookup(customer_ids: list, db: Session) -> dict:
    """Return {customer_id: total_active_premium} for a batch of customers.

    One SQL aggregation instead of N queries. Used by the list endpoint
    serializer. Customers with no active policies are absent from the
    result dict (caller treats absence as None).
    """
    if not customer_ids:
        return {}
    try:
        from app.models.customer import CustomerPolicy
        rows = (
            db.query(
                CustomerPolicy.customer_id,
                func.sum(CustomerPolicy.premium).label("total"),
            )
            .filter(CustomerPolicy.customer_id.in_(customer_ids))
            .filter(or_(
                CustomerPolicy.status.is_(None),
                ~func.lower(CustomerPolicy.status).in_(
                    ["cancelled", "canceled", "expired", "lapsed", "non-renewed", "non renewed"]
                ),
            ))
            .group_by(CustomerPolicy.customer_id)
            .all()
        )
        return {cid: float(total) for cid, total in rows if total and float(total) > 0}
    except Exception as e:
        logger.debug(f"_bulk_premium_lookup failed: {e}")
        return {}


def _format_money(amount: Optional[float]) -> str:
    """$1,234 (no decimals) or em-dash placeholder for None."""
    if amount is None or amount == 0:
        return "—"
    return f"${amount:,.0f}"


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def _can_view(user: User) -> bool:
    """All staff roles can see UW items (their own or all)."""
    return user.role and user.role.lower() in ("admin", "manager", "producer", "retention_specialist")


def _can_admin(user: User) -> bool:
    """Only admin/manager can assign or edit anyone else's items."""
    return user.role and user.role.lower() in ("admin", "manager")


def _log_activity(db: Session, item_id: int, user: Optional[User], action: str, detail: str = ""):
    db.add(UWActivity(
        uw_item_id=item_id,
        user_id=user.id if user else None,
        user_name=(user.full_name or user.username) if user else "system",
        action=action,
        detail=detail,
    ))


def _serialize_item(item: UWItem, include_attachments: bool = False, premium_by_customer: Optional[dict] = None) -> dict:
    """Return UW item as JSON-friendly dict.

    include_attachments: when True, includes attachment metadata
    (filename + size, NOT the base64 bytes) for the kanban preview.
    The base64 bytes are only served via the /attachment/{idx} endpoint
    to keep list responses lean.

    premium_by_customer: optional pre-fetched {customer_id: total_premium}
    dict to avoid N+1 queries when serializing many items at once. List
    endpoints should pre-build this; single-item endpoints can omit it
    and pay the per-call lookup cost.
    """
    today = date.today()
    is_overdue = bool(item.due_date and item.due_date < today and item.status not in ("completed", "dismissed"))
    days_until = (item.due_date - today).days if item.due_date else None

    out = {
        "id": item.id,
        "title": item.title,
        "customer_id": item.customer_id,
        "customer_name": item.customer_name,
        "customer_email": item.customer_email,
        "policy_number": item.policy_number,
        "carrier": item.carrier,
        "line_of_business": item.line_of_business,
        "description": item.description,
        "required_action": item.required_action,
        "consequence": item.consequence,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "days_until_due": days_until,
        "is_overdue": is_overdue,
        "assigned_to": item.assigned_to,
        "assignee_name": item.assignee.full_name if item.assignee else None,
        "assignee_email": item.assignee.email if item.assignee else None,
        "assigned_at": item.assigned_at.isoformat() if item.assigned_at else None,
        "assigned_by": item.assigned_by,
        "assignment_note": item.assignment_note,
        "status": item.status,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "completed_by": item.completed_by,
        "completer_name": item.completer.full_name if item.completer else None,
        "completion_note": item.completion_note,
        "intake_email_subject": item.intake_email_subject,
        "intake_email_from": item.intake_email_from,
        "intake_email_carrier_from": item.intake_email_carrier_from,
        "intake_email_body_text": item.intake_email_body_text,
        "intake_email_body_html": item.intake_email_body_html,
        "intake_received_at": item.intake_received_at.isoformat() if item.intake_received_at else None,
        "ai_confidence": item.ai_confidence,
        # Account total premium — surfaces in kanban card + drawer for
        # at-a-glance "how much business is at risk" visibility.
        "account_premium": _account_total_premium(item, premium_by_customer),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }

    if include_attachments and item.attachment_data:
        atts = []
        for i, att in enumerate(item.attachment_data):
            b64 = att.get("base64_data") or ""
            try:
                size = int(len(b64) * 3 / 4)
            except Exception:
                size = 0
            atts.append({
                "index": i,
                "filename": att.get("filename") or f"attachment_{i}.pdf",
                "content_type": att.get("content_type") or "application/octet-stream",
                "size_bytes": size,
            })
        out["attachments"] = atts
    elif item.attachment_data:
        out["attachment_count"] = len(item.attachment_data)
    else:
        out["attachment_count"] = 0

    return out


# ───────────────────────────────────────────────────────────────────────────
# Mailgun inbound webhook
# ───────────────────────────────────────────────────────────────────────────

@router.post("/inbound")
async def uw_inbound_webhook(request: Request, db: Session = Depends(get_db)):
    """Mailgun forwards emails sent to uw@mail.betterchoiceins.com here.

    Mailgun sends multipart form data including any attachments. We:
      1. Save the raw email + attachments
      2. Run AI extraction to pull policy/customer/due date/required action
      3. Try to match the customer in our DB by policy number → customer name
      4. Create UWItem with status=pending_assignment
      5. Notify Evan that there's a new UW item awaiting assignment

    Mailgun signature verification is optional — gated by env var
    MAILGUN_INBOUND_VERIFY=true. We don't enforce it by default since
    the webhook URL itself is unguessable.
    """
    form = await request.form()
    sender = form.get("From") or form.get("sender") or ""
    subject = form.get("Subject") or form.get("subject") or "(no subject)"
    body_plain = form.get("body-plain") or form.get("stripped-text") or ""
    body_html = form.get("body-html") or form.get("stripped-html") or ""

    # Original carrier (forwarded emails: From = forwarder, original sender in headers)
    # Fallback chain: X-Original-From → first Received: header → forwarder
    carrier_from = (
        form.get("X-Forwarded-From")
        or form.get("X-Original-From")
        or sender
    )

    # Collect attachments (Mailgun sends them as attachment-1, attachment-2, ...)
    attachment_count = int(form.get("attachment-count", 0))
    attachment_data = []
    pdf_bytes_list = []
    for i in range(1, attachment_count + 1):
        att = form.get(f"attachment-{i}")
        if att and hasattr(att, "read"):
            try:
                content = await att.read() if hasattr(att.read, "__await__") else att.file.read()
            except Exception:
                content = att.file.read() if hasattr(att, "file") else b""
            if not content:
                continue
            ctype = att.content_type or "application/octet-stream"
            fname = att.filename or f"attachment_{i}"
            attachment_data.append({
                "filename": fname,
                "content_type": ctype,
                "base64_data": base64.b64encode(content).decode("utf-8"),
            })
            if ctype == "application/pdf" or fname.lower().endswith(".pdf"):
                pdf_bytes_list.append((fname, content))

    logger.info(
        f"UW inbound: from={sender[:60]} subj={subject[:60]} attachments={len(attachment_data)}"
    )

    # Run AI extraction
    try:
        extracted = await extract_uw_details(
            email_body=body_plain or body_html,
            subject=subject,
            sender=carrier_from,
            pdf_bytes_list=pdf_bytes_list,
        )
    except Exception as e:
        logger.error(f"UW extraction crashed: {e}")
        extracted = {
            "title": subject[:60],
            "policy_number": None,
            "customer_name": None,
            "carrier": None,
            "required_action": body_plain[:500],
            "consequence": None,
            "due_date": None,
            "severity": "medium",
            "issues": [],
            "confidence": 0,
        }

    # Look up customer
    customer = None
    try:
        customer = lookup_customer_by_policy(
            db,
            extracted.get("policy_number"),
            extracted.get("customer_name"),
        )
    except Exception as e:
        logger.warning(f"Customer lookup failed: {e}")

    # Parse due_date
    due_date = None
    if extracted.get("due_date"):
        try:
            due_date = date.fromisoformat(extracted["due_date"])
        except Exception:
            pass

    item = UWItem(
        customer_id=customer.id if customer else None,
        customer_name=(customer.full_name if customer else extracted.get("customer_name")),
        customer_email=(customer.email if customer else None),
        policy_number=extracted.get("policy_number"),
        carrier=extracted.get("carrier"),
        line_of_business=extracted.get("line_of_business"),
        title=extracted.get("title") or subject[:60],
        description=extracted.get("required_action"),
        required_action=extracted.get("required_action"),
        consequence=extracted.get("consequence"),
        due_date=due_date,
        status="pending_assignment",
        intake_email_subject=subject,
        intake_email_from=sender,
        intake_email_carrier_from=carrier_from,
        intake_email_body_text=body_plain[:50000] if body_plain else None,
        intake_email_body_html=body_html[:100000] if body_html else None,
        intake_received_at=datetime.utcnow(),
        attachment_data=attachment_data if attachment_data else None,
        ai_extracted=extracted,
        ai_confidence=extracted.get("confidence"),
    )
    db.add(item)
    db.flush()
    _log_activity(db, item.id, None, "created",
                  f"Forwarded by {sender}; AI confidence {extracted.get('confidence', 0)}/100")
    db.commit()
    db.refresh(item)

    # Fire admin alert (best-effort, non-blocking)
    try:
        _send_admin_new_item_alert(item)
    except Exception as e:
        logger.warning(f"Admin alert failed: {e}")

    return {"status": "ok", "id": item.id, "matched_customer": bool(customer)}


def _send_admin_new_item_alert(item: UWItem):
    """Email Evan to let him know there's a new UW item to assign."""
    import os
    import requests as http_requests
    mg_key = os.environ.get("MAILGUN_API_KEY")
    mg_domain = os.environ.get("MAILGUN_DOMAIN")
    if not mg_key or not mg_domain:
        return

    app_url = os.environ.get("APP_URL", "https://better-choice-web.onrender.com")
    due_str = item.due_date.strftime("%b %d, %Y") if item.due_date else "no deadline given"
    customer = item.customer_name or "(unmatched customer)"
    carrier = item.carrier or "(unknown carrier)"
    policy = item.policy_number or "(unknown policy)"
    account_total = _account_total_premium(item)
    premium_row = ""
    if account_total is not None:
        # Only render the row when we have a real number — silent skip
        # when the customer is unmatched or has no synced policies.
        premium_row = (
            f'<tr><td style="color:#64748b;padding:4px 0;">Account Premium:</td>'
            f'<td style="color:#0f172a;font-weight:600;">{_format_money(account_total)}</td></tr>'
        )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
      <div style="background:#1e293b;color:#fff;padding:20px;border-radius:10px 10px 0 0;">
        <div style="font-size:12px;letter-spacing:2px;font-weight:700;">ORBIT · UW TRACKER</div>
        <div style="font-size:18px;font-weight:600;margin-top:6px;">New UW item awaiting assignment</div>
      </div>
      <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;">
        <p style="color:#1e293b;font-size:15px;margin-top:0;"><strong>{item.title or '(no title)'}</strong></p>
        <table style="width:100%;font-size:13px;border-collapse:collapse;margin:12px 0;">
          <tr><td style="color:#64748b;padding:4px 0;width:120px;">Customer:</td><td style="color:#0f172a;">{customer}</td></tr>
          <tr><td style="color:#64748b;padding:4px 0;">Carrier:</td><td style="color:#0f172a;">{carrier}</td></tr>
          <tr><td style="color:#64748b;padding:4px 0;">Policy:</td><td style="color:#0f172a;">{policy}</td></tr>
          {premium_row}
          <tr><td style="color:#64748b;padding:4px 0;">Due:</td><td style="color:#dc2626;font-weight:600;">{due_str}</td></tr>
        </table>
        <p style="color:#475569;font-size:13px;line-height:1.5;">{(item.required_action or '')[:400]}</p>
        <p style="margin:20px 0 0 0;">
          <a href="{app_url}/uw-tracker" style="background:#0ea5e9;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;">
            Open UW Tracker →
          </a>
        </p>
      </div>
    </div>
    """

    http_requests.post(
        f"https://api.mailgun.net/v3/{mg_domain}/messages",
        auth=("api", mg_key),
        data={
            "from": f"ORBIT UW Tracker <noreply@{mg_domain}>",
            "to": "evan@betterchoiceins.com",
            "subject": f"📋 New UW item awaiting assignment — {customer}",
            "html": html,
        },
        timeout=15,
    )


# ───────────────────────────────────────────────────────────────────────────
# List + detail
# ───────────────────────────────────────────────────────────────────────────

@router.get("/items")
def list_uw_items(
    status: Optional[str] = Query(None, description="Filter by status; comma-sep for multiple"),
    assignee: Optional[int] = Query(None, description="user_id; or 'me' via header"),
    overdue_only: bool = Query(False),
    due_within_days: Optional[int] = Query(None, description="Items due within N days"),
    search: Optional[str] = Query(None, description="Search customer/policy"),
    include_completed: bool = Query(False, description="Include completed items"),
    limit: int = Query(200, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_view(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    q = db.query(UWItem)

    # Producers/retention only see their own items unless admin/manager
    if not _can_admin(current_user) and current_user.role.lower() in ("producer", "retention_specialist"):
        q = q.filter(or_(
            UWItem.assigned_to == current_user.id,
            UWItem.status == "pending_assignment",
        ))

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        q = q.filter(UWItem.status.in_(statuses))
    elif not include_completed:
        # Default: hide completed and dismissed unless explicitly asked
        q = q.filter(~UWItem.status.in_(["completed", "dismissed"]))

    if assignee:
        q = q.filter(UWItem.assigned_to == assignee)

    if overdue_only:
        today = date.today()
        q = q.filter(UWItem.due_date < today, UWItem.status.notin_(["completed", "dismissed"]))

    if due_within_days is not None:
        cutoff = date.today() + timedelta(days=due_within_days)
        q = q.filter(UWItem.due_date <= cutoff)

    if search:
        pat = f"%{search.strip()}%"
        q = q.filter(or_(
            UWItem.customer_name.ilike(pat),
            UWItem.policy_number.ilike(pat),
            UWItem.title.ilike(pat),
        ))

    items = q.order_by(
        # sort: pending_assignment first, then overdue, then by due_date asc
        (UWItem.status == "pending_assignment").desc(),
        UWItem.due_date.asc().nullslast(),
        desc(UWItem.created_at),
    ).limit(limit).all()

    # Bulk-fetch premium totals so we don't run N queries when serializing.
    customer_ids = [i.customer_id for i in items if i.customer_id]
    premium_lookup = _bulk_premium_lookup(list(set(customer_ids)), db) if customer_ids else {}

    return {
        "items": [_serialize_item(i, premium_by_customer=premium_lookup) for i in items],
        "count": len(items),
    }


@router.get("/items/{item_id}")
def get_uw_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_view(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="UW item not found")

    activity = (
        db.query(UWActivity)
        .filter(UWActivity.uw_item_id == item_id)
        .order_by(UWActivity.created_at.asc())
        .all()
    )

    out = _serialize_item(item, include_attachments=True)
    out["activity"] = [
        {
            "action": a.action, "detail": a.detail,
            "user_name": a.user_name,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in activity
    ]
    return out


@router.get("/items/{item_id}/attachment/{idx}")
def get_uw_attachment(
    item_id: int,
    idx: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Inline-preview-friendly PDF download. Returns the raw bytes."""
    if not _can_view(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item or not item.attachment_data:
        raise HTTPException(status_code=404, detail="No attachments")
    if idx < 0 or idx >= len(item.attachment_data):
        raise HTTPException(status_code=404, detail="Attachment index out of range")
    att = item.attachment_data[idx]
    try:
        raw = base64.b64decode(att.get("base64_data") or "")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decode attachment")
    fname = att.get("filename") or f"attachment_{idx}.pdf"
    ctype = att.get("content_type") or "application/octet-stream"
    return Response(
        content=raw,
        media_type=ctype,
        headers={
            # inline = browser preview; download = save as
            "Content-Disposition": f'inline; filename="{fname}"',
        },
    )


# ───────────────────────────────────────────────────────────────────────────
# Mutations
# ───────────────────────────────────────────────────────────────────────────

class AssignBody(BaseModel):
    assignee_id: int
    note: Optional[str] = None


@router.post("/items/{item_id}/assign")
def assign_uw_item(
    item_id: int,
    body: AssignBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_admin(current_user):
        raise HTTPException(status_code=403, detail="Only admin/manager can assign")
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="UW item not found")
    target = db.query(User).filter(User.id == body.assignee_id, User.is_active == True).first()
    if not target:
        raise HTTPException(status_code=400, detail="Target user not found or inactive")

    prior = item.assigned_to
    item.assigned_to = target.id
    item.assigned_at = datetime.utcnow()
    item.assigned_by = current_user.id
    item.assignment_note = body.note
    item.status = "assigned" if item.status == "pending_assignment" else item.status
    item.notif_assignment_sent = False  # Reset so the daily scheduler sends fresh

    action = "reassigned" if prior else "assigned"
    detail = f"To {target.full_name or target.username}"
    if body.note:
        detail += f" — {body.note}"
    _log_activity(db, item.id, current_user, action, detail)

    db.commit()
    db.refresh(item)

    # Send immediate assignment notification email to the assignee
    try:
        _send_assignment_notification(item, target)
        item.notif_assignment_sent = True
        db.commit()
    except Exception as e:
        logger.warning(f"Assignment notification failed: {e}")

    return {"status": "ok", "item": _serialize_item(item)}


def _send_assignment_notification(item: UWItem, assignee: User):
    """Immediate email to the assignee when a UW item gets assigned to them."""
    import os
    import requests as http_requests
    mg_key = os.environ.get("MAILGUN_API_KEY")
    mg_domain = os.environ.get("MAILGUN_DOMAIN")
    if not mg_key or not mg_domain or not assignee.email:
        return

    app_url = os.environ.get("APP_URL", "https://better-choice-web.onrender.com")
    due_str = item.due_date.strftime("%b %d, %Y") if item.due_date else "no deadline"
    days_to_go = (item.due_date - date.today()).days if item.due_date else None
    urgency_color = "#dc2626" if (days_to_go is not None and days_to_go <= 7) else "#0ea5e9"
    account_total = _account_total_premium(item)
    premium_line = ""
    if account_total is not None:
        premium_line = (
            f'<div style="color:#475569;font-size:13px;margin-top:6px;">'
            f'Account premium: <strong style="color:#0f172a;">{_format_money(account_total)}</strong>'
            f'</div>'
        )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
      <div style="background:#0ea5e9;color:#fff;padding:20px;border-radius:10px 10px 0 0;">
        <div style="font-size:12px;letter-spacing:2px;font-weight:700;">ORBIT · UW TRACKER</div>
        <div style="font-size:18px;font-weight:600;margin-top:6px;">📋 New UW item assigned to you</div>
      </div>
      <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;">
        <p style="color:#1e293b;font-size:15px;margin-top:0;">Hi {(assignee.full_name or '').split()[0] or 'there'},</p>
        <p style="color:#475569;font-size:14px;line-height:1.5;">An underwriting requirement has been assigned to you:</p>
        <div style="background:#f1f5f9;border-left:4px solid {urgency_color};padding:14px 16px;margin:14px 0;border-radius:4px;">
          <div style="font-weight:700;color:#0f172a;font-size:14px;">{item.title or '(no title)'}</div>
          <div style="color:#475569;font-size:13px;margin-top:4px;">
            {item.customer_name or '(unknown customer)'} &middot; {item.carrier or '(unknown carrier)'}
          </div>
          <div style="color:{urgency_color};font-size:13px;font-weight:600;margin-top:6px;">
            Due: {due_str}
          </div>
          {premium_line}
        </div>
        <p style="color:#475569;font-size:13px;line-height:1.5;">{(item.required_action or '')[:400]}</p>
        <p style="margin:20px 0 0 0;">
          <a href="{app_url}/uw-tracker" style="background:#0ea5e9;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;">
            Open in ORBIT →
          </a>
        </p>
      </div>
    </div>
    """

    http_requests.post(
        f"https://api.mailgun.net/v3/{mg_domain}/messages",
        auth=("api", mg_key),
        data={
            "from": f"ORBIT UW Tracker <noreply@{mg_domain}>",
            "to": assignee.email,
            "subject": f"📋 UW item assigned: {item.customer_name or 'Customer'} — Due {due_str}",
            "html": html,
        },
        timeout=15,
    )


class CompleteBody(BaseModel):
    note: Optional[str] = None


@router.post("/items/{item_id}/complete")
def complete_uw_item(
    item_id: int,
    body: CompleteBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="UW item not found")
    # Allow completion by: assignee, admin/manager, or assigner
    if not (_can_admin(current_user) or item.assigned_to == current_user.id):
        raise HTTPException(status_code=403, detail="Only the assignee or admin/manager can complete")

    item.status = "completed"
    item.completed_at = datetime.utcnow()
    item.completed_by = current_user.id
    item.completion_note = body.note
    detail = body.note or "Marked complete"
    _log_activity(db, item.id, current_user, "completed", detail)
    db.commit()
    db.refresh(item)
    return {"status": "ok", "item": _serialize_item(item)}


@router.post("/items/{item_id}/reopen")
def reopen_uw_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_admin(current_user):
        raise HTTPException(status_code=403, detail="Only admin/manager can reopen")
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="UW item not found")
    item.status = "assigned" if item.assigned_to else "pending_assignment"
    item.completed_at = None
    item.completed_by = None
    item.completion_note = None
    _log_activity(db, item.id, current_user, "reopened", "")
    db.commit()
    db.refresh(item)
    return {"status": "ok", "item": _serialize_item(item)}


@router.post("/items/{item_id}/dismiss")
def dismiss_uw_item(
    item_id: int,
    body: CompleteBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete: e.g., spam, wrong-channel, duplicate. Stays in DB for audit."""
    if not _can_admin(current_user):
        raise HTTPException(status_code=403, detail="Only admin/manager can dismiss")
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="UW item not found")
    item.status = "dismissed"
    _log_activity(db, item.id, current_user, "dismissed", body.note or "")
    db.commit()
    return {"status": "ok"}


class EditBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_action: Optional[str] = None
    consequence: Optional[str] = None
    due_date: Optional[str] = None  # YYYY-MM-DD
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    line_of_business: Optional[str] = None


@router.patch("/items/{item_id}")
def edit_uw_item(
    item_id: int,
    body: EditBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(UWItem).filter(UWItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="UW item not found")
    if not (_can_admin(current_user) or item.assigned_to == current_user.id):
        raise HTTPException(status_code=403, detail="Only assignee or admin/manager can edit")

    changes = []
    payload = body.model_dump(exclude_unset=True)
    for field, value in payload.items():
        if field == "due_date" and value:
            try:
                value = date.fromisoformat(value)
            except Exception:
                raise HTTPException(status_code=400, detail="due_date must be YYYY-MM-DD")
        old = getattr(item, field)
        if old != value:
            changes.append(f"{field}: {old} → {value}")
            setattr(item, field, value)

    if changes:
        # If due date changes, reset reminder flags so they re-fire correctly
        if "due_date" in payload:
            item.notif_3day_sent = False
            item.notif_1day_sent = False
            item.notif_overdue_sent = False
        _log_activity(db, item.id, current_user, "edited", "; ".join(changes))
        db.commit()
        db.refresh(item)
    return {"status": "ok", "item": _serialize_item(item)}


# ───────────────────────────────────────────────────────────────────────────
# Stats (for dashboard widget)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/stats")
def uw_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_view(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    today = date.today()
    base = db.query(UWItem).filter(UWItem.status.notin_(["completed", "dismissed"]))

    total_open = base.count()
    pending = base.filter(UWItem.status == "pending_assignment").count()
    overdue = base.filter(UWItem.due_date < today).count()
    due_7d = base.filter(UWItem.due_date.between(today, today + timedelta(days=7))).count()

    # Assigned to current user (for "your items" count)
    yours = base.filter(UWItem.assigned_to == current_user.id).count()
    yours_overdue = base.filter(
        UWItem.assigned_to == current_user.id,
        UWItem.due_date < today,
    ).count()

    return {
        "total_open": total_open,
        "pending_assignment": pending,
        "overdue": overdue,
        "due_within_7_days": due_7d,
        "your_items_open": yours,
        "your_items_overdue": yours_overdue,
    }


@router.get("/premium-by-producer")
def uw_premium_by_producer(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Total UW account premium at risk, broken down by assignee.

    'At risk' = sum of account_premium across all open UW items
    (status != completed/dismissed), grouped by who they're assigned to.
    Unassigned items roll up under 'Pending Assignment'.

    The 'account premium' for each item is the sum of the customer's
    active policies in the local DB — same number that renders on the
    kanban card pill. Items where we couldn't match a customer or where
    the customer has no synced policies contribute zero (they don't
    cause the row to be missing entirely; the row just shows the count
    without dollars).

    Used by the 'Total UW Premium at Risk' panel at the top of
    /uw-tracker so the team can see which producer has the biggest
    book of UW work in front of them.
    """
    if not _can_view(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    open_items = (
        db.query(UWItem)
        .filter(UWItem.status.notin_(["completed", "dismissed"]))
        .all()
    )

    customer_ids = list({i.customer_id for i in open_items if i.customer_id})
    premium_lookup = _bulk_premium_lookup(customer_ids, db) if customer_ids else {}

    # Group by assignee (None = pending assignment)
    by_producer: dict = {}
    for item in open_items:
        prem = premium_lookup.get(item.customer_id, 0.0) if item.customer_id else 0.0
        if item.assigned_to:
            key = item.assigned_to
            name = item.assignee.full_name if item.assignee else f"User {item.assigned_to}"
        else:
            key = None
            name = "Pending Assignment"
        if key not in by_producer:
            by_producer[key] = {
                "assignee_id": key,
                "assignee_name": name,
                "item_count": 0,
                "total_premium": 0.0,
            }
        by_producer[key]["item_count"] += 1
        by_producer[key]["total_premium"] += prem

    # Sort: highest premium first, with 'Pending Assignment' always last
    # so it doesn't confuse the producer leaderboard
    rows = list(by_producer.values())
    rows.sort(
        key=lambda r: (r["assignee_id"] is None, -r["total_premium"], -r["item_count"])
    )

    grand_total_premium = sum(r["total_premium"] for r in rows)
    grand_total_count = sum(r["item_count"] for r in rows)

    return {
        "by_producer": rows,
        "total_premium": grand_total_premium,
        "total_count": grand_total_count,
    }


# ───────────────────────────────────────────────────────────────────────────
# Manual create
# ───────────────────────────────────────────────────────────────────────────

class ManualCreateBody(BaseModel):
    title: str
    customer_name: Optional[str] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    line_of_business: Optional[str] = None
    description: Optional[str] = None
    required_action: Optional[str] = None
    due_date: Optional[str] = None
    assignee_id: Optional[int] = None


@router.post("/items")
def create_manual_uw(
    body: ManualCreateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a UW item manually (no email forward) — for cases where the agent
    knows about a UW issue from a phone call / portal / non-email channel."""
    if not _can_view(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    due_date = None
    if body.due_date:
        try:
            due_date = date.fromisoformat(body.due_date)
        except Exception:
            raise HTTPException(status_code=400, detail="due_date must be YYYY-MM-DD")

    # Try matching customer
    customer = None
    if body.policy_number or body.customer_name:
        customer = lookup_customer_by_policy(db, body.policy_number, body.customer_name)

    item = UWItem(
        customer_id=customer.id if customer else None,
        customer_name=(customer.full_name if customer else body.customer_name),
        customer_email=(customer.email if customer else None),
        policy_number=body.policy_number,
        carrier=body.carrier,
        line_of_business=body.line_of_business,
        title=body.title,
        description=body.description,
        required_action=body.required_action or body.description,
        due_date=due_date,
        status="pending_assignment" if not body.assignee_id else "assigned",
        assigned_to=body.assignee_id,
        assigned_at=datetime.utcnow() if body.assignee_id else None,
        assigned_by=current_user.id if body.assignee_id else None,
    )
    db.add(item)
    db.flush()
    _log_activity(db, item.id, current_user, "created", "Manually created (not from email)")
    if body.assignee_id:
        target = db.query(User).filter(User.id == body.assignee_id).first()
        if target:
            _log_activity(db, item.id, current_user, "assigned",
                          f"To {target.full_name or target.username}")
    db.commit()
    db.refresh(item)

    # Send assignment notification if applicable
    if body.assignee_id and item.assignee:
        try:
            _send_assignment_notification(item, item.assignee)
            item.notif_assignment_sent = True
            db.commit()
        except Exception as e:
            logger.warning(f"Assignment notification failed: {e}")

    return {"status": "ok", "item": _serialize_item(item)}
