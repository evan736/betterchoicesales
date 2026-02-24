"""Carrier Inspection Email Automation.

Detects inbound inspection/follow-up emails from carriers (Grange, NatGen, etc.),
extracts the key details using Claude API, and sends a customer-friendly email
with the original PDF attached.

Supported carriers:
- Grange: PLFollowUps@grangeinsurance.com — "Regarding Recent Home Inspection"
- NatGen/NGIC: *@NGIC.com — inspection reports, Coverage A revisions

Flow:
1. Inbound email hits Mailgun webhook → routed here by keyword detection
2. Claude API extracts: policy#, insured name, action required, deadline
3. Customer looked up in ORBIT DB
4. Plain-language email generated + original PDF attached
5. Sent from service@betterchoiceins.com, BCC evan@
6. Note pushed to NowCerts

Feature flag: INSPECTION_EMAIL_MODE=live|dry_run (default: dry_run)
"""
import os
import io
import re
import logging
from datetime import datetime
from typing import Optional

import requests as http_requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)

INSPECTION_MODE = os.environ.get("INSPECTION_EMAIL_MODE", "dry_run").lower()

# ── Detection Keywords ────────────────────────────────────────────────

INSPECTION_KEYWORDS = [
    "inspection", "home inspection", "recent home inspection",
    "action required", "action required by",
    "inspector", "inspector's comments",
    "coverage a revision", "policy adjustment",
    "exterior main client output", "photo documentation",
    "fall exposure", "railing", "deck", "roof", "siding",
]

INSPECTION_SENDER_PATTERNS = [
    "plfollowups@grangeinsurance.com",
    "plimages@grangeinsurance.com",
    "grangeinsurance.com",
    "ngic.com",
]


def is_inspection_email(sender: str, subject: str, body_text: str) -> bool:
    """Detect if an inbound email is a carrier inspection follow-up."""
    sender_lower = (sender or "").lower()
    subject_lower = (subject or "").lower()
    body_lower = (body_text or "").lower()
    all_text = f"{sender_lower} {subject_lower} {body_lower}"

    # Check sender patterns
    sender_match = any(pat in sender_lower for pat in INSPECTION_SENDER_PATTERNS)

    # Check keywords in subject or body
    keyword_match = any(kw in all_text for kw in INSPECTION_KEYWORDS)

    # Must match sender pattern AND at least one keyword
    # OR have very strong keyword signals in subject
    if sender_match and keyword_match:
        return True

    # Strong subject-line signals
    strong_subject = any(kw in subject_lower for kw in [
        "home inspection", "recent home inspection",
        "coverage a revision", "inspection report",
    ])
    if strong_subject:
        return True

    return False


def detect_carrier_from_inspection(sender: str, body_text: str) -> str:
    """Determine which carrier sent the inspection email."""
    sender_lower = (sender or "").lower()
    body_lower = (body_text or "").lower()
    all_text = f"{sender_lower} {body_lower}"

    if "grange" in all_text or "grangeinsurance.com" in sender_lower:
        return "grange"
    if "ngic" in all_text or "ngic.com" in sender_lower or "national general" in all_text:
        return "national_general"
    if "progressive" in all_text:
        return "progressive"
    if "travelers" in all_text:
        return "travelers"
    if "safeco" in all_text:
        return "safeco"

    return "unknown"


# ── Claude API Extraction ─────────────────────────────────────────────

async def extract_inspection_details(
    email_body: str,
    subject: str,
    sender: str,
    pdf_bytes_list: list[tuple[str, bytes]] = None,
) -> dict:
    """Use Claude API to extract structured inspection details from email + PDFs.
    
    Returns dict with:
    - policy_number: str
    - insured_name: str  
    - carrier: str
    - action_required: str (plain-language summary of what needs to be done)
    - deadline: str (date by which action is needed)
    - issues_found: list[str] (specific issues identified)
    - underwriter_name: str
    - underwriter_phone: str
    - severity: str (low/medium/high)
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — falling back to regex extraction")
        return _regex_extract_inspection(email_body, subject, sender)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build message content
    content = []

    # Add PDF documents if available
    if pdf_bytes_list:
        for filename, pdf_bytes in pdf_bytes_list[:3]:  # Max 3 PDFs
            import base64
            b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64,
                },
            })

    # Add the email text
    content.append({
        "type": "text",
        "text": f"""Extract structured inspection details from this carrier email.

EMAIL SUBJECT: {subject}
EMAIL FROM: {sender}
EMAIL BODY:
{email_body[:5000]}

Return a JSON object with these exact fields:
- policy_number (string): The policy number mentioned
- insured_name (string): The customer/insured name
- carrier (string): The insurance carrier name
- action_required (string): Plain-language summary of what the customer needs to do, written as if explaining to a homeowner (not insurance jargon). Be specific about what needs to be fixed.
- deadline (string): The date by which action is needed (format: MM/DD/YYYY). If no specific date, say "As soon as possible"
- issues_found (array of strings): Each specific issue identified by the inspector
- underwriter_name (string): Name of the underwriter who sent this
- underwriter_phone (string): Phone number of the underwriter
- severity (string): "low", "medium", or "high" based on whether non-compliance could result in policy cancellation or non-renewal
- has_pdf_report (boolean): Whether a PDF inspection report was attached

Return ONLY the JSON object, no markdown formatting or explanation."""
    })

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )

        # Parse the response
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        import json
        result = json.loads(text)

        logger.info("Claude extracted inspection details: policy=%s insured=%s deadline=%s",
                    result.get("policy_number"), result.get("insured_name"), result.get("deadline"))
        return result

    except Exception as e:
        logger.error("Claude extraction failed: %s — falling back to regex", e)
        return _regex_extract_inspection(email_body, subject, sender)


def _regex_extract_inspection(email_body: str, subject: str, sender: str) -> dict:
    """Fallback regex extraction when Claude API is unavailable."""
    text = f"{subject} {email_body}"

    # Extract policy number (common formats: HM 6650371, 2033220589, etc.)
    policy_match = re.search(r'(?:(?:HM|PP|DF|AU)\s*)?(\d{6,10})', text)
    policy_number = policy_match.group(0).strip() if policy_match else ""

    # Extract insured name (usually on the line after policy number)
    insured_match = re.search(r'(?:' + re.escape(policy_number) + r')\s*\n\s*([A-Z][A-Za-z\s]+?)(?:\n|$)', text) if policy_number else None
    insured_name = insured_match.group(1).strip() if insured_match else ""

    # Also check subject line for "PolicyNumber InsuredName" pattern
    if not insured_name:
        subj_match = re.search(r'(\d{6,10})\s+([A-Z][A-Za-z\s]+?)$', subject)
        if subj_match:
            if not policy_number:
                policy_number = subj_match.group(1)
            insured_name = subj_match.group(2).strip()

    # Extract deadline
    deadline_match = re.search(
        r'(?:action required by|by|before|deadline)[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})',
        text, re.IGNORECASE
    )
    deadline = deadline_match.group(1) if deadline_match else ""

    carrier = detect_carrier_from_inspection(sender, email_body)

    return {
        "policy_number": policy_number,
        "insured_name": insured_name,
        "carrier": carrier,
        "action_required": "Your insurance carrier has completed an inspection and found items requiring attention. Please review the attached inspection report for details.",
        "deadline": deadline or "As soon as possible",
        "issues_found": ["See attached inspection report for details"],
        "underwriter_name": "",
        "underwriter_phone": "",
        "severity": "medium",
        "has_pdf_report": True,
    }


# ── Customer Email Generation ─────────────────────────────────────────

def build_inspection_customer_email(
    customer_name: str,
    policy_number: str,
    carrier: str,
    details: dict,
) -> tuple[str, str]:
    """Build a customer-friendly inspection follow-up email.
    
    Returns (subject, html_body).
    """
    from app.services.welcome_email import (
        CARRIER_INFO, _get_carrier_key,
        AGENCY_PHONE, AGENCY_NAME, BCI_NAVY, BCI_CYAN,
    )

    carrier_key = _get_carrier_key(carrier)
    info = CARRIER_INFO.get(carrier_key, {}) if carrier_key else {}
    display_carrier = info.get("display_name", carrier.replace("_", " ").title() if carrier else "Your Insurance Carrier")
    accent = info.get("accent_color", BCI_NAVY)

    first_name = (customer_name or "Valued Customer").split()[0]
    deadline = details.get("deadline", "as soon as possible")
    action = details.get("action_required", "Please review the attached inspection report.")
    issues = details.get("issues_found", [])
    severity = details.get("severity", "medium")

    subject = f"Action Required: Home Inspection Follow-Up for Your {display_carrier} Policy"

    # Severity-based header color
    if severity == "high":
        header_bg = "linear-gradient(135deg, #dc2626 0%, #b91c1c 100%)"
        header_icon = "⚠️"
        header_text = "URGENT: Action Required"
    elif severity == "medium":
        header_bg = f"linear-gradient(135deg, #d97706 0%, #b45309 100%)"
        header_icon = "📋"
        header_text = "Action Required"
    else:
        header_bg = f"linear-gradient(135deg, {accent} 0%, {BCI_NAVY} 100%)"
        header_icon = "ℹ️"
        header_text = "Information About Your Policy"

    # Build issues list
    issues_html = ""
    if issues and issues != ["See attached inspection report for details"]:
        issues_items = "".join(
            f'<li style="padding:6px 0;color:#334155;">{issue}</li>'
            for issue in issues
        )
        issues_html = f"""
        <div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:16px 20px;margin:20px 0;">
            <p style="margin:0 0 8px;font-weight:700;color:#9a3412;font-size:14px;">Items Identified:</p>
            <ul style="margin:0;padding-left:20px;">{issues_items}</ul>
        </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

<!-- Header -->
<div style="background:{header_bg};border-radius:16px 16px 0 0;padding:28px 32px;text-align:center;">
    <p style="margin:0 0 4px;font-size:13px;color:rgba(255,255,255,0.85);letter-spacing:1px;font-weight:600;">{header_icon} {header_text}</p>
    <h1 style="margin:0;font-size:20px;color:#ffffff;font-weight:700;">Home Inspection Follow-Up</h1>
</div>

<!-- Body -->
<div style="background:#ffffff;padding:32px;border-radius:0 0 16px 16px;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

    <p style="margin:0 0 16px;font-size:16px;color:#1e293b;">Hi {first_name},</p>

    <p style="margin:0 0 16px;font-size:15px;color:#334155;line-height:1.6;">
        {display_carrier} recently completed a routine home inspection on your policy 
        <strong>{policy_number}</strong> and found one or more items that need your attention.
    </p>

    <!-- What needs to be done -->
    <div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:10px;padding:16px 20px;margin:20px 0;">
        <p style="margin:0 0 8px;font-weight:700;color:#0c4a6e;font-size:14px;">What You Need to Do:</p>
        <p style="margin:0;color:#334155;font-size:14px;line-height:1.6;">{action}</p>
    </div>

    {issues_html}

    <!-- Deadline -->
    <div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;padding:16px 20px;margin:20px 0;text-align:center;">
        <p style="margin:0 0 4px;font-size:13px;color:#991B1B;font-weight:600;">DEADLINE</p>
        <p style="margin:0;font-size:20px;font-weight:700;color:#dc2626;">{deadline}</p>
        <p style="margin:8px 0 0;font-size:13px;color:#7f1d1d;">
            Failure to address these items by the deadline may result in changes to your policy coverage or non-renewal.
        </p>
    </div>

    <!-- PDF note -->
    <p style="margin:20px 0 16px;font-size:14px;color:#334155;line-height:1.6;">
        📎 <strong>We've attached the full inspection report</strong> for your reference. 
        Please review it carefully for complete details on what was identified.
    </p>

    <!-- What to do next -->
    <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:10px;padding:16px 20px;margin:20px 0;">
        <p style="margin:0 0 8px;font-weight:700;color:#166534;font-size:14px;">Once You've Addressed the Items:</p>
        <p style="margin:0;color:#334155;font-size:14px;line-height:1.6;">
            Please send us <strong>photos or documentation</strong> showing the completed work. 
            You can reply directly to this email or send them to 
            <a href="mailto:service@betterchoiceins.com" style="color:{accent};font-weight:600;">service@betterchoiceins.com</a>.
            We'll forward the documentation to {display_carrier} on your behalf.
        </p>
    </div>

    <p style="margin:20px 0 0;font-size:14px;color:#334155;line-height:1.6;">
        If you have any questions or need help understanding the inspection findings, 
        don't hesitate to reach out. We're here to help!
    </p>

    <p style="margin:20px 0 0;font-size:14px;color:#334155;">
        Best regards,<br>
        <strong>{AGENCY_NAME}</strong><br>
        <a href="tel:{AGENCY_PHONE}" style="color:{accent};">{AGENCY_PHONE}</a> · 
        <a href="mailto:service@betterchoiceins.com" style="color:{accent};">service@betterchoiceins.com</a>
    </p>

</div>

<!-- Footer -->
<div style="text-align:center;padding:16px;font-size:12px;color:#94a3b8;">
    <p style="margin:0;">{AGENCY_NAME} · Helping you make the right choice</p>
    <p style="margin:4px 0 0;">Policy: {policy_number} · {display_carrier}</p>
</div>

</div></body></html>"""

    return subject, html


# ── Send Email ────────────────────────────────────────────────────────

def send_inspection_customer_email(
    to_email: str,
    customer_name: str,
    policy_number: str,
    carrier: str,
    details: dict,
    pdf_attachments: list[tuple[str, bytes]] = None,
) -> dict:
    """Send the inspection follow-up email to the customer with PDF attachments."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    if not to_email:
        return {"success": False, "error": "No customer email"}

    subject, html = build_inspection_customer_email(
        customer_name=customer_name,
        policy_number=policy_number,
        carrier=carrier,
        details=details,
    )

    mail_data = {
        "from": f"Better Choice Insurance <service@{settings.MAILGUN_DOMAIN}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "h:Reply-To": "service@betterchoiceins.com",
        "bcc": ["evan@betterchoiceins.com"],
    }

    # Attach PDFs
    files = []
    if pdf_attachments:
        for filename, pdf_bytes in pdf_attachments:
            files.append(("attachment", (filename, pdf_bytes, "application/pdf")))
            logger.info("Attaching %s (%d bytes) to inspection email", filename, len(pdf_bytes))

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            files=files if files else None,
            timeout=30,
        )

        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info("Inspection email sent to %s — msg_id: %s", to_email, msg_id)
            return {"success": True, "message_id": msg_id}
        else:
            logger.error("Mailgun error %s: %s", resp.status_code, resp.text)
            return {"success": False, "error": f"Mailgun {resp.status_code}"}

    except Exception as e:
        logger.error("Inspection email send failed: %s", e)
        return {"success": False, "error": str(e)}


# ── Main Handler ──────────────────────────────────────────────────────

async def handle_inspection_email(
    sender: str,
    subject: str,
    html_body: str,
    plain_body: str,
    attachments: list[tuple[str, bytes]],
    db: Session,
) -> dict:
    """Main handler for inbound inspection emails.
    
    Called from the inbound email webhook when an inspection email is detected.
    
    Args:
        sender: email sender
        subject: email subject
        html_body: HTML body
        plain_body: plain text body
        attachments: list of (filename, bytes) tuples
        db: database session
    
    Returns result dict.
    """
    result = {
        "status": "processed",
        "type": "inspection",
        "mode": INSPECTION_MODE,
        "policy_number": None,
        "customer_name": None,
        "customer_email": None,
        "email_sent": False,
        "nowcerts_note": False,
        "details": None,
    }

    # Separate PDF attachments from others
    pdf_attachments = [
        (name, data) for name, data in attachments
        if name.lower().endswith(".pdf")
    ]

    body_text = plain_body or html_body or ""

    # Step 1: Extract details using Claude API
    try:
        details = await extract_inspection_details(
            email_body=body_text,
            subject=subject,
            sender=sender,
            pdf_bytes_list=pdf_attachments,
        )
    except Exception as e:
        logger.error("Inspection detail extraction failed: %s", e)
        details = _regex_extract_inspection(body_text, subject, sender)

    result["details"] = details
    policy_number = details.get("policy_number", "")
    insured_name = details.get("insured_name", "")
    result["policy_number"] = policy_number

    if not policy_number:
        logger.warning("No policy number extracted from inspection email: %s", subject)
        result["status"] = "error"
        result["error"] = "Could not extract policy number"
        # Still notify Evan
        _send_evan_alert(sender, subject, details, "Could not extract policy number")
        return result

    # Step 2: Look up customer in ORBIT
    customer, policy = _lookup_customer(db, policy_number, insured_name)

    if not customer:
        logger.warning("No customer found for inspection policy %s", policy_number)
        result["status"] = "no_match"
        result["error"] = f"Policy {policy_number} not found in ORBIT"
        _send_evan_alert(sender, subject, details, f"Policy {policy_number} not matched")
        return result

    result["customer_name"] = customer.full_name
    result["customer_email"] = customer.email
    carrier = details.get("carrier") or (policy.carrier if policy else "") or detect_carrier_from_inspection(sender, body_text)

    if not customer.email:
        logger.warning("Customer %s has no email — cannot send inspection notice", customer.full_name)
        result["status"] = "no_email"
        result["error"] = "Customer has no email address"
        _send_evan_alert(sender, subject, details, f"Customer {customer.full_name} has no email")
        return result

    # Step 3: Send customer email (if live mode)
    if INSPECTION_MODE == "live":
        email_result = send_inspection_customer_email(
            to_email=customer.email,
            customer_name=customer.full_name,
            policy_number=policy_number,
            carrier=carrier,
            details=details,
            pdf_attachments=pdf_attachments,
        )
        result["email_sent"] = email_result.get("success", False)
        result["email_message_id"] = email_result.get("message_id")
        if not email_result.get("success"):
            result["email_error"] = email_result.get("error")
    else:
        result["email_sent"] = False
        result["dry_run"] = True
        logger.info("DRY RUN: Would send inspection email to %s for policy %s",
                    customer.email, policy_number)

    # Step 4: Push note to NowCerts
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc_client = get_nowcerts_client()
        if nc_client.is_configured:
            deadline = details.get("deadline", "N/A")
            action = details.get("action_required", "See inspection report")
            issues = details.get("issues_found", [])
            issues_text = "\n".join(f"  • {i}" for i in issues) if issues else "See report"

            note_text = (
                f"ORBIT Auto-Inspection Alert\n"
                f"{'='*40}\n"
                f"Carrier: {carrier}\n"
                f"Policy: {policy_number}\n"
                f"Deadline: {deadline}\n"
                f"Action Required: {action}\n"
                f"Issues Found:\n{issues_text}\n"
                f"{'='*40}\n"
                f"Customer email {'SENT' if result['email_sent'] else 'NOT SENT (dry run)' if INSPECTION_MODE != 'live' else 'FAILED'} to {customer.email}\n"
                f"Original from: {sender}"
            )

            nc_client.insert_note({
                "subject": f"🔍 Inspection Follow-Up — {policy_number} (Deadline: {deadline})",
                "text": note_text,
                "insured_commercial_name": customer.full_name,
                "insured_email": customer.email,
                "insured_database_id": customer.nowcerts_insured_id or "",
                "creator_name": "ORBIT System",
                "type": "Email",
            })
            result["nowcerts_note"] = True
            logger.info("NowCerts note pushed for inspection %s", policy_number)
    except Exception as e:
        logger.warning("NowCerts note failed for inspection %s: %s", policy_number, e)

    # Step 5: Send Evan a summary alert
    _send_evan_alert(sender, subject, details,
                     f"{'Email sent' if result['email_sent'] else 'DRY RUN'} to {customer.email}",
                     customer=customer)

    logger.info("Inspection email processed: policy=%s customer=%s sent=%s mode=%s",
                policy_number, customer.full_name, result["email_sent"], INSPECTION_MODE)
    return result


def _lookup_customer(db: Session, policy_number: str, insured_name: str):
    """Look up customer by policy number, with fallback to name search."""
    # Clean up policy number
    clean_num = policy_number.strip().replace(" ", "")

    # Try exact match
    policy = db.query(CustomerPolicy).filter(
        CustomerPolicy.policy_number == policy_number
    ).first()

    # Try without spaces
    if not policy:
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number == clean_num
        ).first()

    # Try partial/contains match
    if not policy:
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number.ilike(f"%{clean_num}%")
        ).first()

    # Try base number
    if not policy:
        base = clean_num.split("-")[0].split(" ")[0]
        if base and len(base) >= 5:
            policy = db.query(CustomerPolicy).filter(
                CustomerPolicy.policy_number.ilike(f"%{base}%")
            ).first()

    if policy:
        customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()
        return customer, policy

    # Fallback: search by insured name
    if insured_name:
        parts = insured_name.strip().split()
        if len(parts) >= 2:
            customer = db.query(Customer).filter(
                Customer.full_name.ilike(f"%{parts[-1]}%")
            ).first()
            if customer:
                # Get their first active policy
                policy = db.query(CustomerPolicy).filter(
                    CustomerPolicy.customer_id == customer.id,
                    CustomerPolicy.status == "Active",
                ).first()
                return customer, policy

    return None, None


def _send_evan_alert(sender: str, subject: str, details: dict, status_msg: str, customer=None):
    """Send Evan a summary email about the inspection detection."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    policy = details.get("policy_number", "Unknown")
    insured = details.get("insured_name", "Unknown")
    carrier = details.get("carrier", "Unknown")
    deadline = details.get("deadline", "N/A")
    action = details.get("action_required", "N/A")
    issues = details.get("issues_found", [])
    issues_html = "".join(f"<li>{i}</li>" for i in issues) if issues else "<li>See report</li>"

    customer_info = ""
    if customer:
        customer_info = f"""
        <tr><td style="padding:6px 0;color:#64748b;">Customer</td><td style="padding:6px 0;font-weight:600;">{customer.full_name}</td></tr>
        <tr><td style="padding:6px 0;color:#64748b;">Email</td><td style="padding:6px 0;">{customer.email or 'N/A'}</td></tr>"""

    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
    <div style="background:linear-gradient(135deg,#7c3aed,#4f46e5);padding:20px;border-radius:12px 12px 0 0;text-align:center;">
        <h2 style="color:white;margin:0;">🔍 Inspection Email Detected</h2>
        <p style="color:#c4b5fd;margin:4px 0 0;font-size:13px;">{INSPECTION_MODE.upper()} MODE</p>
    </div>
    <div style="background:white;padding:24px;border-radius:0 0 12px 12px;border:1px solid #e2e8f0;">
        <p style="font-weight:700;color:#1e293b;margin:0 0 12px;">Status: {status_msg}</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr><td style="padding:6px 0;color:#64748b;">Policy</td><td style="padding:6px 0;font-weight:700;">{policy}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Insured</td><td style="padding:6px 0;">{insured}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Carrier</td><td style="padding:6px 0;">{carrier}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Deadline</td><td style="padding:6px 0;font-weight:700;color:#dc2626;">{deadline}</td></tr>
            {customer_info}
        </table>
        <div style="margin:16px 0;padding:12px;background:#f8fafc;border-radius:8px;">
            <p style="margin:0 0 8px;font-weight:600;font-size:13px;color:#475569;">Action Required:</p>
            <p style="margin:0;font-size:13px;color:#334155;">{action}</p>
        </div>
        <div style="margin:12px 0;padding:12px;background:#f8fafc;border-radius:8px;">
            <p style="margin:0 0 8px;font-weight:600;font-size:13px;color:#475569;">Issues Found:</p>
            <ul style="margin:0;padding-left:20px;font-size:13px;color:#334155;">{issues_html}</ul>
        </div>
        <p style="margin:12px 0 0;font-size:12px;color:#94a3b8;">From: {sender}<br>Subject: {subject}</p>
    </div></div>"""

    try:
        http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"ORBIT System <system@{settings.MAILGUN_DOMAIN}>",
                "to": ["evan@betterchoiceins.com"],
                "subject": f"🔍 Inspection Alert: {policy} — {carrier} ({status_msg})",
                "html": html,
            },
        )
    except Exception as e:
        logger.warning("Evan alert email failed: %s", e)
