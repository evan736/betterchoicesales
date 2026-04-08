"""Quote Follow-Up Email Service — branded follow-up emails after quote delivery.

Sends timed follow-up emails to prospects who received a quote but haven't bound yet.
Automatically stops if:
- Customer has a matching sale in the system (policy bound)
- Follow-ups are manually disabled on the quote
- Customer clicked "I'm Ready to Bind"

Schedule:
- Day 3: Gentle check-in
- Day 7: Value reminder with urgency
- Day 14: Final follow-up with expiration warning
"""
import logging
import os
import requests
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)

AGENCY_NAME = "Better Choice Insurance Group"
PHONE = "(847) 908-5665"


def _has_matching_sale(db, prospect_name: str, prospect_email: str, carrier: str, policy_number: str = "") -> bool:
    """Check if this prospect already has a sale in the system — don't follow up if they've already bought."""
    from app.models.sale import Sale
    from sqlalchemy import func, or_

    if not prospect_name and not prospect_email:
        return False

    filters = []
    if prospect_email:
        filters.append(func.lower(Sale.client_email) == prospect_email.lower())
    if prospect_name:
        filters.append(func.lower(Sale.client_name) == prospect_name.strip().lower())

    if not filters:
        return False

    match = db.query(Sale).filter(or_(*filters)).first()
    return match is not None


def build_followup_email(
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: float,
    premium_term: str,
    agent_name: str,
    agent_email: str,
    quote_id: int,
    day: int,
) -> tuple:
    """Build follow-up email subject + HTML for the given day."""
    first_name = prospect_name.split()[0] if prospect_name else "there"
    carrier_display = (carrier or "").replace("_", " ").title()

    # Calculate monthly
    monthly = ""
    try:
        months_map = {"6 months": 6, "12 months": 12, "annual": 12, "monthly": 1}
        months = months_map.get(premium_term, 6)
        if months > 1 and premium > 0:
            monthly = f"${premium / months:,.2f}/mo"
    except Exception:
        pass

    premium_display = f"${premium:,.2f}" if premium else ""
    agent_first = agent_name.split()[0] if agent_name else "Your agent"

    if day == 3:
        subject = f"Quick check-in — did you get a chance to review your {carrier_display} quote?"
        intro = f"I wanted to follow up on the {carrier_display} quote I sent over. I know life gets busy, so I just wanted to make sure you had a chance to review it."
        cta_text = "Review My Quote"
        closing = "If you have any questions about the coverage or want to adjust anything, just reply to this email or give me a call. I'm happy to walk through it with you."
    elif day == 7:
        subject = f"{first_name}, your {carrier_display} quote is still available — {monthly or premium_display}"
        intro = f"Just a friendly reminder that your {carrier_display} quote is still waiting for you. Insurance rates can change at any time, so I'd hate for you to miss out on this rate."
        cta_text = "Lock In My Rate"
        closing = "If you've found coverage elsewhere, no worries at all — just let me know and I'll close this out. Otherwise, I'm here whenever you're ready to move forward."
    elif day == 14:
        subject = f"Last follow-up — your {carrier_display} quote expires soon"
        intro = f"This is my final check-in on your {carrier_display} quote. Rates are only guaranteed for a limited time, and I want to make sure you don't lose this pricing."
        cta_text = "I'm Ready — Let's Do This"
        closing = "After this, I won't send any more follow-ups — but my door is always open. You can reach me anytime at the number below. I'd love to help you get covered."
    elif day == "bind_retarget":
        subject = f"{first_name} — we still need a few things to finalize your {carrier_display} policy"
        intro = f"I noticed you expressed interest in moving forward with your {carrier_display} quote, but we haven't been able to finalize everything yet. I want to make sure nothing fell through the cracks on our end."
        cta_text = "Let's Finish This Up"
        closing = "Sometimes all it takes is a quick 5-minute call to get everything wrapped up. Reply to this email, give me a call, or click the button above and I'll take care of the rest. I don't want you to go without coverage!"
    elif day == 30:
        subject = f"{first_name}, are you still looking for insurance?"
        intro = f"It's been about a month since I sent over your {carrier_display} quote. I know finding the right insurance can take time, and I wanted to check in to see if your situation has changed or if I can help in any way."
        cta_text = "Get a Fresh Quote"
        closing = f"Rates change frequently, so if you'd like me to re-run your numbers with the latest pricing, I'm happy to do that — no obligation. Just reply to this email or give me a call at {PHONE}."
    elif day == 60:
        subject = f"Still shopping for insurance, {first_name}? Let me help"
        intro = f"I hope you're doing well! I wanted to reach out one more time in case you're still looking for coverage. As an independent agency, we work with 15+ carriers, so even if {carrier_display} wasn't the right fit, I may be able to find something better."
        cta_text = "Shop My Rates Again"
        closing = "If you've already found coverage elsewhere, congratulations — and no need to reply. But if you're still shopping or your situation has changed, I'd love to help. We often find savings people didn't expect."
    elif day == 90:
        subject = f"{first_name} — one last check-in from Better Choice Insurance"
        intro = f"This is my final follow-up for now. It's been about 3 months since your original quote, and I wanted to make one last offer to help before I step back for a while."
        cta_text = "Yes, I Still Need Coverage"
        closing = f"If you ever need insurance down the road — whether it's home, auto, or anything else — my door is always open. You can reach me anytime at {PHONE} or just reply to this email. Wishing you all the best!"
    elif day == 180:
        subject = f"{first_name} — it's been a while! Let's see if we can save you money"
        intro = f"It's been about 6 months since we last connected, and a lot can change in that time — rates, carriers, your coverage needs. As an independent agency with 15+ carriers, I'd love to take another look and see if I can find you a better deal than what you have today."
        cta_text = "Get a Fresh Quote — No Obligation"
        closing = f"Even if you found coverage elsewhere, rates shift constantly and we often save people hundreds by re-shopping. It only takes a few minutes — just reply to this email, call me at {PHONE}, or click above. No pressure either way!"
    elif day == "remarket_quarterly":
        subject = f"{first_name}, rates have changed — time for a free insurance check-up?"
        intro = f"Just a quick note from your friends at Better Choice Insurance! Insurance rates change every quarter, and I wanted to reach out in case now is a better time to look at your options. Whether you're paying too much or just want to make sure you have the right coverage, I'm here to help."
        cta_text = "Check My Rates — Free & Easy"
        closing = f"We work with 15+ top carriers so we can shop the market for you in minutes. No cost, no obligation — just honest advice. Reply here, call {PHONE}, or click above whenever you're ready."
    else:
        return None, None

    bind_url = f"https://better-choice-api.onrender.com/api/bind/{quote_id}"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:20px;">

  <div style="background:linear-gradient(135deg, #1a2b5f 0%, #162249 60%, #0c4a6e 100%); padding:24px 32px; border-radius:12px 12px 0 0; text-align:center;">
    <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="{AGENCY_NAME}" width="200" style="display:block; margin:0 auto; max-width:200px; height:auto;" />
  </div>

  <div style="background:white; padding:32px; border-radius:0 0 12px 12px; border:1px solid #e2e8f0; border-top:none;">

    <p style="color:#1e293b; font-size:16px; margin:0 0 16px;">Hi {first_name},</p>

    <p style="color:#334155; font-size:14px; line-height:1.6; margin:0 0 20px;">{intro}</p>

    <div style="background:linear-gradient(135deg, #1B5FAA12, #1B5FAA08); border:2px solid #1B5FAA40; border-radius:12px; padding:20px; margin:20px 0; text-align:center;">
      <p style="margin:0 0 4px; color:#64748b; font-size:12px; text-transform:uppercase; letter-spacing:1.5px; font-weight:600;">Your {carrier_display} Quote</p>
      <p style="margin:0; color:#1e293b; font-size:36px; font-weight:800;">{premium_display}</p>
      <p style="margin:4px 0 0; color:#64748b; font-size:14px;">{premium_term}</p>
      {f'<p style="margin:4px 0 0; color:#94a3b8; font-size:13px;">{monthly}</p>' if monthly else ""}
    </div>

    <p style="color:#334155; font-size:14px; line-height:1.6; margin:0 0 24px;">{closing}</p>

    <div style="text-align:center; margin:24px 0;">
      <a href="{bind_url}" style="display:inline-block; background:#1B5FAA; color:white; padding:14px 36px; border-radius:8px; text-decoration:none; font-weight:700; font-size:15px;">
        {cta_text}
      </a>
    </div>

    <div style="text-align:center; margin:0 0 20px;">
      <a href="tel:8479085665" style="color:#1B5FAA; font-size:13px; text-decoration:none;">
        Or call us at {PHONE}
      </a>
    </div>

    <div style="background:#f8fafc; border-radius:8px; padding:16px; margin:20px 0; border:1px solid #e2e8f0;">
      <p style="margin:0 0 4px; font-size:12px; color:#64748b; text-transform:uppercase; letter-spacing:1px; font-weight:600;">Your Insurance Advisor</p>
      <p style="margin:0; font-size:15px; font-weight:bold; color:#1e293b;">{agent_name or 'Better Choice Insurance Team'}</p>
      <p style="margin:2px 0 0; font-size:13px; color:#64748b;">{agent_email or 'service@betterchoiceins.com'} · {PHONE}</p>
    </div>

    <div style="border-top:1px solid #e2e8f0; padding-top:16px; margin-top:24px; text-align:center;">
      <p style="color:#94a3b8; font-size:11px; margin:0;">
        {AGENCY_NAME} · {PHONE} · service@betterchoiceins.com
      </p>
    </div>
  </div>
</div></body></html>"""

    return subject, html


def send_followup_email(
    to_email: str,
    subject: str,
    html: str,
    agent_email: str = "",
    quote_id: int = None,
) -> dict:
    """Send a follow-up email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    from_email = settings.MAILGUN_FROM_EMAIL or "service@betterchoiceins.com"
    reply_to = agent_email or "service@betterchoiceins.com"

    data = {
        "from": f"{AGENCY_NAME} <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "h:Reply-To": reply_to,
        "bcc": os.environ.get("SMART_INBOX_BCC", "evan@betterchoiceins.com"),
        "o:tracking-clicks": "yes",
        "o:tracking-opens": "yes",
        "v:email_type": "quote_followup",
        "v:customer_email": to_email,
        "v:agent_email": agent_email,
        "v:quote_id": str(quote_id or ""),
    }

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=data,
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info(f"Follow-up email sent to {to_email} — {msg_id}")
            return {"success": True, "message_id": msg_id}
        else:
            logger.error(f"Follow-up email failed: {resp.status_code} {resp.text}")
            return {"success": False, "error": f"Mailgun {resp.status_code}"}
    except Exception as e:
        logger.error(f"Follow-up email error: {e}")
        return {"success": False, "error": str(e)}
