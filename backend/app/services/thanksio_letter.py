"""
Thanks.io integration for sending past-due letters to customers without email.

Generates a professional PDF letter with carrier branding, uploads it, and sends via Thanks.io API.
"""

import io
import os
import base64
import logging
from datetime import datetime
from pathlib import Path

import httpx
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)

THANKSIO_API_URL = "https://api.thanks.io/api/v2"
THANKSIO_API_KEY = os.environ.get("THANKSIO_API_KEY", "")

# Agency return address
AGENCY_NAME = "Better Choice Insurance Group"
AGENCY_ADDRESS = "300 Cardinal Dr Suite 220"
AGENCY_CITY = "Saint Charles"
AGENCY_STATE = "IL"
AGENCY_ZIP = "60175"
AGENCY_PHONE = "(847) 908-5665"
AGENCY_WEBSITE = "www.betterchoiceins.com"

# Path to carrier logo files — works in both local dev and Docker
_BACKEND_DIR = Path(__file__).parent.parent.parent  # backend/
LOGO_DIR = _BACKEND_DIR.parent / "frontend" / "public" / "carrier-logos"
if not LOGO_DIR.exists():
    # Docker layout: /app/frontend/public/carrier-logos
    LOGO_DIR = Path("/app/frontend/public/carrier-logos")
if not LOGO_DIR.exists():
    # Fallback: check if static dir exists in backend
    LOGO_DIR = _BACKEND_DIR / "static" / "carrier-logos"

# Carrier logo mapping
CARRIER_LOGOS = {
    "grange": "grange.png", "integrity": "integrity.png", "branch": "branch.png",
    "universal_property": "universal_property.png", "next": "next.png", "hippo": "hippo.png",
    "gainsco": "gainsco.png", "steadily": "steadily.png", "geico": "geico.png",
    "american_modern": "american_modern.png", "progressive": "progressive.png",
    "clearcover": "clearcover.png", "safeco": "safeco.png", "travelers": "travelers.png",
    "national_general": "national_general.png", "openly": "openly.png",
    "bristol_west": "bristol_west.png", "covertree": "covertree.png",
}

# Carrier-specific payment info and letter messaging
CARRIER_INFO = {
    "travelers": {
        "name": "Travelers", "phone": "1-800-842-5075",
        "url": "https://www.travelers.com/pay-bill",
        "message": "Your Travelers insurance policy has an outstanding balance. Travelers requires timely payment to maintain continuous coverage and avoid policy cancellation.",
    },
    "progressive": {
        "name": "Progressive", "phone": "1-800-776-4737",
        "url": "https://www.progressive.com/pay-bill/",
        "message": "Your Progressive insurance policy has a past-due balance. Progressive may cancel your policy if payment is not received promptly.",
    },
    "safeco": {
        "name": "Safeco", "phone": "1-800-332-3226",
        "url": "https://www.safeco.com/pay-bill",
        "message": "Your Safeco insurance policy has an outstanding balance that requires immediate attention to avoid a lapse in coverage.",
    },
    "geico": {
        "name": "GEICO", "phone": "1-800-932-8872",
        "url": "https://www.geico.com/pay-bill/",
        "message": "Your GEICO policy has a past-due payment. Please make your payment promptly to keep your policy active and maintain your coverage.",
    },
    "grange": {
        "name": "Grange Insurance", "phone": "(800) 425-1100",
        "url": "https://www.grangeinsurance.com/pay-my-bill",
        "message": "Your Grange Insurance policy has a past-due balance. Please remit payment to avoid cancellation of your coverage.",
    },
    "hippo": {
        "name": "Hippo Insurance", "phone": "1-800-585-0705",
        "url": "https://www.hippo.com/pay",
        "message": "Your Hippo Insurance policy has an outstanding payment. Please make your payment to maintain your homeowners coverage.",
    },
    "branch": {
        "name": "Branch Insurance", "phone": "1-833-427-2624",
        "url": "https://www.ourbranch.com/pay",
        "message": "Your Branch Insurance policy has a past-due balance. Please make your payment to keep your policy active.",
    },
    "national_general": {
        "name": "National General", "phone": "1-800-462-2123",
        "url": "https://www.nationalgeneral.com/pay-bill",
        "message": "Your National General insurance policy has an outstanding balance. Prompt payment is required to avoid cancellation.",
    },
    "bristol_west": {
        "name": "Bristol West", "phone": "1-888-888-0080",
        "url": "https://www.bristolwest.com/pay-bill",
        "message": "Your Bristol West insurance policy has a past-due payment. Please make your payment immediately to keep your auto coverage active.",
    },
    "clearcover": {
        "name": "Clearcover", "phone": "1-855-444-1875",
        "url": "https://www.clearcover.com",
        "message": "Your Clearcover insurance policy has an outstanding balance. Please make your payment to maintain your coverage.",
    },
    "openly": {
        "name": "Openly", "phone": "",
        "url": "https://www.openly.com",
        "message": "Your Openly insurance policy has a past-due balance. Please contact us for payment options.",
    },
    "integrity": {
        "name": "Integrity Insurance", "phone": "1-800-898-4641",
        "url": "https://www.integrityinsurance.com",
        "message": "Your Integrity Insurance policy has an outstanding payment. Please remit payment promptly to avoid any lapse in coverage.",
    },
    "steadily": {
        "name": "Steadily", "phone": "",
        "url": "https://www.steadily.com",
        "message": "Your Steadily insurance policy has a past-due balance. Please log in to your account to make payment.",
    },
    "gainsco": {
        "name": "GAINSCO", "phone": "1-866-639-2860",
        "url": "https://www.gainsco.com",
        "message": "Your GAINSCO auto insurance policy has a past-due payment. Please make your payment to avoid cancellation of your coverage.",
    },
    "next": {
        "name": "NEXT Insurance", "phone": "1-855-222-5919",
        "url": "https://www.nextinsurance.com",
        "message": "Your NEXT Insurance policy has an outstanding balance. Please make your payment to keep your business coverage active.",
    },
    "universal_property": {
        "name": "Universal Property", "phone": "1-800-425-9113",
        "url": "https://www.universalproperty.com",
        "message": "Your Universal Property insurance policy has a past-due balance. Prompt payment is required to maintain your coverage.",
    },
    "american_modern": {
        "name": "American Modern", "phone": "1-800-543-2644",
        "url": "https://www.amig.com",
        "message": "Your American Modern insurance policy has an outstanding payment. Please make your payment to avoid a lapse in coverage.",
    },
    "covertree": {
        "name": "CoverTree", "phone": "",
        "url": "https://www.covertree.com",
        "message": "Your CoverTree insurance policy has a past-due balance. Please log in to your account to make payment.",
    },
}

# Generic fallback message
GENERIC_MESSAGE = (
    "Your insurance policy has an outstanding balance that requires your immediate "
    "attention. Failure to make payment may result in the cancellation of your policy, "
    "leaving you without coverage."
)


def _draw_wrapped_text(c, text, x, y, font_name, font_size, max_width, line_height=None):
    """Draw word-wrapped text. Returns new y position."""
    if line_height is None:
        line_height = font_size + 4
    c.setFont(font_name, font_size)
    words = text.split()
    line = ""
    for word in words:
        test = f"{line} {word}".strip()
        if c.stringWidth(test, font_name, font_size) > max_width:
            c.drawString(x, y, line)
            y -= line_height
            line = word
        else:
            line = test
    if line:
        c.drawString(x, y, line)
        y -= line_height
    return y


def generate_pastdue_pdf(
    client_name: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    policy_number: str,
    carrier: str = "",
    amount_due: float = None,
    due_date: str = None,
) -> bytes:
    """Generate a professional past-due notice PDF letter with carrier branding."""

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    carrier_key = carrier.lower().strip().replace(" ", "_") if carrier else ""
    info = CARRIER_INFO.get(carrier_key, {})
    carrier_name = info.get("name", carrier.replace("_", " ").title() if carrier else "your insurance carrier")
    carrier_phone = info.get("phone", "")
    carrier_url = info.get("url", "")
    carrier_message = info.get("message", GENERIC_MESSAGE)

    # Colors
    navy = HexColor("#1a2744")
    red = HexColor("#c0392b")
    dark_gray = HexColor("#333333")
    medium_gray = HexColor("#666666")
    light_line = HexColor("#cccccc")
    light_bg = HexColor("#f8f9fa")

    left = 0.75 * inch
    max_width = width - 1.5 * inch

    # === HEADER ===
    y = height - 0.55 * inch

    # Always show BCI logo on the left
    bci_logo_path = LOGO_DIR / "bci_logo.png"
    if bci_logo_path.exists():
        try:
            bci_img = ImageReader(str(bci_logo_path))
            biw, bih = bci_img.getSize()
            # Scale BCI logo to max 280w x 65h
            bratio = min(280 / biw, 65 / bih, 1)
            bw, bh = biw * bratio, bih * bratio
            c.drawImage(str(bci_logo_path), left, y - bh + 12, width=bw, height=bh,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            # Fallback to text
            c.setFont("Helvetica-Bold", 16)
            c.setFillColor(navy)
            c.drawString(left, y, AGENCY_NAME)
    else:
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(navy)
        c.drawString(left, y, AGENCY_NAME)

    # Show carrier logo on the right (if available)
    logo_file = CARRIER_LOGOS.get(carrier_key, "")
    logo_path = LOGO_DIR / logo_file if logo_file else None
    if logo_path and logo_path.exists():
        try:
            img = ImageReader(str(logo_path))
            iw, ih = img.getSize()
            ratio = min(120 / iw, 35 / ih, 1)
            draw_w, draw_h = iw * ratio, ih * ratio
            c.drawImage(str(logo_path), width - left - draw_w, y - draw_h + 5,
                        width=draw_w, height=draw_h,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    y -= 46

    # Divider
    c.setStrokeColor(navy)
    c.setLineWidth(2)
    c.line(left, y, width - left, y)
    y -= 4

    # Red "PAST DUE NOTICE" bar
    bar_height = 22
    c.setFillColor(red)
    c.rect(left, y - bar_height, max_width, bar_height, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, y - bar_height + 7, "IMPORTANT: PAST DUE PAYMENT NOTICE")
    y -= bar_height + 16

    # === DATE ===
    today_str = datetime.now().strftime("%B %d, %Y")
    c.setFont("Helvetica", 10)
    c.setFillColor(dark_gray)
    c.drawString(left, y, today_str)
    y -= 24

    # === RECIPIENT ADDRESS ===
    c.setFont("Helvetica", 11)
    c.setFillColor(dark_gray)
    c.drawString(left, y, client_name)
    y -= 15
    if address:
        c.drawString(left, y, address)
        y -= 15
    city_line = ", ".join(filter(None, [city, f"{state} {zip_code}" if state else zip_code]))
    if city_line:
        c.drawString(left, y, city_line)
        y -= 15
    y -= 12

    # === POLICY DETAILS BOX ===
    box_items = [f"Policy Number:  {policy_number}", f"Carrier:  {carrier_name}"]
    if amount_due:
        box_items.append(f"Amount Due:  ${amount_due:,.2f}")
    if due_date:
        box_items.append(f"Due Date:  {due_date}")
    box_height = 28 + len(box_items) * 16

    c.setFillColor(light_bg)
    c.setStrokeColor(light_line)
    c.setLineWidth(0.5)
    c.roundRect(left, y - box_height + 8, max_width, box_height, 4, stroke=1, fill=1)

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(navy)
    c.drawString(left + 12, y - 6, "Policy Details")
    y -= 20

    c.setFont("Helvetica", 10)
    c.setFillColor(dark_gray)
    for item in box_items:
        c.drawString(left + 12, y, item)
        y -= 16
    y -= 14

    # === BODY — Carrier-specific message ===
    first_name = client_name.split()[0] if client_name else "Valued Customer"
    y = _draw_wrapped_text(c, f"Dear {first_name},", left, y, "Helvetica", 10.5, max_width)
    y -= 6
    y = _draw_wrapped_text(c, carrier_message, left, y, "Helvetica", 10.5, max_width)
    y -= 4
    y = _draw_wrapped_text(
        c,
        "We understand that oversights happen, and we want to help you resolve this as "
        "quickly as possible. Please take a moment to make your payment using one of the "
        "following methods:",
        left, y, "Helvetica", 10.5, max_width,
    )
    y -= 8

    # === PAYMENT METHODS ===
    bullet_items = []
    if carrier_url:
        bullet_items.append(("Online:", carrier_url))
    if carrier_phone:
        bullet_items.append(("By Phone:", f"Call {carrier_name} at {carrier_phone}"))
    bullet_items.append(("Contact Us:", f"Call our office at {AGENCY_PHONE} for assistance"))

    for label, detail in bullet_items:
        c.setFont("Helvetica-Bold", 10.5)
        c.setFillColor(dark_gray)
        c.drawString(left + 15, y, "•")
        label_w = c.stringWidth(f"{label} ", "Helvetica-Bold", 10.5)
        c.drawString(left + 30, y, label)
        c.setFont("Helvetica", 10.5)
        c.drawString(left + 30 + label_w, y, f"  {detail}")
        y -= 17

    y -= 10

    # === CLOSING ===
    y = _draw_wrapped_text(
        c,
        "Please make your payment as soon as possible to avoid any lapse in coverage. "
        "If you have already made this payment, please disregard this notice.",
        left, y, "Helvetica", 10.5, max_width,
    )
    y -= 4
    y = _draw_wrapped_text(
        c,
        "If you are experiencing financial difficulties or have questions about your "
        "policy, please don't hesitate to contact our office. We are here to help you "
        "find the best solution to keep your coverage active.",
        left, y, "Helvetica", 10.5, max_width,
    )
    y -= 16

    c.setFont("Helvetica", 10.5)
    c.setFillColor(dark_gray)
    c.drawString(left, y, "Sincerely,")
    y -= 28
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(left, y, AGENCY_NAME)
    y -= 15
    c.setFont("Helvetica", 10)
    c.setFillColor(medium_gray)
    c.drawString(left, y, f"{AGENCY_PHONE}  |  {AGENCY_WEBSITE}")

    # === FOOTER DISCLAIMER ===
    # Divider line above disclaimer
    c.setStrokeColor(light_line)
    c.setLineWidth(0.5)
    c.line(left, 0.85 * inch, width - left, 0.85 * inch)

    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(medium_gray)
    disclaimer_lines = [
        "This is an automated courtesy reminder generated by Better Choice Insurance Group for informational purposes only.",
        "These notices are not guaranteed for every past-due policy and should not be relied upon as your sole source of billing",
        "information. The amount shown may not reflect recent payments or adjustments. Please contact your insurance carrier",
        "directly for the most accurate and up-to-date billing information. Better Choice Insurance Group is not responsible",
        "for any discrepancies between this notice and your carrier's records.",
    ]
    dy = 0.75 * inch
    for line in disclaimer_lines:
        c.drawCentredString(width / 2, dy, line)
        dy -= 9

    c.save()
    buf.seek(0)
    return buf.read()


def send_thanksio_letter(
    client_name: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    policy_number: str,
    carrier: str = "",
    amount_due: float = None,
    due_date: str = None,
) -> dict:
    """
    Generate a past-due PDF letter and send via Thanks.io API.

    Thanks.io requires a publicly accessible URL for the PDF (pdf_only_url).
    We save the PDF to a temp endpoint on our backend and pass that URL.

    Returns dict with 'success', 'order_id', 'error' keys.
    """
    if not THANKSIO_API_KEY:
        return {"success": False, "error": "THANKSIO_API_KEY not configured"}

    if not address or not city or not state or not zip_code:
        return {"success": False, "error": "Incomplete mailing address"}

    # Generate the PDF
    try:
        pdf_bytes = generate_pastdue_pdf(
            client_name=client_name,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            policy_number=policy_number,
            carrier=carrier,
            amount_due=amount_due,
            due_date=due_date,
        )
    except Exception as e:
        logger.error("PDF generation failed: %s", e)
        return {"success": False, "error": f"PDF generation failed: {str(e)}"}

    # Upload PDF to tmpfiles.org for a public URL (Thanks.io needs a URL, not base64)
    try:
        with httpx.Client(timeout=30) as client:
            upload_resp = client.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": ("letter.pdf", pdf_bytes, "application/pdf")},
            )
        if upload_resp.status_code != 200:
            return {"success": False, "error": f"PDF upload failed: {upload_resp.status_code}"}
        upload_data = upload_resp.json()
        raw_url = upload_data.get("data", {}).get("url", "")
        # Convert to direct download URL
        pdf_url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        if not pdf_url:
            return {"success": False, "error": "PDF upload returned no URL"}
    except Exception as e:
        logger.error("PDF upload failed: %s", e)
        return {"success": False, "error": f"PDF upload failed: {str(e)}"}

    # Build Thanks.io API payload
    # Correct endpoint: POST /send/letter (windowed) or /send/windowlessletter
    # Using windowless for a cleaner look
    payload = {
        "recipients": [
            {
                "name": client_name,
                "address": address,
                "city": city,
                "province": state,
                "postal_code": zip_code,
                "country": "US",
            }
        ],
        "pdf_only_url": pdf_url,
    }

    # Send via Thanks.io
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{THANKSIO_API_URL}/send/windowlessletter",
                json=payload,
                headers={
                    "Authorization": f"Bearer {THANKSIO_API_KEY}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            order_id = data.get("id") or data.get("order_id") or data.get("data", {}).get("id", "")
            logger.info("Thanks.io letter sent: order=%s, recipient=%s", order_id, client_name)
            return {"success": True, "order_id": str(order_id), "response": data}
        else:
            error_text = resp.text[:500]
            logger.error("Thanks.io API error %s: %s", resp.status_code, error_text)
            return {"success": False, "error": f"Thanks.io API {resp.status_code}: {error_text}"}

    except Exception as e:
        logger.error("Thanks.io API request failed: %s", e)
        return {"success": False, "error": f"API request failed: {str(e)}"}
