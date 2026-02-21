"""Win-Back Campaign API.

Targets cancelled customers for re-marketing.
Requirements:
- Customer had active policy for >= 6 months
- Agent can manually exclude customers
- Integrates with GHL for outreach sequences
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.campaign import WinBackCampaign
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/winback", tags=["Win-Back Campaigns"])


class WinBackExclude(BaseModel):
    reason: Optional[str] = None


class WinBackCreate(BaseModel):
    """Manually add a customer to win-back campaign."""
    customer_id: Optional[int] = None
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    line_of_business: Optional[str] = None
    cancellation_date: Optional[str] = None
    cancellation_reason: Optional[str] = None


# ── Email template ──

def _build_winback_email_html(campaign: WinBackCampaign, touchpoint: int) -> str:
    """Build win-back email based on touchpoint number."""
    from app.services.welcome_email import BCI_NAVY, BCI_CYAN

    first_name = campaign.customer_name.split()[0] if campaign.customer_name else "there"

    if touchpoint == 1:
        # Initial win-back: warm, personal
        subject_text = "We miss you!"
        body = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Hi {first_name},
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We noticed your insurance policy is no longer active with us, and we wanted
          to reach out personally. At Better Choice Insurance Group, every customer matters
          to us, and we would love the opportunity to help you again.
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Insurance rates change frequently, and we may be able to find you a better rate
          than what you are currently paying. Would you be open to a quick, no-obligation quote?
        </p>"""
    elif touchpoint == 2:
        # Follow-up: value-focused
        subject_text = "New rates available for you"
        body = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Hi {first_name},
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We wanted to follow up and let you know that we have access to new carrier
          options and competitive rates that may save you money on your insurance.
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We work with over 15 carriers and can shop your coverage in minutes. Many of
          our returning customers are pleasantly surprised at the savings.
        </p>"""
    else:
        # Later touchpoints: seasonal/timely
        subject_text = "Time for an insurance check-up?"
        body = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Hi {first_name},
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          It has been a while since we last worked together, and we just wanted to
          remind you that we are always here if you need us. Insurance needs change
          over time, and a quick review could save you money or improve your coverage.
        </p>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
  <div style="background:{BCI_NAVY};padding:24px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:white;font-size:20px;">Better Choice Insurance Group</h1>
    <p style="margin:4px 0 0 0;color:{BCI_CYAN};font-size:13px;">{subject_text}</p>
  </div>
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;">
    {body}
    <div style="text-align:center;margin:24px 0;">
      <a href="tel:8479085665" style="display:inline-block;background:{BCI_CYAN};color:white;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;">
        Call Us: (847) 908-5665
      </a>
    </div>
    <p style="color:#334155;font-size:14px;margin:16px 0 0 0;">
      Best regards,<br><strong>Better Choice Insurance Group</strong>
    </p>
    <p style="color:#94a3b8;font-size:11px;margin:16px 0 0 0;">
      If you no longer wish to receive these messages, simply reply STOP.
    </p>
  </div>
</div>
</body></html>"""


def _send_winback_email(campaign: WinBackCampaign, touchpoint: int) -> bool:
    """Send win-back email via Mailgun."""
    from app.core.config import settings
    import requests

    if not campaign.customer_email:
        return False
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return False

    first_name = campaign.customer_name.split()[0] if campaign.customer_name else "Valued Customer"
    subjects = {
        1: f"{first_name}, we miss having you as a customer!",
        2: f"New insurance rates available for you, {first_name}",
        3: f"Time for an insurance check-up, {first_name}?",
    }
    subject = subjects.get(touchpoint, f"A message from Better Choice Insurance")
    html = _build_winback_email_html(campaign, touchpoint)

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance Group <service@{settings.MAILGUN_DOMAIN}>",
                "to": [campaign.customer_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
            },
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Win-back email error: {e}")
        return False


# ── API Endpoints ──

@router.post("/scan")
def scan_for_winback_candidates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan for cancelled customers eligible for win-back (>= 6 months active).

    Looks at CustomerPolicy records with status='Cancelled' or 'Expired'.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    # Find cancelled policies with sufficient tenure
    cancelled_policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.status.in_(["Cancelled", "cancelled", "Expired", "expired"]),
        CustomerPolicy.effective_date.isnot(None),
    ).all()

    candidates = []
    skipped = 0
    already_exists = 0

    for pol in cancelled_policies:
        # Calculate tenure
        cancel_date = pol.expiration_date or pol.updated_at or datetime.utcnow()
        if pol.effective_date:
            months = (cancel_date.year - pol.effective_date.year) * 12 + (cancel_date.month - pol.effective_date.month)
        else:
            months = 0

        # Must have been active >= 6 months
        if months < 6:
            skipped += 1
            continue

        # Get customer info
        customer = db.query(Customer).filter(Customer.id == pol.customer_id).first()
        if not customer:
            skipped += 1
            continue

        # Skip if no contact info
        if not customer.email and not customer.phone:
            skipped += 1
            continue

        # Check if already in win-back
        existing = db.query(WinBackCampaign).filter(
            WinBackCampaign.customer_id == customer.id,
            WinBackCampaign.status.in_(["pending", "active"]),
        ).first()
        if existing:
            already_exists += 1
            continue

        # Create win-back record
        wb = WinBackCampaign(
            customer_id=customer.id,
            nowcerts_insured_id=customer.nowcerts_insured_id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            customer_phone=customer.phone or customer.mobile_phone,
            policy_number=pol.policy_number,
            carrier=pol.carrier,
            line_of_business=pol.line_of_business,
            premium_at_cancel=pol.premium,
            original_effective_date=pol.effective_date,
            cancellation_date=cancel_date,
            months_active=months,
            agent_name=customer.agent_name,
            status="pending",
        )
        db.add(wb)
        candidates.append(customer.full_name)

    db.commit()

    return {
        "candidates_found": len(candidates),
        "skipped_short_tenure": skipped,
        "already_in_campaign": already_exists,
        "new_candidates": candidates[:50],
    }


@router.get("/")
def list_winback_campaigns(
    status: Optional[str] = None,
    include_excluded: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List win-back campaigns."""
    query = db.query(WinBackCampaign)

    if not include_excluded:
        query = query.filter(WinBackCampaign.excluded == False)
    if status:
        query = query.filter(WinBackCampaign.status == status)

    campaigns = query.order_by(WinBackCampaign.created_at.desc()).limit(200).all()

    return {
        "total": len(campaigns),
        "campaigns": [
            {
                "id": c.id,
                "customer_name": c.customer_name,
                "customer_email": c.customer_email,
                "customer_phone": c.customer_phone,
                "policy_number": c.policy_number,
                "carrier": c.carrier,
                "line_of_business": c.line_of_business,
                "months_active": c.months_active,
                "cancellation_date": c.cancellation_date.isoformat() if c.cancellation_date else None,
                "cancellation_reason": c.cancellation_reason,
                "status": c.status,
                "excluded": c.excluded,
                "excluded_reason": c.excluded_reason,
                "touchpoint_count": c.touchpoint_count,
                "last_touchpoint_at": c.last_touchpoint_at.isoformat() if c.last_touchpoint_at else None,
                "agent_name": c.agent_name,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in campaigns
        ],
    }


@router.post("/{campaign_id}/exclude")
def exclude_from_winback(
    campaign_id: int,
    data: WinBackExclude,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exclude a customer from win-back campaign (agent discretion)."""
    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.excluded = True
    campaign.excluded_by = current_user.id
    campaign.excluded_reason = data.reason or "Excluded by agent"
    campaign.status = "excluded"
    db.commit()

    return {"id": campaign.id, "status": "excluded", "reason": campaign.excluded_reason}


@router.post("/{campaign_id}/include")
def include_in_winback(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-include a previously excluded customer."""
    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.excluded = False
    campaign.excluded_by = None
    campaign.excluded_reason = None
    campaign.status = "pending"
    db.commit()

    return {"id": campaign.id, "status": "pending"}


@router.post("/{campaign_id}/activate")
def activate_winback(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate a win-back campaign (send first touchpoint)."""
    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.excluded:
        raise HTTPException(status_code=400, detail="This customer has been excluded from win-back")

    # Send first email
    email_sent = _send_winback_email(campaign, touchpoint=1)

    campaign.status = "active"
    campaign.touchpoint_count = 1
    campaign.last_touchpoint_at = datetime.utcnow()
    campaign.next_touchpoint_at = datetime.utcnow() + timedelta(days=14)

    # Fire GHL webhook
    try:
        from app.services.ghl_webhook import get_ghl_service
        ghl = get_ghl_service()
        ghl.fire_winback(
            customer_name=campaign.customer_name,
            email=campaign.customer_email or "",
            phone=campaign.customer_phone or "",
            carrier=campaign.carrier or "",
            policy_type=campaign.line_of_business or "",
            months_active=campaign.months_active or 0,
            cancel_reason=campaign.cancellation_reason or "",
        )
        campaign.ghl_webhook_sent = True
    except Exception as e:
        logger.debug(f"GHL webhook failed: {e}")

    # NowCerts note
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if nc.is_configured:
            parts = campaign.customer_name.strip().split(maxsplit=1)
            nc.insert_note({
                "subject": f"Win-Back Campaign Started — {campaign.policy_number or 'N/A'} | Former customer outreach initiated",
                "insured_email": campaign.customer_email or "",
                "insured_first_name": parts[0] if parts else "",
                "insured_last_name": parts[1] if len(parts) > 1 else "",
                "type": "Email",
                "creator_name": "BCI Win-Back System",
                "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
            })
    except Exception as e:
        logger.debug(f"NowCerts note failed: {e}")

    db.commit()

    return {
        "id": campaign.id,
        "status": "active",
        "email_sent": email_sent,
        "ghl_webhook_sent": campaign.ghl_webhook_sent,
        "next_touchpoint": campaign.next_touchpoint_at.isoformat() if campaign.next_touchpoint_at else None,
    }


@router.post("/activate-all")
def activate_all_pending(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate all pending (non-excluded) win-back campaigns."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    pending = db.query(WinBackCampaign).filter(
        WinBackCampaign.status == "pending",
        WinBackCampaign.excluded == False,
    ).all()

    activated = 0
    for campaign in pending:
        email_sent = _send_winback_email(campaign, touchpoint=1)
        campaign.status = "active"
        campaign.touchpoint_count = 1
        campaign.last_touchpoint_at = datetime.utcnow()
        campaign.next_touchpoint_at = datetime.utcnow() + timedelta(days=14)

        try:
            from app.services.ghl_webhook import get_ghl_service
            ghl = get_ghl_service()
            ghl.fire_winback(
                customer_name=campaign.customer_name,
                email=campaign.customer_email or "",
                phone=campaign.customer_phone or "",
                carrier=campaign.carrier or "",
                policy_type=campaign.line_of_business or "",
                months_active=campaign.months_active or 0,
                cancel_reason=campaign.cancellation_reason or "",
            )
            campaign.ghl_webhook_sent = True
        except:
            pass

        activated += 1

    db.commit()
    return {"activated": activated, "total_pending": len(pending)}


@router.post("/create")
def create_winback_manually(
    data: WinBackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually add a customer to win-back campaign."""
    cancel_dt = None
    if data.cancellation_date:
        try:
            cancel_dt = datetime.strptime(data.cancellation_date, "%Y-%m-%d")
        except ValueError:
            pass

    wb = WinBackCampaign(
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        policy_number=data.policy_number,
        carrier=data.carrier,
        line_of_business=data.line_of_business,
        cancellation_date=cancel_dt,
        cancellation_reason=data.cancellation_reason,
        months_active=6,  # manually added = assumed qualified
        agent_name=current_user.username,
        status="pending",
    )
    db.add(wb)
    db.commit()
    db.refresh(wb)

    return {"id": wb.id, "status": "pending", "customer_name": wb.customer_name}
