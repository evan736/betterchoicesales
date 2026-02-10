"""BoldSign e-signature service.

Uses a two-step approach for signature field placement:
1. Detect carrier from PDF text (first page)
2. Use pdfplumber to find "Applicant Signature:" label and place
   the signature field on the blank line RIGHT AFTER it

This is more reliable than searching for invisible markers like
<<named.insured.signature>> which may be stripped or extracted
inconsistently across PDF library versions.
"""
import json
import logging
import re
import io
import httpx
import pdfplumber
from app.core.config import settings

logger = logging.getLogger(__name__)


def _find_applicant_signature_lines(pdf_bytes: bytes) -> list:
    """Find the exact coordinates of 'Applicant Signature:' labels.

    Searches for the visible label text that appears on signature lines,
    then places the signature field on the blank line area after it.

    Returns list of: {"page": int, "x": float, "y": float}
    """
    results = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                words = page.extract_words()
                page_num = page_idx + 1

                for i, word in enumerate(words):
                    text = word["text"].strip()

                    # Match various signature label patterns
                    # Grange: "ApplicantSignature:" (pdfplumber joins words)
                    # National General: "<PrimarySign>" or near "Signature of applicant"
                    matched = False
                    match_type = ""

                    if "ApplicantSignature:" in text.replace(" ", ""):
                        matched = True
                        match_type = "ApplicantSignature"
                    elif text == "Applicant" and i + 1 < len(words):
                        next_text = words[i + 1]["text"].strip()
                        if "Signature:" in next_text.replace(" ", ""):
                            matched = True
                            match_type = "Applicant + Signature"
                    elif "<PrimarySign>" in text:
                        matched = True
                        match_type = "PrimarySign"
                    elif "<<named.insured.signature>>" in text:
                        matched = True
                        match_type = "named.insured.signature"

                    if matched:
                        logger.info(
                            f"FOUND [{match_type}]: word='{text}' "
                            f"page={page_num} x0={word['x0']:.1f} "
                            f"top={word['top']:.1f} bottom={word['bottom']:.1f}"
                        )

                        # For "ApplicantSignature:" - place sig field on the
                        # signature LINE (the blank area after the label)
                        if "Applicant" in match_type:
                            results.append({
                                "page": page_num,
                                "x": word["x0"],  # Same line as label
                                "y": word["top"],
                                "label_width": word["x1"] - word["x0"],
                                "type": match_type,
                            })
                        elif "PrimarySign" in match_type or "named.insured" in match_type:
                            results.append({
                                "page": page_num,
                                "x": word["x0"],
                                "y": word["top"],
                                "label_width": 0,
                                "type": match_type,
                            })

    except Exception as e:
        logger.error(f"Error scanning PDF: {e}", exc_info=True)

    return results


def _build_form_fields(pdf_bytes: bytes) -> list:
    """Build BoldSign form fields for all signature locations found."""
    locations = _find_applicant_signature_lines(pdf_bytes)

    if not locations:
        # Fallback: last page
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)
        except Exception:
            page_count = 1
        logger.warning(f"No signature locations found! Falling back to page {page_count}")
        return [{
            "id": "sig1",
            "name": "Signature",
            "fieldType": "Signature",
            "pageNumber": page_count,
            "bounds": {"x": 100, "y": 600, "width": 200, "height": 40},
            "isRequired": True,
        }]

    # For "ApplicantSignature:" matches, we want to skip any that are
    # waiver/rejection signatures (like UMPD on page 1 of auto apps)
    # and keep the main application signatures.
    # Strategy: if we have both ApplicantSignature and PrimarySign/named.insured
    # matches on the same page, prefer the label match since it's the visible line.

    # Deduplicate by page - prefer "ApplicantSignature" type over marker types
    page_map = {}
    for loc in locations:
        page = loc["page"]
        if page not in page_map:
            page_map[page] = loc
        elif "Applicant" in loc["type"] and "Applicant" not in page_map[page]["type"]:
            page_map[page] = loc

    unique_locs = list(page_map.values())

    form_fields = []
    for i, loc in enumerate(unique_locs):
        # Place the signature field on the blank line AFTER the label
        # The label is ~130pt wide, signature line starts after it
        sig_x = loc["x"] + loc["label_width"] + 5  # Right after label
        sig_y = loc["y"] - 2  # Align with the text baseline

        # If sig_x would be off-page, reset to a reasonable position
        if sig_x > 400:
            sig_x = 150

        form_fields.append({
            "id": f"sig{i + 1}",
            "name": f"Signature",
            "fieldType": "Signature",
            "pageNumber": loc["page"],
            "bounds": {
                "x": sig_x,
                "y": sig_y,
                "width": 200,
                "height": 25,
            },
            "isRequired": True,
        })
        logger.info(
            f"FIELD sig{i+1}: page={loc['page']} x={sig_x:.1f} y={sig_y:.1f} "
            f"type={loc['type']}"
        )

    logger.info(f"Total fields: {len(form_fields)}")
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
