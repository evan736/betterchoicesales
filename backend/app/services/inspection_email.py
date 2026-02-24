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

    # ── Detect specific issue types for better action text ──
    text_lower = text.lower()
    issues = []
    action = ""
    severity = "medium"

    # Coverage A revision detection
    if "coverage a revision" in text_lower or "coverage a" in text_lower:
        issues.append("Coverage A (dwelling coverage) revision required")
        action = (
            "Your insurance carrier has reviewed your property and determined that your dwelling coverage (Coverage A) "
            "needs to be updated. This is typically based on a recent inspection or updated property valuation. "
            "Please contact us so we can review and process the coverage adjustment for your policy."
        )
        severity = "medium"

    # Policy adjustment detection
    if "policy adjustment" in text_lower:
        issues.append("Policy adjustment(s) needed")
        if not action:
            action = (
                "Your insurance carrier has identified adjustments needed on your policy based on a recent review. "
                "Please contact us so we can go over the changes and update your policy accordingly."
            )

    # Inspection-specific items
    if any(kw in text_lower for kw in ["railing", "deck", "fall exposure", "handrail"]):
        issues.append("Railing/deck safety concerns identified")
    if any(kw in text_lower for kw in ["roof", "shingle", "missing"]):
        issues.append("Roof condition issues identified")
    if any(kw in text_lower for kw in ["siding", "exterior"]):
        issues.append("Exterior maintenance items identified")
    if "photo documentation" in text_lower or "photo" in text_lower:
        issues.append("Photo documentation of repairs required")

    # Letter not mailed detection (NatGen pattern)
    if "not been mailed" in text_lower or "please notify the insured" in text_lower:
        if not action:
            action = (
                "Your insurance carrier has sent us a notice regarding your policy that requires your attention. "
                "Please contact us at your earliest convenience so we can review the details and help resolve any required items."
            )
        if not issues:
            issues.append("Carrier notice requires customer notification")

    # General fallback
    if not action:
        action = (
            "Your insurance carrier has completed a review of your policy and found items requiring attention. "
            "Please review the attached report for details and contact us if you need help understanding what needs to be done."
        )
    if not issues:
        issues.append("See attached inspection report for details")

    # Severity escalation
    if any(kw in text_lower for kw in ["cancel", "non-renew", "non-renewal", "terminated"]):
        severity = "high"

    return {
        "policy_number": policy_number,
        "insured_name": insured_name,
        "carrier": carrier,
        "action_required": action,
        "deadline": deadline or "As soon as possible",
        "issues_found": issues,
        "underwriter_name": "",
        "underwriter_phone": "",
        "severity": severity,
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

    # Determine if this is a physical repair (needs photos) or a coverage/policy change (needs contact)
    all_text = f"{action} {' '.join(issues)}".lower()
    is_physical_repair = any(kw in all_text for kw in [
        "railing", "deck", "roof", "siding", "repair", "install", "replace", "fix",
        "photo", "stairs", "handrail", "gutter", "tree", "brush", "chimney",
        "foundation", "electrical", "plumbing", "mold", "water damage",
    ])
    is_coverage_change = any(kw in all_text for kw in [
        "coverage a", "dwelling", "coverage revision", "policy adjustment",
        "increase", "limit", "valuation", "replacement cost",
    ])
    has_pdf = bool(details.get("has_pdf_report") or details.get("attachment_info"))

    # Determine subject line based on type
    if is_coverage_change and not is_physical_repair:
        subject = f"Action Required: Policy Update for Your {display_carrier} Policy"
        intro_text = (
            f"{display_carrier} has completed a review of your policy "
            f"<strong>{policy_number}</strong> and identified updates that need to be made."
        )
        header_title = "Policy Update Required"
    else:
        subject = f"Action Required: Home Inspection Follow-Up for Your {display_carrier} Policy"
        intro_text = (
            f"{display_carrier} recently completed a routine home inspection on your policy "
            f"<strong>{policy_number}</strong> and found one or more items that need your attention."
        )
        header_title = "Home Inspection Follow-Up"

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
    <h1 style="margin:0;font-size:20px;color:#ffffff;font-weight:700;">{header_title}</h1>
</div>

<!-- Body -->
<div style="background:#ffffff;padding:32px;border-radius:0 0 16px 16px;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

    <p style="margin:0 0 16px;font-size:16px;color:#1e293b;">Hi {first_name},</p>

    <p style="margin:0 0 16px;font-size:15px;color:#334155;line-height:1.6;">
        {intro_text}
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

    <!-- PDF note (only if attachments present) -->
    {f'''<p style="margin:20px 0 16px;font-size:14px;color:#334155;line-height:1.6;">
        📎 <strong>We've attached the full report</strong> for your reference. 
        Please review it carefully for complete details.
    </p>''' if has_pdf else ''}

    <!-- Next steps — varies by issue type -->
    {f'''<div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:10px;padding:16px 20px;margin:20px 0;">
        <p style="margin:0 0 8px;font-weight:700;color:#166534;font-size:14px;">Once You've Addressed the Items:</p>
        <p style="margin:0;color:#334155;font-size:14px;line-height:1.6;">
            Please send us <strong>photos or documentation</strong> showing the completed work. 
            You can reply directly to this email or send them to 
            <a href="mailto:service@betterchoiceins.com" style="color:{accent};font-weight:600;">service@betterchoiceins.com</a>.
            We'll forward the documentation to {display_carrier} on your behalf.
        </p>
    </div>''' if is_physical_repair else f'''<div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:10px;padding:16px 20px;margin:20px 0;">
        <p style="margin:0 0 8px;font-weight:700;color:#166534;font-size:14px;">What Happens Next:</p>
        <p style="margin:0;color:#334155;font-size:14px;line-height:1.6;">
            Please give us a call or reply to this email so we can review these changes together. 
            We'll walk you through what's needed and take care of any updates with {display_carrier} on your behalf.
        </p>
    </div>'''}

    <p style="margin:20px 0 0;font-size:14px;color:#334155;line-height:1.6;">
        If you have any questions{' or need help understanding the findings' if is_physical_repair else ''}, 
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
    
    Draft+Approve flow:
    1. Extract details via Claude API
    2. Look up customer
    3. Generate draft email
    4. Store draft in DB with approval_token
    5. Create task in ORBIT
    6. Send Evan approval email with preview + one-click approve button
    7. Push NowCerts note
    
    Nothing goes to the customer until Evan clicks "Approve & Send".
    """
    import pickle
    import uuid
    from app.models.inspection import InspectionDraft
    from app.models.task import Task

    result = {
        "status": "draft_created",
        "type": "inspection",
        "policy_number": None,
        "customer_name": None,
        "customer_email": None,
        "draft_id": None,
        "task_id": None,
        "nowcerts_note": False,
    }

    # Separate PDF attachments
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

    policy_number = details.get("policy_number", "")
    insured_name = details.get("insured_name", "")
    result["policy_number"] = policy_number

    if not policy_number:
        logger.warning("No policy number extracted from inspection email: %s", subject)
        result["status"] = "error"
        result["error"] = "Could not extract policy number"
        _send_evan_alert_no_match(sender, subject, details, "Could not extract policy number")
        return result

    # Step 2: Look up customer
    customer, policy = _lookup_customer(db, policy_number, insured_name)
    carrier = details.get("carrier") or (policy.carrier if policy else "") or detect_carrier_from_inspection(sender, body_text)

    if customer:
        result["customer_name"] = customer.full_name
        result["customer_email"] = customer.email

    # Step 3: Generate draft email
    draft_subject, draft_html = build_inspection_customer_email(
        customer_name=customer.full_name if customer else insured_name,
        policy_number=policy_number,
        carrier=carrier,
        details=details,
    )

    # Step 4: Store draft in DB
    approval_token = str(uuid.uuid4())

    # Serialize PDF attachments for storage
    att_data = None
    att_info = []
    if pdf_attachments:
        att_info = [{"filename": name, "size": len(data)} for name, data in pdf_attachments]
        att_data = pickle.dumps(pdf_attachments)

    # ── Dedup: skip if a pending draft already exists for this policy ──
    existing = db.query(InspectionDraft).filter(
        InspectionDraft.policy_number == policy_number,
        InspectionDraft.status == "pending_review",
    ).first()
    if existing:
        logger.info(f"Inspection draft already pending for policy {policy_number} (draft #{existing.id}) — skipping duplicate")
        return {
            "status": "duplicate_skipped",
            "existing_draft_id": existing.id,
            "policy_number": policy_number,
        }

    draft = InspectionDraft(
        status="pending_review",
        approval_token=approval_token,
        source_sender=sender,
        source_subject=subject,
        policy_number=policy_number,
        customer_name=customer.full_name if customer else insured_name,
        customer_email=customer.email if customer else None,
        carrier=carrier,
        deadline=details.get("deadline", ""),
        action_required=details.get("action_required", ""),
        issues_found=details.get("issues_found", []),
        severity=details.get("severity", "medium"),
        extraction_details=details,
        customer_id=customer.id if customer else None,
        draft_subject=draft_subject,
        draft_html=draft_html,
        attachment_info=att_info,
        attachment_data=att_data,
    )
    db.add(draft)
    db.flush()  # Get the ID
    result["draft_id"] = draft.id

    # Step 5: Create task in ORBIT
    try:
        deadline_str = details.get("deadline", "")
        due_date = None
        if deadline_str:
            for fmt in ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"]:
                try:
                    due_date = datetime.strptime(deadline_str, fmt)
                    break
                except ValueError:
                    continue

        # Dedup: skip if an open inspection task already exists for this policy
        existing_task = db.query(Task).filter(
            Task.policy_number == policy_number,
            Task.task_type == "inspection",
            Task.status.in_(["open", "in_progress"]),
        ).first()
        if existing_task:
            logger.info(f"Inspection task already exists for {policy_number} (task #{existing_task.id}) — linking draft")
            draft.task_id = existing_task.id
            result["task_id"] = existing_task.id
        else:
            task = Task(
                title=f"Inspection Follow-Up: {policy_number} ({carrier})",
                description=(
                    f"Carrier inspection found issues requiring customer action.\n\n"
                    f"Action Required: {details.get('action_required', 'See report')}\n"
                    f"Deadline: {deadline_str}\n"
                    f"Issues: {', '.join(details.get('issues_found', []))}\n\n"
                    f"Draft email pending approval (Draft #{draft.id})"
                ),
                task_type="inspection",
                priority="high" if details.get("severity") == "high" else "medium",
                status="open",
                created_by="system",
                customer_name=customer.full_name if customer else insured_name,
                policy_number=policy_number,
                carrier=carrier,
                due_date=due_date,
                source="inspection_email",
                notes=f"From: {sender}\nSubject: {subject}",
            )
            db.add(task)
            db.flush()
            draft.task_id = task.id
            result["task_id"] = task.id
    except Exception as e:
        logger.warning("Task creation failed for inspection %s: %s", policy_number, e)

    db.commit()

    # Step 6: Send Evan approval email (with PDF attachments so Evan can review)
    _send_evan_approval_email(draft, details, sender, subject, customer, pdf_attachments=pdf_attachments)

    # Step 7: Push NowCerts note
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if nc.is_configured and customer:
            nc.insert_note({
                "subject": f"🔍 Inspection Received — {policy_number} (Deadline: {details.get('deadline', 'N/A')})",
                "text": (
                    f"Carrier inspection email received.\n"
                    f"Carrier: {carrier}\nPolicy: {policy_number}\n"
                    f"Deadline: {details.get('deadline', 'N/A')}\n"
                    f"Action: {details.get('action_required', 'See report')}\n"
                    f"Customer email DRAFTED — awaiting approval."
                ),
                "insured_commercial_name": customer.full_name,
                "insured_email": customer.email or "",
                "insured_database_id": customer.nowcerts_insured_id or "",
                "creator_name": "ORBIT System",
                "type": "Email",
            })
            result["nowcerts_note"] = True
    except Exception as e:
        logger.warning("NowCerts note failed: %s", e)

    logger.info("Inspection draft created: id=%s policy=%s customer=%s",
                draft.id, policy_number, customer.full_name if customer else "unknown")
    return result


def approve_and_send(draft_id: int, db: Session, approved_by: str = "evan") -> dict:
    """Approve a pending inspection draft and send the customer email.
    
    Called when Evan clicks the "Approve & Send" button.
    """
    import pickle
    from app.models.inspection import InspectionDraft
    from app.models.task import Task

    draft = db.query(InspectionDraft).filter(InspectionDraft.id == draft_id).first()
    if not draft:
        return {"success": False, "error": "Draft not found"}

    if draft.status != "pending_review":
        return {"success": False, "error": f"Draft already {draft.status}"}

    if not draft.customer_email:
        return {"success": False, "error": "No customer email on file"}

    # Restore PDF attachments
    pdf_attachments = []
    if draft.attachment_data:
        try:
            pdf_attachments = pickle.loads(draft.attachment_data)
        except Exception as e:
            logger.warning("Failed to restore attachments: %s", e)

    # Send the email
    email_result = send_inspection_customer_email(
        to_email=draft.customer_email,
        customer_name=draft.customer_name,
        policy_number=draft.policy_number,
        carrier=draft.carrier,
        details=draft.extraction_details or {},
        pdf_attachments=pdf_attachments,
    )

    # Update draft
    draft.approved_by = approved_by
    draft.approved_at = datetime.utcnow()

    if email_result.get("success"):
        draft.status = "sent"
        draft.mailgun_message_id = email_result.get("message_id")

        # Update linked task: mark as sent but keep open for follow-ups
        if draft.task_id:
            task = db.query(Task).filter(Task.id == draft.task_id).first()
            if task:
                task.last_sent_at = datetime.utcnow()
                task.send_count = (task.send_count or 0) + 1
                task.last_send_method = "email"
                task.customer_email = draft.customer_email

        # Push NowCerts note
        try:
            from app.services.nowcerts_notes import push_nowcerts_note
            note_text = (
                f"📧 Inspection follow-up email sent to {draft.customer_email}\n"
                f"Policy: {draft.policy_number} | Carrier: {draft.carrier}\n"
                f"Action Required: {(draft.extraction_details or {}).get('action_required', 'See email')}\n"
                f"Deadline: {draft.deadline or 'N/A'}\n"
                f"Sent by: {approved_by} via ORBIT"
            )
            push_nowcerts_note(db, draft.policy_number, note_text)
        except Exception as e:
            logger.warning("NowCerts note push failed for inspection %s: %s", draft.policy_number, e)
    else:
        draft.status = "send_failed"
        draft.send_error = email_result.get("error")

    db.commit()

    return {
        "success": email_result.get("success", False),
        "draft_id": draft.id,
        "status": draft.status,
        "message_id": email_result.get("message_id"),
        "error": email_result.get("error"),
    }


def approve_by_token(token: str, db: Session) -> dict:
    """Approve a draft by its approval token (from email link)."""
    from app.models.inspection import InspectionDraft

    draft = db.query(InspectionDraft).filter(
        InspectionDraft.approval_token == token
    ).first()

    if not draft:
        return {"success": False, "error": "Invalid approval token"}

    return approve_and_send(draft.id, db, approved_by="evan_email_link")


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


def _send_evan_alert_no_match(sender: str, subject: str, details: dict, status_msg: str):
    """Send Evan an alert when we can't match the policy — no approve button."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    policy = details.get("policy_number", "Unknown")
    carrier = details.get("carrier", "Unknown")
    action = details.get("action_required", "N/A")

    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
    <div style="background:linear-gradient(135deg,#dc2626,#b91c1c);padding:20px;border-radius:12px 12px 0 0;text-align:center;">
        <h2 style="color:white;margin:0;">🔍 Inspection Email — Needs Manual Review</h2>
    </div>
    <div style="background:white;padding:24px;border-radius:0 0 12px 12px;border:1px solid #e2e8f0;">
        <p style="font-weight:700;color:#dc2626;margin:0 0 12px;">⚠️ {status_msg}</p>
        <p style="font-size:14px;color:#334155;">Policy: <strong>{policy}</strong> · Carrier: {carrier}</p>
        <p style="font-size:13px;color:#64748b;">Action: {action}</p>
        <p style="font-size:12px;color:#94a3b8;margin-top:12px;">From: {sender}<br>Subject: {subject}</p>
    </div></div>"""

    try:
        http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"ORBIT System <system@{settings.MAILGUN_DOMAIN}>",
                "to": ["evan@betterchoiceins.com"],
                "subject": f"🔍 Inspection Alert: {policy} — {status_msg}",
                "html": html,
            },
        )
    except Exception as e:
        logger.warning("Evan alert failed: %s", e)


def _send_evan_approval_email(draft, details: dict, sender: str, subject: str, customer=None, pdf_attachments=None):
    """Send Evan an approval email with draft preview, one-click Approve button, and PDF attachments."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    from app.core.config import settings as app_settings

    policy = details.get("policy_number", "Unknown")
    carrier = details.get("carrier", "Unknown")
    deadline = details.get("deadline", "N/A")
    action = details.get("action_required", "N/A")
    issues = details.get("issues_found", [])
    issues_html = "".join(f"<li>{i}</li>" for i in issues) if issues else "<li>See report</li>"
    severity = details.get("severity", "medium")

    severity_badge = {
        "high": '<span style="background:#dc2626;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">HIGH</span>',
        "medium": '<span style="background:#d97706;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">MEDIUM</span>',
        "low": '<span style="background:#2563eb;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">LOW</span>',
    }.get(severity, "")

    customer_name = customer.full_name if customer else draft.customer_name or "Unknown"
    customer_email = customer.email if customer else draft.customer_email or "N/A"

    # Approval URL
    api_base = "https://better-choice-api.onrender.com"
    approve_url = f"{api_base}/api/inspection/approve/{draft.approval_token}"

    att_count = len(details.get("issues_found", [])) or 0
    att_info = draft.attachment_info or []
    pdf_list = ", ".join(a["filename"] for a in att_info) if att_info else "None"

    html = f"""<div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#7c3aed,#4f46e5);padding:24px;border-radius:12px 12px 0 0;text-align:center;">
        <h2 style="color:white;margin:0 0 4px;">🔍 Inspection Email — Review Draft</h2>
        <p style="color:#c4b5fd;margin:0;font-size:13px;">Approve to send customer email</p>
    </div>

    <div style="background:white;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e2e8f0;">

        <!-- Key Details -->
        <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px;">
            <tr><td style="padding:6px 0;color:#64748b;width:120px;">Policy</td><td style="padding:6px 0;font-weight:700;">{policy}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Carrier</td><td style="padding:6px 0;">{carrier}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Customer</td><td style="padding:6px 0;font-weight:600;">{customer_name}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Email</td><td style="padding:6px 0;">{customer_email}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Deadline</td><td style="padding:6px 0;font-weight:700;color:#dc2626;">{deadline}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Severity</td><td style="padding:6px 0;">{severity_badge}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">PDFs</td><td style="padding:6px 0;font-size:13px;">{pdf_list}</td></tr>
        </table>

        <!-- Action Required -->
        <div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:8px;padding:14px;margin-bottom:16px;">
            <p style="margin:0 0 6px;font-weight:700;color:#0c4a6e;font-size:13px;">What the customer will be told:</p>
            <p style="margin:0;font-size:14px;color:#334155;line-height:1.5;">{action}</p>
        </div>

        <!-- Issues -->
        <div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:8px;padding:14px;margin-bottom:20px;">
            <p style="margin:0 0 6px;font-weight:700;color:#9a3412;font-size:13px;">Issues Found:</p>
            <ul style="margin:0;padding-left:18px;font-size:13px;color:#334155;">{issues_html}</ul>
        </div>

        <!-- APPROVE BUTTON -->
        <div style="text-align:center;margin:24px 0;">
            <a href="{approve_url}" 
               style="display:inline-block;background:linear-gradient(135deg,#059669,#10b981);color:white;padding:16px 48px;border-radius:10px;text-decoration:none;font-weight:700;font-size:16px;box-shadow:0 4px 12px rgba(5,150,105,0.3);">
                ✅ Approve & Send to Customer
            </a>
        </div>
        <p style="text-align:center;font-size:12px;color:#94a3b8;margin:0;">
            This will send the drafted email with PDF attachments to {customer_email}
        </p>

        <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">
        <p style="font-size:12px;color:#94a3b8;margin:0;">
            Original from: {sender}<br>
            Subject: {subject}<br>
            Draft #{draft.id}
        </p>
    </div></div>"""

    try:
        mail_data = {
            "from": f"ORBIT System <system@{settings.MAILGUN_DOMAIN}>",
            "to": ["evan@betterchoiceins.com"],
            "subject": f"🔍 APPROVE? Inspection: {policy} — {carrier} ({customer_name})",
            "html": html,
        }

        # Attach PDFs so Evan can review what the customer will receive
        files = []
        if pdf_attachments:
            for filename, pdf_bytes in pdf_attachments:
                files.append(("attachment", (filename, pdf_bytes, "application/pdf")))
                logger.info("Attaching %s (%d bytes) to approval email", filename, len(pdf_bytes))

        http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            files=files if files else None,
        )
        logger.info("Approval email sent for draft #%s (with %d attachments)", draft.id, len(files))
    except Exception as e:
        logger.warning("Approval email failed: %s", e)
