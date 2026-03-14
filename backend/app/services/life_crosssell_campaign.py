"""Life Insurance Cross-Sell Campaign Engine.

Automated email drip campaign to cross-sell life insurance to P&C customers
via the Ethos partner link. Fortune 500-quality email design.

Campaign flow:
  Touch 1 (Day 3 after policy bind): "Protect What Matters Most" — soft intro
  Touch 2 (Day 10): "The Coverage Gap Most Families Don't Know About"
  Touch 3 (Day 21): "See Your Rate in 60 Seconds" — direct CTA
  Touch 4 (Day 45): "A Quick Question" — personal check-in from agent

Each touch has unique messaging, design, and CTA approach.
"""
import logging
import os
import requests
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, not_

from app.core.config import settings
from app.models.customer import Customer, CustomerPolicy
from app.models.sale import Sale

logger = logging.getLogger(__name__)

AGENCY_NAME = "Better Choice Insurance Group"
AGENCY_PHONE = "(847) 908-5665"
AGENCY_EMAIL = "service@betterchoiceins.com"
BCI_NAVY = "#0f172a"
BCI_CYAN = "#22d3ee"
ETHOS_LINK = "https://app.ethoslife.com/partner/c0fbf/q/goals"
APP_URL = "https://better-choice-web.onrender.com"


def _fmt(amount) -> str:
    try:
        return f"${float(amount):,.0f}"
    except (ValueError, TypeError):
        return "$0"


# ── Email Templates ──────────────────────────────────────────────────

def _email_header() -> str:
    return f"""
    <div style="background:linear-gradient(135deg, {BCI_NAVY} 0%, #1e293b 100%); padding:32px 24px; text-align:center; border-radius:16px 16px 0 0;">
        <img src="{APP_URL}/carrier-logos/bci_header_white.png" alt="{AGENCY_NAME}" style="height:48px; margin-bottom:8px;" />
    </div>"""


def _email_footer(unsubscribe_url: str = "") -> str:
    unsub = f'<a href="{unsubscribe_url}" style="color:#94a3b8; text-decoration:underline;">Unsubscribe</a> · ' if unsubscribe_url else ""
    return f"""
    <div style="background:#f8fafc; padding:24px; text-align:center; border-radius:0 0 16px 16px; border-top:1px solid #e2e8f0;">
        <p style="margin:0 0 8px; color:#64748b; font-size:12px;">
            {unsub}{AGENCY_NAME} · 300 Cardinal Dr Suite 220, Saint Charles, IL 60175
        </p>
        <p style="margin:0; color:#94a3b8; font-size:11px;">
            {AGENCY_PHONE} · {AGENCY_EMAIL}
        </p>
    </div>"""


def _ethos_button(text: str = "See My Rate →", customer_id: int = 0) -> str:
    # Add tracking param to Ethos link
    link = f"{ETHOS_LINK}&utm_source=orbit&utm_campaign=life_crosssell&utm_content=touch&cid={customer_id}"
    return f"""
    <div style="text-align:center; margin:28px 0;">
        <a href="{link}" style="display:inline-block; background:linear-gradient(135deg, #0ea5e9, #0284c7); color:white; padding:16px 40px; border-radius:12px; text-decoration:none; font-weight:700; font-size:17px; letter-spacing:-0.3px; box-shadow:0 4px 14px rgba(14,165,233,0.4);">
            {text}
        </a>
    </div>"""


def build_touch1(first_name: str, agent_name: str, customer_id: int = 0) -> tuple[str, str]:
    """Touch 1 — 'Protect What Matters Most' (Day 3)
    Soft intro, emotional appeal, no hard sell."""
    agent_first = agent_name.split()[0] if agent_name else "Your Agent"
    subject = f"{first_name}, there's one coverage gap we should talk about"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:560px; margin:0 auto; padding:24px 16px;">
    {_email_header()}
    <div style="background:white; padding:32px 28px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">

        <h1 style="margin:0 0 20px; color:{BCI_NAVY}; font-size:24px; font-weight:800; line-height:1.3;">
            Protect What Matters Most
        </h1>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Hi {first_name},
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Now that your home and auto are covered, I wanted to bring up something most
            families overlook — <strong>life insurance</strong>.
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Your property is protected if something goes wrong. But what about your family's
            income, your mortgage, your kids' future? That's what life insurance is for — and
            it's probably <strong>a lot more affordable than you think</strong>.
        </p>

        <div style="background:#f0f9ff; border-left:4px solid {BCI_CYAN}; padding:16px 20px; border-radius:0 8px 8px 0; margin:24px 0;">
            <p style="margin:0; color:#0c4a6e; font-size:14px; line-height:1.6;">
                <strong>Did you know?</strong> Most people overestimate the cost of life insurance
                by 3x. A healthy 35-year-old can get $500K of coverage for about $25/month.
            </p>
        </div>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            You can check your rate in about 60 seconds — no commitment, no hassle:
        </p>

        {_ethos_button("Check My Rate — Free & Easy →", customer_id)}

        <p style="margin:24px 0 0; color:#64748b; font-size:14px; line-height:1.6;">
            If you have any questions, just reply to this email or call us at {AGENCY_PHONE}.
            We're here to help.
        </p>

        <p style="margin:16px 0 0; color:#334155; font-size:15px;">
            Best,<br>
            <strong>{agent_first}</strong><br>
            <span style="color:#64748b; font-size:13px;">{AGENCY_NAME}</span>
        </p>

    </div>
    {_email_footer()}
</div></body></html>"""
    return subject, html


def build_touch2(first_name: str, agent_name: str, premium: float = 0, customer_id: int = 0) -> tuple[str, str]:
    """Touch 2 — 'The Coverage Gap' (Day 10)
    Educational, value-driven, builds urgency."""
    agent_first = agent_name.split()[0] if agent_name else "Your Agent"
    premium_str = _fmt(premium)
    subject = f"The coverage gap most families don't know about"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:560px; margin:0 auto; padding:24px 16px;">
    {_email_header()}
    <div style="background:white; padding:32px 28px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Hi {first_name},
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            We worked together to protect your property — and I want to make sure
            your family has the <strong>full picture</strong> when it comes to protection.
        </p>

        <div style="background:linear-gradient(135deg, {BCI_NAVY}, #1e293b); border-radius:12px; padding:28px; margin:24px 0;">
            <p style="margin:0 0 4px; color:{BCI_CYAN}; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:2px;">
                The 10X Rule of Thumb
            </p>
            <p style="margin:0 0 12px; color:white; font-size:17px; font-weight:600; line-height:1.5;">
                Financial experts recommend life insurance coverage equal to
                <strong style="color:{BCI_CYAN};">10 times your annual income</strong>.
            </p>
            <p style="margin:0; color:#94a3b8; font-size:13px; line-height:1.5;">
                Why? Because 44% of American families would face financial hardship
                within six months of losing the family breadwinner. Your mortgage alone
                is often the largest monthly bill — and the hardest to cover alone.
            </p>
        </div>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            The good news: through our partner <strong>Ethos</strong>, you can get coverage
            up to <strong>$2 million</strong> with a simple online application. Here's what makes it different:
        </p>

        <table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">
            <tr><td style="padding:10px 0; border-bottom:1px solid #f1f5f9;">✅ <strong>100% online</strong> — no medical exams, blood draws, or home visits</td></tr>
            <tr><td style="padding:10px 0; border-bottom:1px solid #f1f5f9;">✅ <strong>Instant approval</strong> — most people are approved immediately</td></tr>
            <tr><td style="padding:10px 0; border-bottom:1px solid #f1f5f9;">✅ <strong>Activate immediately</strong> — coverage starts the moment you're approved</td></tr>
            <tr><td style="padding:10px 0;">✅ <strong>Top-rated carriers</strong> — backed by trusted, A-rated insurance companies</td></tr>
        </table>

        <p style="margin:24px 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            It takes just a few minutes. You could have your family fully protected before dinner tonight.
        </p>

        {_ethos_button("See What I Qualify For →", customer_id)}

        <p style="margin:24px 0 0; color:#64748b; font-size:14px; line-height:1.6;">
            — {agent_first}, {AGENCY_NAME}
        </p>

    </div>
    {_email_footer()}
</div></body></html>"""
    return subject, html


def build_touch3(first_name: str, agent_name: str, customer_id: int = 0) -> tuple[str, str]:
    """Touch 3 — 'See Your Rate in 60 Seconds' (Day 21)
    Direct, benefit-focused, strong CTA."""
    agent_first = agent_name.split()[0] if agent_name else "Your Agent"
    subject = f"{first_name}, your life insurance rate is waiting"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:560px; margin:0 auto; padding:24px 16px;">
    {_email_header()}
    <div style="background:white; padding:32px 28px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Hi {first_name},
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            I'll keep this one short.
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Getting a life insurance quote used to be a headache — doctors visits, blood tests,
            weeks of waiting. Not anymore.
        </p>

        <div style="background:linear-gradient(135deg, {BCI_NAVY}, #1e293b); border-radius:12px; padding:28px; margin:24px 0; text-align:center;">
            <p style="margin:0 0 4px; color:{BCI_CYAN}; font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:1.5px;">
                Here's how simple it is
            </p>
            <table style="width:100%; margin-top:16px;" cellpadding="0" cellspacing="0">
                <tr>
                    <td style="text-align:center; padding:8px; width:33%;">
                        <p style="margin:0; color:white; font-size:28px; font-weight:800;">1</p>
                        <p style="margin:4px 0 0; color:#94a3b8; font-size:12px;">Answer a few<br>questions</p>
                    </td>
                    <td style="text-align:center; padding:8px; width:33%; border-left:1px solid #334155; border-right:1px solid #334155;">
                        <p style="margin:0; color:white; font-size:28px; font-weight:800;">2</p>
                        <p style="margin:4px 0 0; color:#94a3b8; font-size:12px;">See your<br>rate instantly</p>
                    </td>
                    <td style="text-align:center; padding:8px; width:33%;">
                        <p style="margin:0; color:white; font-size:28px; font-weight:800;">3</p>
                        <p style="margin:4px 0 0; color:#94a3b8; font-size:12px;">Apply online<br>in minutes</p>
                    </td>
                </tr>
            </table>
        </div>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7; text-align:center;">
            <strong>No medical exam. No obligation. 60 seconds.</strong>
        </p>

        {_ethos_button("Get My Free Quote →", customer_id)}

        <p style="margin:24px 0 0; color:#64748b; font-size:14px; line-height:1.6;">
            Questions? Just hit reply. I'm here.<br>
            — {agent_first}
        </p>

    </div>
    {_email_footer()}
</div></body></html>"""
    return subject, html


def build_touch4(first_name: str, agent_name: str, customer_id: int = 0) -> tuple[str, str]:
    """Touch 4 — 'A Quick Question' (Day 45)
    Personal, conversational, last touch."""
    agent_first = agent_name.split()[0] if agent_name else "Your Agent"
    subject = f"Quick question, {first_name}"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:560px; margin:0 auto; padding:24px 16px;">
    {_email_header()}
    <div style="background:white; padding:32px 28px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Hi {first_name},
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            I wanted to circle back one more time about life insurance coverage.
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            Is it something you've been thinking about? A lot of my clients tell me they
            <em>know</em> they need it but keep putting it off. The thing is — life insurance
            rates go up every year you wait, and health changes can make it harder to qualify.
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            <strong>Today is literally the cheapest it will ever be for you.</strong>
        </p>

        <p style="margin:0 0 16px; color:#334155; font-size:15px; line-height:1.7;">
            If you have 60 seconds, you can see exactly what you'd pay — no commitment:
        </p>

        {_ethos_button("See Today's Rate →", customer_id)}

        <p style="margin:24px 0 0; color:#334155; font-size:15px; line-height:1.7;">
            And if life insurance isn't the right fit right now, that's completely okay.
            Just reply and let me know — I won't bring it up again. 😊
        </p>

        <p style="margin:16px 0 0; color:#334155; font-size:15px;">
            Talk soon,<br>
            <strong>{agent_first}</strong><br>
            <span style="color:#64748b; font-size:13px;">{AGENCY_PHONE}</span>
        </p>

    </div>
    {_email_footer()}
</div></body></html>"""
    return subject, html


# ── Touch builders map ───────────────────────────────────────────────
TOUCH_BUILDERS = {
    1: build_touch1,
    2: build_touch2,
    3: build_touch3,
    4: build_touch4,
}

TOUCH_DELAYS = {
    1: 3,    # Day 3 after bind
    2: 10,   # Day 10
    3: 21,   # Day 21
    4: 45,   # Day 45
}


def send_life_crosssell_email(
    to_email: str,
    subject: str,
    html: str,
    agent_email: str = "",
) -> dict:
    """Send a life cross-sell email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    from_addr = f"{AGENCY_NAME} <{os.environ.get('AGENCY_FROM_EMAIL', 'service@betterchoiceins.com')}>"
    reply_to = agent_email or AGENCY_EMAIL

    data = {
        "from": from_addr,
        "to": [to_email],
        "subject": subject,
        "html": html,
        "h:Reply-To": reply_to,
        "o:tracking-clicks": "yes",
        "o:tracking-opens": "yes",
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
            logger.info(f"Life cross-sell email sent to {to_email}: {subject}")
            return {"success": True, "message_id": msg_id}
        else:
            logger.error(f"Life cross-sell email failed: {resp.status_code} {resp.text}")
            return {"success": False, "error": f"Mailgun {resp.status_code}"}
    except Exception as e:
        logger.error(f"Life cross-sell email error: {e}")
        return {"success": False, "error": str(e)}
