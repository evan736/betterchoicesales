"""PDF extraction service — uses Claude API to parse insurance applications."""
import base64
import json
import io
import httpx
from typing import Optional
from app.core.config import settings

EXTRACTION_PROMPT = """You are an expert insurance document parser. Analyze this PDF insurance application/declaration page and extract the following data.

Return ONLY a valid JSON object with these fields:

{
  "client_name": "Full name of the primary insured/applicant",
  "client_email": "Email address if found, or null",
  "client_phone": "Phone number if found, or null",
  "carrier": "Insurance carrier/company name",
  "state": "Two-letter state code (e.g. IL, CA, FL)",
  "policies": [
    {
      "policy_number": "Policy number if visible, or null",
      "policy_type": "auto|home|renters|condo|landlord|umbrella|motorcycle|boat|rv|life|health|bundled|commercial|other",
      "written_premium": 1234.56,
      "item_count": 1,
      "effective_date": "YYYY-MM-DD or null",
      "notes": "Brief description, e.g. '2 vehicles - 2020 Toyota Camry, 2022 Honda CR-V'"
    }
  ],
  "total_premium": 1234.56,
  "total_items": 1
}

IMPORTANT RULES FOR ITEM COUNTING:
- Home, Renters, Condo, Landlord, Dwelling, Umbrella policies = 1 item each
- Auto policies: count the number of VEHICLES listed. 1 car = 1 item, 2 cars = 2 items, etc.
- If a bundled application has home + auto with 2 cars, that's 3 items total (1 home + 2 auto)
- Life/Health = 1 item per policy

IMPORTANT:
- Extract the ANNUAL premium amount, not monthly
- If you see multiple policies in one document, list each separately in the policies array
- policy_type must be one of the exact enum values listed above
- If you can't determine a field, use null
- Return ONLY the JSON, no markdown, no explanation"""


def truncate_pdf(pdf_bytes: bytes, max_pages: int = 50) -> bytes:
    """Truncate a PDF to the first N pages to stay within API limits."""
    try:
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) <= max_pages:
            return pdf_bytes

        writer = PdfWriter()
        for i in range(min(max_pages, len(reader.pages))):
            writer.add_page(reader.pages[i])

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception:
        # If truncation fails, return original and let the API handle it
        return pdf_bytes


async def extract_pdf_data(pdf_bytes: bytes) -> dict:
    """Send PDF to Claude API for extraction."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured. Set it in Render environment variables.")

    # Truncate large PDFs
    pdf_bytes = truncate_pdf(pdf_bytes, max_pages=50)

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
                "max_tokens": 2000,
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
                            {
                                "type": "text",
                                "text": EXTRACTION_PROMPT,
                            },
                        ],
                    }
                ],
            },
        )

    if response.status_code != 200:
        error_detail = response.text
        raise ValueError(f"Claude API error ({response.status_code}): {error_detail}")

    result = response.json()

    # Extract text from response
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    # Parse JSON from response — strip any markdown fencing
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        extracted = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse extraction result: {e}\nRaw: {text[:500]}")

    return extracted
