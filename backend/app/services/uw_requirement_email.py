"""Underwriting requirement notification emails.

Sends branded emails to insureds (and CC's their producer) when a carrier
requests underwriting documentation (e.g., proof of continuous insurance).
"""
import logging
import requests
from typing import Optional
from app.core.config import settings
from app.services.welcome_email import (
    CARRIER_INFO, _get_carrier_key,
    AGENCY_PHONE, AGENCY_NAME, BCI_NAVY, BCI_CYAN,
)

logger = logging.getLogger(__name__)

# ── Templates by requirement type ──────────────────────────────────────

UW_REQUIREMENT_TYPES = {
    "proof_of_continuous_insurance": {
        "short": "Proof of Continuous Insurance",
        "subject": "Action Required: Proof of Insurance Needed for Your {carrier} Policy",
        "what_needed": "Your carrier has requested <strong>proof of continuous insurance coverage</strong>. "
                       "This is typically a declarations page (dec page) from your prior insurance policy showing "
                       "your coverage dates and limits.",
        "how_to": [
            "Contact your previous insurance company and request a <strong>declarations page</strong> or letter confirming your prior coverage dates",
            "You can also log into your prior carrier's website or app to download your dec page",
            "Forward the document to us at <strong>service@betterchoiceins.com</strong> or reply to this email with the attachment",
        ],
        "urgency": "If this documentation is not provided by the deadline, your policy premium may increase "
                   "or your policy could be subject to cancellation.",
    },
    "nopop": {
        "short": "Proof of Prior Insurance",
        "subject": "Action Required: Proof of Prior Insurance Needed for Your {carrier} Policy",
        "what_needed": "Your carrier has requested <strong>proof of prior insurance (Proof of Prior)</strong>. "
                       "This confirms you had active insurance coverage before your current policy started.",
        "how_to": [
            "Contact your previous insurance company and request a <strong>declarations page</strong> or a letter confirming your prior coverage",
            "If you did not have prior insurance, please let us know so we can update your carrier",
            "Forward the document to us at <strong>service@betterchoiceins.com</strong> or reply to this email",
        ],
        "urgency": "Without this documentation, your premium may be adjusted or your policy could face cancellation.",
    },
    "change_prior_bi": {
        "short": "Prior Bodily Injury Limits Documentation",
        "subject": "Action Required: Prior Insurance Limits Needed for Your {carrier} Policy",
        "what_needed": "Your carrier has requested documentation of your <strong>prior bodily injury liability limits</strong>. "
                       "This is needed to verify the liability coverage you carried on your previous policy.",
        "how_to": [
            "Contact your previous insurance company and request a <strong>declarations page</strong> showing your prior bodily injury liability limits",
            "The dec page should clearly show your BI (Bodily Injury) limit amounts (e.g., 100/300 or 250/500)",
            "Forward the document to us at <strong>service@betterchoiceins.com</strong> or reply to this email with the attachment",
        ],
        "urgency": "Without this documentation, your liability limits and premium may be adjusted or your policy could face cancellation.",
    },
    "proof_of_prior_bi": {
        "short": "Proof of Prior Bodily Injury Limits",
        "subject": "Action Required: Prior BI Limits Documentation Needed for Your {carrier} Policy",
        "what_needed": "Your carrier needs <strong>proof of your prior bodily injury (BI) liability limits</strong>. "
                       "This verifies the coverage level you had before your current policy.",
        "how_to": [
            "Contact your previous insurance company and request a <strong>declarations page</strong> showing your bodily injury liability limits",
            "The dec page should show your BI limits (e.g., 25/50, 100/300, 250/500)",
            "Forward the document to us at <strong>service@betterchoiceins.com</strong> or reply to this email",
        ],
        "urgency": "If this documentation is not provided promptly, your coverage limits or premium may be adjusted.",
    },
}


def build_uw_requirement_email_html(
    client_name: str,
    policy_number: str,
    carrier: str,
    requirement_type: str = "proof_of_continuous_insurance",
    due_date: Optional[str] = None,
    producer_name: Optional[str] = None,
) -> tuple[str, str]:
    """Build UW requirement email. Returns (subject, html_body)."""

    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key, {}) if carrier_key else {}
    display_carrier = info.get("display_name", carrier or "Your Insurance Carrier")
    accent = info.get("accent_color", BCI_NAVY)

    req = UW_REQUIREMENT_TYPES.get(requirement_type, UW_REQUIREMENT_TYPES["proof_of_continuous_insurance"])
    first_name = (client_name or "Valued Customer").split()[0]
    subject = req["subject"].format(carrier=display_carrier)

    h = []
    h.append('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>')
    h.append('<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">')
    h.append('<div style="max-width:600px; margin:0 auto; padding:20px;">')

    # ── Header banner ──
    h.append(f'<div style="background:linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border-radius:16px 16px 0 0; padding:28px 32px; text-align:center;">')
    h.append(f'<p style="margin:0 0 4px; font-size:13px; color:rgba(255,255,255,0.85); letter-spacing:1px; font-weight:600;">📋 UNDERWRITING REQUIREMENT</p>')
    h.append(f'<h1 style="margin:0; font-size:22px; color:#ffffff; font-weight:700;">Documentation Needed</h1>')
    h.append('</div>')

    # ── White card body ──
    h.append('<div style="background:#ffffff; padding:32px; border-radius:0 0 16px 16px; box-shadow:0 4px 24px rgba(0,0,0,0.08);">')

    # Carrier logo
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
        app_url = getattr(settings, "APP_URL", "https://better-choice-web.onrender.com")
        logo_url = f"{app_url}/carrier-logos/{logo_file}"
        h.append(f'<div style="text-align:center; margin:0 0 20px; padding:16px 0 8px;">')
        h.append(f'<img src="{logo_url}" alt="{display_carrier}" style="max-height:50px; max-width:240px; height:auto; width:auto;" />')
        h.append('</div>')

    # Greeting
    h.append(f'<p style="font-size:16px; color:#1e293b; margin:0 0 16px; line-height:1.6;">Hi {first_name},</p>')

    # What's needed
    h.append(f'<p style="font-size:15px; color:#334155; margin:0 0 20px; line-height:1.7;">{req["what_needed"]}</p>')

    # Policy details box
    h.append(f'<div style="margin:24px 0; padding:20px; background:#fffbeb; border-radius:12px; border:1px solid #fde68a; border-left:4px solid #f59e0b;">')
    h.append(f'<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b; width:160px;">Policy Number</td><td style="padding:6px 0; font-weight:700; color:#1e293b;">{policy_number}</td></tr>')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Carrier</td><td style="padding:6px 0; font-weight:600;">{display_carrier}</td></tr>')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Requirement</td><td style="padding:6px 0; font-weight:600; color:#d97706;">{req["short"]}</td></tr>')
    if due_date:
        h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Due By</td><td style="padding:6px 0; font-weight:700; color:#dc2626;">{due_date}</td></tr>')
    h.append('</table></div>')

    # How to provide
    h.append('<h2 style="margin:24px 0 12px; font-size:17px; color:#1e293b;">How to Provide This</h2>')
    h.append('<div style="margin:0 0 20px;">')
    for i, step in enumerate(req["how_to"], 1):
        h.append(f'<div style="display:flex; margin:0 0 12px;">')
        h.append(f'<div style="min-width:28px; height:28px; border-radius:50%; background:{accent}; color:white; font-weight:700; font-size:13px; display:inline-block; text-align:center; line-height:28px; margin-right:12px;">{i}</div>')
        h.append(f'<p style="margin:0; font-size:14px; color:#334155; line-height:1.6; padding-top:3px;">{step}</p>')
        h.append('</div>')
    h.append('</div>')

    # Email button
    h.append(f'<a href="mailto:service@betterchoiceins.com?subject=Proof of Insurance - {policy_number}" style="display:block; padding:14px 24px; background:{accent}; color:#ffffff; text-decoration:none; border-radius:10px; font-weight:700; font-size:15px; text-align:center; margin:0 0 16px;">📎 Email Your Documents</a>')

    # Urgency note
    h.append(f'<div style="margin:20px 0; padding:16px; background:#fef2f2; border-radius:10px; border:1px solid #fecaca;">')
    h.append(f'<p style="margin:0; font-size:14px; color:#991b1b; line-height:1.6;"><strong>⚠️ Important:</strong> {req["urgency"]}</p>')
    h.append('</div>')

    # Agency footer
    h.append(f'<div style="margin:24px 0 0; padding:16px 20px; background:#fafbfc; border-radius:10px; border:1px solid #e2e8f0;">')
    h.append(f'<p style="margin:0 0 4px; font-size:12px; color:#64748b; font-weight:600; letter-spacing:0.5px;">YOUR AGENCY</p>')
    h.append(f'<p style="margin:0 0 2px; font-weight:700; font-size:15px; color:#1e293b;">{AGENCY_NAME}</p>')
    h.append(f'<p style="margin:0; font-size:14px;"><a href="tel:8479085665" style="color:{BCI_CYAN}; text-decoration:none; font-weight:600;">{AGENCY_PHONE}</a></p>')
    if producer_name:
        h.append(f'<p style="margin:4px 0 0; font-size:13px; color:#64748b;">Your agent: <strong>{producer_name}</strong></p>')
    h.append('</div>')

    h.append('<hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">')
    h.append(f'<p style="font-size:11px; color:#94a3b8; text-align:center; margin:0; line-height:1.5;">')
    h.append(f'This is an automated notice from {AGENCY_NAME}. If you have questions, call us at {AGENCY_PHONE}.</p>')
    h.append('</div></div></body></html>')

    return subject, "\n".join(h)


def send_uw_requirement_email(
    to_email: str,
    client_name: str,
    policy_number: str,
    carrier: str,
    requirement_type: str = "proof_of_continuous_insurance",
    due_date: Optional[str] = None,
    producer_name: Optional[str] = None,
    producer_email: Optional[str] = None,
) -> dict:
    """Send UW requirement email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    if not to_email:
        return {"success": False, "error": "No email address"}

    subject, html_body = build_uw_requirement_email_html(
        client_name=client_name,
        policy_number=policy_number,
        carrier=carrier,
        requirement_type=requirement_type,
        due_date=due_date,
        producer_name=producer_name,
    )

    cc_list = ["evan@betterchoiceins.com"]
    if producer_email and producer_email != "evan@betterchoiceins.com":
        cc_list.append(producer_email)

    mail_data = {
        "from": f"{AGENCY_NAME} <service@{settings.MAILGUN_DOMAIN}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "h:Reply-To": "service@betterchoiceins.com",
        "cc": cc_list,
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
            logger.info("UW requirement email sent to %s for %s - %s", to_email, policy_number, msg_id)
            return {"success": True, "message_id": msg_id}
        else:
            logger.error("Mailgun error %s: %s", resp.status_code, resp.text)
            return {"success": False, "error": f"Mailgun {resp.status_code}"}
    except Exception as e:
        logger.error("Failed to send UW requirement email: %s", e)
        return {"success": False, "error": str(e)}


def send_undeliverable_mail_alert(
    producer_email: str,
    client_name: str,
    policy_number: str,
    carrier: str,
    mail_description: str = "",
    phone: Optional[str] = None,
) -> dict:
    """Notify producer about undeliverable mail so they can update customer address."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key, {}) if carrier_key else {}
    display_carrier = info.get("display_name", carrier or "Unknown Carrier")

    subject = f"📬 Undeliverable Mail — {client_name} ({policy_number})"

    h = []
    h.append('<!DOCTYPE html><html><head><meta charset="utf-8"></head>')
    h.append('<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">')
    h.append('<div style="max-width:600px; margin:0 auto; padding:20px;">')
    h.append('<div style="background:linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%); border-radius:16px 16px 0 0; padding:24px 32px; text-align:center;">')
    h.append('<h1 style="margin:0; font-size:20px; color:#ffffff;">📬 Undeliverable Mail Notice</h1>')
    h.append('</div>')
    h.append('<div style="background:#ffffff; padding:28px 32px; border-radius:0 0 16px 16px;">')
    h.append(f'<p style="font-size:15px; color:#334155; line-height:1.7;">Mail sent to <strong>{client_name}</strong> was returned as <strong>undeliverable</strong> by {display_carrier}. Please contact the customer to update their mailing address.</p>')
    h.append(f'<div style="margin:20px 0; padding:16px; background:#f5f3ff; border-radius:10px; border-left:4px solid #7c3aed;">')
    h.append(f'<table style="font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
    h.append(f'<tr><td style="padding:4px 16px 4px 0; color:#64748b;">Customer</td><td style="font-weight:700;">{client_name}</td></tr>')
    h.append(f'<tr><td style="padding:4px 16px 4px 0; color:#64748b;">Policy</td><td style="font-weight:600;">{policy_number}</td></tr>')
    h.append(f'<tr><td style="padding:4px 16px 4px 0; color:#64748b;">Carrier</td><td>{display_carrier}</td></tr>')
    if mail_description:
        h.append(f'<tr><td style="padding:4px 16px 4px 0; color:#64748b;">Mail Type</td><td>{mail_description}</td></tr>')
    if phone:
        h.append(f'<tr><td style="padding:4px 16px 4px 0; color:#64748b;">Phone</td><td><a href="tel:{phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")}" style="color:#7c3aed; font-weight:600;">{phone}</a></td></tr>')
    h.append('</table></div>')
    h.append(f'<p style="font-size:13px; color:#64748b; margin:16px 0 0;">Update the address in NowCerts and notify {display_carrier} of the change.</p>')
    h.append('</div></div></body></html>')

    mail_data = {
        "from": f"{AGENCY_NAME} <service@{settings.MAILGUN_DOMAIN}>",
        "to": [producer_email, "evan@betterchoiceins.com"],
        "subject": subject,
        "html": "\n".join(h),
    }

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info("Undeliverable mail alert sent for %s/%s", client_name, policy_number)
            return {"success": True}
        return {"success": False, "error": f"Mailgun {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def build_non_renewal_email_html(
    client_name: str,
    policy_number: str,
    carrier: str,
    effective_date: str = "",
    premium: Optional[float] = None,
    product: str = "",
    description: str = "",
    producer_name: Optional[str] = None,
) -> tuple[str, str]:
    """Build non-renewal notification email for the insured. Returns (subject, html_body)."""

    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key, {}) if carrier_key else {}
    display_carrier = info.get("display_name", carrier or "Your Insurance Carrier")
    accent = info.get("accent_color", BCI_NAVY)

    first_name = (client_name or "Valued Customer").split()[0]
    subject = f"Important: Your {display_carrier} Policy Will Not Be Renewed — We're Here to Help"

    h = []
    h.append('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>')
    h.append('<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">')
    h.append('<div style="max-width:600px; margin:0 auto; padding:20px;">')

    # Header
    h.append('<div style="background:linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%); border-radius:16px 16px 0 0; padding:28px 32px; text-align:center;">')
    h.append('<p style="margin:0 0 4px; font-size:13px; color:rgba(255,255,255,0.85); letter-spacing:1px; font-weight:600;">📋 POLICY UPDATE</p>')
    h.append('<h1 style="margin:0; font-size:22px; color:#ffffff; font-weight:700;">Your Policy Is Not Being Renewed</h1>')
    h.append('</div>')

    h.append('<div style="background:#ffffff; padding:32px; border-radius:0 0 16px 16px; box-shadow:0 4px 24px rgba(0,0,0,0.08);">')

    # Greeting
    h.append(f'<p style="font-size:16px; color:#1e293b; margin:0 0 16px; line-height:1.6;">Hi {first_name},</p>')
    h.append(f'<p style="font-size:15px; color:#334155; margin:0 0 20px; line-height:1.7;">')
    h.append(f'We\'re writing to let you know that <strong>{display_carrier}</strong> has decided not to renew your policy. ')
    h.append(f'<strong>This does not mean you\'ll be without coverage</strong> — our team is already working on finding you the best replacement options.</p>')

    # Policy details
    h.append('<div style="margin:24px 0; padding:20px; background:#f5f3ff; border-radius:12px; border:1px solid #ddd6fe; border-left:4px solid #7c3aed;">')
    h.append('<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b; width:160px;">Policy Number</td><td style="padding:6px 0; font-weight:700; color:#1e293b;">{policy_number}</td></tr>')
    h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Current Carrier</td><td style="padding:6px 0; font-weight:600;">{display_carrier}</td></tr>')
    if effective_date:
        h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Coverage Ends</td><td style="padding:6px 0; font-weight:700; color:#dc2626;">{effective_date}</td></tr>')
    if premium:
        h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Current Premium</td><td style="padding:6px 0; font-weight:600;">${premium:,.2f}</td></tr>')
    if product:
        h.append(f'<tr><td style="padding:6px 0; color:#64748b;">Policy Type</td><td style="padding:6px 0;">{product}</td></tr>')
    h.append('</table></div>')

    # What happens next
    h.append('<h2 style="margin:24px 0 12px; font-size:17px; color:#1e293b;">What Happens Next</h2>')
    steps = [
        "Our team will shop your coverage across multiple carriers to find you the best rate",
        "We'll reach out with your new options <strong>before your current coverage ends</strong>",
        "We'll handle all the paperwork to switch you seamlessly — no gap in coverage",
    ]
    for i, step in enumerate(steps, 1):
        h.append(f'<div style="display:flex; margin:0 0 12px;">')
        h.append(f'<div style="min-width:28px; height:28px; border-radius:50%; background:#7c3aed; color:white; font-weight:700; font-size:13px; display:inline-block; text-align:center; line-height:28px; margin-right:12px;">{i}</div>')
        h.append(f'<p style="margin:0; font-size:14px; color:#334155; line-height:1.6; padding-top:3px;">{step}</p>')
        h.append('</div>')

    # Reassurance
    h.append('<div style="margin:20px 0; padding:16px; background:#f0fdf4; border-radius:10px; border:1px solid #bbf7d0;">')
    h.append('<p style="margin:0; font-size:14px; color:#166534; line-height:1.6;">')
    h.append(f'<strong>You don\'t need to do anything right now.</strong> We\'ll be in touch shortly with replacement options. ')
    h.append(f'If you have questions in the meantime, call us at <strong>{AGENCY_PHONE}</strong>.')
    h.append('</p></div>')

    # Agency footer
    h.append(f'<div style="margin:24px 0 0; padding:16px 20px; background:#fafbfc; border-radius:10px; border:1px solid #e2e8f0;">')
    h.append(f'<p style="margin:0 0 4px; font-size:12px; color:#64748b; font-weight:600; letter-spacing:0.5px;">YOUR AGENCY</p>')
    h.append(f'<p style="margin:0 0 2px; font-weight:700; font-size:15px; color:#1e293b;">{AGENCY_NAME}</p>')
    h.append(f'<p style="margin:0; font-size:14px;"><a href="tel:8479085665" style="color:{BCI_CYAN}; text-decoration:none; font-weight:600;">{AGENCY_PHONE}</a></p>')
    if producer_name:
        h.append(f'<p style="margin:4px 0 0; font-size:13px; color:#64748b;">Your agent: <strong>{producer_name}</strong></p>')
    h.append('</div>')

    h.append('<hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0;">')
    h.append(f'<p style="font-size:11px; color:#94a3b8; text-align:center; margin:0;">This is an automated notice from {AGENCY_NAME}.</p>')
    h.append('</div></div></body></html>')

    return subject, "\n".join(h)


def send_non_renewal_email(
    to_email: str,
    client_name: str,
    policy_number: str,
    carrier: str,
    effective_date: str = "",
    premium: Optional[float] = None,
    product: str = "",
    description: str = "",
    producer_name: Optional[str] = None,
    producer_email: Optional[str] = None,
) -> dict:
    """Send non-renewal notification email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    if not to_email:
        return {"success": False, "error": "No email address"}

    subject, html_body = build_non_renewal_email_html(
        client_name=client_name,
        policy_number=policy_number,
        carrier=carrier,
        effective_date=effective_date,
        premium=premium,
        product=product,
        description=description,
        producer_name=producer_name,
    )

    cc_list = ["evan@betterchoiceins.com"]
    if producer_email and producer_email != "evan@betterchoiceins.com":
        cc_list.append(producer_email)

    mail_data = {
        "from": f"{AGENCY_NAME} <service@{settings.MAILGUN_DOMAIN}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "h:Reply-To": "service@betterchoiceins.com",
        "cc": cc_list,
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
            logger.info("Non-renewal email sent to %s for %s", to_email, policy_number)
            return {"success": True, "message_id": msg_id}
        return {"success": False, "error": f"Mailgun {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
