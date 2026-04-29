"""Underwriting item extraction service.

Takes a forwarded email + PDF attachments and extracts:
  - customer name + policy number + carrier
  - what the carrier wants the agent to do (the 'required action')
  - deadline by which the action is needed
  - severity (low/medium/high based on consequence)

Uses Claude API with PDF document support so the actual inspection report
or UW requirement letter contents inform the extraction, not just the email
body. Falls back to regex on the email body alone if AI is unavailable.
"""
import logging
import re
import base64
import json as json_lib
from datetime import datetime, date
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


async def extract_uw_details(
    email_body: str,
    subject: str,
    sender: str,
    pdf_bytes_list: Optional[list[tuple[str, bytes]]] = None,
) -> dict:
    """Use Claude API to extract structured UW details from email + PDFs.

    Returns a dict with keys (all optional, may be None):
      title           — short label for the kanban card
      policy_number
      customer_name
      carrier
      line_of_business — home/auto/commercial/etc
      required_action — plain-language summary
      consequence      — what happens if not done by deadline
      due_date         — ISO date string YYYY-MM-DD or None
      severity         — low/medium/high
      issues           — list of bullet points if multiple
      confidence       — 0-100
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — falling back to regex UW extraction")
        return _regex_extract(email_body, subject, sender)

    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    content = []
    if pdf_bytes_list:
        for filename, pdf_bytes in pdf_bytes_list[:3]:
            try:
                b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64,
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to encode PDF {filename}: {e}")

    today = date.today().isoformat()
    content.append({
        "type": "text",
        "text": f"""You are an insurance agency assistant. A carrier has sent an underwriting requirement
to an independent agency, and the agent has forwarded it to ORBIT for tracking. Extract structured
information so we can manage the deadline.

Today's date is {today}.

EMAIL SUBJECT: {subject}
EMAIL FROM: {sender}
EMAIL BODY:
{email_body[:6000]}

Return a JSON object with these EXACT fields. Use null for missing values, never empty strings.

{{
  "title": (string, max 60 chars: short label for a kanban card, e.g., "Tree trimming required" or "MVR needed"),
  "policy_number": (string or null),
  "customer_name": (string or null: insured/named insured),
  "carrier": (string or null: the insurance carrier - e.g., "National General", "Grange", "Travelers", "Liberty Mutual"),
  "line_of_business": (string or null: "home", "auto", "commercial", "umbrella", or "other"),
  "required_action": (string: plain-language explanation of what the customer or agent needs to do, written for the agent's eyes - 1-3 sentences),
  "consequence": (string or null: what happens if not completed - e.g., "Policy will be non-renewed" or "Premium surcharge applied"),
  "due_date": (string YYYY-MM-DD or null: the deadline date. If only a relative date is given like "30 days from receipt", calculate from today),
  "severity": ("low"|"medium"|"high"),
  "issues": (array of strings: bullet-point list of specific issues if multiple),
  "confidence": (integer 0-100: how confident you are this is a real UW requirement vs spam/marketing/other)
}}

Severity guide:
- HIGH: cancellation or non-renewal threatened, or due in <14 days
- MEDIUM: requirement with 14-60 day deadline, premium impact possible
- LOW: informational, optional, or 60+ days out

Return ONLY the JSON object. No markdown fences, no explanation."""
    })

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )

        text = response.content[0].text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json_lib.loads(text)

        logger.info(
            "UW extraction: policy=%s customer=%s due=%s severity=%s",
            result.get("policy_number"), result.get("customer_name"),
            result.get("due_date"), result.get("severity"),
        )
        return result
    except Exception as e:
        logger.error(f"UW Claude extraction failed: {e} — falling back to regex")
        return _regex_extract(email_body, subject, sender)


def _regex_extract(email_body: str, subject: str, sender: str) -> dict:
    """Best-effort regex fallback when Claude API isn't available."""
    text = f"{subject}\n{email_body}"

    # Policy number — look for sequences of 7+ digits/letters near 'policy'
    policy = None
    m = re.search(r"policy\s*(?:number|#|no\.?)?\s*[:\-]?\s*([A-Z0-9\-]{6,20})", text, re.I)
    if m:
        policy = m.group(1).strip()

    # Carrier — look for known names in subject/body
    carrier = None
    for c, label in [
        ("national general", "National General"), ("ngic", "National General"),
        ("grange", "Grange"), ("travelers", "Travelers"),
        ("liberty mutual", "Liberty Mutual"), ("safeco", "Liberty Mutual"),
        ("progressive", "Progressive"), ("geico", "GEICO"),
        ("openly", "Openly"), ("branch", "Branch"), ("hippo", "Hippo"),
    ]:
        if c in text.lower():
            carrier = label
            break

    # Due date — try several formats
    due = None
    for pat in [
        r"by\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"deadline:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"due\s+(?:by|on)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            try:
                d = m.group(1).replace("-", "/")
                parts = d.split("/")
                if len(parts) == 3:
                    mo, dy, yr = parts
                    if len(yr) == 2:
                        yr = "20" + yr
                    parsed = date(int(yr), int(mo), int(dy))
                    due = parsed.isoformat()
                    break
            except Exception:
                continue

    return {
        "title": (subject[:57] + "...") if len(subject) > 60 else subject,
        "policy_number": policy,
        "customer_name": None,
        "carrier": carrier,
        "line_of_business": None,
        "required_action": email_body[:300] + ("..." if len(email_body) > 300 else ""),
        "consequence": None,
        "due_date": due,
        "severity": "medium",
        "issues": [],
        "confidence": 30,
    }


def lookup_customer_by_policy(db, policy_number: Optional[str], customer_name: Optional[str]):
    """Find the matching customer record from the local DB.

    Returns the Customer object or None.
    """
    if not policy_number and not customer_name:
        return None
    from app.models.customer import Customer, CustomerPolicy

    # First: try exact policy match
    if policy_number:
        clean_pn = policy_number.strip()
        policy = (
            db.query(CustomerPolicy)
            .filter(CustomerPolicy.policy_number.ilike(f"%{clean_pn}%"))
            .first()
        )
        if policy and policy.customer_id:
            customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()
            if customer:
                return customer

    # Fallback: customer name fuzzy match
    if customer_name:
        clean_name = customer_name.strip()
        match = (
            db.query(Customer)
            .filter(Customer.full_name.ilike(f"%{clean_name}%"))
            .first()
        )
        if match:
            return match

    return None
