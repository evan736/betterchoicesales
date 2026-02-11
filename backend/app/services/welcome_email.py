"""Welcome email service — carrier-specific templates sent via Mailgun."""
import logging
import requests
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Carrier-specific content ──────────────────────────────────────────

CARRIER_INFO = {
    "national_general": {
        "display_name": "National General Insurance",
        "logo_color": "#003366",
        "mobile_app_url": "https://www.nationalgeneral.com/about/mobile-app",
        "mobile_app_name": "National General Insurance App",
        "online_account_url": "https://www.nationalgeneral.com/manage-your-policy",
        "online_account_text": "Set Up Your Online Account",
        "claims_phone": "1-800-325-1088",
        "roadside_phone": "1-877-468-3466",
        "payment_url": "https://www.nationalgeneral.com/make-a-payment",
        "extra_tip": "You can manage your policy, view ID cards, and make payments right from the app.",
    },
    "progressive": {
        "display_name": "Progressive Insurance",
        "logo_color": "#0033A0",
        "mobile_app_url": "https://www.progressive.com/app/",
        "mobile_app_name": "Progressive App",
        "online_account_url": "https://www.progressive.com/register/",
        "online_account_text": "Create Your Progressive Account",
        "claims_phone": "1-800-776-4737",
        "roadside_phone": "1-800-776-4737",
        "payment_url": "https://www.progressive.com/pay-bill/",
        "extra_tip": "Download the Progressive app to get your digital ID card, track claims, and manage your policy.",
    },
    "safeco": {
        "display_name": "Safeco Insurance",
        "logo_color": "#00529B",
        "mobile_app_url": "https://www.safeco.com/about/mobile",
        "mobile_app_name": "Safeco Mobile App",
        "online_account_url": "https://www.safeco.com/manage-your-policy",
        "online_account_text": "Set Up Your Safeco Account",
        "claims_phone": "1-800-332-3226",
        "roadside_phone": "1-877-762-3101",
        "payment_url": "https://www.safeco.com/manage-your-policy",
        "extra_tip": "The Safeco app lets you view ID cards, file claims, and contact roadside assistance instantly.",
    },
    "travelers": {
        "display_name": "Travelers Insurance",
        "logo_color": "#E31837",
        "mobile_app_url": "https://www.travelers.com/tools-resources/apps/mytravelers",
        "mobile_app_name": "MyTravelers App",
        "online_account_url": "https://www.travelers.com/online-account-access",
        "online_account_text": "Create Your MyTravelers Account",
        "claims_phone": "1-800-252-4633",
        "roadside_phone": "1-800-252-4633",
        "payment_url": "https://www.travelers.com/pay-your-bill",
        "extra_tip": "With MyTravelers, you can view policy documents, report claims, and manage billing all in one place.",
    },
    "grange": {
        "display_name": "Grange Insurance",
        "logo_color": "#1B5E20",
        "mobile_app_url": "https://www.grangeinsurance.com/manage-your-policy/download-our-app",
        "mobile_app_name": "Grange Mobile App",
        "online_account_url": "https://www.grangeinsurance.com/manage-your-policy",
        "online_account_text": "Set Up Your Grange Online Account",
        "claims_phone": "1-800-445-3030",
        "roadside_phone": "1-800-445-3030",
        "payment_url": "https://www.grangeinsurance.com/manage-your-policy/pay-my-bill",
        "extra_tip": "The Grange app gives you instant access to ID cards, claims filing, and payment options.",
    },
}


def _get_carrier_key(carrier: str) -> Optional[str]:
    """Normalize carrier name to our key."""
    if not carrier:
        return None
    c = carrier.lower().replace(" ", "_").replace("-", "_")
    # Try exact match first
    if c in CARRIER_INFO:
        return c
    # Try partial matches
    for key in CARRIER_INFO:
        if key in c or c in key:
            return key
    return None


def build_welcome_email_html(
    client_name: str,
    policy_number: str,
    carrier: str,
    producer_name: str,
    sale_id: int,
    policy_type: Optional[str] = None,
) -> tuple[str, str]:
    """Build the welcome email HTML and subject line.
    
    Returns: (subject, html_body)
    """
    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key or "", None)
    
    # Fallback for unknown carriers
    if not info:
        info = {
            "display_name": carrier or "Your Insurance",
            "logo_color": "#374151",
            "mobile_app_url": "",
            "mobile_app_name": "",
            "online_account_url": "",
            "online_account_text": "Set Up Your Online Account",
            "claims_phone": "",
            "roadside_phone": "",
            "payment_url": "",
            "extra_tip": "",
        }

    survey_url = f"{settings.APP_URL}/survey/{sale_id}"
    first_name = client_name.split()[0] if client_name else "Valued Customer"
    
    policy_type_display = ""
    if policy_type:
        policy_type_display = policy_type.replace("_", " ").title()
    
    subject = f"Welcome to {info['display_name']}! Your policy is ready 🎉"
    
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:20px;">
  
  <!-- Header -->
  <div style="background: linear-gradient(135deg, {info['logo_color']}, #1e293b); border-radius:16px 16px 0 0; padding:32px 24px; text-align:center;">
    <h1 style="color:#ffffff; margin:0; font-size:28px; font-weight:700;">Welcome, {first_name}! 🎉</h1>
    <p style="color:rgba(255,255,255,0.85); margin:8px 0 0; font-size:16px;">Your {info['display_name']} policy is all set</p>
  </div>
  
  <!-- Body -->
  <div style="background:#ffffff; padding:32px 24px; border-radius:0 0 16px 16px; box-shadow:0 4px 6px rgba(0,0,0,0.05);">
    
    <!-- Policy Info Card -->
    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:20px; margin-bottom:24px;">
      <h2 style="margin:0 0 12px; font-size:16px; color:#64748b; font-weight:600;">YOUR POLICY DETAILS</h2>
      <table style="width:100%; font-size:15px; color:#334155;">
        <tr>
          <td style="padding:6px 0; color:#94a3b8; width:140px;">Policy Number</td>
          <td style="padding:6px 0; font-weight:700; font-size:17px; color:{info['logo_color']};">{policy_number}</td>
        </tr>
        <tr>
          <td style="padding:6px 0; color:#94a3b8;">Carrier</td>
          <td style="padding:6px 0; font-weight:600;">{info['display_name']}</td>
        </tr>
        {f'<tr><td style="padding:6px 0; color:#94a3b8;">Coverage Type</td><td style="padding:6px 0; font-weight:600;">{policy_type_display}</td></tr>' if policy_type_display else ''}
        <tr>
          <td style="padding:6px 0; color:#94a3b8;">Your Agent</td>
          <td style="padding:6px 0; font-weight:600;">{producer_name}</td>
        </tr>
      </table>
    </div>
    
    <!-- Getting Started -->
    <h2 style="margin:0 0 16px; font-size:18px; color:#1e293b;">Get Started with {info['display_name']}</h2>
    
    <!-- Action Buttons -->
    <div style="margin-bottom:12px;">
      {f"""
      <a href="{info['online_account_url']}" style="display:block; background:{info['logo_color']}; color:#ffffff; padding:14px 24px; border-radius:10px; text-decoration:none; font-weight:600; font-size:15px; text-align:center; margin-bottom:10px;">
        🌐 {info['online_account_text']}
      </a>
      """ if info['online_account_url'] else ""}
      
      {f"""
      <a href="{info['mobile_app_url']}" style="display:block; background:#059669; color:#ffffff; padding:14px 24px; border-radius:10px; text-decoration:none; font-weight:600; font-size:15px; text-align:center; margin-bottom:10px;">
        📱 Download the {info['mobile_app_name']}
      </a>
      """ if info['mobile_app_url'] else ""}
      
      {f"""
      <a href="{info['payment_url']}" style="display:block; background:#475569; color:#ffffff; padding:14px 24px; border-radius:10px; text-decoration:none; font-weight:600; font-size:15px; text-align:center; margin-bottom:10px;">
        💳 Make a Payment
      </a>
      """ if info['payment_url'] else ""}
    </div>
    
    {f'<p style="color:#64748b; font-size:14px; margin:16px 0; padding:12px 16px; background:#f0fdf4; border-radius:8px; border-left:4px solid #22c55e;">💡 <strong>Pro Tip:</strong> {info["extra_tip"]}</p>' if info.get("extra_tip") else ""}
    
    <!-- Important Numbers -->
    <div style="margin:24px 0; padding:16px; background:#fafbfc; border-radius:10px; border:1px solid #e2e8f0;">
      <h3 style="margin:0 0 10px; font-size:14px; color:#64748b; font-weight:600;">IMPORTANT NUMBERS</h3>
      <table style="width:100%; font-size:14px; color:#334155;">
        {f'<tr><td style="padding:4px 0; color:#94a3b8;">Claims</td><td style="padding:4px 0; font-weight:600;">{info["claims_phone"]}</td></tr>' if info.get("claims_phone") else ''}
        {f'<tr><td style="padding:4px 0; color:#94a3b8;">Roadside Assistance</td><td style="padding:4px 0; font-weight:600;">{info["roadside_phone"]}</td></tr>' if info.get("roadside_phone") else ''}
        <tr><td style="padding:4px 0; color:#94a3b8;">Your Agent</td><td style="padding:4px 0; font-weight:600;">{producer_name} at Better Choice Insurance</td></tr>
      </table>
    </div>
    
    <!-- Divider -->
    <hr style="border:none; border-top:1px solid #e2e8f0; margin:28px 0;">
    
    <!-- Survey CTA -->
    <div style="text-align:center; padding:20px; background:#faf5ff; border-radius:12px;">
      <h3 style="margin:0 0 8px; font-size:18px; color:#7c3aed;">How did {producer_name.split()[0]} do?</h3>
      <p style="color:#64748b; font-size:14px; margin:0 0 16px;">Your feedback takes just 5 seconds — tap a star below!</p>
      <div style="margin:0 auto;">
        <a href="{survey_url}?rating=1" style="text-decoration:none; font-size:32px; padding:0 4px;">⭐</a>
        <a href="{survey_url}?rating=2" style="text-decoration:none; font-size:32px; padding:0 4px;">⭐</a>
        <a href="{survey_url}?rating=3" style="text-decoration:none; font-size:32px; padding:0 4px;">⭐</a>
        <a href="{survey_url}?rating=4" style="text-decoration:none; font-size:32px; padding:0 4px;">⭐</a>
        <a href="{survey_url}?rating=5" style="text-decoration:none; font-size:32px; padding:0 4px;">⭐</a>
      </div>
    </div>
    
  </div>
  
  <!-- Footer -->
  <div style="text-align:center; padding:24px 0; color:#94a3b8; font-size:12px;">
    <p style="margin:4px 0;">Better Choice Insurance</p>
    <p style="margin:4px 0;">Thank you for choosing us!</p>
  </div>
  
</div>
</body>
</html>"""
    
    return subject, html


def send_welcome_email(
    to_email: str,
    client_name: str,
    policy_number: str,
    carrier: str,
    producer_name: str,
    sale_id: int,
    policy_type: Optional[str] = None,
) -> dict:
    """Send the carrier-specific welcome email via Mailgun.
    
    Returns dict with success status and message_id.
    """
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping welcome email")
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
        response = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"{settings.MAILGUN_FROM_NAME} <{settings.MAILGUN_FROM_EMAIL}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=15,
        )
        
        if response.status_code == 200:
            msg_id = response.json().get("id", "")
            logger.info(f"Welcome email sent to {to_email} (policy {policy_number}) — msg_id: {msg_id}")
            return {"success": True, "message_id": msg_id}
        else:
            logger.error(f"Mailgun error {response.status_code}: {response.text}")
            return {"success": False, "error": f"Mailgun returned {response.status_code}"}
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        return {"success": False, "error": str(e)}
