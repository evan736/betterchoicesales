"""
Smart Inbox AI Service — classifies inbound emails and drafts responses.

Uses Anthropic Claude API to:
1. Parse email content → extract policy numbers, customer info, category
2. Classify sensitivity (routine vs. sensitive)
3. Draft appropriate client communication when needed
"""
import os
import json
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("SMART_INBOX_MODEL", "claude-sonnet-4-5-20250929")

AGENCY_NAME = "Better Choice Insurance"
AGENCY_PHONE = os.getenv("AGENCY_PHONE", "(555) 555-5555")
AGENCY_EMAIL = os.getenv("AGENCY_FROM_EMAIL", "evan@betterchoiceins.com")


# ── Classification Prompt ────────────────────────────────────────────────────

CLASSIFICATION_PROMPT = """You are an AI assistant for an insurance agency called Better Choice Insurance. 
You are analyzing a forwarded email to classify it and extract key information.

Analyze this email and respond with a JSON object (no markdown, just raw JSON):

{{
  "category": "<one of: non_payment, cancellation, non_renewal, underwriting_requirement, renewal_notice, policy_change, claim_notice, billing_inquiry, customer_request, general_inquiry, endorsement, new_business_confirmation, audit_notice, other>",
  "sensitivity": "<one of: routine, moderate, sensitive, critical>",
  "summary": "<one-line plain English summary of what this email is about>",
  "extracted": {{
    "policy_number": "<policy number if found, null otherwise>",
    "insured_name": "<insured/customer name if found, null otherwise>",
    "carrier": "<insurance carrier name if found, null otherwise>",
    "due_date": "<any deadline or due date in YYYY-MM-DD format, null otherwise>",
    "amount": <dollar amount if relevant, null otherwise>,
    "phone": "<phone number if found, null otherwise>",
    "email": "<customer email if found, null otherwise>"
  }},
  "needs_client_communication": true/false,
  "communication_urgency": "<immediate, within_24h, within_week, none>",
  "communication_reason": "<why the client needs to be contacted, or null>",
  "confidence": <0.0-1.0 confidence in classification>
}}

SENSITIVITY RULES:
- "routine": Payment reminders, standard renewal notices, policy confirmations, basic status updates
- "moderate": Underwriting requirements, endorsement requests, billing inquiries  
- "sensitive": Cancellation notices, non-renewal notices, claim notices, coverage disputes
- "critical": Immediate cancellation, lapse in coverage, legal notices, compliance issues

EMAIL TO ANALYZE:
From: {from_address}
Subject: {subject}
Date: {date}

{body}
"""


# ── Response Draft Prompt ────────────────────────────────────────────────────

RESPONSE_DRAFT_PROMPT = """You are writing an email on behalf of Better Choice Insurance Group to a customer.

CONTEXT:
- This is regarding: {summary}
- Category: {category}  
- Carrier: {carrier}
- Policy Number: {policy_number}
- Customer Name: {customer_name}

ORIGINAL EMAIL CONTENT (that triggered this):
{original_body}

Write a professional, warm, and helpful email to the customer. Guidelines:
- Address the customer by first name
- Be empathetic and solution-oriented
- Include specific action items if applicable
- Include deadlines if they exist
- Keep it concise — 2-4 short paragraphs max
- Do NOT include any header, logo, or signature block — just the message paragraphs
- Do NOT include a subject line in the body
- Do NOT wrap in full HTML document tags — just provide the inner content paragraphs as simple HTML (<p> tags, <strong> for emphasis)
- End with something like "If you have any questions, don't hesitate to reach out."

Also provide a subject line separately.

Respond with JSON (no markdown):
{{
  "subject": "<email subject line>",
  "body_html": "<just the inner message paragraphs as HTML>",
  "body_plain": "<plain text version>",
  "rationale": "<1-2 sentence explanation of why this communication is needed>"
}}
"""


def wrap_branded_email(inner_html: str, customer_name: str = "Valued Customer") -> str:
    """Wrap AI-generated email content in the BCI branded template."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:20px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg, #1a2b5f 0%, #0c4a6e 100%); border-radius:16px 16px 0 0; padding:28px 32px; text-align:center;">
        <h1 style="margin:0; color:#ffffff; font-size:20px; font-weight:700; letter-spacing:-0.3px;">Better Choice Insurance Group</h1>
        <p style="margin:6px 0 0; color:#2cb5e8; font-size:13px; font-weight:500;">Your trusted insurance partner</p>
    </div>

    <!-- Body -->
    <div style="background:#ffffff; padding:32px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">
        <div style="font-size:15px; color:#334155; line-height:1.7;">
            {inner_html}
        </div>
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc; padding:24px 32px; border-radius:0 0 16px 16px; border:1px solid #e2e8f0; border-top:none; text-align:center;">
        <p style="margin:0 0 4px; font-size:14px; color:#1e293b; font-weight:600;">Better Choice Insurance Group</p>
        <p style="margin:0 0 2px; font-size:13px; color:#64748b;">
            <a href="tel:8479085665" style="color:#2cb5e8; text-decoration:none; font-weight:600;">847-908-5665</a>
        </p>
        <p style="margin:0 0 2px; font-size:13px; color:#64748b;">
            <a href="mailto:service@betterchoiceins.com" style="color:#2cb5e8; text-decoration:none;">service@betterchoiceins.com</a>
        </p>
        <p style="margin:0; font-size:13px; color:#64748b;">
            <a href="https://www.betterchoiceins.com" style="color:#2cb5e8; text-decoration:none;">www.betterchoiceins.com</a>
        </p>
        <hr style="border:none; border-top:1px solid #e2e8f0; margin:16px 0;">
        <p style="margin:0; font-size:11px; color:#94a3b8; line-height:1.5;">
            This message was sent by Better Choice Insurance Group. If you believe this was sent in error, please contact us at 847-908-5665.
        </p>
    </div>

</div>
</body>
</html>"""


async def classify_email(
    from_address: str,
    subject: str,
    body: str,
    date: Optional[str] = None,
    attachments: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Send email content to Claude for classification and data extraction.
    Supports PDF and image attachments via Claude's vision API.
    Returns parsed classification dict or error dict.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set — cannot classify email")
        return {"error": "ANTHROPIC_API_KEY not configured", "category": "other", "sensitivity": "sensitive"}

    prompt = CLASSIFICATION_PROMPT.format(
        from_address=from_address or "Unknown",
        subject=subject or "(no subject)",
        date=date or datetime.utcnow().strftime("%Y-%m-%d"),
        body=(body or "")[:8000],  # Truncate very long emails
    )

    # Build message content with attachments
    content = []

    # Add PDF/image attachments as vision content
    if attachments:
        for att in attachments:
            try:
                ct = att.get("content_type", "")
                b64 = att.get("base64_data", "")
                fname = att.get("filename", "unknown")
                if not b64:
                    continue

                if ct == "application/pdf":
                    content.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    })
                    content.append({
                        "type": "text",
                        "text": f"[The above is an attached PDF document: {fname}. Include information from this PDF in your analysis.]",
                    })
                    logger.info(f"Including PDF attachment in AI analysis: {fname}")
                elif ct.startswith("image/"):
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": ct,
                            "data": b64,
                        },
                    })
                    content.append({
                        "type": "text",
                        "text": f"[The above is an attached image: {fname}. Include information from this image in your analysis.]",
                    })
                    logger.info(f"Including image attachment in AI analysis: {fname}")
            except Exception as e:
                logger.warning(f"Failed to include attachment in AI call: {e}")

    # Add the classification prompt text
    content.append({"type": "text", "text": prompt})

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": content}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract text from response
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        # Parse JSON from response (handle potential markdown wrapping)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)
        logger.info(f"Email classified: category={result.get('category')}, sensitivity={result.get('sensitivity')}")
        return result

    except httpx.HTTPStatusError as e:
        logger.error(f"Anthropic API error: {e.response.status_code} — {e.response.text[:200]}")
        return {"error": f"API error: {e.response.status_code}", "category": "other", "sensitivity": "sensitive"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        return {"error": "JSON parse error", "category": "other", "sensitivity": "sensitive"}
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return {"error": str(e), "category": "other", "sensitivity": "sensitive"}


async def draft_response(
    summary: str,
    category: str,
    carrier: Optional[str],
    policy_number: Optional[str],
    customer_name: str,
    original_body: str,
) -> Dict[str, Any]:
    """
    Ask Claude to draft a customer-facing email response.
    Returns dict with subject, body_html, body_plain, rationale.
    """
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    prompt = RESPONSE_DRAFT_PROMPT.format(
        summary=summary or "Unknown",
        category=category or "other",
        carrier=carrier or "Unknown carrier",
        policy_number=policy_number or "N/A",
        customer_name=customer_name or "Valued Customer",
        original_body=(original_body or "")[:6000],
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)
        # Wrap the AI-generated body in the branded email template
        if result.get("body_html"):
            result["body_html"] = wrap_branded_email(
                result["body_html"],
                customer_name=customer_name,
            )
        return result

    except Exception as e:
        logger.error(f"Response drafting failed: {e}")
        return {"error": str(e)}


def determine_auto_send(category: str, sensitivity: str) -> bool:
    """
    Decide if an outbound email should auto-send or queue for approval.
    
    Auto-send (routine):
      - Payment reminders / non-payment notices
      - Renewal notices
      - Policy confirmations
      - Basic billing updates
    
    Queue for approval (sensitive/critical):
      - Cancellations
      - Non-renewals
      - Claims
      - Coverage disputes
      - Anything classified as sensitive/critical
    """
    if sensitivity in ("sensitive", "critical"):
        return False

    auto_send_categories = {
        "non_payment",
        "renewal_notice",
        "new_business_confirmation",
        "billing_inquiry",
        "endorsement",
        "policy_change",
    }

    return category in auto_send_categories and sensitivity == "routine"
