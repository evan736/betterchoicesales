"""Inspection Email API — approval workflow endpoints.

- GET  /api/inspection/approve/{token}   — One-click approve from email (no auth)
- GET  /api/inspection/drafts             — List pending drafts (auth required)
- POST /api/inspection/drafts/{id}/reject — Reject a draft (auth required)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.inspection import InspectionDraft
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
    db.commit()

    return {"status": "rejected", "draft_id": draft.id}
