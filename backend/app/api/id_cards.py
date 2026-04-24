"""ID Card Email endpoint — email a customer their ID card PDF + carrier app info.

Agent uploads a PDF (pulled from the carrier portal) and ORBIT emails it to the customer
with branded copy plus a section inviting them to download the carrier's mobile app.

Reuses the carrier catalog (CARRIER_INFO) and alias/resolution logic (_get_carrier_key)
from services/welcome_email.py so we have a single source of truth for carrier metadata
— mobile app URLs, customer service phones, accent colors, etc. — across all
customer-facing emails.
"""
import os
import logging
from typing import Optional

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.customer import Customer
from app.services.welcome_email import (
    CARRIER_INFO,
    _get_carrier_key,
    BCI_NAVY,
    BCI_CYAN,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/id-cards", tags=["id-cards"])


def _resolve_carrier(carrier: str) -> Optional[dict]:
    """Return the CARRIER_INFO entry for a carrier string, or None if not matched."""
    key = _get_carrier_key(carrier)
    if not key:
        return None
    info = CARRIER_INFO.get(key)
    if not info:
        return None
    return {"_key": key, **info}


def _build_idcard_html(customer_name: str, carrier_info: Optional[dict], original_carrier: str,
                       line_of_business: str) -> str:
    """Build the branded ID card email body. Falls back gracefully if carrier not known."""
    first_name = (customer_name or "there").split()[0] if customer_name else "there"
    lob_label = (line_of_business or "policy").replace("_", " ").title()
    carrier_display = (carrier_info or {}).get("display_name") or original_carrier or "your insurance"
    accent_color = (carrier_info or {}).get("accent_color") or BCI_CYAN

    app_section = ""
    if carrier_info:
        app_url = carrier_info.get("mobile_app_url", "")
        app_name = carrier_info.get("mobile_app_name", "")
        service_phone = carrier_info.get("customer_service", "")
        extra_tip = carrier_info.get("extra_tip", "")
        online_url = carrier_info.get("online_account_url", "")
        online_text = carrier_info.get("online_account_text", "")

        if app_url and app_name:
            app_section = f'''
            <tr><td style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e5e7eb;">
              <div style="font-size:15px;font-weight:700;color:{BCI_NAVY};margin-bottom:8px;">
                Get the {app_name}
              </div>
              <div style="font-size:14px;color:#475569;line-height:1.5;margin-bottom:14px;">
                {extra_tip or f"Access your ID card anytime, file claims, and manage your policy on the go."}
              </div>
              <div style="text-align:center;">
                <a href="{app_url}" style="display:inline-block;padding:12px 24px;background:{accent_color};color:white;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">
                  Download the {app_name}
                </a>
              </div>
            </td></tr>
            '''
        elif online_url:
            app_section = f'''
            <tr><td style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e5e7eb;">
              <div style="font-size:15px;font-weight:700;color:{BCI_NAVY};margin-bottom:8px;">
                Manage Your {carrier_display} Policy Online
              </div>
              <div style="font-size:14px;color:#475569;line-height:1.5;margin-bottom:14px;">
                {extra_tip or f"Log in to your {carrier_display} account to manage your policy, view documents, and file claims."}
              </div>
              <div style="text-align:center;">
                <a href="{online_url}" style="display:inline-block;padding:12px 24px;background:{accent_color};color:white;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">
                  {online_text or "Log In"}
                </a>
              </div>
              {f'<div style="text-align:center;margin-top:10px;font-size:12px;color:#64748b;">Customer service: <strong>{service_phone}</strong></div>' if service_phone else ''}
            </td></tr>
            '''
        elif service_phone:
            app_section = f'''
            <tr><td style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e5e7eb;">
              <div style="font-size:15px;font-weight:700;color:{BCI_NAVY};margin-bottom:8px;">
                Need help with your {carrier_display} policy?
              </div>
              <div style="font-size:14px;color:#475569;line-height:1.5;">
                You can reach {carrier_display} customer service directly at <strong>{service_phone}</strong>.
              </div>
            </td></tr>
            '''

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f5f5;padding:30px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,.08);">
        <tr><td style="background:linear-gradient(135deg,{BCI_NAVY} 0%,{BCI_CYAN} 100%);padding:30px;color:white;">
          <div style="font-size:12px;letter-spacing:2px;opacity:.85;">BETTER CHOICE INSURANCE GROUP</div>
          <div style="font-size:26px;font-weight:700;margin-top:8px;">Your ID Card</div>
        </td></tr>
        <tr><td style="padding:32px;color:#1a1a1a;line-height:1.6;font-size:15px;">
          Hi {first_name},<br><br>
          Attached is your ID card for your <strong>{carrier_display} {lob_label}</strong> policy.
          Keep a copy on your phone or print it and store it in your vehicle &mdash; you'll need it if you're ever pulled over or involved in an accident.
          <br><br>
          If you need anything else, call or text us anytime at <strong>847-908-5665</strong>.
          <br><br>
          Thanks for choosing Better Choice Insurance.<br>
          &mdash; The Better Choice Team
        </td></tr>
        {app_section}
        <tr><td style="background:#f8f8f8;padding:18px 32px;border-top:1px solid #e5e7eb;color:#666;font-size:12px;">
          Better Choice Insurance Group &middot; 300 Cardinal Dr Suite 220, Saint Charles, IL 60175<br>
          847-908-5665 &middot; service@betterchoiceins.com
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


@router.post("/send")
async def send_id_card_email(
    pdf: UploadFile = File(...),
    customer_id: int = Form(...),
    policy_id: Optional[int] = Form(None),
    recipient_email: str = Form(...),
    carrier: str = Form(...),
    line_of_business: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Email the customer their ID card PDF with branded copy and carrier info."""
    mg_key = os.environ.get("MAILGUN_API_KEY") or settings.MAILGUN_API_KEY
    mg_domain = os.environ.get("MAILGUN_DOMAIN") or settings.MAILGUN_DOMAIN
    if not mg_key or not mg_domain:
        raise HTTPException(status_code=503, detail="Mailgun not configured")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await pdf.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="PDF is empty")
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF exceeds 10MB limit")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF")

    carrier_info = _resolve_carrier(carrier)
    customer_name = customer.full_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip()
    html = _build_idcard_html(customer_name, carrier_info, carrier, line_of_business or "")
    carrier_display = (carrier_info or {}).get("display_name") or carrier
    subject = f"Your {carrier_display} ID Card — Better Choice Insurance"

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{mg_domain}/messages",
            auth=("api", mg_key),
            data={
                "from": "Better Choice Insurance <service@betterchoiceins.com>",
                "to": recipient_email,
                "bcc": "service@betterchoiceins.com",
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
                "h:X-Customer-Id": str(customer_id),
                "h:X-Agent": current_user.username or str(current_user.id),
            },
            files=[("attachment", (pdf.filename, pdf_bytes, "application/pdf"))],
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "sent")
            logger.info("ID card sent for customer %s (%s → %s) by %s — msg %s",
                        customer_id, carrier, (carrier_info or {}).get("_key", "unknown"),
                        current_user.username, msg_id)
            return {
                "status": "ok",
                "message_id": msg_id,
                "recipient": recipient_email,
                "resolved_carrier": (carrier_info or {}).get("_key"),
                "has_app": bool(carrier_info and carrier_info.get("mobile_app_url")),
            }
        raise HTTPException(status_code=502, detail=f"Mailgun error: {resp.status_code} {resp.text[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ID card send failed")
        raise HTTPException(status_code=500, detail=f"Send failed: {str(e)[:200]}")


@router.get("/carrier-app-info")
def get_carrier_app_info(carrier: str):
    """Preview what the email would include for a given carrier."""
    info = _resolve_carrier(carrier)
    if not info:
        return {"carrier": carrier, "found": False}
    return {
        "carrier": carrier,
        "found": True,
        "resolved_key": info.get("_key"),
        "name": info.get("display_name") or info.get("_key"),
        "has_app": bool(info.get("mobile_app_url")),
        "app_name": info.get("mobile_app_name") or None,
        "app_url": info.get("mobile_app_url") or None,
        "has_online_portal": bool(info.get("online_account_url")),
        "service_phone": info.get("customer_service") or None,
    }
