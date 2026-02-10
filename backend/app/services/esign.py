"""BoldSign e-signature service.

Smart signature field placement: scans PDF text for carrier-specific
signature markers and places BoldSign signature fields at each location.

Supported markers:
  - Grange: <<named.insured.signature>>
  - National General: <PrimarySign>
  - Fallback: 'Applicant Signature:' text

Places a signature field on EVERY page that contains a marker,
so the customer can sign all required pages in one session.
"""
import json
import logging
import re
import io
import httpx
from PyPDF2 import PdfReader
from app.core.config import settings

logger = logging.getLogger(__name__)

# Carrier-specific signature markers (order = priority)
PRIMARY_MARKERS = [
    "<<named.insured.signature>>",
    "<PrimarySign>",
]

FALLBACK_MARKERS = [
    "applicant signature:",
    "applicant\nsignature:",
    "account holder's authorized signature:",
]


def _find_all_signature_locations(pdf_bytes: bytes) -> list:
    """Scan every page for signature markers.

    Returns list of: {"page": int, "y": float, "marker": str}
    Page numbers are 1-indexed (BoldSign convention).
    """
    locations = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        logger.warning(f"Error reading PDF: {e}")
        return locations

    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text_lower = text.lower()
        page_num = page_idx + 1

        # Check primary markers first
        for marker in PRIMARY_MARKERS:
            marker_lower = marker.lower()
            if marker_lower in text_lower:
                pos = text_lower.index(marker_lower)
                ratio = pos / len(text_lower) if len(text_lower) > 0 else 0.5
                y_pos = ratio * 792  # US Letter height in points

                locations.append({
                    "page": page_num,
                    "y": y_pos,
                    "ratio": ratio,
                    "marker": marker,
                    "priority": "primary",
                })
                logger.info(
                    f"Found '{marker}' on page {page_num}, "
                    f"ratio={ratio:.3f}, y={y_pos:.0f}"
                )
                break  # Only one marker per page

    # If no primary markers found, try fallback markers
    if not locations:
        reader2 = PdfReader(io.BytesIO(pdf_bytes))
        for page_idx, page in enumerate(reader2.pages):
            text = page.extract_text() or ""
            text_lower = text.lower()
            page_num = page_idx + 1

            for marker in FALLBACK_MARKERS:
                if marker in text_lower:
                    pos = text_lower.index(marker)
                    ratio = pos / len(text_lower) if len(text_lower) > 0 else 0.5
                    y_pos = ratio * 792

                    locations.append({
                        "page": page_num,
                        "y": y_pos,
                        "ratio": ratio,
                        "marker": marker,
                        "priority": "fallback",
                    })
                    logger.info(
                        f"Found fallback '{marker}' on page {page_num}, "
                        f"ratio={ratio:.3f}, y={y_pos:.0f}"
                    )
                    break

    return locations


def _build_form_fields(pdf_bytes: bytes) -> list:
    """Build BoldSign form fields for all detected signature locations.

    BoldSign coordinate system:
    - Origin: top-left of page
    - Units: points (1/72 inch)
    - US Letter: 612w x 792h points
    """
    locations = _find_all_signature_locations(pdf_bytes)

    if not locations:
        # Ultimate fallback: last page
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            page_count = len(reader.pages)
        except Exception:
            page_count = 1

        logger.info(f"No markers found, placing signature on last page ({page_count})")
        return [
            {
                "id": "sig1",
                "name": "Applicant Signature",
                "fieldType": "Signature",
                "pageNumber": page_count,
                "bounds": {"x": 100, "y": 600, "width": 200, "height": 40},
                "isRequired": True,
            },
        ]

    form_fields = []

    # Deduplicate by page number (keep first marker found per page)
    seen_pages = set()
    unique_locations = []
    for loc in locations:
        if loc["page"] not in seen_pages:
            seen_pages.add(loc["page"])
            unique_locations.append(loc)

    for i, loc in enumerate(unique_locations):
        field_id = f"sig{i + 1}"
        page = loc["page"]
        y = loc["y"]

        # Clamp Y to valid range (leave room for field height)
        y = max(30, min(y, 740))

        form_fields.append({
            "id": field_id,
            "name": f"Signature (Page {page})",
            "fieldType": "Signature",
            "pageNumber": page,
            "bounds": {
                "x": 100,      # Left-aligned with signature line
                "y": y - 5,    # Slightly above to align with line
                "width": 200,
                "height": 30,
            },
            "isRequired": True,
        })

        logger.info(
            f"Field {field_id}: page {page}, y={y - 5:.0f}, "
            f"marker='{loc['marker']}'"
        )

    logger.info(f"Total signature fields: {len(form_fields)}")
    return form_fields


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Send document to BoldSign for electronic signature.

    Automatically detects signature field locations by scanning
    the PDF text for carrier-specific markers.
    """
    if not settings.BOLDSIGN_API_KEY:
        raise ValueError(
            "BOLDSIGN_API_KEY not configured. Set it in Render environment variables."
        )

    # Clean title
    clean_title = re.sub(r'[^a-zA-Z0-9_ -]', '', title)[:80] or "Application"

    # Build form fields by scanning the PDF
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
