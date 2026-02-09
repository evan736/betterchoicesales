"""DocuSeal e-signature service — sends documents for electronic signature.

DocuSeal API: https://www.docuseal.com/docs/api
- Single JSON POST to send a PDF for signature
- No multipart form data needed — just base64 the PDF
- $0.20 per completed signature
- Auto-detects fillable fields in PDFs
"""
import base64
import json
import logging
import httpx
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
) -> dict:
    """Send document to DocuSeal for electronic signature.
    
    Uses the create_submission_from_pdf endpoint which:
    1. Uploads the PDF
    2. Auto-detects fillable form fields  
    3. Sends signing email to the signer
    All in one API call.
    """
    if not settings.DOCUSEAL_API_KEY:
        raise ValueError("DOCUSEAL_API_KEY not configured. Set it in Render environment variables.")

    logger.info(f"Sending to DocuSeal: signer={signer_name}, email={signer_email}, pdf_size={len(pdf_bytes)}")

    # Base64 encode the PDF
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "name": title,
        "send_email": True,
        "documents": [
            {
                "name": f"{title}.pdf",
                "file": pdf_base64,
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

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.docuseal.com/submissions/pdf",
            headers={
                "X-Auth-Token": settings.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )

    logger.info(f"DocuSeal response: status={response.status_code}, body={response.text[:500]}")

    if response.status_code not in (200, 201):
        raise ValueError(f"DocuSeal API error ({response.status_code}): {response.text[:500]}")

    data = response.json()

    # Extract submission ID and submitter info
    submission_id = None
    if isinstance(data, list) and len(data) > 0:
        submission_id = str(data[0].get("submission_id", ""))
    elif isinstance(data, dict):
        submission_id = str(data.get("id", data.get("submission_id", "")))

    return {
        "documentId": submission_id,
        "raw": data,
    }


async def get_document_status(submission_id: str) -> dict:
    """Check the status of a DocuSeal submission."""
    if not settings.DOCUSEAL_API_KEY:
        raise ValueError("DOCUSEAL_API_KEY not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"https://api.docuseal.com/submissions/{submission_id}",
            headers={
                "X-Auth-Token": settings.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
        )

    if response.status_code != 200:
        raise ValueError(f"DocuSeal API error ({response.status_code}): {response.text[:300]}")

    data = response.json()
    status = data.get("status", "unknown")
    
    return {
        "status": status,
        "data": data,
    }
