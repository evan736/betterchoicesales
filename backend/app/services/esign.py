"""BoldSign e-signature service — sends documents for electronic signature."""
import base64
import json
import io
import httpx
from typing import Optional, List
from app.core.config import settings


FIELD_DETECTION_PROMPT = """You are an expert at analyzing insurance application PDFs. 
Scan this PDF and identify EVERY location where the applicant needs to sign, initial, or write a date.

Return ONLY a valid JSON object:
{
  "fields": [
    {
      "type": "Signature",
      "page": 1,
      "x": 100,
      "y": 700,
      "width": 200,
      "height": 50,
      "label": "Applicant Signature"
    }
  ],
  "total_pages": 5
}

FIELD TYPES (use exactly these strings):
- "Signature" — for signature lines, "Sign here", "Applicant Signature", "X___"
- "Initial" — for initial boxes, "Initials", small boxes next to paragraphs
- "DateSigned" — for date fields next to signatures like "Date:", "Date Signed"

COORDINATE SYSTEM:
- PDF pages are 612 x 792 points (standard letter size)
- x=0 is left edge, y=0 is TOP of page
- Signature fields are typically ~200 wide x 50 tall
- Initial fields are typically ~80 wide x 30 tall
- DateSigned fields are typically ~150 wide x 30 tall

Look for:
- Signature lines (horizontal lines with "sign" text nearby)
- "X" marks indicating signature spots
- "Applicant Signature" / "Insured Signature" / "Agent Signature" labels
- Initial boxes (small squares or lines labeled "Initials")
- Date fields adjacent to signature lines
- Any blank line preceded by "Sign", "Signature", "Initial", "Date"

Only include fields for the APPLICANT/INSURED, not the agent.
Return ONLY JSON, no explanation."""


async def detect_signature_fields(pdf_bytes: bytes) -> dict:
    """Use Claude AI to detect signature field locations in the PDF."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    # Truncate to first 20 pages for field detection
    from app.services.pdf_extract import truncate_pdf
    pdf_bytes = truncate_pdf(pdf_bytes, max_pages=20)
    
    pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

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
        raise ValueError(f"Claude API error ({response.status_code}): {response.text[:500]}")

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

    return json.loads(text.strip())


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    fields: List[dict] = None,
) -> dict:
    """Send document to BoldSign for electronic signature.
    Uses BoldSign's built-in AI field detection for accurate placement."""
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError("BOLDSIGN_API_KEY not configured. Set it in Render environment variables.")

    signer_data = {
        "name": signer_name,
        "emailAddress": signer_email,
        "signerType": "Signer",
        "signerRole": "Signer",
        "locale": "EN",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        files = {
            "Files": (f"{title}.pdf", pdf_bytes, "application/pdf"),
        }
        data = {
            "Title": title,
            "Message": f"Please review and sign the attached insurance application.",
            "Signers": json.dumps(signer_data),
            "AutoDetectFields": "true",
            "EnablePrintAndSign": "true",
        }

        response = await client.post(
            "https://api.boldsign.com/v1/document/send",
            headers={
                "accept": "application/json",
                "X-API-KEY": settings.BOLDSIGN_API_KEY,
            },
            data=data,
            files=files,
        )

    if response.status_code not in (200, 201):
        raise ValueError(f"BoldSign API error ({response.status_code}): {response.text[:500]}")

    return response.json()


async def get_document_status(document_id: str) -> dict:
    """Check the status of a BoldSign document."""
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError("BOLDSIGN_API_KEY not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"https://api.boldsign.com/v1/document/properties",
            params={"documentId": document_id},
            headers={
                "accept": "application/json",
                "X-API-KEY": settings.BOLDSIGN_API_KEY,
            },
        )

    if response.status_code != 200:
        raise ValueError(f"BoldSign API error ({response.status_code}): {response.text[:300]}")

    return response.json()
