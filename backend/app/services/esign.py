"""DocuSeal e-signature service.

Two modes:
1. TEMPLATE MODE — For known carriers with pre-built templates in DocuSeal.
   Fields are perfectly placed via DocuSeal's drag-and-drop builder.
   Uses POST /submissions with template_id.

2. SELF-PLACE MODE — For unknown/one-off carriers.
   Sends the raw PDF. Customer gets a simple signing page where
   they draw their signature — DocuSeal handles the UX.
   Uses POST /submissions/pdf with a single signature field.
"""
import base64
import json
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

DOCUSEAL_API_URL = "https://api.docuseal.com"

# =============================================
# CARRIER → TEMPLATE MAPPING
# =============================================
# Add your DocuSeal template IDs here after creating them in the DocuSeal web UI.
# Go to console.docuseal.com → Templates → Create → Upload carrier PDF → 
# Drag signature/date/initial fields to exact spots → Save → Copy template ID
#
# You can also manage these via the database/admin UI (future enhancement)
CARRIER_TEMPLATES: dict[str, int] = {
    # "imperial fire": 1000001,
    # "travelers": 1000002,
    # "openly": 1000003,
    # "simply": 1000004,
}


def get_template_for_carrier(carrier: str) -> int | None:
    """Look up DocuSeal template ID for a carrier name."""
    if not carrier:
        return None
    normalized = carrier.strip().lower()
    for key, template_id in CARRIER_TEMPLATES.items():
        if key in normalized or normalized in key:
            return template_id
    return None


async def send_with_template(
    template_id: int,
    signer_name: str,
    signer_email: str,
) -> dict:
    """Send a signature request using a pre-built DocuSeal template.
    Fields are already perfectly placed in the template."""
    
    payload = {
        "template_id": template_id,
        "send_email": True,
        "submitters": [
            {
                "role": "First Party",
                "name": signer_name,
                "email": signer_email,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{DOCUSEAL_API_URL}/submissions",
            headers={
                "X-Auth-Token": settings.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )

    logger.info(f"DocuSeal template response: status={response.status_code}, body={response.text[:500]}")

    if response.status_code not in (200, 201):
        raise ValueError(f"DocuSeal API error ({response.status_code}): {response.text[:500]}")

    result = response.json()
    
    submission_id = None
    if isinstance(result, list) and len(result) > 0:
        submission_id = result[0].get("submission_id")
    elif isinstance(result, dict):
        submission_id = result.get("id")

    return {
        "documentId": str(submission_id) if submission_id else "unknown",
        "mode": "template",
    }


async def send_self_place(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
) -> dict:
    """Send PDF for signing — customer places their own signature.
    
    Adds a single required signature field. DocuSeal's signing UI
    presents a clean step-by-step flow where the signer draws/types
    their signature and it gets applied to the document.
    """
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "name": title,
        "send_email": True,
        "documents": [
            {
                "name": title,
                "file": pdf_base64,
                "fields": [
                    {
                        "name": "Signature",
                        "type": "signature",
                        "role": "First Party",
                        "required": True,
                        "areas": [
                            {"x": 0.05, "y": 0.9, "w": 0.3, "h": 0.05, "page": -1}
                        ],
                    },
                    {
                        "name": "Date",
                        "type": "date",
                        "role": "First Party",
                        "required": True,
                        "areas": [
                            {"x": 0.6, "y": 0.9, "w": 0.2, "h": 0.04, "page": -1}
                        ],
                    },
                ],
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
            f"{DOCUSEAL_API_URL}/submissions/pdf",
            headers={
                "X-Auth-Token": settings.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )

    logger.info(f"DocuSeal self-place response: status={response.status_code}, body={response.text[:500]}")

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
        "mode": "self_place",
    }


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Main entry point — routes to template or self-place mode."""
    if not settings.DOCUSEAL_API_KEY:
        raise ValueError("DOCUSEAL_API_KEY not configured. Set it in Render environment variables.")

    logger.info(f"DocuSeal: sending to {signer_email}, carrier={carrier}, pdf_size={len(pdf_bytes)}")

    # Check if we have a template for this carrier
    template_id = get_template_for_carrier(carrier) if carrier else None

    if template_id:
        logger.info(f"Using template {template_id} for carrier '{carrier}'")
        return await send_with_template(template_id, signer_name, signer_email)
    else:
        logger.info(f"No template for carrier '{carrier}' — using self-place mode")
        return await send_self_place(pdf_bytes, signer_name, signer_email, title)


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
