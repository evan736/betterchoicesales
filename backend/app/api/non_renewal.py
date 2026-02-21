"""Non-Renewal Notification API.

Handles carrier non-renewal notices — when a carrier decides not to renew a policy.
Different from cancellation (non-pay). This is the carrier choosing to drop the customer.

Sends branded notification to customer explaining:
- Your carrier has chosen not to renew
- We are already shopping alternatives for you
- Your current coverage remains active until [expiration date]
- Call us with questions
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/non-renewal", tags=["Non-Renewal"])


class NonRenewalCreate(BaseModel):
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    policy_number: str
    carrier: Optional[str] = None
    line_of_business: Optional[str] = None
    expiration_date: Optional[str] = None  # "2026-04-15"
    reason: Optional[str] = None  # claims history, underwriting, market exit, etc.
    agent_name: Optional[str] = None
    send_notification: bool = True


def _build_nonrenewal_email_html(
    customer_name: str,
    carrier: str,
    policy_number: str,
    expiration_date: str,
    line_of_business: str,
    reason: str,
) -> str:
    """Build non-renewal notification email."""
    from app.services.welcome_email import CARRIER_INFO, BCI_NAVY, BCI_CYAN

    carrier_key = (carrier or "").lower().replace(" ", "_")
    cinfo = CARRIER_INFO.get(carrier_key, {})
    accent = cinfo.get("accent_color", BCI_CYAN)
    carrier_name = cinfo.get("display_name", (carrier or "your insurance carrier").title())
    first_name = customer_name.split()[0] if customer_name else "there"
    lob = (line_of_business or "insurance").title()

    reason_html = ""
    if reason:
        reason_html = f"""
        <div style="background:#F8FAFC;border-radius:8px;padding:14px;margin:16px 0;">
            <p style="margin:0;font-size:13px;color:#64748B;"><strong>Reason provided:</strong> {reason}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

  <div style="background:linear-gradient(135deg,#1a2b5f 0%,#162249 60%,#0c4a6e 100%);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:white;font-size:20px;">Better Choice Insurance Group</h1>
    <p style="margin:6px 0 0 0;color:{accent};font-size:13px;font-weight:600;">Important Policy Update</p>
  </div>

  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;border:1px solid #E2E8F0;border-top:none;">
    <p style="color:#1e293b;font-size:16px;margin:0 0 16px 0;">Hi {first_name},</p>

    <p style="color:#334155;font-size:14px;line-height:1.6;">
      We are writing to let you know that <strong>{carrier_name}</strong> has decided
      not to renew your <strong>{lob}</strong> policy (<strong>{policy_number}</strong>).
    </p>

    <div style="background:#FEF3C7;border-left:4px solid #F59E0B;padding:14px 16px;margin:16px 0;border-radius:0 8px 8px 0;">
      <p style="margin:0;color:#92400E;font-size:14px;">
        <strong>Your current coverage remains active</strong> through
        <strong>{expiration_date or "your policy expiration date"}</strong>.
        You are still fully insured until then.
      </p>
    </div>

    {reason_html}

    <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:8px;padding:20px;margin:20px 0;">
      <p style="margin:0 0 8px 0;font-size:15px;font-weight:700;color:#059669;">
        &#10003; We Are Already Working on It
      </p>
      <p style="margin:0;font-size:14px;color:#334155;line-height:1.6;">
        As your independent insurance agency, we have access to multiple carriers.
        We are already shopping for replacement coverage to make sure you have
        <strong>no gap in protection</strong>. We will reach out soon with your options.
      </p>
    </div>

    <p style="color:#334155;font-size:14px;line-height:1.6;">
      <strong>What you need to do:</strong> Nothing right now. We will handle everything
      and contact you with replacement options. If you have questions or concerns, please
      do not hesitate to reach out.
    </p>

    <div style="text-align:center;margin:24px 0;">
      <a href="tel:8479085665" style="display:inline-block;background:{accent};color:white;padding:14px 36px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;">
        Call Us: (847) 908-5665
      </a>
    </div>

    <p style="color:#334155;font-size:14px;margin:20px 0 0 0;">
      We know this can feel concerning, but this is exactly what we are here for.
      We will find you the right coverage at the right price.<br><br>
      <strong>Better Choice Insurance Group</strong><br>
      <span style="color:#64748B;font-size:13px;">(847) 908-5665 | service@betterchoiceins.com</span>
    </p>
  </div>
</div></body></html>"""


def _send_nonrenewal_email(data: NonRenewalCreate) -> bool:
    """Send non-renewal notification email."""
    from app.core.config import settings
    import requests

    if not data.customer_email:
        return False
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return False

    carrier_name = (data.carrier or "your carrier").replace("_", " ").title()
    subject = f"Important: {carrier_name} Policy Non-Renewal Notice — {data.policy_number}"

    html = _build_nonrenewal_email_html(
        customer_name=data.customer_name,
        carrier=data.carrier or "",
        policy_number=data.policy_number,
        expiration_date=data.expiration_date or "",
        line_of_business=data.line_of_business or "",
        reason=data.reason or "",
    )

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance Group <service@{settings.MAILGUN_DOMAIN}>",
                "to": [data.customer_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
            },
        )
        if resp.status_code == 200:
            logger.info(f"Non-renewal email sent to {data.customer_email} for {data.policy_number}")
            return True
        else:
            logger.warning(f"Non-renewal email failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Non-renewal email error: {e}")
        return False


@router.post("/notify")
def send_nonrenewal_notification(
    data: NonRenewalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a non-renewal notification to a customer."""
    email_sent = False
    nowcerts_noted = False

    if data.send_notification and data.customer_email:
        email_sent = _send_nonrenewal_email(data)

    # Add NowCerts note
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if nc.is_configured:
            parts = data.customer_name.strip().split(maxsplit=1)
            carrier_name = (data.carrier or "carrier").replace("_", " ").title()
            note_body = (
                f"Non-Renewal Notice — {carrier_name} | "
                f"Policy: {data.policy_number} | "
                f"Expires: {data.expiration_date or 'TBD'} | "
                f"Reason: {data.reason or 'Not specified'} | "
                f"Customer notified via email: {'Yes' if email_sent else 'No'}"
            )
            nc.insert_note({
                "subject": note_body,
                "insured_email": data.customer_email or "",
                "insured_first_name": parts[0] if parts else "",
                "insured_last_name": parts[1] if len(parts) > 1 else "",
                "type": "Email",
                "creator_name": "BCI Non-Renewal System",
                "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
            })
            nowcerts_noted = True
    except Exception as e:
        logger.error(f"NowCerts note failed for non-renewal: {e}")

    # Fire GHL webhook for re-marketing workflow
    ghl_sent = False
    try:
        from app.services.ghl_webhook import get_ghl_service
        ghl = get_ghl_service()
        parts = data.customer_name.strip().split(maxsplit=1)
        ghl._fire(
            ghl.renewal_webhook_url,
            {
                "first_name": parts[0] if parts else "",
                "last_name": parts[1] if len(parts) > 1 else "",
                "email": data.customer_email or "",
                "phone": data.customer_phone or "",
                "policy_number": data.policy_number,
                "carrier": (data.carrier or "").replace("_", " ").title(),
                "event_type": "non_renewal_notice",
                "expiration_date": data.expiration_date or "",
                "reason": data.reason or "",
                "sent_at": datetime.utcnow().isoformat(),
            },
            "non_renewal_notice",
        )
        ghl_sent = True
    except Exception as e:
        logger.debug(f"GHL webhook failed: {e}")

    return {
        "email_sent": email_sent,
        "nowcerts_noted": nowcerts_noted,
        "ghl_webhook_sent": ghl_sent,
        "policy_number": data.policy_number,
        "customer_name": data.customer_name,
    }


@router.get("/preview")
def preview_nonrenewal_email(
    customer_name: str = "John Smith",
    carrier: str = "grange",
    policy_number: str = "HM 6605796",
    expiration_date: str = "April 15, 2026",
    line_of_business: str = "homeowners",
    reason: str = "Underwriting review",
):
    """Preview the non-renewal email HTML."""
    html = _build_nonrenewal_email_html(
        customer_name=customer_name,
        carrier=carrier,
        policy_number=policy_number,
        expiration_date=expiration_date,
        line_of_business=line_of_business,
        reason=reason,
    )
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)
