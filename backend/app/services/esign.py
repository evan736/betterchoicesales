"""BoldSign e-signature service.

Uses pdfplumber to find the EXACT pixel coordinates of signature markers
in carrier PDFs, then places BoldSign signature fields precisely on top.

Supported markers:
  - Grange: <<named.insured.signature>>
  - National General: <PrimarySign>
  - Fallback: text containing 'Applicant Signature:'
"""
import json
import logging
import re
import io
import httpx
import pdfplumber
from app.core.config import settings

logger = logging.getLogger(__name__)

# Signature markers - exact text as it appears in carrier PDFs
# All use angle brackets so they can't match regular words like "Signature"
SIGNATURE_MARKERS = [
    "<<named.insured.signature>>",   # Grange
    "<PrimarySign>",                  # National General
]


def _find_signature_fields(pdf_bytes: bytes) -> list:
    """Use pdfplumber to find exact coordinates of signature markers.

    pdfplumber coordinate system matches BoldSign:
    - Origin: top-left
    - Units: points (1/72 inch)
    - US Letter: 612w x 792h

    Returns list of: {"page": int, "x": float, "y": float, "marker": str}
    """
    fields = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                words = page.extract_words()
                page_num = page_idx + 1

                for word in words:
                    text = word["text"].strip()

                    # Only match exact marker strings (they all contain < >)
                    for marker in SIGNATURE_MARKERS:
                        if marker in text:
                            logger.info(
                                f"MATCH: word='{text}' marker='{marker}' "
                                f"page={page_num} x={word['x0']:.1f} y={word['top']:.1f}"
                            )
                            fields.append({
                                "page": page_num,
                                "x": word["x0"],
                                "y": word["top"],
                                "width": word["x1"] - word["x0"],
                                "height": word["bottom"] - word["top"],
                                "marker": marker,
                            })
                            break
    except Exception as e:
        logger.error(f"Error scanning PDF with pdfplumber: {e}")

    return fields


def _build_form_fields(pdf_bytes: bytes) -> list:
    """Build BoldSign form fields at exact signature marker positions."""
    sig_fields = _find_signature_fields(pdf_bytes)

    if not sig_fields:
        # Fallback: try to find 'Applicant Signature:' text
        logger.info("No primary markers found, trying fallback text search")
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    words = page.extract_words()
                    page_num = page_idx + 1

                    for i, word in enumerate(words):
                        if "signature:" in word["text"].lower() and (
                            "applicant" in word["text"].lower()
                            or (i > 0 and "applicant" in words[i-1]["text"].lower())
                        ):
                            # Place signature after the "Signature:" label
                            sig_fields.append({
                                "page": page_num,
                                "x": word["x1"] + 5,  # Right after the label
                                "y": word["top"],
                                "width": 100,
                                "height": word["bottom"] - word["top"],
                                "marker": "Applicant Signature:",
                            })
                            logger.info(
                                f"Found fallback 'Applicant Signature:' on page {page_num} "
                                f"at x={word['x1']:.1f}, y={word['top']:.1f}"
                            )
        except Exception as e:
            logger.error(f"Fallback search error: {e}")

    if not sig_fields:
        # Ultimate fallback: last page, bottom area
        logger.info("No markers found at all, using last-page fallback")
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)
        except Exception:
            page_count = 1

        return [{
            "id": "sig1",
            "name": "Applicant Signature",
            "fieldType": "Signature",
            "pageNumber": page_count,
            "bounds": {"x": 100, "y": 600, "width": 200, "height": 40},
            "isRequired": True,
        }]

    # Deduplicate by page (keep first marker per page)
    seen_pages = set()
    unique_fields = []
    for f in sig_fields:
        if f["page"] not in seen_pages:
            seen_pages.add(f["page"])
            unique_fields.append(f)

    form_fields = []
    for i, sf in enumerate(unique_fields):
        form_fields.append({
            "id": f"sig{i + 1}",
            "name": f"Signature (Page {sf['page']})",
            "fieldType": "Signature",
            "pageNumber": sf["page"],
            "bounds": {
                "x": sf["x"],
                "y": sf["y"],       # Exact marker position
                "width": 200,
                "height": 30,
            },
            "isRequired": True,
        })
        logger.info(
            f"Field sig{i + 1}: page={sf['page']}, "
            f"x={sf['x']:.1f}, y={sf['y']:.1f}, "
            f"marker='{sf['marker']}'"
        )

    logger.info(f"Total signature fields placed: {len(form_fields)}")
    return form_fields


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Send document to BoldSign for electronic signature.

    Uses pdfplumber to find exact coordinates of signature markers
    in the PDF and places signature fields precisely on top.
    """
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError(
            "BOLDSIGN_API_KEY not configured. Set it in Render environment variables."
        )

    clean_title = re.sub(r'[^a-zA-Z0-9_ -]', '', title)[:80] or "Application"

    form_fields = _build_form_fields(pdf_bytes)

    signer_data = {
        "name": signer_name,
        "emailAddress": signer_email,
        "signerType": "Signer",
        "signerRole": "Signer",
        "deliveryMode": "Email",
        "locale": "EN",
        "formFields": form_fields,
    }

    logger.info(
        f"BoldSign: sending to {signer_email}, name={signer_name}, "
        f"pdf_size={len(pdf_bytes)}, title={clean_title}, "
        f"fields={len(form_fields)}"
    )

    send_data = {
        "Title": clean_title,
        "Message": "Please review and sign the attached insurance application.",
        "Signers": json.dumps(signer_data),
        "EnablePrintAndSign": "true",
    }

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
        raise ValueError(
            f"BoldSign API error ({response.status_code}): {response.text[:500]}"
        )

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
        raise ValueError(
            f"BoldSign API error ({response.status_code}): {response.text[:300]}"
        )

    result = response.json()
    return {
        "status": result.get("status", "unknown"),
        "raw": result,
    }
