"""Welcome email service - carrier-specific templates sent via Mailgun.

All emails feature Better Choice Insurance Group branding with
carrier-specific content when available. Generic BCI-branded fallback
for unrecognized carriers.

Agency phone: 847-908-5665 (shown in every email, not prominent)
Carrier numbers shown prominently when available.
"""
import logging
import requests
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Brand constants ──────────────────────────────────────────────────

AGENCY_PHONE = "847-908-5665"
AGENCY_NAME = "Better Choice Insurance Group"

# Brand colors from logo
BCI_NAVY = "#1a2b5f"
BCI_DARK = "#162249"
BCI_CYAN = "#2cb5e8"
BCI_LIGHT_CYAN = "#3ec7f5"
BCI_GRADIENT = "linear-gradient(135deg, #1a2b5f 0%, #162249 60%, #0c4a6e 100%)"


# ── Carrier-specific content ─────────────────────────────────────────

CARRIER_INFO = {
    "national_general": {
        "display_name": "National General Insurance",
        "accent_color": "#003366",
        "mobile_app_url": "https://www.nationalgeneral.com/about/mobile-app",
        "mobile_app_name": "National General Insurance App",
        "online_account_url": "https://www.nationalgeneral.com/manage-your-policy",
        "online_account_text": "Set Up Your Online Account",
        "claims_phone": "1-800-325-1088",
        "roadside_phone": "1-877-468-3466",
        "billing_phone": "1-800-462-2123",
        "payment_url": "https://www.nationalgeneral.com/make-a-payment",
        "extra_tip": "You can manage your policy, view ID cards, and make payments right from the app.",
    },
    "progressive": {
        "display_name": "Progressive Insurance",
        "accent_color": "#0033A0",
        "mobile_app_url": "https://www.progressive.com/app/",
        "mobile_app_name": "Progressive App",
        "online_account_url": "https://www.progressive.com/register/",
        "online_account_text": "Create Your Progressive Account",
        "claims_phone": "1-800-776-4737",
        "roadside_phone": "1-800-776-4737",
        "billing_phone": "1-800-776-4737",
        "payment_url": "https://www.progressive.com/pay-bill/",
        "extra_tip": "Download the Progressive app to get your digital ID card, track claims, and manage your policy.",
    },
    "safeco": {
        "display_name": "Safeco Insurance",
        "accent_color": "#00529B",
        "mobile_app_url": "https://www.safeco.com/about/mobile",
        "mobile_app_name": "Safeco Mobile App",
        "online_account_url": "https://www.safeco.com/manage-your-policy",
        "online_account_text": "Set Up Your Safeco Account",
        "claims_phone": "1-800-332-3226",
        "roadside_phone": "1-877-762-3101",
        "billing_phone": "1-800-332-3226",
        "payment_url": "https://www.safeco.com/manage-your-policy",
        "extra_tip": "The Safeco app lets you view ID cards, file claims, and contact roadside assistance instantly.",
    },
    "travelers": {
        "display_name": "Travelers Insurance",
        "accent_color": "#E31837",
        "mobile_app_url": "https://www.travelers.com/tools-resources/apps/mytravelers",
        "mobile_app_name": "MyTravelers App",
        "online_account_url": "https://www.travelers.com/online-account-access",
        "online_account_text": "Create Your MyTravelers Account",
        "claims_phone": "1-800-252-4633",
        "roadside_phone": "1-800-252-4633",
        "billing_phone": "1-800-842-5075",
        "payment_url": "https://www.travelers.com/pay-your-bill",
        "extra_tip": "With MyTravelers, you can view policy documents, report claims, and manage billing all in one place.",
    },
    "grange": {
        "display_name": "Grange Insurance",
        "accent_color": "#1B5E20",
        "mobile_app_url": "https://www.grangeinsurance.com/manage-your-policy/download-our-app",
        "mobile_app_name": "Grange Mobile App",
        "online_account_url": "https://www.grangeinsurance.com/manage-your-policy",
        "online_account_text": "Set Up Your Grange Online Account",
        "claims_phone": "1-800-445-3030",
        "roadside_phone": "1-800-445-3030",
        "billing_phone": "1-800-445-3030",
        "payment_url": "https://www.grangeinsurance.com/manage-your-policy/pay-my-bill",
        "extra_tip": "The Grange app gives you instant access to ID cards, claims filing, and payment options.",
    },
}

# ── Carrier aliases ──────────────────────────────────────────────────

CARRIER_ALIASES = {
    "trustgard": "grange",
    "trustgard_insurance": "grange",
    "trust_gard": "grange",
    "trustgard_mutual": "grange",
}


def _get_carrier_key(carrier):
    if not carrier:
        return None
    c = carrier.lower().replace(" ", "_").replace("-", "_")
    if c in CARRIER_ALIASES:
        return CARRIER_ALIASES[c]
    if c in CARRIER_INFO:
        return c
    for key in CARRIER_INFO:
        if key in c or c in key:
            return key
    for alias, target in CARRIER_ALIASES.items():
        if alias in c:
            return target
    return None


# ── HTML helpers ─────────────────────────────────────────────────────

def _btn(url, bg, icon, label):
    if not url:
        return ""
    return (
        '<a href="' + url + '" style="display:block; background:' + bg
        + '; color:#fff; padding:14px 24px; border-radius:10px; text-decoration:none;'
        + ' font-weight:600; font-size:15px; text-align:center; margin-bottom:10px;">'
        + icon + " " + label + "</a>"
    )


def _phone_row(label, phone, bold=False):
    if not phone:
        return ""
    weight = "700" if bold else "600"
    size = "15px" if bold else "14px"
    return (
        '<tr><td style="padding:6px 0; color:#94a3b8; font-size:14px;">' + label
        + '</td><td style="padding:6px 0; font-weight:' + weight
        + '; font-size:' + size + '; color:#1e293b;">'
        + '<a href="tel:' + phone.replace("-", "") + '" style="color:#1e293b; text-decoration:none;">'
        + phone + "</a></td></tr>"
    )


def _star(survey_url, n):
    return (
        '<a href="' + survey_url + "?rating=" + str(n)
        + '" style="text-decoration:none; font-size:32px; padding:0 4px;">&#11088;</a>'
    )


def _logo_html():
    """BCI logo for email header - white text on dark background."""
    return (
        '<table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">'
        "<tr>"
        '<td style="vertical-align:middle; padding-right:14px;">'
        '<div style="width:48px; text-align:center;">'
        '<div style="font-size:8px; line-height:1.4; color:' + BCI_CYAN + ';">'
        '&#9679;</div>'
        '<div style="font-size:8px; line-height:1.4; color:' + BCI_LIGHT_CYAN + ';">'
        '&#9679; &#9679; &#9679;</div>'
        '<div style="font-size:8px; line-height:1.4; color:' + BCI_CYAN + ';">'
        '&#9679; &#9679; &#9679; &#9679; &#9679;</div>'
        '<div style="font-size:8px; line-height:1.4; color:' + BCI_LIGHT_CYAN + ';">'
        '&#9679; &#9679; &#9679;</div>'
        '<div style="font-size:8px; line-height:1.4; color:' + BCI_CYAN + ';">'
        '&#9679;</div>'
        '</div>'
        "</td>"
        '<td style="vertical-align:middle; text-align:left;">'
        '<div style="font-size:22px; font-weight:800; color:#ffffff; line-height:1.15; letter-spacing:0.5px;">Better<br>Choice</div>'
        '<div style="font-size:10px; font-weight:600; color:' + BCI_CYAN + '; letter-spacing:2.5px; text-transform:uppercase; margin-top:3px;">Insurance Group</div>'
        "</td>"
        "</tr>"
        "</table>"
    )


def _agency_footer():
    """Agency footer with phone - subtle, not prominent."""
    return (
        '<div style="text-align:center; padding:24px 20px; color:#94a3b8; font-size:12px;">'
        '<table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 8px;">'
        "<tr>"
        '<td style="vertical-align:middle; padding-right:8px;">'
        '<div style="width:24px; text-align:center;">'
        '<div style="font-size:5px; line-height:1.4; color:' + BCI_CYAN + ';">&#9679;</div>'
        '<div style="font-size:5px; line-height:1.4; color:' + BCI_LIGHT_CYAN + ';">&#9679; &#9679; &#9679;</div>'
        '<div style="font-size:5px; line-height:1.4; color:' + BCI_CYAN + ';">&#9679;</div>'
        "</div>"
        "</td>"
        '<td style="vertical-align:middle;">'
        '<span style="font-size:13px; font-weight:700; color:#64748b;">' + AGENCY_NAME + "</span>"
        "</td>"
        "</tr>"
        "</table>"
        '<p style="margin:4px 0;">'
        '<a href="tel:8479085665" style="color:#94a3b8; text-decoration:none;">' + AGENCY_PHONE + "</a>"
        "</p>"
        '<p style="margin:8px 0 4px; color:#cbd5e1;">Thank you for choosing us!</p>'
        "</div>"
    )


# ── Email builder ────────────────────────────────────────────────────

def build_welcome_email_html(
    client_name,
    policy_number,
    carrier,
    producer_name,
    sale_id,
    policy_type=None,
):
    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key or "", None)
    is_generic = info is None

    if is_generic:
        info = {
            "display_name": carrier or "Your Insurance Carrier",
            "accent_color": BCI_NAVY,
            "mobile_app_url": "",
            "mobile_app_name": "",
            "online_account_url": "",
            "online_account_text": "",
            "claims_phone": "",
            "roadside_phone": "",
            "billing_phone": "",
            "payment_url": "",
            "extra_tip": "",
        }

    app_url = getattr(settings, "APP_URL", "https://better-choice-web.onrender.com")
    survey_url = app_url + "/survey/" + str(sale_id)
    first_name = client_name.split()[0] if client_name else "Valued Customer"
    producer_first = producer_name.split()[0] if producer_name else "Your Agent"

    # Subject line
    if is_generic:
        subject = "Welcome to " + AGENCY_NAME + "! Your new policy is ready"
    else:
        subject = "Welcome to " + info["display_name"] + "! Your policy is ready"

    h = []
    h.append('<!DOCTYPE html><html><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    h.append("</head>")
    h.append('<body style="margin:0; padding:0; background-color:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">')
    h.append('<div style="max-width:600px; margin:0 auto; padding:20px;">')

    # ── Header with BCI branding ─────────────────────────────────
    h.append('<div style="background:' + BCI_GRADIENT + '; border-radius:16px 16px 0 0; padding:28px 24px 24px; text-align:center;">')
    h.append(_logo_html())
    h.append('<div style="height:20px;"></div>')
    h.append('<h1 style="color:#fff; margin:0; font-size:26px; font-weight:700;">Welcome, ' + first_name + "!</h1>")

    if is_generic:
        h.append('<p style="color:rgba(255,255,255,0.85); margin:8px 0 0; font-size:15px;">Your new policy is all set and ready to go</p>')
    else:
        h.append('<p style="color:rgba(255,255,255,0.85); margin:8px 0 0; font-size:15px;">Your ' + info["display_name"] + " policy is all set</p>")

    h.append("</div>")

    # ── Body ─────────────────────────────────────────────────────
    h.append('<div style="background:#fff; padding:32px 24px; border-radius:0 0 16px 16px; box-shadow:0 4px 6px rgba(0,0,0,0.05);">')

    # Policy details card
    accent = info.get("accent_color", BCI_NAVY)
    h.append('<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:20px; margin-bottom:24px; border-top:3px solid ' + accent + ';">')
    h.append('<h2 style="margin:0 0 12px; font-size:14px; color:#64748b; font-weight:600; letter-spacing:1px;">YOUR POLICY DETAILS</h2>')
    h.append('<table style="width:100%; font-size:15px; color:#334155;" cellpadding="0" cellspacing="0">')

    h.append('<tr><td style="padding:8px 0; color:#94a3b8; width:140px;">Policy Number</td>')
    h.append('<td style="padding:8px 0; font-weight:700; font-size:17px; color:' + accent + ';">' + (policy_number or "Pending") + "</td></tr>")

    h.append('<tr><td style="padding:6px 0; color:#94a3b8;">Carrier</td>')
    h.append('<td style="padding:6px 0; font-weight:600;">' + info["display_name"] + "</td></tr>")

    if policy_type:
        ptd = policy_type.replace("_", " ").title()
        h.append('<tr><td style="padding:6px 0; color:#94a3b8;">Coverage Type</td>')
        h.append('<td style="padding:6px 0; font-weight:600;">' + ptd + "</td></tr>")

    h.append('<tr><td style="padding:6px 0; color:#94a3b8;">Your Agent</td>')
    h.append('<td style="padding:6px 0; font-weight:600;">' + producer_name + "</td></tr>")

    h.append("</table></div>")

    # ── Carrier-specific section (recognized carriers) ───────────
    if not is_generic:
        h.append('<h2 style="margin:0 0 16px; font-size:18px; color:#1e293b;">Get Started with ' + info["display_name"] + "</h2>")

        h.append('<div style="margin-bottom:16px;">')
        h.append(_btn(info["online_account_url"], accent, "&#127760;", info["online_account_text"]))
        h.append(_btn(info["mobile_app_url"], "#059669", "&#128241;", "Download the " + info["mobile_app_name"]))
        h.append(_btn(info["payment_url"], "#475569", "&#128179;", "Make a Payment"))
        h.append("</div>")

        if info.get("extra_tip"):
            h.append(
                '<p style="color:#64748b; font-size:14px; margin:16px 0; padding:12px 16px;'
                + " background:#f0fdf4; border-radius:8px; border-left:4px solid #22c55e;\">"
                + "&#128161; <strong>Pro Tip:</strong> " + info["extra_tip"] + "</p>"
            )

        # Carrier numbers - PROMINENT
        has_numbers = info.get("claims_phone") or info.get("roadside_phone") or info.get("billing_phone")
        if has_numbers:
            h.append('<div style="margin:24px 0; padding:20px; background:#f8fafc; border-radius:12px; border:1px solid #e2e8f0; border-left:4px solid ' + accent + ';">')
            h.append('<h3 style="margin:0 0 12px; font-size:15px; color:' + accent + '; font-weight:700; letter-spacing:0.5px;">' + info["display_name"].upper() + " CONTACT NUMBERS</h3>")
            h.append('<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
            h.append(_phone_row("Claims", info.get("claims_phone", ""), bold=True))
            h.append(_phone_row("Roadside Assistance", info.get("roadside_phone", ""), bold=True))
            h.append(_phone_row("Billing", info.get("billing_phone", ""), bold=True))
            h.append("</table></div>")

    else:
        # ── Generic BCI email section ────────────────────────────
        h.append('<div style="margin:0 0 20px; padding:20px; background:linear-gradient(135deg, #f0f9ff, #e0f2fe); border-radius:12px; border:1px solid #bae6fd;">')
        h.append('<h2 style="margin:0 0 10px; font-size:18px; color:' + BCI_NAVY + ';">Welcome to the ' + AGENCY_NAME + ' Family!</h2>')
        h.append('<p style="color:#334155; font-size:14px; margin:0; line-height:1.6;">')
        h.append("We are excited to have you as a client! Your new policy with <strong>" + info["display_name"] + "</strong> has been set up successfully. ")
        h.append("As your insurance agency, we are here to help with any questions about your coverage, billing, or claims.")
        h.append("</p></div>")

        h.append('<div style="margin:0 0 20px;">')
        h.append('<h3 style="margin:0 0 12px; font-size:16px; color:#1e293b;">What We Can Help You With</h3>')
        h.append('<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
        h.append('<tr><td style="padding:8px 0; width:28px; color:#64748b; font-size:16px;">&#128196;</td><td style="padding:8px 0;">Policy questions and changes</td></tr>')
        h.append('<tr><td style="padding:8px 0; color:#64748b; font-size:16px;">&#128176;</td><td style="padding:8px 0;">Billing and payment assistance</td></tr>')
        h.append('<tr><td style="padding:8px 0; color:#64748b; font-size:16px;">&#128221;</td><td style="padding:8px 0;">Claims guidance and support</td></tr>')
        h.append('<tr><td style="padding:8px 0; color:#64748b; font-size:16px;">&#128663;</td><td style="padding:8px 0;">Adding vehicles, drivers, or properties</td></tr>')
        h.append('<tr><td style="padding:8px 0; color:#64748b; font-size:16px;">&#128200;</td><td style="padding:8px 0;">Coverage reviews and re-quotes</td></tr>')
        h.append("</table></div>")

        # Contact us button for generic
        h.append('<div style="margin-bottom:16px;">')
        h.append(_btn("tel:8479085665", BCI_NAVY, "&#128222;", "Call Us: " + AGENCY_PHONE))
        h.append("</div>")

    # ── Your Agent section ───────────────────────────────────────
    h.append('<div style="margin:24px 0; padding:16px 20px; background:#fafbfc; border-radius:10px; border:1px solid #e2e8f0;">')
    h.append('<h3 style="margin:0 0 10px; font-size:14px; color:#64748b; font-weight:600; letter-spacing:0.5px;">YOUR AGENT</h3>')
    h.append('<p style="margin:0 0 4px; font-weight:700; font-size:16px; color:#1e293b;">' + producer_name + "</p>")
    h.append('<p style="margin:0 0 2px; font-size:14px; color:#64748b;">' + AGENCY_NAME + "</p>")
    h.append('<p style="margin:0; font-size:14px;">')
    h.append('<a href="tel:8479085665" style="color:' + BCI_CYAN + '; text-decoration:none; font-weight:600;">' + AGENCY_PHONE + "</a>")
    h.append("</p></div>")

    # ── Divider ──────────────────────────────────────────────────
    h.append('<hr style="border:none; border-top:1px solid #e2e8f0; margin:28px 0;">')

    # ── Survey ───────────────────────────────────────────────────
    h.append('<div style="text-align:center; padding:20px; background:linear-gradient(135deg, #f5f3ff, #ede9fe); border-radius:12px;">')
    h.append('<h3 style="margin:0 0 8px; font-size:18px; color:' + BCI_NAVY + ';">How did ' + producer_first + " do?</h3>")
    h.append('<p style="color:#64748b; font-size:14px; margin:0 0 16px;">Your feedback takes just 5 seconds - tap a star below!</p>')
    stars = "".join(_star(survey_url, i) for i in range(1, 6))
    h.append('<div style="margin:0 auto;">' + stars + "</div>")
    h.append("</div>")

    # Close body card
    h.append("</div>")

    # ── Footer ───────────────────────────────────────────────────
    h.append(_agency_footer())

    h.append("</div></body></html>")

    html = "\n".join(h)
    return subject, html


# ── Send via Mailgun ─────────────────────────────────────────────────

def send_welcome_email(
    to_email,
    client_name,
    policy_number,
    carrier,
    producer_name,
    sale_id,
    policy_type=None,
):
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured - skipping welcome email")
        return {"success": False, "error": "Mailgun not configured"}

    if not to_email:
        return {"success": False, "error": "No email address provided"}

    subject, html_body = build_welcome_email_html(
        client_name=client_name,
        policy_number=policy_number,
        carrier=carrier,
        producer_name=producer_name,
        sale_id=sale_id,
        policy_type=policy_type,
    )

    try:
        resp = requests.post(
            "https://api.mailgun.net/v3/" + settings.MAILGUN_DOMAIN + "/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": AGENCY_NAME + " <" + settings.MAILGUN_FROM_EMAIL + ">",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=15,
        )

        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info("Welcome email sent to %s - msg_id: %s", to_email, msg_id)
            return {"success": True, "message_id": msg_id}
        else:
            logger.error("Mailgun error %s: %s", resp.status_code, resp.text)
            return {"success": False, "error": "Mailgun returned " + str(resp.status_code)}
    except Exception as e:
        logger.error("Failed to send welcome email: %s", e)
        return {"success": False, "error": str(e)}
