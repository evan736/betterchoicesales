"""Plain-text quote email service — Variant B of the A/B test.

Designed to look like a normal, personal email a producer would type from their
own Gmail/Outlook. NO HTML, NO branding, NO carrier logos, NO call-to-action
buttons, NO trust badges. Just words.

Sent as text/plain via Mailgun (text= instead of html=). The "From" line uses
the producer's first name + agency address (e.g. "Joseph Rivera
<sales@betterchoiceins.com>") to keep deliverability through the verified
domain while looking like the producer wrote it personally.

Why a separate file: keeping plain-text logic isolated from the branded HTML
template (quote_email.py) makes the experiment cleaner and easier to roll
back if Variant B underperforms.
"""
import os
import logging
import re
import requests
from app.core.config import settings

logger = logging.getLogger(__name__)

AGENCY_PHONE = "(847) 908-5665"


def _premium_phrase(premium: str, premium_term: str = "6 months") -> str:
    """Return a phrase like '$1,234.56 every 6 months ($205.76/month)'.

    Plain text doesn't get the giant headline number — it gets the figures
    woven into a sentence like a person would write.
    """
    if not premium:
        return ""
    raw = str(premium).replace("$", "").replace(",", "")
    try:
        total = float(raw)
    except ValueError:
        return f"{premium}"

    months = 6
    if premium_term:
        m = re.search(r'(\d+)', premium_term)
        if m:
            months = int(m.group(1))

    if months > 1:
        monthly = total / months
        return f"${total:,.2f} for the {months}-month term (about ${monthly:,.2f}/mo)"
    return f"${total:,.2f}/month"


def build_plaintext_quote_email(
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: str,
    premium_term: str = "6 months",
    effective_date: str = "",
    agent_name: str = "",
    agent_phone: str = "",
    additional_notes: str = "",
    unsubscribe_url: str = None,
) -> tuple:
    """Return (subject, plain_text_body) for a Variant B initial quote email.

    The text deliberately avoids salesy language and any kind of formatting
    that would betray it as a marketing email. A real person typing on a
    keyboard might write a few sentences with a sign-off — that's the goal.
    """
    first_name = (prospect_name or "").split()[0] or "there"
    agent_first = (agent_name or "").split()[0] or "your agent"
    carrier_display = (carrier or "").replace("_", " ").title()
    if not carrier_display:
        carrier_display = "the carrier"

    phrase = _premium_phrase(premium, premium_term)

    subject = f"Your {carrier_display} quote"

    # Body — short, conversational, no marketing language. The PDF is attached
    # so the customer has full details if they want them.
    lines = [
        f"Hi {first_name},",
        "",
        f"I put together your {carrier_display} quote — full details are attached.",
        "",
    ]
    if phrase:
        lines.append(f"The premium came in at {phrase}.")
        lines.append("")
    if effective_date:
        lines.append(f"Effective date would be {effective_date}.")
        lines.append("")

    if additional_notes:
        lines.append(additional_notes.strip())
        lines.append("")

    lines.append("Let me know if you'd like to move forward or if you have any questions.")
    lines.append("")
    lines.append("Thanks,")
    lines.append(agent_name or "Better Choice Insurance")
    if agent_phone:
        lines.append(agent_phone)
    else:
        lines.append(AGENCY_PHONE)

    if unsubscribe_url:
        # CAN-SPAM compliance — even on plain text we must include opt-out.
        # Keep it understated, on its own line at the end.
        lines.append("")
        lines.append("---")
        lines.append(f"Unsubscribe: {unsubscribe_url}")

    return subject, "\n".join(lines)


def build_plaintext_followup_email(
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: float,
    premium_term: str,
    agent_name: str,
    agent_phone: str,
    day,
    unsubscribe_url: str = None,
) -> tuple:
    """Return (subject, plain_text_body) for a Variant B follow-up.

    `day` matches the existing followup schedule: 3, 7, 14, 30, or
    "bind_retarget".
    """
    first_name = (prospect_name or "").split()[0] or "there"
    carrier_display = (carrier or "").replace("_", " ").title() or "the carrier"
    monthly = ""
    try:
        months_map = {"6 months": 6, "12 months": 12, "annual": 12, "monthly": 1}
        months = months_map.get(premium_term, 6)
        if months > 1 and premium:
            monthly = f"${float(premium) / months:,.2f}/mo"
    except Exception:
        pass

    if day == 3:
        subject = f"Following up on your {carrier_display} quote"
        body_lines = [
            f"Hi {first_name},",
            "",
            f"Just wanted to make sure you saw the {carrier_display} quote I sent over.",
            "Did you have any questions on it, or want to talk through anything?",
            "",
        ]
    elif day == 7:
        subject = f"Quick question on your {carrier_display} quote"
        body_lines = [
            f"Hi {first_name},",
            "",
            f"Wanted to circle back on the {carrier_display} quote.",
        ]
        if monthly:
            body_lines.append(f"The rate we found was {monthly} — happy to walk through it with you if helpful.")
        else:
            body_lines.append("Happy to walk through it with you if it would help.")
        body_lines.append("")
        body_lines.append("Just let me know if you'd like to move forward or have questions.")
        body_lines.append("")
    elif day == 14:
        subject = f"One last check on your {carrier_display} quote"
        body_lines = [
            f"Hi {first_name},",
            "",
            f"I haven't heard back yet on your {carrier_display} quote, so I wanted to check one more time.",
            "Insurance rates do change, so the longer it sits the more chance the price moves.",
            "",
            "If you've gone with someone else, no problem — just let me know and I'll close it out.",
            "",
        ]
    elif day == "bind_retarget":
        subject = "We're almost done with your policy"
        body_lines = [
            f"Hi {first_name},",
            "",
            f"It looked like you wanted to move forward on the {carrier_display} policy but we never wrapped up the last few items.",
            "Want to find a few minutes to finish it? Should only take a few minutes.",
            "",
        ]
    elif day == 30:
        subject = "Are you still looking for insurance?"
        body_lines = [
            f"Hi {first_name},",
            "",
            f"Been about a month since I put together that {carrier_display} quote.",
            "If you're still shopping around, I'd be glad to re-run your numbers — rates have moved a bit.",
            "",
            "Otherwise no worries, just wanted to check in.",
            "",
        ]
    else:
        subject = f"Following up on your {carrier_display} quote"
        body_lines = [
            f"Hi {first_name},",
            "",
            "Just wanted to follow up.",
            "",
        ]

    body_lines.append("Thanks,")
    body_lines.append(agent_name or "Better Choice Insurance")
    body_lines.append(agent_phone or AGENCY_PHONE)

    if unsubscribe_url:
        body_lines.append("")
        body_lines.append("---")
        body_lines.append(f"Unsubscribe: {unsubscribe_url}")

    return subject, "\n".join(body_lines)


def send_plaintext_quote_email(
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
    pdf_paths: list = None,  # multi-PDF: [{"path", "filename"}, ...]
    quote_id: int = None,
    unsubscribe_token: str = None,
) -> dict:
    """Send the Variant B plain-text initial quote email."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    app_url = getattr(settings, 'FRONTEND_URL', None) or "https://better-choice-web.onrender.com"
    unsubscribe_url = f"{app_url}/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else None

    subject, body = build_plaintext_quote_email(
        prospect_name=prospect_name,
        carrier=carrier,
        policy_type=policy_type,
        premium=premium,
        premium_term=premium_term,
        effective_date=effective_date,
        agent_name=agent_name,
        agent_phone=agent_phone,
        additional_notes=additional_notes,
        unsubscribe_url=unsubscribe_url,
    )

    return _send_plaintext(
        to_email=to_email,
        subject=subject,
        body=body,
        agent_name=agent_name,
        agent_email=agent_email,
        prospect_name=prospect_name,
        carrier=carrier,
        quote_id=quote_id,
        pdf_path=pdf_path,
        pdf_filename=pdf_filename,
        pdf_paths=pdf_paths,
    )


def send_plaintext_followup_email(
    to_email: str,
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: float,
    premium_term: str,
    agent_name: str,
    agent_email: str,
    agent_phone: str,
    quote_id: int,
    day,
    unsubscribe_token: str = None,
) -> dict:
    """Send a Variant B plain-text follow-up. Same auth/from path as initial."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    app_url = getattr(settings, 'FRONTEND_URL', None) or "https://better-choice-web.onrender.com"
    unsubscribe_url = f"{app_url}/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else None

    subject, body = build_plaintext_followup_email(
        prospect_name=prospect_name,
        carrier=carrier,
        policy_type=policy_type,
        premium=premium,
        premium_term=premium_term,
        agent_name=agent_name,
        agent_phone=agent_phone,
        day=day,
        unsubscribe_url=unsubscribe_url,
    )

    return _send_plaintext(
        to_email=to_email,
        subject=subject,
        body=body,
        agent_name=agent_name,
        agent_email=agent_email,
        prospect_name=prospect_name,
        carrier=carrier,
        quote_id=quote_id,
        followup_day=str(day),
    )


def _send_plaintext(
    to_email: str,
    subject: str,
    body: str,
    agent_name: str,
    agent_email: str,
    prospect_name: str,
    carrier: str,
    quote_id: int = None,
    pdf_path: str = None,
    pdf_filename: str = None,
    pdf_paths: list = None,
    followup_day: str = None,
) -> dict:
    """Shared Mailgun send for plain-text variant.

    Critical detail: we send `text=` only, NOT `html=`. Mailgun gives us
    proper text/plain Content-Type that way. If we send both, mail clients
    pick the HTML and we lose the variant.

    From-name uses the producer's name with the agency address so:
      a) DKIM/SPF/DMARC pass (we sign as the verified domain)
      b) The recipient sees a personal name like "Joseph Rivera"
    """
    # From line: "Joseph Rivera <sales@betterchoiceins.com>" — looks like the
    # producer wrote it personally while staying on the verified domain.
    from_addr = "sales@betterchoiceins.com"
    if agent_name:
        from_line = f"{agent_name} <{from_addr}>"
    else:
        from_line = f"Better Choice Insurance <{from_addr}>"

    # Reply-to should be the agent's personal email if we have one, otherwise
    # sales@. This way replies go to the actual person rather than a shared
    # inbox where they might get lost.
    reply_to = agent_email or "sales@betterchoiceins.com"

    data = {
        "from": from_line,
        "to": [to_email],
        "subject": subject,
        "text": body,  # text/plain ONLY — no html field
        "o:tracking-opens": "yes",
        "o:tracking-clicks": "no",  # plain text has no links to track anyway
        "h:Reply-To": reply_to,
        "bcc": [os.environ.get("SMART_INBOX_BCC", "evan@betterchoiceins.com")],
        # Custom variables for analytics
        "v:email_type": "quote_followup" if followup_day else "quote",
        "v:variant": "B",
        "v:customer_name": prospect_name or "",
        "v:customer_email": to_email or "",
        "v:carrier": carrier or "",
        "v:agent_name": agent_name or "",
        "v:agent_email": agent_email or "",
        "v:quote_id": str(quote_id or ""),
    }
    if followup_day:
        data["v:followup_day"] = followup_day

    files = []
    attach_list = []
    if pdf_paths:
        attach_list = [
            (p.get("path"), p.get("filename") or f"Quote_{i+1}.pdf")
            for i, p in enumerate(pdf_paths)
            if p and p.get("path")
        ]
    elif pdf_path:
        attach_list = [(pdf_path, pdf_filename or "Quote.pdf")]

    for path, fname in attach_list:
        try:
            files.append(("attachment", (fname, open(path, "rb"), "application/pdf")))
        except Exception as e:
            logger.warning(f"Could not attach PDF {path}: {e}")

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=data,
            files=files if files else None,
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info(f"Variant B plain-text sent to {to_email} (carrier={carrier}) - {msg_id}")
            return {"success": True, "message_id": msg_id}
        else:
            logger.error(f"Variant B send failed: {resp.status_code} {resp.text[:200]}")
            return {"success": False, "error": f"Mailgun returned {resp.status_code}"}
    except Exception as e:
        logger.error(f"Variant B send error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        for f in files:
            try:
                f[1][1].close()
            except Exception:
                pass
