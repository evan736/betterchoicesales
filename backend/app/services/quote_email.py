"""Quote Email Service — carrier-branded quote emails with PDF attachments.

Sends professional carrier-specific emails with:
- Carrier logo + selling point
- Highlighted premium amount
- Attached quote PDF(s)
- Agent contact info
- CTA to bind (mailto reply)
"""
import logging
import requests
from typing import Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)


POLICY_TYPE_LABELS = {
    "auto": "Auto Insurance",
    "home": "Homeowners Insurance",
    "renters": "Renters Insurance",
    "condo": "Condo Insurance",
    "landlord": "Landlord Insurance",
    "umbrella": "Umbrella Insurance",
    "motorcycle": "Motorcycle Insurance",
    "boat": "Boat Insurance",
    "rv": "RV Insurance",
    "life": "Life Insurance",
    "commercial": "Commercial Insurance",
    "bundled": "Bundled Insurance",
    "other": "Insurance",
}

# ── Carrier selling points ────────────────────────────────────────
CARRIER_SELLING_POINTS = {
    "national_general": (
        "National General has been protecting families for over 80 years. "
        "Rated A+ (Superior) by AM Best, they're known for flexible payment options, "
        "fast claims handling, and affordable bundled coverage — a top choice for home and auto."
    ),
    "progressive": (
        "Progressive is the #3 largest auto insurer in the U.S. and a proven industry leader. "
        "Known for their innovative Name Your Price\u00ae tool, multi-policy discounts, "
        "and 24/7 claims service, Progressive consistently delivers exceptional value."
    ),
    "travelers": (
        "Travelers is one of the largest and most respected insurers in the country, "
        "with over 160 years of experience. Rated A++ by AM Best, they offer superior "
        "coverage options, industry-leading claim response times, and personalized service."
    ),
    "safeco": (
        "Safeco, a Liberty Mutual company, is built specifically for independent agents "
        "who put customers first. With broad coverage options, generous discounts, and an "
        "A (Excellent) AM Best rating, Safeco is a trusted name in personal insurance."
    ),
    "grange": (
        "Grange Insurance has been a Midwest staple since 1935, earning an A (Excellent) "
        "AM Best rating. Known for their outstanding local claims service, community focus, "
        "and competitive bundle discounts, Grange is a customer-first company."
    ),
    "hippo": (
        "Hippo is modernizing home insurance with proactive smart home protection. "
        "Their policies include built-in equipment breakdown coverage, home maintenance "
        "monitoring, and a fast digital experience — insurance designed for how you live today."
    ),
    "openly": (
        "Openly specializes in premium homeowners insurance with best-in-class coverage. "
        "Their policies feature guaranteed replacement cost, water backup coverage, and "
        "flexible deductible options — all backed by exceptional customer satisfaction ratings."
    ),
    "bristol_west": (
        "Bristol West, a Farmers Insurance company, specializes in auto coverage for every "
        "driver. With flexible payment plans, a streamlined claims process, and strong "
        "financial backing, Bristol West makes quality coverage accessible to everyone."
    ),
    "branch": (
        "Branch is one of the fastest-growing insurers in America, offering instant quotes "
        "and community-based pricing that rewards responsible neighbors. Their bundled home "
        "and auto packages deliver some of the most competitive rates in the market."
    ),
    "clearcover": (
        "Clearcover offers premium auto insurance at lower prices by using smart technology "
        "to reduce overhead. Their mobile-first experience includes a fast claims process, "
        "great customer ratings, and prices that are often 20%+ below traditional carriers."
    ),
    "gainsco": (
        "Gainsco has been a trusted auto insurer since 1978, specializing in affordable "
        "coverage with flexible payment options. Known for competitive rates and responsive "
        "claims service, Gainsco keeps you protected without breaking the bank."
    ),
    "geico": (
        "GEICO is one of the most recognized names in insurance, serving over 17 million "
        "policyholders. With a AA+ financial strength rating, 24/7 service, and consistently "
        "competitive rates, GEICO continues to be a market leader."
    ),
    "american_modern": (
        "American Modern, a Munich Re company, is the nation's leading specialty insurer. "
        "With an A+ AM Best rating and 50+ years of experience, they provide tailored "
        "coverage for manufactured homes, landlord properties, and unique insurance needs."
    ),
    "covertree": (
        "CoverTree is revolutionizing manufactured home insurance with fast, affordable, "
        "digital-first policies. Their coverage is designed specifically for mobile and "
        "manufactured homes, offering comprehensive protection at competitive prices."
    ),
    "steadily": (
        "Steadily is the #1 landlord insurance provider in the U.S., purpose-built for "
        "rental property owners. With instant quotes, broad coverage including loss of rent, "
        "and competitive pricing, Steadily makes protecting your investment effortless."
    ),
    "next": (
        "NEXT Insurance is the leading digital insurer for small businesses, rated A- "
        "by AM Best. With instant certificates of insurance, affordable premiums, and a "
        "100% online experience, NEXT makes commercial coverage simple and accessible."
    ),
    "integrity": (
        "Integrity Insurance has been a trusted Midwest carrier since 1933. With an A "
        "(Excellent) AM Best rating, they provide personalized coverage, local claims "
        "handling, and the kind of service that keeps customers for life."
    ),
    "universal_property": (
        "Universal Property & Casualty is Florida's #1 homeowners insurer, providing "
        "comprehensive hurricane and windstorm coverage. With rapid claims processing and "
        "competitive rates, they specialize in protecting homes in high-risk areas."
    ),
}


def build_quote_email_html(
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: str,
    premium_term: str = "6 months",
    effective_date: str = "",
    agent_name: str = "",
    agent_email: str = "",
    agent_phone: str = "",
    additional_notes: str = "",
    is_multi_quote: bool = False,
    quotes_summary: list = None,
) -> str:
    """Build carrier-branded quote email HTML."""
    from app.services.welcome_email import CARRIER_INFO, BCI_NAVY, BCI_CYAN

    carrier_key = (carrier or "").lower().replace(" ", "_")
    cinfo = CARRIER_INFO.get(carrier_key, {})
    accent = cinfo.get("accent_color", BCI_CYAN)
    carrier_name = cinfo.get("display_name", (carrier or "Insurance").title())
    policy_label = POLICY_TYPE_LABELS.get(policy_type, "Insurance")
    first_name = prospect_name.split()[0] if prospect_name else "there"

    # Carrier logo URL
    app_url = getattr(settings, 'FRONTEND_URL', None) or "https://better-choice-web.onrender.com"
    carrier_logo_url = f"{app_url}/carrier-logos/{carrier_key}.png"

    # Carrier selling point
    selling_point = CARRIER_SELLING_POINTS.get(carrier_key, "")

    # Effective date display
    eff_html = ""
    if effective_date:
        eff_html = f'<p style="color:#64748B;font-size:13px;margin:4px 0 0 0;">Effective Date: <strong>{effective_date}</strong></p>'

    # Multi-quote comparison table
    multi_html = ""
    if is_multi_quote and quotes_summary:
        rows = ""
        for q in quotes_summary:
            rows += f"""<tr>
                <td style="padding:10px 14px;border-bottom:1px solid #E2E8F0;font-size:14px;font-weight:600;color:#1e293b;">{q.get('carrier','').title()}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #E2E8F0;font-size:14px;color:#334155;">{q.get('policy_type','').title()}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #E2E8F0;font-size:18px;font-weight:700;color:{accent};">{q.get('premium','')}</td>
            </tr>"""
        multi_html = f"""
        <div style="margin:20px 0;">
            <p style="color:#1e293b;font-size:14px;font-weight:bold;margin:0 0 10px 0;">Your Coverage Breakdown:</p>
            <table style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;">
                <tr style="background:#F8FAFC;">
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#64748B;font-weight:600;">Carrier</th>
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#64748B;font-weight:600;">Coverage</th>
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#64748B;font-weight:600;">Premium</th>
                </tr>
                {rows}
            </table>
        </div>"""

    # Carrier logo + selling point section
    carrier_section = ""
    if selling_point:
        carrier_section = f"""
        <div style="background:#F8FAFC;border-radius:10px;padding:20px;margin:20px 0;border:1px solid #E2E8F0;text-align:center;">
            <img src="{carrier_logo_url}" alt="{carrier_name}" style="max-height:48px;max-width:200px;margin:0 auto 12px auto;display:block;" />
            <p style="margin:0 0 8px 0;font-size:12px;color:#64748B;text-transform:uppercase;letter-spacing:1px;font-weight:600;">AI Overview of {carrier_name}</p>
            <p style="margin:0;color:#475569;font-size:13px;line-height:1.6;font-style:italic;">
                "{selling_point}"
            </p>
        </div>"""

    # Agent section
    agent_html = ""
    if agent_name:
        agent_html = f"""
        <div style="background:#F8FAFC;border-radius:8px;padding:16px;margin:20px 0;border:1px solid #E2E8F0;">
            <p style="margin:0 0 4px 0;font-size:12px;color:#64748B;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Your Insurance Advisor</p>
            <p style="margin:0;font-size:15px;font-weight:bold;color:#1e293b;">{agent_name}</p>
            {f'<p style="margin:2px 0 0 0;font-size:13px;color:#64748B;">{agent_email}</p>' if agent_email else ''}
            {f'<p style="margin:2px 0 0 0;font-size:13px;color:#64748B;">{agent_phone}</p>' if agent_phone else ''}
        </div>"""

    # Notes
    notes_html = ""
    if additional_notes:
        notes_html = f"""
        <div style="background:#FFFBEB;border-left:4px solid #F59E0B;padding:12px 16px;margin:16px 0;border-radius:0 8px 8px 0;">
            <p style="margin:0;color:#92400E;font-size:13px;"><strong>A note for you:</strong> {additional_notes}</p>
        </div>"""

    # Build the reply-to mailto link for the CTA
    reply_email = agent_email or "service@betterchoiceins.com"
    import urllib.parse
    bind_subject = urllib.parse.quote(f"I am ready to bind - {carrier_name} {policy_label}")
    bind_body = urllib.parse.quote(f"Hi {agent_name or 'team'},\n\nI would like to move forward with my {carrier_name} {policy_label.lower()} quote for {premium}/{premium_term}.\n\nPlease let me know the next steps.\n\nThank you,\n{prospect_name}")
    bind_mailto = f"mailto:{reply_email}?subject={bind_subject}&body={bind_body}"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg, #1a2b5f 0%, #162249 60%, #0c4a6e 100%);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:white;font-size:20px;font-weight:700;">Better Choice Insurance Group</h1>
    <p style="margin:6px 0 0 0;color:{accent};font-size:13px;font-weight:600;">Your {carrier_name} {policy_label} Quote</p>
  </div>

  <!-- Body -->
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;border:1px solid #E2E8F0;border-top:none;">

    <p style="color:#1e293b;font-size:16px;margin:0 0 16px 0;">
      Hi {first_name},
    </p>

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 20px 0;">
      Thank you for the opportunity to quote your {policy_label.lower()}!
      {"Here are the options we found for you:" if is_multi_quote else f"We have put together a {carrier_name} quote for your review."}
    </p>

    {multi_html}

    <!-- Premium Highlight Box -->
    <div style="background:linear-gradient(135deg, {accent}12, {accent}08);border:2px solid {accent}40;border-radius:12px;padding:24px;margin:20px 0;text-align:center;">
      <p style="margin:0 0 4px 0;color:#64748B;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">
        {"Total Bundle" if is_multi_quote else carrier_name} Quote
      </p>
      <p style="margin:0;color:#1e293b;font-size:42px;font-weight:800;letter-spacing:-1px;">
        {premium}
      </p>
      <p style="margin:4px 0 0 0;color:#64748B;font-size:14px;">
        per {premium_term}
      </p>
      {eff_html}
    </div>

    {carrier_section}

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 8px 0;">
      Your full quote details are attached as a PDF. Please review the coverages,
      deductibles, and limits to make sure everything looks good.
    </p>

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 20px 0;">
      Ready to get covered? Simply reply to this email, give us a call, or click
      the button below.
    </p>

    {notes_html}

    <!-- CTA Buttons -->
    <div style="text-align:center;margin:24px 0;">
      <a href="{bind_mailto}" style="display:inline-block;background:{accent};color:white;padding:14px 36px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.3px;">
        I am Ready to Bind!
      </a>
    </div>
    <div style="text-align:center;margin:0 0 20px 0;">
      <a href="tel:8479085665" style="color:{accent};font-size:13px;text-decoration:none;">
        Or call us at (847) 908-5665
      </a>
    </div>

    {agent_html}

    <!-- What Happens Next -->
    <div style="border-top:1px solid #E2E8F0;padding-top:20px;margin-top:20px;">
      <p style="color:#1e293b;font-size:14px;font-weight:bold;margin:0 0 10px 0;">What happens next?</p>
      <table style="width:100%;">
        <tr>
          <td style="vertical-align:top;padding:4px 12px 4px 0;width:24px;">
            <div style="width:24px;height:24px;background:{accent}18;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:{accent};">1</div>
          </td>
          <td style="padding:4px 0;color:#334155;font-size:13px;">Review your quote PDF and coverages</td>
        </tr>
        <tr>
          <td style="vertical-align:top;padding:4px 12px 4px 0;">
            <div style="width:24px;height:24px;background:{accent}18;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:{accent};">2</div>
          </td>
          <td style="padding:4px 0;color:#334155;font-size:13px;">Reply or call us to confirm you would like to proceed</td>
        </tr>
        <tr>
          <td style="vertical-align:top;padding:4px 12px 4px 0;">
            <div style="width:24px;height:24px;background:{accent}18;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:{accent};">3</div>
          </td>
          <td style="padding:4px 0;color:#334155;font-size:13px;">We will handle the rest and get you covered!</td>
        </tr>
      </table>
    </div>

    <!-- Footer -->
    <div style="border-top:1px solid #E2E8F0;padding-top:16px;margin-top:24px;text-align:center;">
      <p style="color:#94a3b8;font-size:11px;margin:0;">
        Better Choice Insurance Group | (847) 908-5665 | service@betterchoiceins.com
      </p>
      <p style="color:#94a3b8;font-size:11px;margin:4px 0 0 0;">
        This quote is valid for 24 hours. Rates and availability subject to change.
      </p>
    </div>
  </div>
</div>
</body></html>"""


def send_quote_email(
    to_email: str,
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: str,
    premium_term: str = "6 months",
    effective_date: str = "",
    agent_name: str = "",
    agent_email: str = "",
    agent_phone: str = "",
    additional_notes: str = "",
    pdf_path: str = None,
    pdf_filename: str = None,
    is_multi_quote: bool = False,
    quotes_summary: list = None,
) -> dict:
    """Send quote email with PDF attachment via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    from app.services.welcome_email import CARRIER_INFO
    carrier_key = (carrier or "").lower().replace(" ", "_")
    cinfo = CARRIER_INFO.get(carrier_key, {})
    carrier_name = cinfo.get("display_name", (carrier or "Insurance").title())
    policy_label = POLICY_TYPE_LABELS.get(policy_type, "Insurance")

    subject = f"Your {carrier_name} {policy_label} Quote \u2014 {premium}/{premium_term}"
    html = build_quote_email_html(
        prospect_name=prospect_name,
        carrier=carrier,
        policy_type=policy_type,
        premium=premium,
        premium_term=premium_term,
        effective_date=effective_date,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_phone=agent_phone,
        additional_notes=additional_notes,
        is_multi_quote=is_multi_quote,
        quotes_summary=quotes_summary,
    )

    reply_to = agent_email if agent_email else "service@betterchoiceins.com"
    from_name = f"{agent_name} at Better Choice Insurance" if agent_name else "Better Choice Insurance Group"

    data = {
        "from": f"{from_name} <quotes@{settings.MAILGUN_DOMAIN}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "h:Reply-To": reply_to,
    }

    files = []
    if pdf_path:
        try:
            fname = pdf_filename or f"{carrier_name}_{policy_label}_Quote.pdf"
            files.append(("attachment", (fname, open(pdf_path, "rb"), "application/pdf")))
        except Exception as e:
            logger.warning(f"Could not attach PDF {pdf_path}: {e}")

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=data,
            files=files if files else None,
        )

        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info(f"Quote email sent to {to_email} for {carrier_name} - {msg_id}")
            return {"success": True, "message_id": msg_id}
        else:
            logger.error(f"Quote email failed: {resp.status_code} {resp.text}")
            return {"success": False, "error": f"Mailgun returned {resp.status_code}"}
    except Exception as e:
        logger.error(f"Quote email error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        for _, (_, f, _) in files:
            try:
                f.close()
            except:
                pass
