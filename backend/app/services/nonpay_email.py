"""Non-pay / past-due email service — carrier-specific templates via Mailgun.

Sends professional past-due notices branded per carrier, with payment links
and agency contact info. Mirrors the welcome email pattern.
"""
import logging
import requests
from typing import Optional
from app.core.config import settings
from app.services.welcome_email import (
    CARRIER_INFO, CARRIER_ALIASES, _get_carrier_key,
    AGENCY_PHONE, AGENCY_NAME, BCI_NAVY, BCI_CYAN, BCI_DARK,
)

logger = logging.getLogger(__name__)


def build_nonpay_email_html(
    client_name: str,
    policy_number: str,
    carrier: str,
    amount_due: Optional[float] = None,
    due_date: Optional[str] = None,
) -> tuple[str, str]:
    """Build carrier-specific past-due email. Returns (subject, html_body)."""

    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key, {}) if carrier_key else {}
    is_generic = not carrier_key or carrier_key not in CARRIER_INFO
    display_carrier = info.get("display_name", carrier or "Your Insurance Carrier")
    accent = info.get("accent_color", BCI_NAVY)

    first_name = (client_name or "Valued Customer").split()[0]
    subject = f"Important: Payment Required for Your {display_carrier} Policy"

    h = []
    h.append('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>')
    h.append('<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">')
    h.append('<div style="max-width:600px; margin:0 auto; padding:20px;">')

    # ── Urgent header banner ──
    h.append(f'<div style="background:linear-gradient(135deg, #dc2626 0%, #b91c1c 100%); border-radius:16px 16px 0 0; padding:28px 32px; text-align:center;">')
    h.append(f'<p style="margin:0 0 4px; font-size:13px; color:rgba(255,255,255,0.85); letter-spacing:1px; font-weight:600;">⚠️ PAYMENT NOTICE</p>')
    h.append(f'<h1 style="margin:0; font-size:22px; color:#ffffff; font-weight:700;">Action Required on Your Policy</h1>')
    h.append('</div>')

    # ── White card body ──
    h.append('<div style="background:#ffffff; padding:32px; border-radius:0 0 16px 16px; box-shadow:0 4px 24px rgba(0,0,0,0.08);">')

    # ── Carrier logo ──
    LOGO_FILES = {
        "grange": "grange.png", "integrity": "integrity.png", "branch": "branch.png",
        "universal_property": "universal_property.png", "next": "next.png", "hippo": "hippo.png",
        "gainsco": "gainsco.png", "steadily": "steadily.png", "geico": "geico.png",
        "american_modern": "american_modern.png", "progressive": "progressive.png",
        "clearcover": "clearcover.png", "safeco": "safeco.png", "travelers": "travelers.png",
        "national_general": "national_general.png", "openly": "openly.png",
        "bristol_west": "bristol_west.png", "covertree": "covertree.png",
    }
    logo_file = LOGO_FILES.get(carrier_key, "")
    if logo_file:
        app_url = "https://better-choice-web.onrender.com"
        try:
            from app.core.config import settings
            app_url = getattr(settings, "APP_URL", app_url)
        except Exception:
            pass
        logo_url = f"{app_url}/carrier-logos/{logo_file}"
        h.append(f'<div style="text-align:center; margin:0 0 20px; padding:16px 0 8px;">')
        h.append(f'<img src="{logo_url}" alt="{display_carrier}" style="max-height:50px; max-width:240px; height:auto; width:auto;" />')
        h.append('</div>')

    # Greeting
    h.append(f'<p style="font-size:16px; color:#1e293b; margin:0 0 16px; line-height:1.6;">Hi {first_name},</p>')
    h.append(f'<p style="font-size:15px; color:#334155; margin:0 0 20px; line-height:1.7;">')
    h.append(f'We want to make sure your insurance coverage stays active. Our records show a <strong>past-due balance</strong> on your policy with <strong>{display_carrier}</strong>. ')
    h.append(f'If payment is not received, your policy may be at risk of cancellation.</p>')

    # ── Policy details box ──
    h.append(f'<div style="margin:24px 0; padding:20px; background:#fef2f2; border-radius:12px; border:1px solid #fecaca; border-left:4px solid #dc2626;">')
    h.append(f'<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b; width:140px;">Policy Number</td><td style="padding:6px 0; font-weight:700; color:#1e293b;">{policy_number or "See your statement"}</td></tr>')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Carrier</td><td style="padding:6px 0; font-weight:600;">{display_carrier}</td></tr>')
    if amount_due:
        h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Amount Due</td><td style="padding:6px 0; font-weight:700; color:#dc2626; font-size:18px;">${amount_due:,.2f}</td></tr>')
    if due_date:
        h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Due Date</td><td style="padding:6px 0; font-weight:600; color:#dc2626;">{due_date}</td></tr>')
    h.append('</table></div>')

    # ── Payment action ──
    h.append('<h2 style="margin:24px 0 12px; font-size:17px; color:#1e293b;">How to Make Your Payment</h2>')

    payment_url = info.get("payment_url", "")
    if payment_url:
        h.append(f'<a href="{payment_url}" style="display:block; padding:14px 24px; background:{accent}; color:#ffffff; text-decoration:none; border-radius:10px; font-weight:700; font-size:15px; text-align:center; margin:0 0 12px;">💳 Pay Now at {display_carrier}</a>')

    call_phone = info.get("payment_phone") or info.get("customer_service") or AGENCY_PHONE
    call_label = f"Call {display_carrier}: {call_phone}" if call_phone != AGENCY_PHONE else f"Call Us: {AGENCY_PHONE}"
    call_digits = call_phone.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    h.append(f'<a href="tel:{call_digits}" style="display:block; padding:14px 24px; background:#475569; color:#ffffff; text-decoration:none; border-radius:10px; font-weight:700; font-size:15px; text-align:center; margin:0 0 16px;">📞 {call_label}</a>')

    # ── Helpful context ──
    h.append('<div style="margin:20px 0; padding:16px; background:#fffbeb; border-radius:10px; border:1px solid #fde68a;">')
    h.append('<p style="margin:0; font-size:14px; color:#92400e; line-height:1.6;">')
    h.append('<strong>💡 Already made your payment?</strong> It may take a few days to process. If you recently paid, please disregard this notice. ')
    h.append(f'If you have any questions or need to set up a payment plan, don\'t hesitate to call us at <strong>{AGENCY_PHONE}</strong>.')
    h.append('</p></div>')

    # ── Why this matters ──
    h.append('<div style="margin:20px 0; padding:16px; background:#f0f9ff; border-radius:10px; border:1px solid #bae6fd;">')
    h.append('<p style="margin:0; font-size:14px; color:#0369a1; line-height:1.6;">')
    h.append('<strong>Why this matters:</strong> A lapse in your insurance coverage could leave you financially exposed in the event of an accident or loss. ')
    h.append('It may also affect your ability to drive legally and could result in higher rates when you re-insure.')
    h.append('</p></div>')

    # ── Carrier contact section ──
    if not is_generic and (info.get("customer_service") or info.get("payment_url") or info.get("payment_phone")):
        h.append(f'<div style="margin:24px 0; padding:20px; background:#f8fafc; border-radius:12px; border:1px solid #e2e8f0; border-left:4px solid {accent};">')
        h.append(f'<h3 style="margin:0 0 12px; font-size:14px; color:{accent}; font-weight:700; letter-spacing:0.5px;">{display_carrier.upper()} PAYMENT OPTIONS</h3>')
        h.append(f'<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
        if info.get("payment_phone"):
            pp = info["payment_phone"]
            h.append(f'<tr><td style="padding:6px 0;">📞 Make a Payment: <a href="tel:{pp.replace("-","")}" style="color:{accent}; font-weight:700;">{pp}</a></td></tr>')
        if info.get("payment_url"):
            h.append(f'<tr><td style="padding:6px 0;">💻 Online: <a href="{info["payment_url"]}" style="color:{accent}; font-weight:600;">Pay Online</a></td></tr>')
        if info.get("online_account_url"):
            h.append(f'<tr><td style="padding:6px 0;">👤 Account: <a href="{info["online_account_url"]}" style="color:{accent}; font-weight:600;">{info.get("online_account_text", "Log In")}</a></td></tr>')
        cs = info.get("customer_service", "")
        if cs and cs != AGENCY_PHONE and cs != info.get("payment_phone", ""):
            h.append(f'<tr><td style="padding:6px 0;">📞 {display_carrier}: <a href="tel:{cs.replace("-","")}" style="color:{accent}; font-weight:700;">{cs}</a></td></tr>')
        h.append('</table></div>')

    # ── Agency footer ──
    h.append(f'<div style="margin:24px 0 0; padding:16px 20px; background:#fafbfc; border-radius:10px; border:1px solid #e2e8f0;">')
    h.append(f'<p style="margin:0 0 4px; font-size:12px; color:#64748b; font-weight:600; letter-spacing:0.5px;">YOUR AGENCY</p>')
    h.append(f'<p style="margin:0 0 2px; font-weight:700; font-size:15px; color:#1e293b;">{AGENCY_NAME}</p>')
    h.append(f'<p style="margin:0; font-size:14px;"><a href="tel:8479085665" style="color:{BCI_CYAN}; text-decoration:none; font-weight:600;">{AGENCY_PHONE}</a></p>')
    h.append('</div>')

    h.append('<hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">')
    h.append(f'<p style="font-size:11px; color:#94a3b8; text-align:center; margin:0; line-height:1.5;">')
    h.append(f'This is an automated courtesy notice from {AGENCY_NAME}. ')
    h.append(f'If you believe this was sent in error or have already made your payment, please contact us at {AGENCY_PHONE}.</p>')

    h.append('</div></div></body></html>')

    return subject, "\n".join(h)


def send_nonpay_email(
    to_email: str,
    client_name: str,
    policy_number: str,
    carrier: str,
    amount_due: Optional[float] = None,
    due_date: Optional[str] = None,
) -> dict:
    """Send past-due email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured - skipping non-pay email")
        return {"success": False, "error": "Mailgun not configured"}

    if not to_email:
        return {"success": False, "error": "No email address"}

    subject, html_body = build_nonpay_email_html(
        client_name=client_name,
        policy_number=policy_number,
        carrier=carrier,
        amount_due=amount_due,
        due_date=due_date,
    )

    mail_data = {
        "from": f"{AGENCY_NAME} <{settings.MAILGUN_FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "bcc": ["evan@betterchoiceins.com"],
    }

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info("Non-pay email sent to %s for policy %s - msg_id: %s", to_email, policy_number, msg_id)
            return {"success": True, "message_id": msg_id}
        else:
            logger.error("Mailgun error %s: %s", resp.status_code, resp.text)
            return {"success": False, "error": f"Mailgun returned {resp.status_code}"}
    except Exception as e:
        logger.error("Failed to send non-pay email: %s", e)
        return {"success": False, "error": str(e)}
