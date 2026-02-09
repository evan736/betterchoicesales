"""DocuSeal e-signature service with Claude AI field detection.

Flow:
1. Claude AI scans the PDF and finds signature/date/initial field locations
2. Converts coordinates to DocuSeal's ratio format (0-1 range)
3. Sends PDF + field positions to DocuSeal /submissions/pdf
4. DocuSeal emails the signer with fields in the right spots
"""
import base64
import json
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

DOCUSEAL_API_URL = "https://api.docuseal.com"

# Claude prompt to detect signature fields and return DocuSeal-compatible ratios
FIELD_DETECTION_PROMPT = """Analyze this insurance application PDF. Find EVERY place where the applicant/insured needs to sign, initial, or write a date.

Return ONLY valid JSON — no explanation, no markdown:
{
  "fields": [
    {
      "name": "Applicant Signature Page 3",
      "type": "signature",
      "page": 3,
      "x": 0.1,
      "y": 0.85,
      "w": 0.3,
      "h": 0.05
    }
  ]
}

RULES:
- x, y, w, h are RATIOS from 0.0 to 1.0 (fraction of page width/height)
- x=0 is left edge, x=1 is right edge
- y=0 is TOP of page, y=1 is bottom
- Typical signature: w=0.3, h=0.05
- Typical initials: w=0.1, h=0.04
- Typical date field: w=0.2, h=0.04

FIELD TYPES (use exactly):
- "signature" — signature lines, "Sign here", "Applicant Signature", "X___"
- "initials" — initial boxes, small boxes labeled "Initials"  
- "date" — date fields next to signatures

ONLY include fields for the APPLICANT/INSURED, not the agent/producer.
Look on every page for signature lines, X marks, "Sign here" text, blank lines with labels.
Return ONLY JSON."""


async def detect_fields_with_ai(pdf_bytes: bytes) -> list:
    """Use Claude AI to detect signature field locations in the PDF."""
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY — skipping AI field detection")
        return []

    # Truncate to first 20 pages for speed
    try:
        from app.services.pdf_extract import truncate_pdf
        pdf_bytes_truncated = truncate_pdf(pdf_bytes, max_pages=20)
    except Exception:
        pdf_bytes_truncated = pdf_bytes

    pdf_base64 = base64.standard_b64encode(pdf_bytes_truncated).decode("utf-8")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4000,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "document",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "application/pdf",
                                        "data": pdf_base64,
                                    },
                                },
                                {"type": "text", "text": FIELD_DETECTION_PROMPT},
                            ],
                        }
                    ],
                },
            )

        if response.status_code != 200:
            logger.error(f"Claude API error: {response.status_code} {response.text[:300]}")
            return []

        result = response.json()
        text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        data = json.loads(text.strip())
        fields = data.get("fields", [])
        logger.info(f"AI detected {len(fields)} fields")
        return fields

    except Exception as e:
        logger.error(f"AI field detection failed: {e}")
        return []


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
) -> dict:
    """Send PDF to DocuSeal with AI-detected signature fields."""
    if not settings.DOCUSEAL_API_KEY:
        raise ValueError("DOCUSEAL_API_KEY not configured. Set it in Render environment variables.")

    logger.info(f"DocuSeal: sending to {signer_email}, name={signer_name}, pdf_size={len(pdf_bytes)}")

    # Step 1: Detect fields with AI
    ai_fields = await detect_fields_with_ai(pdf_bytes)

    # Step 2: Convert AI fields to DocuSeal format
    docuseal_fields = []
    for f in ai_fields:
        docuseal_fields.append({
            "name": f.get("name", f.get("type", "Signature")),
            "type": f.get("type", "signature"),
            "role": "First Party",
            "required": True,
            "areas": [
                {
                    "x": f.get("x", 0.1),
                    "y": f.get("y", 0.8),
                    "w": f.get("w", 0.3),
                    "h": f.get("h", 0.05),
                    "page": f.get("page", 1),
                }
            ],
        })

    # If no fields detected, add a default signature on page 1
    if not docuseal_fields:
        logger.warning("No AI fields detected — adding default signature field")
        docuseal_fields.append({
            "name": "Applicant Signature",
            "type": "signature",
            "role": "First Party",
            "required": True,
            "areas": [{"x": 0.1, "y": 0.85, "w": 0.3, "h": 0.05, "page": 1}],
        })

    # Step 3: Encode PDF and send to DocuSeal
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "name": title,
        "send_email": True,
        "documents": [
            {
                "name": title,
                "file": pdf_base64,
                "fields": docuseal_fields,
            }
        ],
        "submitters": [
            {
                "role": "First Party",
                "name": signer_name,
                "email": signer_email,
            }
        ],
    }

    logger.info(f"DocuSeal payload: {len(docuseal_fields)} fields, sending to {signer_email}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{DOCUSEAL_API_URL}/submissions/pdf",
            headers={
                "X-Auth-Token": settings.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )

    logger.info(f"DocuSeal response: status={response.status_code}, body={response.text[:500]}")

    if response.status_code not in (200, 201):
        raise ValueError(f"DocuSeal API error ({response.status_code}): {response.text[:500]}")

    result = response.json()

    submission_id = None
    if isinstance(result, list) and len(result) > 0:
        submission_id = result[0].get("submission_id")
    elif isinstance(result, dict):
        submission_id = result.get("id") or result.get("submission_id")

    return {
        "documentId": str(submission_id) if submission_id else "unknown",
        "fields_detected": len(docuseal_fields),
    }


async def get_document_status(submission_id: str) -> dict:
    """Check the status of a DocuSeal submission."""
    if not settings.DOCUSEAL_API_KEY:
        raise ValueError("DOCUSEAL_API_KEY not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{DOCUSEAL_API_URL}/submissions/{submission_id}",
            headers={
                "X-Auth-Token": settings.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
        )

    if response.status_code != 200:
        raise ValueError(f"DocuSeal API error ({response.status_code}): {response.text[:300]}")

    return response.json()
