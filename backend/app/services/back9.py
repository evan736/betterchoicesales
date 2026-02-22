"""Back9 Life Insurance Integration — Quote & Apply prefill, quote API, email template."""
import logging
import json
import requests
from urllib.parse import quote as url_quote
from typing import Optional, Dict, Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def build_prefill_url(
    first_name: str, last_name: str, state: str = "IL",
    email: str = "", phone: str = "", gender: str = "",
    birthdate: str = "", metadata: dict = None,
) -> str:
    """Build a Back9 Quote & Apply prefill URL."""
    npn = settings.BACK9_NPN
    base = settings.BACK9_BASE_URL
    if not npn:
        return f"{base}/apply"

    params = ["prefill"]
    if first_name: params.append(f"first_name={url_quote(first_name)}")
    if last_name: params.append(f"last_name={url_quote(last_name)}")
    if state: params.append(f"state={state.upper()[:2]}")
    if email: params.append(f"email={url_quote(email, safe='@.')}")
    if phone:
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            fmt = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            params.append(f"phone={url_quote(fmt, safe='() -')}")
    if gender and gender in ("Male", "Female"):
        params.append(f"gender={gender}")
    if birthdate: params.append(f"birthdate={birthdate}")
    if metadata: params.append(f"metadata={url_quote(json.dumps(metadata))}")
    return f"{base}/apply?{'&'.join(params)}&npn={npn}"


def get_teaser_quote(
    first_name="John", last_name="Doe", gender="Male",
    birthdate="1985-01-01", state="IL", health=4,
    death_benefit=500000, term_duration=20,
) -> Optional[Dict[str, Any]]:
    """Fetch term life quote from Back9 API for teaser rate."""
    api_key = settings.BACK9_API_KEY
    npn = settings.BACK9_NPN
    base = settings.BACK9_BASE_URL
    if not api_key or not npn:
        return None
    try:
        resp = requests.post(
            f"{base}/api/v1/eapp-quotes",
            headers={"X-BACKNINE-AUTHENTICATION": api_key, "Content-Type": "application/json"},
            json={
                "npn": int(npn) if npn else 0, "death_benefit": death_benefit,
                "insured": {"first_name": first_name, "last_name": last_name,
                            "gender": gender, "health": health, "smoker": "Never",
                            "birthdate": birthdate},
                "mode": 12, "selected_type": "term", "state": state,
                "term_duration": term_duration,
            },
            timeout=15,
        )
        if resp.status_code == 201:
            quotes = resp.json().get("quotes") or []
            if quotes:
                c = min(quotes, key=lambda q: q.get("premium", 999999))
                return {"premium": c["premium"], "carrier": c.get("carrier", {}).get("name", ""),
                        "product": c.get("product", {}).get("name", ""),
                        "death_benefit": c.get("death_benefit", death_benefit)}
        else:
            logger.error(f"Back9 quote API {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Back9 quote API error: {e}")
    return None


def build_crosssell_email_html(
    first_name, apply_url, pc_carrier="", pc_policy_type="",
    teaser_premium=None, teaser_death_benefit=500000,
    producer_name="", producer_phone="(847) 908-5665",
) -> str:
    """Build branded HTML email for life insurance cross-sell."""
    teaser_block = ""
    if teaser_premium:
        teaser_block = (
            '<div style="background:#EFF6FF;border:2px solid #3B82F6;border-radius:12px;'
            'padding:20px;margin:24px 0;text-align:center;">'
            '<p style="color:#1E40AF;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;'
            'font-weight:600;margin-bottom:4px;">Term Life Insurance Starting At</p>'
            f'<p style="color:#1E3A8A;font-size:42px;font-weight:800;margin:4px 0;">'
            f'${teaser_premium:.0f}<span style="font-size:18px;color:#3B82F6;">/mo</span></p>'
            f'<p style="color:#3B82F6;font-size:14px;">for ${teaser_death_benefit:,.0f} in coverage</p>'
            '</div>'
        )

    pc = ""
    if pc_carrier and pc_policy_type:
        pc = f"As your {pc_carrier} {pc_policy_type} policyholder, "
    elif pc_carrier:
        pc = f"As your {pc_carrier} policyholder, "
    else:
        pc = "As a valued client, "

    advisor = producer_name or "Your Better Choice Insurance Team"

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
        '<body style="margin:0;padding:0;background:#F1F5F9;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;\">"
        '<div style="max-width:600px;margin:0 auto;background:#fff;">'

        # Header
        '<div style="background:linear-gradient(135deg,#1E3A5F,#2563EB);padding:32px 24px;text-align:center;">'
        '<h1 style="color:#fff;font-size:22px;font-weight:700;margin:0;">Better Choice Insurance</h1>'
        '<p style="color:#93C5FD;font-size:13px;margin-top:4px;">Protecting What Matters Most</p></div>'

        # Body
        '<div style="padding:32px 24px;">'
        '<h2 style="color:#1E293B;font-size:20px;font-weight:700;margin-bottom:16px;">'
        "You've protected your home and car &mdash; now let's protect your family.</h2>"

        f'<p style="color:#475569;font-size:15px;line-height:1.7;">Hi {first_name},</p>'

        f'<p style="color:#475569;font-size:15px;line-height:1.7;">'
        f'{pc}we wanted to reach out about something important that many of our clients '
        'overlook &mdash; <strong>life insurance</strong>. While your property is covered, '
        'protecting the people who depend on you is just as critical.</p>'

        '<p style="color:#475569;font-size:15px;line-height:1.7;">'
        'Term life insurance is more affordable than most people think. We\'ve partnered with '
        'top-rated carriers to make it easy to get a quote and apply online in minutes &mdash; '
        'no medical exam required for many applicants.</p>'

        f'{teaser_block}'

        '<div style="text-align:center;margin:28px 0;">'
        f'<a href="{apply_url}" style="display:inline-block;background:linear-gradient(135deg,#2563EB,#1D4ED8);'
        'color:#fff;font-weight:700;font-size:16px;padding:14px 40px;border-radius:8px;text-decoration:none;">'
        'Get My Free Quote &rarr;</a>'
        '<p style="color:#94A3B8;font-size:12px;margin-top:8px;">Takes less than 2 minutes. No obligation.</p></div>'

        '<div style="background:#F8FAFC;border-radius:10px;padding:20px;margin:24px 0;">'
        '<p style="color:#1E293B;font-size:14px;font-weight:600;margin-bottom:12px;">Why consider life insurance?</p>'
        '<p style="color:#475569;font-size:14px;line-height:2;">'
        '<strong style="color:#2563EB;">&#10003;</strong> Replace lost income for your family<br>'
        '<strong style="color:#2563EB;">&#10003;</strong> Pay off your mortgage and debts<br>'
        '<strong style="color:#2563EB;">&#10003;</strong> Cover your children\'s education<br>'
        '<strong style="color:#2563EB;">&#10003;</strong> Lock in low rates while you\'re healthy</p></div>'

        '<p style="color:#475569;font-size:15px;line-height:1.7;">'
        'Click the button above to see personalized quotes from multiple carriers. '
        'Your information is already pre-filled &mdash; just review and choose.</p>'

        f'<p style="color:#475569;font-size:15px;line-height:1.7;margin-top:24px;">'
        f'Questions? Reply to this email or call us at {producer_phone}.</p>'

        f'<p style="color:#475569;font-size:15px;line-height:1.7;margin-top:16px;">'
        f'Best,<br><strong>{advisor}</strong><br>'
        '<span style="color:#94A3B8;font-size:13px;">Better Choice Insurance</span></p>'
        '</div>'

        # Footer
        '<div style="background:#F8FAFC;padding:20px 24px;text-align:center;border-top:1px solid #E2E8F0;">'
        '<p style="color:#94A3B8;font-size:11px;line-height:1.6;margin:0;">'
        'Better Choice Insurance | (847) 908-5665<br>'
        "You're receiving this because you're a valued Better Choice Insurance customer.<br>"
        'Life insurance products offered through BackNine Insurance &amp; Financial Services.</p>'
        '</div></div></body></html>'
    )


def send_crosssell_email(to_email, subject, html, reply_to=None) -> bool:
    """Send cross-sell email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.error("Mailgun not configured")
        return False
    try:
        data = {
            "from": f"{settings.MAILGUN_FROM_NAME} <{settings.MAILGUN_FROM_EMAIL}>",
            "to": [to_email], "subject": subject, "html": html,
        }
        if reply_to:
            data["h:Reply-To"] = reply_to
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY), data=data, timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"Cross-sell email sent to {to_email}")
            return True
        logger.error(f"Mailgun error {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False
