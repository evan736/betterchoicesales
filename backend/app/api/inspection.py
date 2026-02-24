"""Inspection Email API — approval workflow endpoints.

- GET  /api/inspection/approve/{token}   — One-click approve from email (no auth)
- GET  /api/inspection/drafts             — List pending drafts (auth required)
- POST /api/inspection/drafts/{id}/reject — Reject a draft (auth required)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.inspection import InspectionDraft
from app.models.task import Task, TaskStatus
from app.services.inspection_email import approve_by_token, approve_and_send

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/inspection", tags=["Inspection"])


@router.get("/approve/{token}", response_class=HTMLResponse)
def approve_via_email_link(token: str, db: Session = Depends(get_db)):
    """One-click approve from Evan's email. No auth — token is the secret.
    
    Returns a nice HTML confirmation page.
    """
    result = approve_by_token(token, db)

    if result.get("success"):
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Email Approved & Sent</title></head>
        <body style="margin:0;padding:40px 20px;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
        <div style="max-width:500px;margin:0 auto;text-align:center;">
            <div style="background:white;border-radius:16px;padding:40px;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
                <div style="width:80px;height:80px;background:linear-gradient(135deg,#059669,#10b981);border-radius:50%;margin:0 auto 20px;display:flex;align-items:center;justify-content:center;">
                    <span style="font-size:40px;">✅</span>
                </div>
                <h1 style="color:#1e293b;margin:0 0 12px;font-size:24px;">Email Sent!</h1>
                <p style="color:#64748b;font-size:16px;margin:0 0 8px;">
                    The inspection follow-up email has been sent to the customer.
                </p>
                <p style="color:#94a3b8;font-size:14px;margin:0;">Draft #{result.get('draft_id', '')}</p>
            </div>
        </div></body></html>"""
    else:
        error = result.get("error", "Unknown error")
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Approval Issue</title></head>
        <body style="margin:0;padding:40px 20px;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
        <div style="max-width:500px;margin:0 auto;text-align:center;">
            <div style="background:white;border-radius:16px;padding:40px;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
                <div style="width:80px;height:80px;background:linear-gradient(135deg,#d97706,#f59e0b);border-radius:50%;margin:0 auto 20px;display:flex;align-items:center;justify-content:center;">
                    <span style="font-size:40px;">⚠️</span>
                </div>
                <h1 style="color:#1e293b;margin:0 0 12px;font-size:24px;">Could Not Send</h1>
                <p style="color:#64748b;font-size:16px;margin:0;">{error}</p>
            </div>
        </div></body></html>"""

    return HTMLResponse(content=html)


@router.get("/drafts")
def list_drafts(
    status: str = "pending_review",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List inspection drafts, filtered by status."""
    drafts = (
        db.query(InspectionDraft)
        .filter(InspectionDraft.status == status)
        .order_by(InspectionDraft.created_at.desc())
        .limit(50)
        .all()
    )

    return {
        "drafts": [
            {
                "id": d.id,
                "status": d.status,
                "policy_number": d.policy_number,
                "customer_name": d.customer_name,
                "customer_email": d.customer_email,
                "carrier": d.carrier,
                "deadline": d.deadline,
                "action_required": d.action_required,
                "issues_found": d.issues_found,
                "severity": d.severity,
                "source_sender": d.source_sender,
                "source_subject": d.source_subject,
                "attachment_info": d.attachment_info,
                "task_id": d.task_id,
                "draft_subject": d.draft_subject,
                "draft_html": d.draft_html,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "approved_by": d.approved_by,
                "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            }
            for d in drafts
        ],
        "count": len(drafts),
        "filter_status": status,
    }


@router.post("/drafts/{draft_id}/approve")
def approve_draft_api(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a draft via the API (from the ORBIT dashboard)."""
    result = approve_and_send(draft_id, db, approved_by=current_user.username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a draft — mark it as rejected, no email sent."""
    draft = db.query(InspectionDraft).filter(InspectionDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Draft already {draft.status}")

    draft.status = "rejected"
    draft.approved_by = current_user.username

    # Also close the associated task if one exists
    if draft.task_id:
        task = db.query(Task).filter(Task.id == draft.task_id).first()
        if task:
            task.status = TaskStatus.COMPLETED
            task.notes = (task.notes or "") + "\n[Draft rejected — task auto-closed]"

    db.commit()

    return {"status": "rejected", "draft_id": draft.id}


@router.patch("/drafts/{draft_id}")
def update_draft(
    draft_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a pending inspection draft — update customer email, action text, deadline, etc.
    
    Allows editing before approval. Also regenerates the draft email HTML.
    """
    draft = db.query(InspectionDraft).filter(InspectionDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Draft already {draft.status} — cannot edit")

    # Updatable fields
    editable = ["customer_email", "customer_name", "action_required", "deadline", "severity", "issues_found"]
    changed = False
    for field in editable:
        if field in body:
            setattr(draft, field, body[field])
            changed = True

    if changed:
        # Regenerate the draft email HTML with updated details
        details = draft.extraction_details or {}
        details["action_required"] = draft.action_required
        details["deadline"] = draft.deadline
        details["issues_found"] = draft.issues_found or []
        details["severity"] = draft.severity

        from app.services.inspection_email import build_inspection_customer_email
        draft_subject, draft_html = build_inspection_customer_email(
            customer_name=draft.customer_name or "Valued Customer",
            policy_number=draft.policy_number or "",
            carrier=draft.carrier or "",
            details=details,
        )
        draft.draft_subject = draft_subject
        draft.draft_html = draft_html
        draft.extraction_details = details
        db.commit()

    return {
        "status": "updated",
        "draft_id": draft.id,
        "customer_email": draft.customer_email,
        "customer_name": draft.customer_name,
        "action_required": draft.action_required,
        "deadline": draft.deadline,
        "severity": draft.severity,
        "issues_found": draft.issues_found,
        "draft_subject": draft.draft_subject,
    }


@router.get("/drafts/{draft_id}/preview", response_class=HTMLResponse)
def preview_draft_email(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the draft HTML for preview in an iframe."""
    draft = db.query(InspectionDraft).filter(InspectionDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if not draft.draft_html:
        # Generate it on the fly
        details = draft.extraction_details or {}
        details["action_required"] = draft.action_required
        details["deadline"] = draft.deadline
        details["issues_found"] = draft.issues_found or []
        details["severity"] = draft.severity

        from app.services.inspection_email import build_inspection_customer_email
        draft_subject, draft_html = build_inspection_customer_email(
            customer_name=draft.customer_name or "Valued Customer",
            policy_number=draft.policy_number or "",
            carrier=draft.carrier or "",
            details=details,
        )
        draft.draft_subject = draft_subject
        draft.draft_html = draft_html
        db.commit()
        return HTMLResponse(content=draft_html)

    return HTMLResponse(content=draft.draft_html)


@router.get("/drafts/{draft_id}/attachments")
def list_draft_attachments(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List attachments for a draft."""
    draft = db.query(InspectionDraft).filter(InspectionDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"attachments": draft.attachment_info or [], "draft_id": draft.id}


@router.get("/drafts/{draft_id}/attachment/{index}")
def download_draft_attachment(
    draft_id: int,
    index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a specific PDF attachment from a draft."""
    import pickle
    from fastapi.responses import Response

    draft = db.query(InspectionDraft).filter(InspectionDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if not draft.attachment_data:
        raise HTTPException(status_code=404, detail="No attachments on this draft")

    try:
        attachments = pickle.loads(draft.attachment_data)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load attachment data")

    if index < 0 or index >= len(attachments):
        raise HTTPException(status_code=404, detail=f"Attachment index {index} out of range (0-{len(attachments)-1})")

    filename, pdf_bytes = attachments[index]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )

@router.post("/test-forward")
async def test_forward_inspection_email(
    sender: str = "",
    subject: str = "",
    body_plain: str = "",
    body_html: str = "",
    attachments: list = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test endpoint: simulate an inbound carrier inspection email.
    
    Accepts multipart form data — forward a real carrier email here:
    - sender: original sender (e.g. Jamie.Zuppa@NGIC.com)
    - subject: original subject
    - body_plain: plain text body
    - body_html: HTML body
    - attachments: PDF file uploads (multipart)
    
    This runs the full inspection pipeline: detection → Claude extraction → 
    customer lookup → draft creation → Evan approval email.
    """
    from fastapi import UploadFile, File, Form, Request
    # Re-import needed since this uses the service directly
    from app.services.inspection_email import is_inspection_email, handle_inspection_email

    logger.info("Test forward: sender=%s subject=%s", sender, subject[:80])

    return {"status": "use_form_endpoint", "message": "Use POST /api/inspection/test-forward-form with multipart form data"}


@router.post("/test-forward-form")
async def test_forward_form(
    request: "Request",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test endpoint: forward a real carrier email with PDF attachments.
    
    Send as multipart form with fields:
    - sender: original sender email
    - subject: original subject line  
    - body_plain: plain text body
    - body_html: HTML body (optional)
    - file(s): PDF attachments (field name: files)
    
    Example curl:
      curl -X POST .../api/inspection/test-forward-form \\
        -H "Authorization: Bearer TOKEN" \\
        -F "sender=Jamie.Zuppa@NGIC.com" \\
        -F "subject=2033220589 Nancy Pilato" \\
        -F "body_plain=Coverage A revision..." \\
        -F "files=@inspection_report.pdf"
    """
    from app.services.inspection_email import handle_inspection_email

    form = await request.form()
    
    sender = str(form.get("sender", ""))
    subject_val = str(form.get("subject", ""))
    body_plain = str(form.get("body_plain", ""))
    body_html = str(form.get("body_html", ""))

    # Collect file uploads
    pdf_attachments = []
    for key in form:
        val = form[key]
        if hasattr(val, 'filename') and hasattr(val, 'read'):
            file_bytes = await val.read()
            if file_bytes and len(file_bytes) > 0:
                fname = val.filename or f"attachment_{len(pdf_attachments)+1}.pdf"
                pdf_attachments.append((fname, file_bytes))
                logger.info("Test forward: received attachment %s (%d bytes)", fname, len(file_bytes))

    logger.info("Test forward: sender=%s subject=%s attachments=%d body_len=%d",
                sender, subject_val[:80], len(pdf_attachments), len(body_plain) + len(body_html))

    if not sender and not subject_val and not body_plain and not body_html:
        raise HTTPException(status_code=400, detail="No email content provided. Send sender, subject, body_plain, and optionally files.")

    try:
        result = await handle_inspection_email(
            sender=sender,
            subject=subject_val,
            html_body=body_html,
            plain_body=body_plain,
            attachments=pdf_attachments,
            db=db,
        )
        return result
    except Exception as e:
        logger.error("Test forward failed: %s", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup-orphaned-tasks")
def cleanup_orphaned_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close tasks linked to rejected inspection drafts."""
    if (current_user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    # Find rejected drafts that still have open tasks
    rejected = db.query(InspectionDraft).filter(
        InspectionDraft.status == "rejected",
        InspectionDraft.task_id.isnot(None),
    ).all()

    closed = []
    for draft in rejected:
        task = db.query(Task).filter(Task.id == draft.task_id).first()
        if task and task.status in ("open", "in_progress"):
            task.status = TaskStatus.COMPLETED
            task.notes = (task.notes or "") + "\n[Auto-closed: draft was rejected]"
            closed.append({"task_id": task.id, "draft_id": draft.id, "policy": draft.policy_number})

    # Also find duplicate inspection tasks (same policy, multiple open tasks)
    from sqlalchemy import func
    dupes = db.query(Task.policy_number, func.count(Task.id)).filter(
        Task.task_type == "inspection",
        Task.status.in_(["open", "in_progress"]),
    ).group_by(Task.policy_number).having(func.count(Task.id) > 1).all()

    for policy_number, count in dupes:
        tasks = db.query(Task).filter(
            Task.policy_number == policy_number,
            Task.task_type == "inspection",
            Task.status.in_(["open", "in_progress"]),
        ).order_by(Task.created_at.desc()).all()
        # Keep the newest, close the rest
        for t in tasks[1:]:
            t.status = TaskStatus.COMPLETED
            t.notes = (t.notes or "") + "\n[Auto-closed: duplicate]"
            closed.append({"task_id": t.id, "policy": policy_number, "reason": "duplicate"})

    db.commit()
    return {"closed": closed, "count": len(closed)}


@router.post("/run-compliance-reminders")
def trigger_compliance_reminders(
    dry_run: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger compliance reminder check. Set dry_run=false to actually send."""
    if (current_user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    from app.services.compliance_reminders import run_compliance_reminders
    result = run_compliance_reminders(db, dry_run=dry_run)
    return result
