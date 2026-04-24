"""ID Card Email endpoint — email a customer their ID card PDF + carrier app download info.

Agent uploads a PDF (pulled from the carrier portal) and ORBIT emails it to the customer
with branded copy plus a section inviting them to download the carrier's mobile app.

This is a convenience tool for retention/service workflows: customer calls in asking for
their ID card, agent grabs it from the carrier portal, clicks the button on the customer
card, uploads the PDF, and ORBIT sends a polished email so the customer also learns
about the carrier's app.
"""
import os
import base64
import logging
from typing import Optional

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/id-cards", tags=["id-cards"])


# Carrier app links — maintained hand-curated list. If a carrier isn't here,
# the email skips the app-download section rather than showing a broken link.
# Keys are lowercase; match is substring-based to handle aliases like "Nat Gen".
CARRIER_APPS = {
    "travelers": {
        "name": "Travelers",
        "ios": "https://apps.apple.com/us/app/mytravelers/id1050323579",
        "android": "https://play.google.com/store/apps/details?id=com.travelers.mytravelers",
        "service_phone": "1-800-252-4633",
    },
    "safeco": {
        "name": "Safeco",
        "ios": "https://apps.apple.com/us/app/safeco-mobile/id957619925",
        "android": "https://play.google.com/store/apps/details?id=com.safecoinsurance.mobile",
        "service_phone": "1-800-332-3226",
    },
    "national general": {
        "name": "National General",
        "ios": "https://apps.apple.com/us/app/national-general-insurance/id1476440076",
        "android": "https://play.google.com/store/apps/details?id=com.nationalgeneral.policy",
        "service_phone": "1-888-293-5108",
    },
    "nat gen": {"alias": "national general"},
    "integon": {"alias": "national general"},
    "grange": {
        "name": "Grange",
        "ios": "https://apps.apple.com/us/app/grange-insurance/id1138023041",
        "android": "https://play.google.com/store/apps/details?id=com.grangeinsurance.mobile",
        "service_phone": "1-800-422-0550",
    },
    "progressive": {
        "name": "Progressive",
        "ios": "https://apps.apple.com/us/app/progressive/id333807476",
        "android": "https://play.google.com/store/apps/details?id=com.phx.progressive",
        "service_phone": "1-800-776-4737",
    },
    "geico": {
        "name": "GEICO",
        "ios": "https://apps.apple.com/us/app/geico-mobile/id300975395",
        "android": "https://play.google.com/store/apps/details?id=com.geico.mobile",
        "service_phone": "1-800-207-7847",
    },
    "openly": {
        "name": "Openly",
        "ios": None,  # Openly doesn't have a consumer mobile app as of 2026
        "android": None,
        "service_phone": "1-833-224-0036",
    },
    "branch": {
        "name": "Branch",
        "ios": "https://apps.apple.com/us/app/branch-insurance/id1498293894",
        "android": "https://play.google.com/store/apps/details?id=com.ourbranch.app",
        "service_phone": "1-833-427-2624",
    },
    "hippo": {
        "name": "Hippo",
        "ios": "https://apps.apple.com/us/app/hippo-insurance/id1479562027",
        "android": "https://play.google.com/store/apps/details?id=com.hippo.policyholder",
        "service_phone": "1-800-585-0705",
    },
    "bristol west": {
        "name": "Bristol West",
        "ios": None,
        "android": None,
        "service_phone": "1-800-274-7865",
    },
    "clearcover": {
        "name": "Clearcover",
        "ios": "https://apps.apple.com/us/app/clearcover/id1276148566",
        "android": "https://play.google.com/store/apps/details?id=com.clearcover",
        "service_phone": "1-855-444-1875",
    },
    "american modern": {
        "name": "American Modern",
        "ios": None,
        "android": None,
        "service_phone": "1-800-543-2644",
    },
    "steadily": {
        "name": "Steadily",
        "ios": None,
        "android": None,
        "service_phone": "1-888-966-1611",
    },
    "obsidian": {"alias": "steadily"},
    "canopius": {"alias": "steadily"},
    "spinnaker": {"alias": "hippo"},
    "american economy": {"alias": "safeco"},
}


def _resolve_carrier_app(carrier: str) -> Optional[dict]:
    """Look up carrier app info with alias resolution and substring matching."""
    if not carrier:
        return None
    c = carrier.lower().strip()
    # Exact match first
    if c in CARRIER_APPS:
        entry = CARRIER_APPS[c]
        # Follow alias chain
        while "alias" in entry:
            entry = CARRIER_APPS.get(entry["alias"], {})
            if not entry:
                return None
        return entry
    # Substring match
    for key, entry in CARRIER_APPS.items():
        if key in c:
            while "alias" in entry:
                entry = CARRIER_APPS.get(entry["alias"], {})
                if not entry:
                    return None
            return entry
    return None


def _build_idcard_html(customer_name: str, carrier: str, line_of_business: str, app_info: Optional[dict]) -> str:
    """Build the branded ID card email body."""
    BCI_NAVY = "#1B3A5C"
    BCI_CYAN = "#2DD4BF"
    first_name = (customer_name or "there").split()[0] if customer_name else "there"
    lob_label = (line_of_business or "policy").replace("_", " ").title()
    carrier_display = carrier or "your insurance"

    # Build app section
    if app_info and (app_info.get("ios") or app_info.get("android")):
        app_buttons = ""
        if app_info.get("ios"):
            app_buttons += f'''
                <a href="{app_info["ios"]}" style="display:inline-block;padding:10px 18px;background:#000;color:white;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;margin:4px;">
                  📱 Download for iPhone
                </a>'''
        if app_info.get("android"):
            app_buttons += f'''
                <a href="{app_info["android"]}" style="display:inline-block;padding:10px 18px;background:#000;color:white;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;margin:4px;">
                  🤖 Download for Android
                </a>'''
        app_section = f'''
        <tr><td style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e5e7eb;">
          <div style="font-size:15px;font-weight:700;color:{BCI_NAVY};margin-bottom:8px;">
            Get the {app_info["name"]} app
          </div>
          <div style="font-size:14px;color:#475569;line-height:1.5;margin-bottom:14px;">
            Access your ID card anytime, report a claim, and manage your policy on the go with the {app_info["name"]} mobile app.
          </div>
          <div style="text-align:center;">
            {app_buttons}
          </div>
        </td></tr>
        '''
    elif app_info and app_info.get("service_phone"):
        # No app but we have a service number
        app_section = f'''
        <tr><td style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e5e7eb;">
          <div style="font-size:15px;font-weight:700;color:{BCI_NAVY};margin-bottom:8px;">
            Need help with your {app_info["name"]} policy?
          </div>
          <div style="font-size:14px;color:#475569;line-height:1.5;">
            You can reach {app_info["name"]} customer service directly at <strong>{app_info["service_phone"]}</strong>.
          </div>
        </td></tr>
        '''
    else:
        app_section = ""

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
          Keep a copy on your phone or print it and store it in your vehicle — you'll need it if you're ever pulled over or involved in an accident.
          <br><br>
          If you need anything else, call or text us anytime at <strong>847-908-5665</strong>.
          <br><br>
          Thanks for choosing Better Choice Insurance.<br>
          — The Better Choice Team
        </td></tr>
        {app_section}
        <tr><td style="background:#f8f8f8;padding:18px 32px;border-top:1px solid #e5e7eb;color:#666;font-size:12px;">
          Better Choice Insurance Group · 300 Cardinal Dr Suite 220, Saint Charles, IL 60175<br>
          847-908-5665 · service@betterchoiceins.com
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
    """Email the customer their ID card PDF with branded copy and carrier app info.

    The agent uploads the PDF (pulled from the carrier portal). ORBIT adds the
    BCI-branded template, attaches the PDF, and sends to the recipient email.
    BCCs the selling agent / service mailbox so we have a record.
    """
    mg_key = os.environ.get("MAILGUN_API_KEY") or settings.MAILGUN_API_KEY
    mg_domain = os.environ.get("MAILGUN_DOMAIN") or settings.MAILGUN_DOMAIN
    if not mg_key or not mg_domain:
        raise HTTPException(status_code=503, detail="Mailgun not configured")

    # Validate customer exists
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Validate file type (basic)
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    pdf_bytes = await pdf.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="PDF is empty")
    if len(pdf_bytes) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(status_code=400, detail="PDF exceeds 10MB limit")

    # Validate PDF magic bytes
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF")

    # Look up app info
    app_info = _resolve_carrier_app(carrier)

    # Build email HTML
    customer_name = customer.full_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip()
    html = _build_idcard_html(customer_name, carrier, line_of_business or "", app_info)
    subject = f"Your {carrier} ID Card — Better Choice Insurance"

    # Send via Mailgun with the PDF attached
    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{mg_domain}/messages",
            auth=("api", mg_key),
            data={
                "from": f"Better Choice Insurance <service@{mg_domain}>",
                "to": recipient_email,
                "bcc": f"service@betterchoiceins.com",
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
                "h:X-Customer-Id": str(customer_id),
                "h:X-Agent": current_user.username or str(current_user.id),
            },
            files=[
                ("attachment", (pdf.filename, pdf_bytes, "application/pdf")),
            ],
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "sent")
            logger.info("ID card sent for customer %s (%s) by %s — msg %s",
                        customer_id, carrier, current_user.username, msg_id)
            return {
                "status": "ok",
                "message_id": msg_id,
                "recipient": recipient_email,
                "has_app": bool(app_info and (app_info.get("ios") or app_info.get("android"))),
            }
        raise HTTPException(status_code=502, detail=f"Mailgun error: {resp.status_code} {resp.text[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ID card send failed")
        raise HTTPException(status_code=500, detail=f"Send failed: {str(e)[:200]}")


@router.get("/carrier-app-info")
def get_carrier_app_info(carrier: str):
    """Lightweight lookup: given a carrier name, return the app info we'd use.
    Lets the frontend preview what the email will contain before sending.
    """
    info = _resolve_carrier_app(carrier)
    if not info:
        return {"carrier": carrier, "found": False}
    return {
        "carrier": carrier,
        "found": True,
        "name": info.get("name"),
        "has_ios": bool(info.get("ios")),
        "has_android": bool(info.get("android")),
        "service_phone": info.get("service_phone"),
    }
