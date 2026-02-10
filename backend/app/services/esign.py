"""BoldSign e-signature service.

APPROACH: Find the visible 'Applicant Signature:' label text using
pdfplumber word extraction, then place the signature field on the
blank line area immediately to the right of that label.

Key rule: ONLY match words containing 'Applicant' followed by 'Signature'
to avoid false matches on the 'Signature' heading.
"""
import json
import logging
import re
import io
import httpx
import pdfplumber
from app.core.config import settings

logger = logging.getLogger(__name__)


def _find_signature_positions(pdf_bytes: bytes) -> list:
    """Find 'Applicant Signature:' or '<PrimarySign>' positions.

    Returns list of {"page": int, "x": float, "y": float, "after_x": float}
    where after_x is where the blank signature line starts.
    """
    results = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"Scanning {total_pages} pages for signature positions")

            for page_idx, page in enumerate(pdf.pages):
                words = page.extract_words()
                page_num = page_idx + 1

                # Log all words on signature pages for debugging
                if page_num <= 2:
                    sig_words = [w for w in words if any(
                        k in w["text"].lower()
                        for k in ["signature", "sign", "applicant", "primary"]
                    )]
                    for sw in sig_words:
                        logger.info(
                            f"  DEBUG p{page_num}: '{sw['text']}' "
                            f"x0={sw['x0']:.1f} top={sw['top']:.1f}"
                        )

                for i, word in enumerate(words):
                    text = word["text"]

                    # Strategy 1: Find "ApplicantSignature:" as single word
                    # (pdfplumber often joins adjacent words)
                    if "Applicant" in text and "ignature" in text:
                        results.append({
                            "page": page_num,
                            "x": word["x1"] + 3,   # Start AFTER the label
                            "y": word["top"],
                            "type": "ApplicantSignature",
                        })
                        logger.info(
                            f"MATCH [ApplicantSignature]: '{text}' "
                            f"page={page_num} label_ends={word['x1']:.1f} "
                            f"y={word['top']:.1f}"
                        )
                        continue

                    # Strategy 2: Find "Applicant" then "Signature:" as separate words
                    if text.strip() == "Applicant" and i + 1 < len(words):
                        next_word = words[i + 1]
                        if "Signature" in next_word["text"]:
                            results.append({
                                "page": page_num,
                                "x": next_word["x1"] + 3,
                                "y": word["top"],
                                "type": "Applicant+Signature",
                            })
                            logger.info(
                                f"MATCH [Applicant+Signature]: page={page_num} "
                                f"y={word['top']:.1f}"
                            )
                            continue

                    # Strategy 3: National General <PrimarySign>
                    if "<PrimarySign>" in text:
                        results.append({
                            "page": page_num,
                            "x": word["x0"],
                            "y": word["top"],
                            "type": "PrimarySign",
                        })
                        logger.info(
                            f"MATCH [PrimarySign]: page={page_num} "
                            f"x={word['x0']:.1f} y={word['top']:.1f}"
                        )

    except Exception as e:
        logger.error(f"Error scanning PDF: {e}", exc_info=True)

    return results


def _build_form_fields(pdf_bytes: bytes) -> list:
    """Build BoldSign form fields at detected signature positions."""
    positions = _find_signature_positions(pdf_bytes)

    if not positions:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)
        except Exception:
            page_count = 1
        logger.warning(f"NO signature positions found! Fallback to page {page_count}")
        return [{
            "id": "sig1",
            "name": "Signature",
            "fieldType": "Signature",
            "pageNumber": page_count,
            "bounds": {"x": 100, "y": 600, "width": 200, "height": 40},
            "isRequired": True,
        }]

    # Deduplicate by page number (keep first match per page)
    seen = set()
    unique = []
    for p in positions:
        if p["page"] not in seen:
            seen.add(p["page"])
            unique.append(p)

    form_fields = []
    for i, pos in enumerate(unique):
        form_fields.append({
            "id": f"sig{i + 1}",
            "name": "Signature",
            "fieldType": "Signature",
            "pageNumber": pos["page"],
            "bounds": {
                "x": pos["x"],
                "y": pos["y"] - 2,
                "width": 200,
                "height": 25,
            },
            "isRequired": True,
        })
        logger.info(
            f"PLACED sig{i+1}: page={pos['page']} "
            f"x={pos['x']:.1f} y={pos['y']-2:.1f} "
            f"type={pos['type']}"
        )

    return form_fields


async def send_for_signature(
    pdf_bytes: bytes,
    signer_name: str,
    signer_email: str,
    title: str,
    carrier: str = None,
) -> dict:
    """Send document to BoldSign for electronic signature."""
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
        f"BoldSign: sending '{clean_title}' to {signer_email}, "
        f"pdf_size={len(pdf_bytes)}, fields={len(form_fields)}"
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
    return {"documentId": result.get("documentId")}


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
