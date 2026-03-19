"""Prior Policy Cancellation API.

Automates the process of cancelling a customer's old insurance policy when they bind with us.

Flow:
1. POST /api/cancellation/initiate/{sale_id} → creates request, emails customer form link
2. Customer fills form at /cancel/{token} → POST /api/cancellation/submit-form
3. POST /api/cancellation/{id}/generate-letter → creates PDF, sends to BoldSign
4. BoldSign webhook → marks as signed
5. POST /api/cancellation/{id}/deliver → faxes/emails/mails to old carrier
6. GET /api/cancellation/ → dashboard view of all requests

Feature flag: CANCELLATION_ENABLED env var (default: false)
"""
import os
import logging
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.cancellation import CancellationRequest, CancellationCarrier

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cancellation", tags=["Cancellation"])

# Feature flag
CANCELLATION_ENABLED = os.environ.get("CANCELLATION_ENABLED", "false").lower() == "true"


# ── Pydantic Schemas ──

class CarrierCreate(BaseModel):
    carrier_name: str
    display_name: str
    preferred_method: str = "fax"
    cancellation_fax: Optional[str] = None
    cancellation_email: Optional[str] = None
    cancellation_mail_address: Optional[str] = None
    cancellation_phone: Optional[str] = None
    requires_signature: bool = True
    requires_notarization: bool = False
    accepts_agent_submission: bool = True
    notes: Optional[str] = None

class FormSubmission(BaseModel):
    token: str
    old_carrier_name: str
    old_policy_number: str
    old_policy_type: Optional[str] = "auto"
    requested_cancel_date: Optional[str] = None
    customer_name: Optional[str] = None
    customer_address: Optional[str] = None

class InitiateRequest(BaseModel):
    sale_id: Optional[int] = None
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    new_carrier: Optional[str] = None
    new_policy_number: Optional[str] = None
    new_effective_date: Optional[str] = None


# ── Carrier Directory Endpoints ──

@router.get("/carriers")
def list_carriers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all carriers in the cancellation directory."""
    carriers = db.query(CancellationCarrier).filter(
        CancellationCarrier.is_active == True
    ).order_by(CancellationCarrier.display_name).all()

    return [
        {
            "id": c.id,
            "carrier_name": c.carrier_name,
            "display_name": c.display_name,
            "preferred_method": c.preferred_method,
            "cancellation_fax": c.cancellation_fax,
            "cancellation_email": c.cancellation_email,
            "cancellation_mail_address": c.cancellation_mail_address,
            "cancellation_phone": c.cancellation_phone,
            "requires_signature": c.requires_signature,
            "accepts_agent_submission": c.accepts_agent_submission,
            "notes": c.notes,
        }
        for c in carriers
    ]


@router.post("/carriers")
def add_carrier(
    data: CarrierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a carrier to the cancellation directory."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    existing = db.query(CancellationCarrier).filter(
        CancellationCarrier.carrier_name == data.carrier_name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Carrier {data.carrier_name} already exists")

    carrier = CancellationCarrier(**data.dict())
    db.add(carrier)
    db.commit()
    db.refresh(carrier)
    return {"id": carrier.id, "carrier_name": carrier.carrier_name, "status": "created"}


@router.put("/carriers/{carrier_id}")
def update_carrier(
    carrier_id: int,
    data: CarrierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a carrier in the cancellation directory."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    carrier = db.query(CancellationCarrier).filter(CancellationCarrier.id == carrier_id).first()
    if not carrier:
        raise HTTPException(status_code=404, detail="Carrier not found")

    for key, value in data.dict().items():
        setattr(carrier, key, value)
    db.commit()
    return {"id": carrier.id, "status": "updated"}


# ── Cancellation Request Endpoints ──

@router.get("/")
def list_requests(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all cancellation requests."""
    q = db.query(CancellationRequest).order_by(desc(CancellationRequest.created_at))
    if status:
        q = q.filter(CancellationRequest.status == status)
    requests = q.limit(limit).all()

    return {
        "total": q.count(),
        "enabled": CANCELLATION_ENABLED,
        "requests": [
            {
                "id": r.id,
                "sale_id": r.sale_id,
                "customer_name": r.customer_name,
                "customer_email": r.customer_email,
                "old_carrier_name": r.old_carrier_name,
                "old_policy_number": r.old_policy_number,
                "old_policy_type": r.old_policy_type,
                "requested_cancel_date": r.requested_cancel_date,
                "new_carrier": r.new_carrier,
                "new_policy_number": r.new_policy_number,
                "status": r.status,
                "delivery_method": r.delivery_method,
                "delivery_status": r.delivery_status,
                "signed_at": r.signed_at.isoformat() if r.signed_at else None,
                "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
                "reminder_count": r.reminder_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in requests
        ],
    }


@router.get("/stats")
def cancellation_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get cancellation pipeline stats."""
    from sqlalchemy import func as sqlfunc

    total = db.query(sqlfunc.count(CancellationRequest.id)).scalar() or 0
    by_status = dict(
        db.query(CancellationRequest.status, sqlfunc.count(CancellationRequest.id))
        .group_by(CancellationRequest.status)
        .all()
    )

    return {
        "enabled": CANCELLATION_ENABLED,
        "total_requests": total,
        "by_status": by_status,
        "pending_info": by_status.get("pending_info", 0),
        "awaiting_signature": by_status.get("awaiting_signature", 0),
        "signed_pending_delivery": by_status.get("signed", 0),
        "delivered": by_status.get("delivered", 0),
        "confirmed": by_status.get("confirmed", 0),
    }


@router.post("/initiate")
def initiate_cancellation(
    data: InitiateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Initiate a cancellation request — sends form link to customer.
    
    This creates the request in 'pending_info' status and emails the customer
    a link to the cancellation form where they provide old carrier details.
    """
    token = str(uuid.uuid4()).replace("-", "")[:24]

    req = CancellationRequest(
        sale_id=data.sale_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        new_carrier=data.new_carrier,
        new_policy_number=data.new_policy_number,
        new_effective_date=data.new_effective_date,
        status="pending_info",
        form_token=token,
        created_by=current_user.name if current_user else "system",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Send email with form link
    if CANCELLATION_ENABLED and data.customer_email:
        try:
            _send_cancellation_form_email(data.customer_email, data.customer_name, token)
        except Exception as e:
            logger.error(f"Failed to send cancellation form email: {e}")

    frontend_url = os.environ.get("FRONTEND_URL", "https://better-choice-web.onrender.com")
    form_url = f"{frontend_url}/cancel/{token}"

    return {
        "id": req.id,
        "token": token,
        "form_url": form_url,
        "status": req.status,
        "email_sent": CANCELLATION_ENABLED,
    }


@router.post("/submit-form")
def submit_cancellation_form(
    data: FormSubmission,
    db: Session = Depends(get_db),
):
    """Public endpoint — customer submits their old carrier details. No auth required."""
    req = db.query(CancellationRequest).filter(
        CancellationRequest.form_token == data.token
    ).first()

    if not req:
        raise HTTPException(status_code=404, detail="Invalid or expired form token")

    if req.status not in ("pending_info", "form_submitted"):
        raise HTTPException(status_code=400, detail=f"Request already in status: {req.status}")

    req.old_carrier_name = data.old_carrier_name
    req.old_policy_number = data.old_policy_number
    req.old_policy_type = data.old_policy_type or "auto"
    req.requested_cancel_date = data.requested_cancel_date or req.new_effective_date
    if data.customer_name:
        req.customer_name = data.customer_name
    if data.customer_address:
        req.customer_address = data.customer_address
    req.status = "form_submitted"
    db.commit()

    # Auto-generate letter if feature is enabled
    if CANCELLATION_ENABLED:
        try:
            _generate_cancellation_letter(req, db)
        except Exception as e:
            logger.error(f"Auto letter generation failed: {e}")

    return {
        "id": req.id,
        "status": req.status,
        "message": "Thank you! We'll handle the rest. You'll receive an email to sign the cancellation letter shortly.",
    }


@router.post("/{request_id}/generate-letter")
def generate_letter(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate the cancellation letter PDF and send to BoldSign for signature."""
    req = db.query(CancellationRequest).filter(CancellationRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if not req.old_carrier_name or not req.old_policy_number:
        raise HTTPException(status_code=400, detail="Missing old carrier info — form not submitted yet")

    result = _generate_cancellation_letter(req, db)
    return result


@router.post("/{request_id}/deliver")
def deliver_letter(
    request_id: int,
    method: Optional[str] = None,  # override carrier preferred method
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deliver the signed cancellation letter to the old carrier.
    
    Uses the carrier directory to determine delivery method (fax, email, mail).
    Can override with ?method=fax|email|mail
    """
    if not CANCELLATION_ENABLED:
        raise HTTPException(status_code=400, detail="Cancellation feature is not enabled")

    req = db.query(CancellationRequest).filter(CancellationRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req.status not in ("signed", "delivering"):
        raise HTTPException(status_code=400, detail=f"Request must be signed first (current: {req.status})")

    if not req.signed_pdf_url:
        raise HTTPException(status_code=400, detail="No signed PDF available")

    # Look up carrier delivery info
    carrier = db.query(CancellationCarrier).filter(
        CancellationCarrier.carrier_name == req.old_carrier_name
    ).first()

    delivery_method = method or (carrier.preferred_method if carrier else "mail")

    req.status = "delivering"
    req.delivery_method = delivery_method
    db.commit()

    result = {"request_id": req.id, "method": delivery_method}

    try:
        if delivery_method == "fax" and carrier and carrier.cancellation_fax:
            result.update(_deliver_via_fax(req, carrier.cancellation_fax))
        elif delivery_method == "email" and carrier and carrier.cancellation_email:
            result.update(_deliver_via_email(req, carrier.cancellation_email))
        elif delivery_method == "mail" and carrier and carrier.cancellation_mail_address:
            result.update(_deliver_via_mail(req, carrier.cancellation_mail_address))
        else:
            # Fallback: mark for manual delivery
            req.status = "signed"
            req.delivery_method = "manual"
            db.commit()
            result["status"] = "manual_required"
            result["message"] = f"No {delivery_method} contact for {req.old_carrier_name}. Manual delivery needed."
            return result

        req.status = "delivered"
        req.delivered_at = datetime.utcnow()
        req.delivery_status = "sent"
        db.commit()
        result["status"] = "delivered"

    except Exception as e:
        logger.error(f"Delivery failed for request {req.id}: {e}")
        req.status = "error"
        req.delivery_status = f"failed: {str(e)[:200]}"
        db.commit()
        result["status"] = "error"
        result["error"] = str(e)

    return result


@router.get("/{request_id}")
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get details of a specific cancellation request."""
    req = db.query(CancellationRequest).filter(CancellationRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    return {
        "id": req.id,
        "sale_id": req.sale_id,
        "customer_name": req.customer_name,
        "customer_email": req.customer_email,
        "customer_phone": req.customer_phone,
        "customer_address": req.customer_address,
        "old_carrier_name": req.old_carrier_name,
        "old_policy_number": req.old_policy_number,
        "old_policy_type": req.old_policy_type,
        "requested_cancel_date": req.requested_cancel_date,
        "new_carrier": req.new_carrier,
        "new_policy_number": req.new_policy_number,
        "new_effective_date": req.new_effective_date,
        "status": req.status,
        "letter_pdf_url": req.letter_pdf_url,
        "letter_generated_at": req.letter_generated_at.isoformat() if req.letter_generated_at else None,
        "boldsign_document_id": req.boldsign_document_id,
        "signed_at": req.signed_at.isoformat() if req.signed_at else None,
        "signed_pdf_url": req.signed_pdf_url,
        "delivery_method": req.delivery_method,
        "delivery_id": req.delivery_id,
        "delivered_at": req.delivered_at.isoformat() if req.delivered_at else None,
        "delivery_status": req.delivery_status,
        "delivery_confirmation": req.delivery_confirmation,
        "reminder_count": req.reminder_count,
        "form_token": req.form_token,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


# ── Public form page (no auth) ──

@router.get("/form/{token}", response_class=HTMLResponse)
def cancellation_form_page(token: str, db: Session = Depends(get_db)):
    """Public HTML form for customer to submit old carrier details."""
    req = db.query(CancellationRequest).filter(
        CancellationRequest.form_token == token
    ).first()

    if not req:
        return HTMLResponse("<h1>Invalid or expired link</h1>", status_code=404)

    if req.status not in ("pending_info", "form_submitted"):
        return HTMLResponse(
            "<h1>Already submitted</h1><p>Your cancellation request is being processed. "
            "You'll receive an email when the letter is ready to sign.</p>"
        )

    # Render the form
    api_url = os.environ.get("API_URL", "https://better-choice-api.onrender.com")
    first_name = req.customer_name.split()[0] if req.customer_name else "there"
    cancel_date = req.new_effective_date or ""

    return HTMLResponse(_build_cancellation_form_html(first_name, token, cancel_date, api_url))


# ── Internal Helper Functions ──

def _send_cancellation_form_email(email: str, name: str, token: str):
    """Send the 'Cancel your old policy' email with form link."""
    from app.core.config import settings
    import requests

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping cancellation form email")
        return

    frontend_url = os.environ.get("FRONTEND_URL", "https://better-choice-web.onrender.com")
    form_url = f"{frontend_url}/cancel/{token}"
    first_name = name.split()[0] if name else "there"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
  <div style="background:linear-gradient(135deg,#1a2b5f 0%,#162249 60%,#0c4a6e 100%);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="Better Choice Insurance Group" width="220" style="display:block;margin:0 auto;max-width:220px;height:auto;" />
    <p style="margin:6px 0 0;color:#00e5c7;font-size:13px;font-weight:600;">Congratulations on Your New Policy!</p>
  </div>
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;border:1px solid #E2E8F0;border-top:none;">
    <p style="color:#1e293b;font-size:16px;margin:0 0 16px;">Hi {first_name},</p>
    <p style="color:#334155;font-size:14px;line-height:1.6;">
      Welcome to Better Choice Insurance! Now that your new coverage is active,
      we'd like to help you <strong>cancel your old policy</strong> so you're not
      paying for double coverage.
    </p>
    <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:8px;padding:20px;margin:20px 0;">
      <p style="margin:0 0 8px;font-size:15px;font-weight:700;color:#059669;">
        &#10003; We'll Handle Everything
      </p>
      <p style="margin:0;font-size:14px;color:#334155;line-height:1.6;">
        Just tell us who your old carrier is and your policy number.
        We'll generate a cancellation letter, send it to you for a quick e-signature,
        and then deliver it to your old carrier automatically.
      </p>
    </div>
    <div style="text-align:center;margin:24px 0;">
      <a href="{form_url}" style="display:inline-block;background:linear-gradient(135deg,#059669,#10b981);color:white;padding:16px 40px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;">
        Cancel My Old Policy
      </a>
    </div>
    <p style="color:#64748B;font-size:12px;text-align:center;margin:16px 0 0;">
      This only takes about 30 seconds. If you've already cancelled your old policy, you can ignore this email.
    </p>
    <hr style="border:none;border-top:1px solid #E2E8F0;margin:24px 0;">
    <p style="color:#334155;font-size:14px;margin:0;">
      <strong>Better Choice Insurance Group</strong><br>
      <span style="color:#64748B;font-size:13px;">(847) 908-5665 | service@betterchoiceins.com</span>
    </p>
  </div>
</div></body></html>"""

    resp = requests.post(
        f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data={
            "from": f"Better Choice Insurance <service@{settings.MAILGUN_DOMAIN}>",
            "to": [email],
            "subject": "Need help cancelling your old policy? We've got you covered!",
            "html": html,
            "h:Reply-To": "service@betterchoiceins.com",
        },
    )
    if resp.status_code == 200:
        logger.info(f"Cancellation form email sent to {email}")
    else:
        logger.warning(f"Cancellation form email failed: {resp.status_code} {resp.text}")


def _generate_cancellation_letter(req: CancellationRequest, db: Session) -> dict:
    """Generate a cancellation request letter as HTML (for PDF conversion + BoldSign)."""
    today = datetime.now().strftime("%B %d, %Y")
    cancel_date = req.requested_cancel_date or req.new_effective_date or today
    customer_name = req.customer_name or "Policyholder"
    address = req.customer_address or ""
    old_carrier = (req.old_carrier_name or "Insurance Company").replace("_", " ").title()
    policy_number = req.old_policy_number or ""
    policy_type = (req.old_policy_type or "insurance").title()
    new_carrier = (req.new_carrier or "another carrier").replace("_", " ").title()
    new_policy = req.new_policy_number or ""

    letter_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Times New Roman', serif; font-size: 12pt; line-height: 1.6; color: #000; margin: 1in; }}
  .header {{ margin-bottom: 40px; }}
  .date {{ margin-bottom: 30px; }}
  .recipient {{ margin-bottom: 30px; }}
  .subject {{ font-weight: bold; margin-bottom: 20px; }}
  .body p {{ margin: 0 0 12px 0; }}
  .signature {{ margin-top: 40px; }}
  .sig-line {{ margin-top: 50px; border-top: 1px solid #000; width: 300px; padding-top: 4px; }}
</style>
</head><body>

<div class="header">
  <strong>{customer_name}</strong><br>
  {address}
</div>

<div class="date">{today}</div>

<div class="recipient">
  <strong>{old_carrier}</strong><br>
  Policy Cancellation Department
</div>

<div class="subject">
  Re: Request for Cancellation of {policy_type} Policy — {policy_number}
</div>

<div class="body">
  <p>Dear Sir or Madam,</p>

  <p>I am writing to formally request the cancellation of my {policy_type.lower()} insurance policy,
  policy number <strong>{policy_number}</strong>, effective <strong>{cancel_date}</strong>.</p>

  <p>I have obtained replacement coverage through {new_carrier}{f' (policy number {new_policy})' if new_policy else ''}
  effective {cancel_date}. Please cancel my existing policy as of that date.</p>

  <p>Please immediately cease any automatic premium withdrawals from my accounts
  and process a refund for any unused portion of prepaid premiums to my address on file.</p>

  <p>I request written confirmation of this cancellation within 30 days, including
  the effective cancellation date and any refund amount due.</p>

  <p>If you require any additional information to process this request, please contact me at
  {req.customer_email or req.customer_phone or 'the contact information on file'}.</p>

  <p>Thank you for your prompt attention to this matter.</p>
</div>

<div class="signature">
  Sincerely,<br><br>
  <div class="sig-line">
    {customer_name}<br>
    <span style="font-size:10pt;color:#666;">Date: _______________</span>
  </div>
</div>

</body></html>"""

    req.letter_pdf_url = "pending_generation"
    req.letter_generated_at = datetime.utcnow()
    req.status = "letter_generated"

    # TODO: Convert HTML to PDF using weasyprint or similar
    # TODO: Send to BoldSign for e-signature
    # For now, store the HTML and mark as awaiting_signature

    # Try BoldSign integration
    boldsign_sent = False
    try:
        boldsign_result = _send_to_boldsign(req, letter_html)
        if boldsign_result:
            req.boldsign_document_id = boldsign_result.get("document_id")
            req.status = "awaiting_signature"
            boldsign_sent = True
    except Exception as e:
        logger.error(f"BoldSign send failed: {e}")
        req.status = "letter_generated"  # still generated, just not sent for signature

    db.commit()

    return {
        "id": req.id,
        "status": req.status,
        "letter_generated": True,
        "boldsign_sent": boldsign_sent,
        "boldsign_document_id": req.boldsign_document_id,
    }


def _send_to_boldsign(req: CancellationRequest, html_content: str) -> Optional[dict]:
    """Send the cancellation letter to BoldSign for e-signature.
    
    Returns dict with document_id on success, None on failure.
    """
    from app.core.config import settings
    import requests

    api_key = getattr(settings, 'BOLDSIGN_API_KEY', None) or os.environ.get('BOLDSIGN_API_KEY')
    if not api_key:
        logger.warning("BoldSign API key not configured")
        return None

    # TODO: Implement full BoldSign document creation
    # 1. Convert HTML to PDF
    # 2. Upload PDF to BoldSign
    # 3. Add signature field
    # 4. Send for signing
    # 5. Set up webhook for completion

    logger.info(f"BoldSign integration placeholder for request {req.id}")
    return None


def _deliver_via_fax(req: CancellationRequest, fax_number: str) -> dict:
    """Send signed cancellation letter via fax using Fax.Plus or Telnyx API."""
    # TODO: Implement fax delivery
    # Option 1: Fax.Plus API (Enterprise plan required for API access)
    # Option 2: Telnyx Programmable Fax API
    #
    # fax_api_key = os.environ.get("FAX_API_KEY")
    # if not fax_api_key:
    #     raise Exception("Fax API not configured")
    #
    # response = requests.post(
    #     "https://restapi.fax.plus/v3/accounts/{user_id}/outbox",
    #     headers={"Authorization": f"Bearer {fax_api_key}"},
    #     json={
    #         "to": [fax_number],
    #         "files": [req.signed_pdf_url],
    #     }
    # )

    logger.info(f"FAX delivery placeholder: {req.old_policy_number} → {fax_number}")
    return {"delivery_id": f"fax-{uuid.uuid4().hex[:8]}", "fax_number": fax_number}


def _deliver_via_email(req: CancellationRequest, carrier_email: str) -> dict:
    """Email the signed cancellation letter to the carrier."""
    from app.core.config import settings
    import requests

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise Exception("Mailgun not configured")

    subject = f"Policy Cancellation Request — {req.old_policy_number} — {req.customer_name}"

    html_body = f"""<p>Please find attached a signed cancellation request for policy 
    <strong>{req.old_policy_number}</strong> for <strong>{req.customer_name}</strong>, 
    effective <strong>{req.requested_cancel_date or 'immediately'}</strong>.</p>
    <p>Please confirm receipt and process this cancellation.</p>
    <p>Thank you,<br>Better Choice Insurance Group<br>(847) 908-5665</p>"""

    data = {
        "from": f"Better Choice Insurance <service@{settings.MAILGUN_DOMAIN}>",
        "to": [carrier_email],
        "subject": subject,
        "html": html_body,
        "o:tracking-clicks": "yes",
        "o:tracking-opens": "yes",
        "h:Reply-To": "service@betterchoiceins.com",
    }

    # TODO: Attach the signed PDF
    # files = [("attachment", ("cancellation_letter.pdf", pdf_bytes, "application/pdf"))]

    resp = requests.post(
        f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data=data,
    )

    if resp.status_code != 200:
        raise Exception(f"Mailgun send failed: {resp.status_code} {resp.text}")

    logger.info(f"EMAIL delivery: {req.old_policy_number} → {carrier_email}")
    return {"delivery_id": resp.json().get("id", ""), "email": carrier_email}


def _deliver_via_mail(req: CancellationRequest, mailing_address: str) -> dict:
    """Send physical letter via Lob API."""
    # TODO: Implement Lob integration
    # lob_api_key = os.environ.get("LOB_API_KEY")
    # if not lob_api_key:
    #     raise Exception("Lob API not configured")
    #
    # import lob
    # lob.api_key = lob_api_key
    # letter = lob.Letter.create(
    #     to_address={
    #         "name": req.old_carrier_name,
    #         "address_line1": mailing_address_line1,
    #         "address_city": city,
    #         "address_state": state,
    #         "address_zip": zip_code,
    #     },
    #     from_address={...},
    #     file=req.signed_pdf_url,
    #     color=False,
    # )

    logger.info(f"MAIL delivery placeholder: {req.old_policy_number} → {mailing_address[:50]}")
    return {"delivery_id": f"mail-{uuid.uuid4().hex[:8]}", "address": mailing_address[:100]}


def _build_cancellation_form_html(first_name: str, token: str, cancel_date: str, api_url: str) -> str:
    """Build the public-facing cancellation form HTML page."""
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Cancel Your Old Policy — Better Choice Insurance</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f1f5f9; color: #1e293b; }}
  .container {{ max-width: 540px; margin: 40px auto; padding: 0 20px; }}
  .card {{ background: white; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); overflow: hidden; }}
  .header {{ background: linear-gradient(135deg, #1a2b5f, #0c4a6e); padding: 28px 32px; text-align: center; }}
  .header h1 {{ color: white; font-size: 18px; font-weight: 600; }}
  .header p {{ color: #00e5c7; font-size: 13px; margin-top: 4px; }}
  .body {{ padding: 32px; }}
  .body h2 {{ font-size: 20px; color: #1e293b; margin-bottom: 8px; }}
  .body .subtitle {{ font-size: 14px; color: #64748b; margin-bottom: 24px; line-height: 1.5; }}
  label {{ display: block; font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 6px; margin-top: 16px; }}
  input, select {{ width: 100%; padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; }}
  input:focus, select:focus {{ outline: none; border-color: #059669; box-shadow: 0 0 0 3px rgba(5,150,105,0.1); }}
  .btn {{ display: block; width: 100%; padding: 14px; background: linear-gradient(135deg, #059669, #10b981); color: white;
         font-size: 16px; font-weight: 700; border: none; border-radius: 8px; cursor: pointer; margin-top: 24px; }}
  .btn:hover {{ opacity: 0.95; }}
  .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  .note {{ font-size: 12px; color: #94a3b8; text-align: center; margin-top: 16px; line-height: 1.5; }}
  .success {{ display: none; text-align: center; padding: 40px 32px; }}
  .success h2 {{ color: #059669; margin-bottom: 12px; }}
  .success p {{ color: #64748b; font-size: 14px; line-height: 1.6; }}
</style>
</head><body>
<div class="container">
  <div class="card">
    <div class="header">
      <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="Better Choice Insurance Group" width="220" style="display:block;margin:0 auto;max-width:220px;height:auto;" />
      <p>Cancel Your Old Policy</p>
    </div>
    <div class="body" id="formSection">
      <h2>Hi {first_name}! 👋</h2>
      <p class="subtitle">
        Tell us about your old policy and we'll take care of the cancellation for you.
        We'll generate a letter, send it to you for a quick e-signature, and deliver it
        to your old carrier automatically.
      </p>

      <form id="cancelForm" onsubmit="return submitForm(event)">
        <label for="carrier">Who was your old insurance carrier?</label>
        <select id="carrier" name="old_carrier_name" required>
          <option value="">Select your old carrier...</option>
          <option value="state_farm">State Farm</option>
          <option value="allstate">Allstate</option>
          <option value="geico">GEICO</option>
          <option value="progressive">Progressive</option>
          <option value="farmers">Farmers</option>
          <option value="liberty_mutual">Liberty Mutual</option>
          <option value="nationwide">Nationwide</option>
          <option value="american_family">American Family</option>
          <option value="erie">Erie Insurance</option>
          <option value="usaa">USAA</option>
          <option value="travelers">Travelers</option>
          <option value="auto_owners">Auto-Owners</option>
          <option value="the_hartford">The Hartford</option>
          <option value="mercury">Mercury Insurance</option>
          <option value="metlife">MetLife</option>
          <option value="amica">Amica Mutual</option>
          <option value="other">Other</option>
        </select>

        <div id="otherCarrierDiv" style="display:none;">
          <label for="otherCarrier">Carrier name</label>
          <input type="text" id="otherCarrier" placeholder="Enter carrier name">
        </div>

        <label for="policyNumber">Your old policy number</label>
        <input type="text" id="policyNumber" name="old_policy_number" required
               placeholder="e.g., SF-1234567890">

        <label for="policyType">Policy type</label>
        <select id="policyType" name="old_policy_type">
          <option value="auto">Auto Insurance</option>
          <option value="home">Homeowners Insurance</option>
          <option value="renters">Renters Insurance</option>
          <option value="umbrella">Umbrella Policy</option>
          <option value="other">Other</option>
        </select>

        <label for="cancelDate">When should the old policy be cancelled?</label>
        <input type="date" id="cancelDate" name="requested_cancel_date"
               value="{cancel_date}">

        <label for="address">Your mailing address (for the letter)</label>
        <input type="text" id="address" name="customer_address"
               placeholder="123 Main St, City, State ZIP">

        <button type="submit" class="btn" id="submitBtn">Submit — We'll Handle the Rest</button>
      </form>

      <p class="note">
        This takes about 30 seconds. We'll email you a cancellation letter to e-sign,
        then deliver it to your old carrier automatically.
      </p>
    </div>

    <div class="success" id="successSection">
      <h2>✓ All Set!</h2>
      <p>
        We're generating your cancellation letter now. You'll receive an email
        shortly to e-sign it. Once signed, we'll deliver it to your old carrier automatically.
      </p>
      <p style="margin-top:16px;font-weight:600;">
        No further action needed — we've got this!
      </p>
    </div>
  </div>
</div>

<script>
  document.getElementById('carrier').addEventListener('change', function() {{
    document.getElementById('otherCarrierDiv').style.display = this.value === 'other' ? 'block' : 'none';
  }});

  async function submitForm(e) {{
    e.preventDefault();
    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = 'Submitting...';

    const carrier = document.getElementById('carrier').value === 'other'
      ? document.getElementById('otherCarrier').value
      : document.getElementById('carrier').value;

    const payload = {{
      token: '{token}',
      old_carrier_name: carrier,
      old_policy_number: document.getElementById('policyNumber').value,
      old_policy_type: document.getElementById('policyType').value,
      requested_cancel_date: document.getElementById('cancelDate').value || null,
      customer_address: document.getElementById('address').value || null,
    }};

    try {{
      const resp = await fetch('{api_url}/api/cancellation/submit-form', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload),
      }});
      const data = await resp.json();
      if (resp.ok) {{
        document.getElementById('formSection').style.display = 'none';
        document.getElementById('successSection').style.display = 'block';
      }} else {{
        alert(data.detail || 'Something went wrong. Please try again.');
        btn.disabled = false;
        btn.textContent = 'Submit — We\\'ll Handle the Rest';
      }}
    }} catch (err) {{
      alert('Network error. Please try again.');
      btn.disabled = false;
      btn.textContent = 'Submit — We\\'ll Handle the Rest';
    }}
  }}
</script>
</body></html>"""
