"""BoldSign e-signature service with AI auto-detection.

Uses BoldSign's AutoDetectFields=true to automatically find and place
signature, date, initial, checkbox fields in the PDF.
"""
import json
import logging
import re
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Send document to BoldSign for electronic signature.
    Uses BoldSign's built-in AI field detection (AutoDetectFields=true).
    """
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError("BOLDSIGN_API_KEY not configured. Set it in Render environment variables.")

    # Clean title for filename
    clean_title = re.sub(r'[^a-zA-Z0-9_ -]', '', title)[:80] or "Application"

    signer_data = {
        "name": signer_name,
        "emailAddress": signer_email,
        "signerType": "Signer",
        "signerRole": "Signer",
        "locale": "EN",
    }

    logger.info(f"BoldSign: sending to {signer_email}, name={signer_name}, "
                f"pdf_size={len(pdf_bytes)}, title={clean_title}")

    send_data = {
        "Title": clean_title,
        "Message": "Please review and sign the attached insurance application.",
        "Signers": json.dumps(signer_data),
        "AutoDetectFields": "true",
        "EnablePrintAndSign": "true",
    }

    # Use sender identity if configured (sends from your business email)
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
