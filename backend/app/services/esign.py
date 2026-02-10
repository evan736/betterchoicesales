"""BoldSign e-signature service.

Sends PDFs with an explicit signature field placed on the last page.
Uses formFields instead of AutoDetectFields to guarantee field placement.
"""
import json
import logging
import re
import httpx
from PyPDF2 import PdfReader
import io
from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_page_count(pdf_bytes: bytes) -> int:
    """Get the number of pages in a PDF."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        return 1


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Send document to BoldSign for electronic signature.
    Places a signature field on the last page of the PDF.
    """
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError("BOLDSIGN_API_KEY not configured. Set it in Render environment variables.")

    # Clean title for filename
    clean_title = re.sub(r'[^a-zA-Z0-9_ -]', '', title)[:80] or "Application"

    # Get page count so we put the signature on the last page
    page_count = _get_page_count(pdf_bytes)

    signer_data = {
        "name": signer_name,
        "emailAddress": signer_email,
        "signerType": "Signer",
        "signerRole": "Signer",
        "deliveryMode": "Email",
        "locale": "EN",
        "formFields": [
            {
                "id": "sig1",
                "name": "Signature",
                "fieldType": "Signature",
                "pageNumber": page_count,
                "bounds": {
                    "x": 50,
                    "y": 600,
                    "width": 200,
                    "height": 50
                },
                "isRequired": True
            },
            {
                "id": "date1",
                "name": "Date",
                "fieldType": "DateSigned",
                "pageNumber": page_count,
                "bounds": {
                    "x": 350,
                    "y": 600,
                    "width": 150,
                    "height": 30
                },
                "isRequired": True
            }
        ]
    }

    logger.info(f"BoldSign: sending to {signer_email}, name={signer_name}, "
                f"pdf_size={len(pdf_bytes)}, pages={page_count}, title={clean_title}")

    send_data = {
        "Title": clean_title,
        "Message": "Please review and sign the attached insurance application.",
        "Signers": json.dumps(signer_data),
        "EnablePrintAndSign": "true",
    }

    # Use sender identity if configured
    if settings.BOLDSIGN_SENDER_EMAIL:
        send_data["OnBehalfOf"] = settings.BOLDSIGN_SENDER_EMAIL

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.boldsign.com/v1/document/send",
            headers={
                "accept": "application/json",
                "X-API-KEY": settings.BOLDSIGN_API_KEY,
            },
            data=send_data,
            files={
                "Files": (f"{clean_title}.pdf", pdf_bytes, "application/pdf"),
            },
        )

    logger.info(f"BoldSign response: status={response.status_code}")
    logger.info(f"BoldSign body: {response.text[:500]}")

    if response.status_code not in (200, 201):
        raise ValueError(f"BoldSign API error ({response.status_code}): {response.text[:500]}")

    result = response.json()
    return {
        "documentId": result.get("documentId"),
    }


async def get_document_status(document_id: str) -> dict:
    """Check the status of a BoldSign document."""
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError("BOLDSIGN_API_KEY not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://api.boldsign.com/v1/document/properties",
            params={"documentId": document_id},
            headers={
                "accept": "application/json",
                "X-API-KEY": settings.BOLDSIGN_API_KEY,
            },
        )

    if response.status_code != 200:
        raise ValueError(f"BoldSign API error ({response.status_code}): {response.text[:300]}")

    result = response.json()
    return {
        "status": result.get("status", "unknown"),
        "raw": result,
    }
