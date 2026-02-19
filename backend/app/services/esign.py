"""BoldSign e-signature service.

APPROACH: Instead of trying to auto-detect signature positions in the PDF
(which is unreliable across different carrier forms), we use BoldSign's
Embedded Request API to create a draft document and return a URL where
a human can visually place signature fields, then hit Send.

Flow:
  1. Agent clicks "Send for Signature" in the CRM
  2. Backend uploads the PDF to BoldSign via createEmbeddedRequestUrl
  3. BoldSign returns a URL that opens their document editor
  4. Backend returns this URL to the frontend
  5. Frontend opens the URL in a new tab
  6. Agent drags signature boxes where needed, clicks Send
  7. Client receives the signing email from BoldSign

The signer name/email are pre-filled. The agent just places the fields.
"""
import logging
import re
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


async def create_signature_request(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
    redirect_url: str = None,
) -> dict:
    """Create a BoldSign embedded request and return the sender URL.

    Returns:
        {
            "documentId": "...",
            "sendUrl": "https://app.boldsign.com/document/...",
        }

    The sendUrl opens BoldSign's prepare page where the agent can
    drag-and-drop signature fields onto the PDF, then click Send.
    """
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError(
            "BOLDSIGN_API_KEY not configured. Set it in Render environment variables."
        )

    clean_title = re.sub(r'[^a-zA-Z0-9_ -]', '', title)[:80] or "Application"

    if not redirect_url:
        redirect_url = settings.APP_URL + "/sales"

    logger.info(
        f"BoldSign embedded request: '{clean_title}' for {signer_email}, "
        f"pdf_size={len(pdf_bytes)}"
    )

    # Build the multipart form data for BoldSign's embedded request API.
    # We pre-fill the signer info but do NOT send any formFields —
    # the agent will place them manually in the BoldSign UI.
    send_data = {
        "Title": clean_title,
        "Message": "Please review and sign the attached insurance application.",
        "ShowToolbar": "true",
        "ShowNavigationButtons": "true",
        "ShowPreviewButton": "true",
        "ShowSendButton": "true",
        "ShowSaveButton": "true",
        "SendViewOption": "PreparePage",
        "ShowTooltip": "false",
        "Locale": "EN",
        "EnablePrintAndSign": "true",
        "RedirectUrl": redirect_url,
        "Signers[0][Name]": signer_name,
        "Signers[0][EmailAddress]": signer_email,
        "Signers[0][SignerType]": "Signer",
        "Signers[0][SignerOrder]": "1",
        "Signers[0][Locale]": "EN",
    }

    if settings.BOLDSIGN_SENDER_EMAIL:
        send_data["OnBehalfOf"] = settings.BOLDSIGN_SENDER_EMAIL

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.boldsign.com/v1/document/createEmbeddedRequestUrl",
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
        raise ValueError(
            f"BoldSign API error ({response.status_code}): {response.text[:500]}"
        )

    result = response.json()
    document_id = result.get("documentId", "")
    send_url = result.get("sendUrl", "")

    if not send_url:
        raise ValueError(
            "BoldSign did not return a sendUrl. Response: " + str(result)[:300]
        )

    logger.info(f"BoldSign embedded URL created: doc={document_id}")

    return {
        "documentId": document_id,
        "sendUrl": send_url,
    }


# ── Keep the old function name as a wrapper for backward compatibility ──

async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Legacy wrapper — now creates an embedded request instead of auto-sending."""
    return await create_signature_request(
        pdf_bytes=pdf_bytes,
        signer_name=signer_name,
        signer_email=signer_email,
        title=title,
        carrier=carrier,
    )


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
        raise ValueError(
            f"BoldSign API error ({response.status_code}): {response.text[:300]}"
        )

    result = response.json()
    return {"status": result.get("status", "unknown"), "raw": result}
