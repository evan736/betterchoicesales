"""Welcome email service - carrier-specific templates sent via Mailgun.

All emails feature Better Choice Insurance Group branding with
carrier-specific content when available. Generic BCI-branded fallback
for unrecognized carriers.

Agency phone: 847-908-5665 (shown in every email, not prominent)
Carrier numbers shown prominently when available.

Brand colors verified from official brand guidelines and brandfetch.com:
- Progressive: #0053BA (Progressive Blue, Pantone 2935)
- Travelers: #E61616 (Travelers Red, iconic umbrella)
- GEICO: #104293 (Ultramarine blue, text logo)
- Safeco: #1A1446 (Bunting/dark navy, Liberty Mutual subsidiary)
- Hippo: #88B714 (Lime green, insurtech brand)
- National General: #1F3661 (Dark navy, Allstate subsidiary)
- Grange: #00843D (Grange green)
- Integrity: #003DA5 (Blue, Grange subsidiary)
- Branch: #6236FF (Purple/indigo, insurtech)
- Clearcover: #00BFA5 (Teal, insurtech)
- Openly: #FF6B00 (Orange, insurtech)
- Bristol West: #003366 (Navy, Farmers subsidiary)
- Steadily: #6B46C1 (Purple, landlord specialist)
- Gainsco: #C8102E (Red)
- American Modern: #00558C (Blue, Munich Re subsidiary)
- Universal Property: #003087 (Dark blue)
- Next: #0066FF (Bright blue, commercial insurtech)
- CoverTree: #2D8B4E (Green, manufactured home specialist)
"""
import logging
import requests
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Brand constants ──────────────────────────────────────────────────

AGENCY_PHONE = "847-908-5665"
AGENCY_NAME = "Better Choice Insurance Group"

BCI_NAVY = "#1a2b5f"
BCI_DARK = "#162249"
BCI_CYAN = "#2cb5e8"
BCI_LIGHT_CYAN = "#3ec7f5"
BCI_GRADIENT = "linear-gradient(135deg, #1a2b5f 0%, #162249 60%, #0c4a6e 100%)"


# ── Carrier-specific content ─────────────────────────────────────────
# Brand colors verified via official sites, brandfetch.com, schemecolor.com
# Logo URLs point to official carrier websites (publicly accessible)

CARRIER_INFO = {
    "grange": {
        "display_name": "Grange Insurance",
        "accent_color": "#4D9B3A",
        "logo_url": "",
        "mobile_app_url": "https://www.grangeinsurance.com/grange-mobile-app",
        "mobile_app_name": "Grange Mobile App",
        "online_account_url": "https://www.grangeinsurance.com/login",
        "online_account_text": "Log In to Your Grange Account",
        "claims_url": "https://www.grangeinsurance.com/claims/report-or-track-a-claim",
        "claims_phone": "",
        "customer_service": "(800) 425-1100",
        "payment_phone": "(800) 425-1100",
        "payment_url": "https://www.grangeinsurance.com/pay-your-bill",
        "extra_tip": "Download the Grange app for instant access to ID cards, claims filing, and payment options.",
    },
    "integrity": {
        "display_name": "Integrity Insurance",
        "accent_color": "#003DA5",
        "logo_url": "",
        "mobile_app_url": "https://www.integrityinsurance.com/integrity-insurance-mobile-app",
        "mobile_app_name": "Integrity Insurance App",
        "online_account_url": "https://www.integrityinsurance.com/login",
        "online_account_text": "Log In to Your Integrity Account",
        "claims_url": "https://www.integrityinsurance.com/claims/file-a-claim",
        "claims_phone": "",
        "customer_service": AGENCY_PHONE,
        "payment_url": "https://www.integrityinsurance.com/pay-your-bill",
        "extra_tip": "Use the Integrity app to manage your policy, view documents, and file claims on the go.",
    },
    "branch": {
        "display_name": "Branch Insurance",
        "accent_color": "#6B7C3E",
        "logo_url": "",
        "mobile_app_url": "https://play.google.com/store/apps/details?id=com.branch.accountmobile",
        "mobile_app_name": "Branch Insurance App",
        "online_account_url": "https://account.ourbranch.com/",
        "online_account_text": "Log In to Your Branch Account",
        "claims_url": "https://www.ourbranch.com/s/claims",
        "claims_phone": "",
        "customer_service": AGENCY_PHONE,
        "payment_url": "https://account.ourbranch.com/?getHelpNextPath=billing",
        "extra_tip": "The Branch app makes it easy to manage your policy and billing right from your phone.",
    },
    "universal_property": {
        "display_name": "Universal Property and Casualty",
        "accent_color": "#003087",
        "logo_url": "",
        "mobile_app_url": "",
        "mobile_app_name": "",
        "online_account_url": "https://universalproperty.com/account/registration",
        "online_account_text": "Create Your Universal Property Account",
        "claims_url": "https://universalproperty.com/claims/",
        "claims_phone": "",
        "customer_service": AGENCY_PHONE,
        "payment_url": "https://universalproperty.com/account/visitorpayment/",
        "extra_tip": "Set up your online account to view policy documents, make payments, and track claims.",
    },
    "next": {
        "display_name": "Next Insurance",
        "accent_color": "#0066FF",
        "logo_url": "",
        "mobile_app_url": "https://play.google.com/store/apps/details?id=com.nextinsurance",
        "mobile_app_name": "Next Insurance App",
        "online_account_url": "https://app.nextinsurance.com/",
        "online_account_text": "Log In to Your Next Insurance Account",
        "claims_url": "https://www.nextinsurance.com/claim-page/",
        "claims_phone": "",
        "customer_service": AGENCY_PHONE,
        "payment_url": "https://app.nextinsurance.com/",
        "extra_tip": "The Next Insurance app lets you manage your commercial policy and access your certificate of insurance anytime.",
    },
    "hippo": {
        "display_name": "Hippo Insurance",
        "accent_color": "#2CD5A0",
        "logo_url": "",
        "mobile_app_url": "https://play.google.com/store/apps/details?id=com.hippo.insurance",
        "mobile_app_name": "Hippo Insurance App",
        "online_account_url": "https://myhippo.com/account/login",
        "online_account_text": "Log In to Your Hippo Account",
        "claims_url": "https://www.hippo.com/claim",
        "claims_phone": "",
        "customer_service": AGENCY_PHONE,
        "payment_url": "https://myhippo.com/account/login",
        "extra_tip": "Hippo offers smart home monitoring and proactive protection. Check the app for home care tips and alerts.",
    },
    "gainsco": {
        "display_name": "Gainsco Insurance",
        "accent_color": "#C41230",
        "logo_url": "",
        "mobile_app_url": "",
        "mobile_app_name": "",
        "online_account_url": "https://myaccount.gainsco.com/home",
        "online_account_text": "Log In to Your Gainsco Account",
        "claims_url": "https://www.gainsco.com/customers/report-a-claim/",
        "claims_phone": "",
        "customer_service": AGENCY_PHONE,
        "payment_url": "https://www.gainsco.com/customers/make-a-payment/",
        "extra_tip": "Set up your online account to view ID cards, make payments, and manage your policy easily.",
    },
    "steadily": {
        "display_name": "Steadily Insurance",
        "accent_color": "#6B2D8B",
        "logo_url": "",
        "mobile_app_url": "",
        "mobile_app_name": "",
        "online_account_url": "",
        "online_account_text": "",
        "claims_url": "https://www.steadily.com/claims",
        "claims_phone": "888-966-1611",
        "customer_service": "888-966-1611",
        "payment_url": "",
        "extra_tip": "For billing or policy questions, call Steadily directly at 888-966-1611.",
    },
    "geico": {
        "display_name": "GEICO",
        "accent_color": "#104293",
        "logo_url": "",
        "mobile_app_url": "https://www.geico.com/web-and-mobile/mobile-apps/",
        "mobile_app_name": "GEICO Mobile App",
        "online_account_url": "https://www.geico.com/account/",
        "online_account_text": "Log In to Your GEICO Account",
        "claims_url": "https://claims.geico.com/ReportClaim#/",
        "claims_phone": "1-800-207-7847",
        "customer_service": "1-800-932-8872",
        "payment_phone": "1-800-932-8872",
        "payment_url": "https://www.geico.com/information/make-a-payment/",
        "extra_tip": "The GEICO app lets you view ID cards, file claims, request roadside assistance, and manage your policy instantly.",
    },
    "american_modern": {
        "display_name": "American Modern Insurance",
        "accent_color": "#00A94F",
        "logo_url": "",
        "mobile_app_url": "",
        "mobile_app_name": "",
        "online_account_url": "https://policyholders.amig.com/content/munichre/amiggrp/policy-holder/account-access/en/create-account/landing-page.html",
        "online_account_text": "Create Your American Modern Account",
        "claims_url": "https://myclaim.amig.com/",
        "claims_phone": "1-800-543-2644",
        "customer_service": "1-800-543-2644",
        "payment_url": "",
        "extra_tip": "Set up your online account to manage your specialty insurance policy and file claims easily.",
    },
    "progressive": {
        "display_name": "Progressive Insurance",
        "accent_color": "#0053BA",
        "logo_url": "",
        "mobile_app_url": "https://www.progressive.com/mobile-app/",
        "mobile_app_name": "Progressive App",
        "online_account_url": "https://www.progressive.com/manage-policy/",
        "online_account_text": "Manage Your Progressive Policy",
        "claims_url": "https://www.progressive.com/claims/",
        "claims_phone": "1-800-687-5581",
        "customer_service": "1-800-687-5581",
        "payment_url": "https://account.apps.progressive.com/access/ez-payment/policy-info",
        "extra_tip": "Download the Progressive app to get your digital ID card, track claims, and manage your policy.",
    },
    "clearcover": {
        "display_name": "Clearcover Insurance",
        "accent_color": "#4834D4",
        "logo_url": "",
        "mobile_app_url": "https://clearcover.com/app/",
        "mobile_app_name": "Clearcover App",
        "online_account_url": "https://clearcover.com/app/",
        "online_account_text": "Log In to Your Clearcover Account",
        "claims_url": "https://support.clearcover.com/hc/en-us/articles/360046229514-Filing-a-claim",
        "claims_phone": "1-855-444-1875",
        "customer_service": "1-855-444-1875",
        "payment_url": "https://clearcover.com/app/",
        "extra_tip": "Use the Clearcover app to manage payments, view your ID card, and file claims quickly.",
    },
    "safeco": {
        "display_name": "Safeco Insurance",
        "accent_color": "#1A3054",
        "logo_url": "",
        "mobile_app_url": "https://www.safeco.com/customer-resources/mobile-voice-apps/safeco-mobile-app",
        "mobile_app_name": "Safeco Mobile App",
        "online_account_url": "https://www.safeco.com/homepage/returning",
        "online_account_text": "Log In to Your Safeco Account",
        "claims_url": "https://www.safeco.com/claims",
        "claims_phone": "1-866-272-3326",
        "customer_service": "1-866-272-3326",
        "payment_url": "https://customer.safeco.com/accountmanager/billing/guest-payment?view=customerSearch",
        "extra_tip": "The Safeco app lets you view ID cards, file claims, and contact roadside assistance instantly.",
    },
    "travelers": {
        "display_name": "Travelers Insurance",
        "accent_color": "#E31937",
        "logo_url": "",
        "mobile_app_url": "https://pages.travelers.com/MyTravelersApp_Redirect",
        "mobile_app_name": "MyTravelers App",
        "online_account_url": "https://signin.travelers.com/",
        "online_account_text": "Log In to Your Travelers Account",
        "claims_url": "https://www.travelers.com/claims/file-claim",
        "claims_phone": "1-866-933-7287",
        "customer_service": "1-866-933-7287",
        "payment_url": "https://personal.travelers.com/paybill/#/findAccount?flow=otp",
        "extra_tip": "With MyTravelers, you can view policy documents, report claims, and manage billing all in one place.",
    },
    "national_general": {
        "display_name": "National General Insurance",
        "accent_color": "#1B5FAA",
        "logo_url": "",
        "mobile_app_url": "https://nationalgeneral.com/policyholders/mobileapp/",
        "mobile_app_name": "National General App",
        "online_account_url": "https://nationalgeneral.com/policyholders/my-policy/",
        "online_account_text": "Log In to Your National General Account",
        "claims_url": "https://claims.nationalgeneral.com/report",
        "claims_phone": "1-877-468-3466",
        "customer_service": "1-877-468-3466",
        "payment_url": "https://mynatgenpolicy.com/pay",
        "extra_tip": "You can manage your policy, view ID cards, and make payments right from the National General app.",
    },
    "openly": {
        "display_name": "Openly Insurance",
        "accent_color": "#7B5EA7",
        "logo_url": "",
        "mobile_app_url": "",
        "mobile_app_name": "",
        "online_account_url": "",
        "online_account_text": "",
        "claims_url": "https://fnol.openly.com/file-a-claim/intro",
        "claims_phone": "1-888-808-4842",
        "customer_service": "1-888-808-4842",
        "payment_url": "",
        "extra_tip": "For policy questions, billing, or to file a claim, call Openly at 1-888-808-4842.",
    },
    "bristol_west": {
        "display_name": "Bristol West Insurance",
        "accent_color": "#003B8E",
        "logo_url": "",
        "mobile_app_url": "https://play.google.com/store/apps/details?id=com.bristolwest.app",
        "mobile_app_name": "Bristol West App",
        "online_account_url": "https://www.bristolwest.com/css/login",
        "online_account_text": "Log In to Your Bristol West Account",
        "claims_url": "https://www.bristolwest.com/home/claims/",
        "claims_phone": "1-888-888-0080",
        "customer_service": "1-888-888-0080",
        "payment_url": "https://www.bristolwest.com/payments/",
        "extra_tip": "Download the Bristol West app to view your ID card, make payments, and manage your policy.",
    },
    "covertree": {
        "display_name": "CoverTree Insurance",
        "accent_color": "#007A5E",
        "logo_url": "",
        "mobile_app_url": "",
        "mobile_app_name": "",
        "online_account_url": "https://residents.covertree.com/auth/login",
        "online_account_text": "Log In to Your CoverTree Account",
        "claims_url": "https://www.covertree.com/claims/",
        "claims_phone": "877-417-8733",
        "customer_service": "877-417-8733",
        "payment_url": "",
        "extra_tip": "Log in to your CoverTree account to manage your manufactured home policy and file claims.",
    },
}

# ── Carrier aliases ──────────────────────────────────────────────────

CARRIER_ALIASES = {
    "trustgard": "grange",
    "trustgard_insurance": "grange",
    "trust_gard": "grange",
    "trustgard_mutual": "grange",
    "universal_property_and_casualty": "universal_property",
    "universal_property_casualty": "universal_property",
    "upcic": "universal_property",
    "next_insurance": "next",
    "hippo_insurance": "hippo",
    "gainsco_auto": "gainsco",
    "american_modern_insurance": "american_modern",
    "amig": "american_modern",
    "clearcover_insurance": "clearcover",
    "openly_insurance": "openly",
    "bristol_west_insurance": "bristol_west",
    "covertree_insurance": "covertree",
    "cover_tree": "covertree",
    "geico_insurance": "geico",
    "steadily_insurance": "steadily",
    "obsidian": "steadily",
    "obsedian": "steadily",
    "obsidian_insurance": "steadily",
    "obsedian_insurance": "steadily",
    "integon": "national_general",
    "integon_national": "national_general",
    "integon_national_insurance": "national_general",
    "integon_national_insurance_company": "national_general",
    "integrity_insurance": "integrity",
    "branch_insurance": "branch",
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
    """BCI logo for email header - PNG image on dark background."""
    app_url = "https://better-choice-web.onrender.com"
    try:
        from app.core.config import settings as _s
        app_url = getattr(_s, "APP_URL", app_url)
    except Exception:
        pass
    logo_url = app_url + "/carrier-logos/bci_header_white.png"
    return (
        '<div style="text-align:center;">'
        '<img src="' + logo_url + '" alt="Better Choice Insurance Group"'
        ' style="max-height:56px; width:auto; height:auto;" />'
        '</div>'
    )


def _carrier_logo_html(info, carrier_key):
    """Carrier logo image tag using self-hosted logos."""
    display = info.get("display_name", "")
    accent = info.get("accent_color", BCI_NAVY)

    # Map carrier keys to their logo filenames hosted on the frontend
    LOGO_FILES = {
        "grange": "grange.png",
        "integrity": "integrity.png",
        "branch": "branch.png",
        "universal_property": "universal_property.png",
        "next": "next.png",
        "hippo": "hippo.png",
        "gainsco": "gainsco.png",
        "steadily": "steadily.png",
        "geico": "geico.png",
        "american_modern": "american_modern.png",
        "progressive": "progressive.png",
        "clearcover": "clearcover.png",
        "safeco": "safeco.png",
        "travelers": "travelers.png",
        "national_general": "national_general.png",
        "openly": "openly.png",
        "bristol_west": "bristol_west.png",
        "covertree": "covertree.png",
    }

    logo_file = LOGO_FILES.get(carrier_key, "")
    if logo_file:
        app_url = getattr(settings, "APP_URL", "https://better-choice-web.onrender.com")
        logo_url = app_url + "/carrier-logos/" + logo_file
        return (
            '<div style="text-align:center; margin:0 0 20px; padding:16px;">'
            '<img src="' + logo_url + '" alt="' + display
            + '" style="max-height:60px; max-width:280px; height:auto; width:auto;" />'
            '</div>'
        )
    else:
        return (
            '<div style="text-align:center; margin:0 0 20px; padding:16px;">'
            '<span style="font-size:22px; font-weight:800; color:' + accent + ';">'
            + display + '</span>'
            '</div>'
        )


def _agency_footer():
    """Agency footer with phone - subtle, not prominent."""
    app_url = "https://better-choice-web.onrender.com"
    try:
        from app.core.config import settings as _s
        app_url = getattr(_s, "APP_URL", app_url)
    except Exception:
        pass
    footer_url = app_url + "/carrier-logos/bci_footer.png"
    return (
        '<div style="text-align:center; padding:24px 20px; color:#94a3b8; font-size:12px;">'
        '<div style="margin:0 auto 8px;">'
        '<img src="' + footer_url + '" alt="Better Choice Insurance Group"'
        ' style="max-height:36px; width:auto; height:auto;" />'
        '</div>'
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
            "logo_url": "",
            "mobile_app_url": "",
            "mobile_app_name": "",
            "online_account_url": "",
            "online_account_text": "",
            "claims_url": "",
            "claims_phone": "",
            "customer_service": "",
            "payment_url": "",
            "extra_tip": "",
        }

    app_url = getattr(settings, "APP_URL", "https://better-choice-web.onrender.com")
    survey_url = app_url + "/survey/" + str(sale_id)
    first_name = client_name.split()[0] if client_name else "Valued Customer"
    producer_first = producer_name.split()[0] if producer_name else "Your Agent"

    if is_generic:
        subject = "Welcome to " + AGENCY_NAME + "! Your new policy is ready"
    else:
        subject = "Welcome to " + info["display_name"] + "! Your policy is ready"

    accent = info.get("accent_color", BCI_NAVY)

    h = []
    h.append('<!DOCTYPE html><html><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    h.append("</head>")
    h.append('<body style="margin:0; padding:0; background-color:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">')

    # Hidden preheader text - prevents email clients from showing BCI logo dots as preview
    if is_generic:
        preheader = "Your new policy is all set! Here's everything you need to get started with " + AGENCY_NAME + "."
    else:
        preheader = "Your " + info["display_name"] + " policy is all set! Here's everything you need to get started."
    h.append('<div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">' + preheader + '</div>')
    h.append('<div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">' + '&nbsp;' * 80 + '</div>')

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

    # ── Carrier logo ─────────────────────────────────────────────
    if not is_generic:
        h.append(_carrier_logo_html(info, carrier_key))
    else:
        # BCI logo for generic emails
        dark_logo_url = app_url + "/carrier-logos/bci_header_dark.png"
        h.append(
            '<div style="text-align:center; margin:0 0 20px; padding:20px;">'
            '<img src="' + dark_logo_url + '" alt="Better Choice Insurance Group"'
            ' style="max-height:56px; width:auto; height:auto;" />'
            "</div>"
        )

    # ── Policy details card (no agent row) ───────────────────────
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
    h.append("</table></div>")

    # ── Carrier-specific section ─────────────────────────────────
    if not is_generic:
        h.append('<h2 style="margin:0 0 16px; font-size:18px; color:#1e293b;">Get Started with ' + info["display_name"] + "</h2>")

        h.append('<div style="margin-bottom:16px;">')
        h.append(_btn(info.get("online_account_url", ""), accent, "&#127760;", info.get("online_account_text", "Set Up Your Account")))
        if info.get("mobile_app_url"):
            h.append(_btn(info["mobile_app_url"], "#059669", "&#128241;", "Download the " + info["mobile_app_name"]))
        h.append(_btn(info.get("payment_url", ""), "#475569", "&#128179;", "Make a Payment"))
        if info.get("claims_url"):
            h.append(_btn(info["claims_url"], "#dc2626", "&#128221;", "File a Claim"))
        h.append("</div>")

        if info.get("extra_tip"):
            h.append(
                '<p style="color:#64748b; font-size:14px; margin:16px 0; padding:12px 16px;'
                + " background:#f0fdf4; border-radius:8px; border-left:4px solid #22c55e;\">"
                + "&#128161; <strong>Pro Tip:</strong> " + info["extra_tip"] + "</p>"
            )

        # Carrier contact numbers - PROMINENT
        has_numbers = info.get("claims_phone") or info.get("customer_service") or info.get("payment_phone")
        if has_numbers:
            h.append('<div style="margin:24px 0; padding:20px; background:#f8fafc; border-radius:12px; border:1px solid #e2e8f0; border-left:4px solid ' + accent + ';">')
            h.append('<h3 style="margin:0 0 12px; font-size:15px; color:' + accent + '; font-weight:700; letter-spacing:0.5px;">' + info["display_name"].upper() + " CONTACT</h3>")
            h.append('<table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">')
            if info.get("payment_phone"):
                h.append(_phone_row("Make a Payment", info["payment_phone"], bold=True))
            if info.get("claims_phone"):
                h.append(_phone_row("Claims", info["claims_phone"], bold=True))
            cs = info.get("customer_service", "")
            if cs and cs != AGENCY_PHONE and cs != info.get("payment_phone", ""):
                h.append(_phone_row("Customer Service", cs, bold=True))
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

    h.append('<hr style="border:none; border-top:1px solid #e2e8f0; margin:28px 0;">')

    # ── Survey ───────────────────────────────────────────────────
    h.append('<div style="text-align:center; padding:20px; background:linear-gradient(135deg, #f5f3ff, #ede9fe); border-radius:12px;">')
    h.append('<h3 style="margin:0 0 8px; font-size:18px; color:' + BCI_NAVY + ';">How did ' + producer_first + " do?</h3>")
    h.append('<p style="color:#64748b; font-size:14px; margin:0 0 16px;">Your feedback takes just 5 seconds - tap a star below!</p>')
    stars = "".join(_star(survey_url, i) for i in range(1, 6))
    h.append('<div style="margin:0 auto;">' + stars + "</div>")
    h.append("</div>")

    h.append("</div>")
    h.append(_agency_footer())
    h.append("</div></body></html>")

    return subject, "\n".join(h)


# ── Send via Mailgun ─────────────────────────────────────────────────

def send_welcome_email(
    to_email,
    client_name,
    policy_number,
    carrier,
    producer_name,
    sale_id,
    policy_type=None,
    producer_email=None,
    attachment=None,
):
    """Send welcome email via Mailgun.

    attachment: optional tuple of (filename, bytes) to attach a PDF.
    """
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

    mail_data = {
        "from": AGENCY_NAME + " <" + settings.MAILGUN_FROM_EMAIL + ">",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }

    # BCC the selling agent + agency owner on all welcome emails
    bcc_list = ["evan@betterchoiceins.com"]
    cc_enabled = getattr(settings, "WELCOME_EMAIL_CC_AGENT", False)
    if cc_enabled and producer_email:
        bcc_list.append(producer_email)
        logger.info("BCC'ing agent %s on welcome email to %s", producer_email, to_email)
    mail_data["bcc"] = bcc_list
    logger.info("BCC list for welcome email to %s: %s", to_email, bcc_list)

    # Optional PDF attachment
    files = None
    if attachment:
        att_name, att_bytes = attachment
        files = [("attachment", (att_name, att_bytes, "application/pdf"))]
        logger.info("Attaching %s (%d bytes) to welcome email", att_name, len(att_bytes))

    try:
        resp = requests.post(
            "https://api.mailgun.net/v3/" + settings.MAILGUN_DOMAIN + "/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            files=files,
            timeout=30,
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
