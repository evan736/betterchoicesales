"""Underwriting Requirements API.

Manages UW requirements (proof of prior, excluded drivers, inspections, etc.)
with customer email notifications and NowCerts note integration.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.campaign import UWRequirement

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uw-requirements", tags=["UW Requirements"])


# ── Pydantic schemas ──

class UWRequirementCreate(BaseModel):
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_id: Optional[int] = None
    policy_number: str
    carrier: Optional[str] = None
    requirement_type: str  # proof_of_prior, excluded_driver, etc.
    requirement_description: Optional[str] = None
    due_date: Optional[str] = None  # "2026-03-15"
    consequence: Optional[str] = None
    agent_name: Optional[str] = None
    send_notification: bool = True


class UWRequirementUpdate(BaseModel):
    status: Optional[str] = None
    requirement_description: Optional[str] = None
    due_date: Optional[str] = None
    consequence: Optional[str] = None
    resolution_notes: Optional[str] = None


# ── Requirement type display names ──

REQUIREMENT_TYPES = {
    "proof_of_prior": "Proof of Prior Insurance",
    "excluded_driver": "Excluded Driver Form",
    "non_disclosed_driver": "Non-Disclosed Driver Information",
    "vehicle_registration": "Vehicle Registration",
    "trampoline": "Trampoline Disclosure / Removal",
    "inspection": "Property Inspection",
    "dog_notification": "Dog Breed Disclosure",
    "roof_certification": "Roof Certification / Age Verification",
    "occupancy_verification": "Occupancy Verification",
    "photos": "Property / Vehicle Photos",
    "signature": "Missing Signature",
    "payment": "Payment Information Required",
    "other": "Other Requirement",
}


# ── Email template ──

def _build_uw_email_html(req: UWRequirement) -> str:
    """Build carrier-branded UW requirement notification email."""
    from app.services.welcome_email import CARRIER_INFO, BCI_NAVY, BCI_CYAN

    carrier_key = (req.carrier or "").lower().replace(" ", "_")
    carrier = CARRIER_INFO.get(carrier_key, {})
    accent = carrier.get("accent_color", BCI_CYAN)
    carrier_name = carrier.get("display_name", (req.carrier or "your insurance").title())
    req_display = REQUIREMENT_TYPES.get(req.requirement_type, req.requirement_type.replace("_", " ").title())

    due_str = ""
    if req.due_date:
        try:
            due_str = req.due_date.strftime("%B %d, %Y")
        except:
            due_str = str(req.due_date)

    consequence_html = ""
    if req.consequence:
        consequence_html = f"""
        <div style="background:#FEF2F2;border-left:4px solid #EF4444;padding:12px 16px;margin:16px 0;border-radius:0 8px 8px 0;">
            <p style="margin:0;color:#991B1B;font-size:14px;"><strong>Important:</strong> {req.consequence}</p>
        </div>"""

    due_html = ""
    if due_str:
        due_html = f'<p style="color:#64748B;font-size:14px;margin:8px 0 0 0;"><strong>Deadline:</strong> {due_str}</p>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

  <!-- Header -->
  <div style="background:{BCI_NAVY};padding:24px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:white;font-size:20px;">Better Choice Insurance Group</h1>
    <p style="margin:4px 0 0 0;color:{accent};font-size:13px;">Action Required for Your {carrier_name} Policy</p>
  </div>

  <!-- Body -->
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;">
    <p style="color:#1e293b;font-size:16px;margin:0 0 16px 0;">
      Hi {req.customer_name.split()[0] if req.customer_name else "there"},
    </p>

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 16px 0;">
      We are reaching out regarding your <strong>{carrier_name}</strong> policy
      (<strong>{req.policy_number}</strong>). Your insurance carrier has requested
      the following:
    </p>

    <!-- Requirement Box -->
    <div style="background:#F0F7FF;border:1px solid #DBEAFE;border-radius:8px;padding:20px;margin:16px 0;">
      <p style="margin:0 0 4px 0;color:{accent};font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:1px;">
        Required Action
      </p>
      <p style="margin:0;color:#1e293b;font-size:18px;font-weight:bold;">{req_display}</p>
      {due_html}
      {f'<p style="color:#64748B;font-size:14px;margin:8px 0 0 0;">{req.requirement_description}</p>' if req.requirement_description else ''}
    </div>

    {consequence_html}

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:16px 0;">
      Please submit the required documentation as soon as possible. You can:
    </p>
    <ul style="color:#334155;font-size:14px;line-height:1.8;padding-left:20px;">
      <li>Reply to this email with the required documents attached</li>
      <li>Call us at <strong>(847) 908-5665</strong></li>
      <li>Email us at <a href="mailto:service@betterchoiceins.com" style="color:{accent};">service@betterchoiceins.com</a></li>
    </ul>

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:16px 0 0 0;">
      We are here to help make this as easy as possible. Do not hesitate to reach out
      if you have any questions.
    </p>

    <p style="color:#334155;font-size:14px;margin:24px 0 0 0;">
      Thank you,<br>
      <strong>Better Choice Insurance Group</strong>
    </p>
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:16px;color:#94a3b8;font-size:11px;">
    Better Choice Insurance Group | (847) 908-5665 | service@betterchoiceins.com
  </div>
</div>
</body></html>"""


def _send_uw_email(req: UWRequirement):
    """Send UW requirement notification email via Mailgun."""
    from app.core.config import settings
    import requests as http_requests

    if not req.customer_email:
        logger.debug(f"No email for UW req {req.id}, skipping email")
        return False

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured, skipping UW email")
        return False

    req_display = REQUIREMENT_TYPES.get(req.requirement_type, req.requirement_type.replace("_", " ").title())
    subject = f"Action Required: {req_display} — {req.policy_number}"
    html = _build_uw_email_html(req)

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance Group <service@{settings.MAILGUN_DOMAIN}>",
                "to": [req.customer_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
            },
        )
        if resp.status_code == 200:
            logger.info(f"UW requirement email sent to {req.customer_email} for {req.policy_number}")
            return True
        else:
            logger.warning(f"UW email failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"UW email error: {e}")
        return False


def _add_uw_nowcerts_note(req: UWRequirement):
    """Add NowCerts note for UW requirement."""
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if not nc.is_configured:
            return

        req_display = REQUIREMENT_TYPES.get(req.requirement_type, req.requirement_type)
        parts = req.customer_name.strip().split(maxsplit=1)

        note_body = (
            f"Requirement: {req_display}\n"
            f"Policy: {req.policy_number}\n"
            f"Carrier: {(req.carrier or 'N/A').title()}\n"
            f"Due: {req.due_date or 'N/A'}\n"
            f"{f'Consequence: {req.consequence}' if req.consequence else ''}\n"
            f"Customer notified via email"
        )

        note_data = {
            "subject": f"UW Requirement: {req_display} — {req.policy_number} | {note_body}",
            "insured_email": req.customer_email or "",
            "insured_first_name": parts[0] if parts else "",
            "insured_last_name": parts[1] if len(parts) > 1 else "",
            "type": "Email",
            "creator_name": "BCI UW System",
            "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
        }
        nc.insert_note(note_data)
        logger.info(f"NowCerts note added for UW req {req.policy_number}")
    except Exception as e:
        logger.error(f"NowCerts note failed for UW req: {e}")


# ── API Endpoints ──

@router.post("/")
def create_uw_requirement(
    data: UWRequirementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new UW requirement and optionally notify customer."""
    due_dt = None
    if data.due_date:
        try:
            due_dt = datetime.strptime(data.due_date, "%Y-%m-%d")
        except ValueError:
            pass

    req = UWRequirement(
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        policy_number=data.policy_number,
        carrier=data.carrier,
        requirement_type=data.requirement_type,
        requirement_description=data.requirement_description,
        due_date=due_dt,
        consequence=data.consequence,
        agent_name=data.agent_name,
        created_by=current_user.id,
        status="notified" if data.send_notification else "open",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Send notification
    if data.send_notification and data.customer_email:
        email_sent = _send_uw_email(req)
        if email_sent:
            req.notification_count = 1
            req.last_notified_at = datetime.utcnow()
            req.nowcerts_note_added = True
            _add_uw_nowcerts_note(req)
            db.commit()

            # Fire GHL webhook
            try:
                from app.services.ghl_webhook import get_ghl_service
                ghl = get_ghl_service()
                ghl.fire_uw_requirement(
                    customer_name=data.customer_name,
                    email=data.customer_email or "",
                    phone=data.customer_phone or "",
                    policy_number=data.policy_number,
                    carrier=data.carrier or "",
                    requirement_type=data.requirement_type,
                    description=data.requirement_description or "",
                    due_date=data.due_date or "",
                )
            except Exception as e:
                logger.debug(f"GHL webhook failed: {e}")

    return {
        "id": req.id,
        "status": req.status,
        "notification_sent": req.notification_count > 0,
        "requirement_type": req.requirement_type,
        "policy_number": req.policy_number,
    }


@router.get("/")
def list_uw_requirements(
    status: Optional[str] = None,
    policy_number: Optional[str] = None,
    requirement_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List UW requirements with optional filters."""
    query = db.query(UWRequirement)
    if status:
        query = query.filter(UWRequirement.status == status)
    if policy_number:
        query = query.filter(UWRequirement.policy_number == policy_number)
    if requirement_type:
        query = query.filter(UWRequirement.requirement_type == requirement_type)

    reqs = query.order_by(UWRequirement.created_at.desc()).limit(200).all()

    return {
        "total": len(reqs),
        "requirements": [
            {
                "id": r.id,
                "customer_name": r.customer_name,
                "customer_email": r.customer_email,
                "policy_number": r.policy_number,
                "carrier": r.carrier,
                "requirement_type": r.requirement_type,
                "requirement_display": REQUIREMENT_TYPES.get(r.requirement_type, r.requirement_type),
                "requirement_description": r.requirement_description,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "consequence": r.consequence,
                "status": r.status,
                "notification_count": r.notification_count,
                "last_notified_at": r.last_notified_at.isoformat() if r.last_notified_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "resolution_notes": r.resolution_notes,
                "agent_name": r.agent_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reqs
        ],
    }


@router.patch("/{req_id}")
def update_uw_requirement(
    req_id: int,
    data: UWRequirementUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a UW requirement (status, resolve, etc.)."""
    req = db.query(UWRequirement).filter(UWRequirement.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if data.status:
        req.status = data.status
        if data.status in ("received", "closed"):
            req.resolved_at = datetime.utcnow()
            req.resolved_by = current_user.username
    if data.requirement_description is not None:
        req.requirement_description = data.requirement_description
    if data.due_date:
        try:
            req.due_date = datetime.strptime(data.due_date, "%Y-%m-%d")
        except ValueError:
            pass
    if data.consequence is not None:
        req.consequence = data.consequence
    if data.resolution_notes is not None:
        req.resolution_notes = data.resolution_notes

    db.commit()
    return {"id": req.id, "status": req.status}


@router.post("/{req_id}/resend")
def resend_uw_notification(
    req_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resend notification for a UW requirement."""
    req = db.query(UWRequirement).filter(UWRequirement.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if not req.customer_email:
        raise HTTPException(status_code=400, detail="No email on file for this customer")

    sent = _send_uw_email(req)
    if sent:
        req.notification_count = (req.notification_count or 0) + 1
        req.last_notified_at = datetime.utcnow()
        req.status = "reminded"
        _add_uw_nowcerts_note(req)
        db.commit()

    return {"sent": sent, "notification_count": req.notification_count}


@router.get("/types")
def list_requirement_types():
    """List available requirement types."""
    return {"types": [{"key": k, "label": v} for k, v in REQUIREMENT_TYPES.items()]}
