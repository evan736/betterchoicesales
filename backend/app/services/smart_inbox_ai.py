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

RESPONSE_DRAFT_PROMPT = """You are writing an email on behalf of Better Choice Insurance to a customer.

CONTEXT:
- This is regarding: {summary}
- Category: {category}  
- Carrier: {carrier}
- Policy Number: {policy_number}
- Customer Name: {customer_name}

ORIGINAL EMAIL CONTENT (that triggered this):
{original_body}

Write a professional, warm, and helpful email to the customer. Guidelines:
- Be empathetic and solution-oriented
- Include specific action items if applicable
- Include deadlines if they exist
- Sign off as Better Choice Insurance team
- Do NOT include a subject line in the body
- Keep it concise but thorough

Also provide a subject line separately.

Respond with JSON (no markdown):
{{
  "subject": "<email subject line>",
  "body_html": "<HTML formatted email body with <p> tags, <strong> for emphasis, etc.>",
  "body_plain": "<plain text version>",
  "rationale": "<1-2 sentence explanation of why this communication is needed>"
}}
"""


async def classify_email(
    from_address: str,
    subject: str,
    body: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send email content to Claude for classification and data extraction.
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
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
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
