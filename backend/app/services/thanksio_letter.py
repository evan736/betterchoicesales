"""
Thanks.io integration for sending past-due letters to customers without email.

Generates a professional PDF letter, uploads it, and sends via Thanks.io API.
"""

import io
import os
import base64
import logging
from datetime import datetime

import httpx
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

THANKSIO_API_URL = "https://api.thanks.io/api/v2"
THANKSIO_API_KEY = os.environ.get("THANKSIO_API_KEY", "")

# Agency return address
AGENCY_NAME = "Better Choice Insurance Group"
AGENCY_ADDRESS = "1435 Randall Rd Ste 326"
AGENCY_CITY = "Crystal Lake"
AGENCY_STATE = "IL"
AGENCY_ZIP = "60014"
AGENCY_PHONE = "(847) 908-5665"
AGENCY_WEBSITE = "www.betterchoiceins.com"

# Carrier info for payment details
CARRIER_PAYMENT_INFO = {
    "travelers": {"name": "Travelers", "phone": "1-800-842-5075", "url": "https://www.travelers.com/pay-bill"},
    "progressive": {"name": "Progressive", "phone": "1-800-776-4737", "url": "https://www.progressive.com/pay-bill/"},
    "safeco": {"name": "Safeco", "phone": "1-800-332-3226", "url": "https://www.safeco.com/pay-bill"},
    "geico": {"name": "GEICO", "phone": "1-800-932-8872", "url": "https://www.geico.com/pay-bill/"},
    "grange": {"name": "Grange Insurance", "phone": "1-800-422-0550", "url": "https://www.grangeinsurance.com/pay-my-bill"},
    "hippo": {"name": "Hippo Insurance", "phone": "1-800-585-0705", "url": "https://www.hippo.com/pay"},
    "branch": {"name": "Branch Insurance", "phone": "1-833-427-2624", "url": "https://www.ourbranch.com/pay"},
    "national_general": {"name": "National General", "phone": "1-800-462-2123", "url": "https://www.nationalgeneral.com/pay-bill"},
    "bristol_west": {"name": "Bristol West", "phone": "1-888-888-0080", "url": "https://www.bristolwest.com/pay-bill"},
    "clearcover": {"name": "Clearcover", "phone": "1-855-444-1875", "url": "https://www.clearcover.com"},
    "openly": {"name": "Openly", "phone": "", "url": "https://www.openly.com"},
    "integrity": {"name": "Integrity Insurance", "phone": "1-800-898-4641", "url": "https://www.integrityinsurance.com"},
    "steadily": {"name": "Steadily", "phone": "", "url": "https://www.steadily.com"},
    "gainsco": {"name": "GAINSCO", "phone": "1-866-639-2860", "url": "https://www.gainsco.com"},
    "next": {"name": "NEXT Insurance", "phone": "1-855-222-5919", "url": "https://www.nextinsurance.com"},
    "universal_property": {"name": "Universal Property", "phone": "1-800-425-9113", "url": "https://www.universalproperty.com"},
    "american_modern": {"name": "American Modern", "phone": "1-800-543-2644", "url": "https://www.amig.com"},
    "covertree": {"name": "CoverTree", "phone": "", "url": "https://www.covertree.com"},
}


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
    """Generate a professional past-due notice PDF letter."""

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    # Colors
    navy = HexColor("#1a2744")
    red = HexColor("#c0392b")
    dark_gray = HexColor("#333333")
    medium_gray = HexColor("#666666")
    light_line = HexColor("#cccccc")

    # --- HEADER: Agency Letterhead ---
    y = height - 0.75 * inch

    # Agency name
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(navy)
    c.drawString(0.75 * inch, y, AGENCY_NAME)
    y -= 18

    # Agency address line
    c.setFont("Helvetica", 9)
    c.setFillColor(medium_gray)
    c.drawString(0.75 * inch, y, f"{AGENCY_ADDRESS}  |  {AGENCY_CITY}, {AGENCY_STATE} {AGENCY_ZIP}  |  {AGENCY_PHONE}")
    y -= 12
    c.drawString(0.75 * inch, y, AGENCY_WEBSITE)
    y -= 6

    # Divider line
    c.setStrokeColor(navy)
    c.setLineWidth(2)
    c.line(0.75 * inch, y, width - 0.75 * inch, y)
    y -= 30

    # --- DATE ---
    today_str = datetime.now().strftime("%B %d, %Y")
    c.setFont("Helvetica", 10)
    c.setFillColor(dark_gray)
    c.drawString(0.75 * inch, y, today_str)
    y -= 30

    # --- RECIPIENT ADDRESS ---
    c.setFont("Helvetica", 11)
    c.setFillColor(dark_gray)
    c.drawString(0.75 * inch, y, client_name)
    y -= 15
    if address:
        c.drawString(0.75 * inch, y, address)
        y -= 15
    city_state_zip = ", ".join(filter(None, [city, f"{state} {zip_code}" if state else zip_code]))
    if city_state_zip:
        c.drawString(0.75 * inch, y, city_state_zip)
        y -= 15
    y -= 15

    # --- SUBJECT LINE ---
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(red)
    c.drawString(0.75 * inch, y, "RE: IMPORTANT — Past Due Payment Notice")
    y -= 8

    # Red underline
    c.setStrokeColor(red)
    c.setLineWidth(1)
    c.line(0.75 * inch, y, 4.5 * inch, y)
    y -= 25

    # --- BODY ---
    carrier_info = CARRIER_PAYMENT_INFO.get(carrier, {})
    carrier_name = carrier_info.get("name", carrier.replace("_", " ").title() if carrier else "your insurance carrier")
    carrier_phone = carrier_info.get("phone", "")
    carrier_url = carrier_info.get("url", "")

    # Policy details box
    c.setStrokeColor(light_line)
    c.setLineWidth(0.5)
    box_top = y + 5
    box_height = 55
    if amount_due:
        box_height += 15
    if due_date:
        box_height += 15
    c.roundRect(0.75 * inch, y - box_height + 10, width - 1.5 * inch, box_height, 4, stroke=1, fill=0)

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(navy)
    c.drawString(1.0 * inch, y - 8, "Policy Details")
    y -= 22

    c.setFont("Helvetica", 10)
    c.setFillColor(dark_gray)
    c.drawString(1.0 * inch, y, f"Policy Number:  {policy_number}")
    y -= 15
    c.drawString(1.0 * inch, y, f"Carrier:  {carrier_name}")
    y -= 15
    if amount_due:
        c.drawString(1.0 * inch, y, f"Amount Due:  ${amount_due:,.2f}")
        y -= 15
    if due_date:
        c.drawString(1.0 * inch, y, f"Due Date:  {due_date}")
        y -= 15

    y -= 20

    # Letter body paragraphs
    c.setFont("Helvetica", 10.5)
    c.setFillColor(dark_gray)
    line_height = 15
    left = 0.75 * inch
    max_width = width - 1.5 * inch

    paragraphs = [
        f"Dear {client_name.split()[0] if client_name else 'Valued Customer'},",
        "",
        f"We are writing to inform you that your insurance policy with {carrier_name} "
        f"has an outstanding balance that requires your immediate attention. Failure to "
        f"make payment may result in the cancellation of your policy, leaving you without "
        f"coverage.",
        "",
        "We understand that oversights happen, and we want to help you resolve this as "
        "quickly as possible. Please take a moment to make your payment using one of the "
        "following methods:",
    ]

    for para in paragraphs:
        if not para:
            y -= 8
            continue
        # Simple word-wrap
        words = para.split()
        line = ""
        for word in words:
            test_line = f"{line} {word}".strip()
            if c.stringWidth(test_line, "Helvetica", 10.5) > max_width:
                c.drawString(left, y, line)
                y -= line_height
                line = word
            else:
                line = test_line
        if line:
            c.drawString(left, y, line)
            y -= line_height

    y -= 5

    # Payment methods
    bullet_items = []
    if carrier_url:
        bullet_items.append(f"Online:  {carrier_url}")
    if carrier_phone:
        bullet_items.append(f"By Phone:  Call {carrier_name} at {carrier_phone}")
    bullet_items.append(f"Contact Us:  Call our office at {AGENCY_PHONE} for assistance")

    for item in bullet_items:
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(left + 15, y, "•")
        c.setFont("Helvetica", 10.5)
        # Word wrap bullet items
        words = item.split()
        line = ""
        first_line = True
        for word in words:
            test_line = f"{line} {word}".strip()
            indent = left + 30 if first_line else left + 30
            if c.stringWidth(test_line, "Helvetica", 10.5) > (max_width - 30):
                c.drawString(indent, y, line)
                y -= line_height
                line = word
                first_line = False
            else:
                line = test_line
        if line:
            c.drawString(left + 30, y, line)
            y -= line_height
        y -= 3

    y -= 10

    # Closing paragraphs
    closing = [
        "Please make your payment as soon as possible to avoid any lapse in coverage. "
        "If you have already made this payment, please disregard this notice.",
        "",
        "If you are experiencing financial difficulties or have questions about your "
        "policy, please don't hesitate to contact our office. We are here to help you "
        "find the best solution to keep your coverage active.",
        "",
        "Sincerely,",
        "",
        "",
        AGENCY_NAME,
        f"{AGENCY_PHONE}  |  {AGENCY_WEBSITE}",
    ]

    for para in closing:
        if not para:
            y -= 10
            continue
        words = para.split()
        line = ""
        for word in words:
            test_line = f"{line} {word}".strip()
            if c.stringWidth(test_line, "Helvetica", 10.5) > max_width:
                c.drawString(left, y, line)
                y -= line_height
                line = word
            else:
                line = test_line
        if line:
            c.drawString(left, y, line)
            y -= line_height

    # --- FOOTER ---
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(medium_gray)
    c.drawCentredString(width / 2, 0.5 * inch,
                        "This is an automated notice from Better Choice Insurance Group. Please retain for your records.")

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

    # Encode PDF as base64 for Thanks.io
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    # Build Thanks.io API payload
    payload = {
        "recipient": {
            "name": client_name,
            "address": address,
            "city": city,
            "state": state,
            "zip": zip_code,
        },
        "return_address": {
            "name": AGENCY_NAME,
            "address": AGENCY_ADDRESS,
            "city": AGENCY_CITY,
            "state": AGENCY_STATE,
            "zip": AGENCY_ZIP,
        },
        "letter_pdf": f"data:application/pdf;base64,{pdf_b64}",
    }

    # Send via Thanks.io
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{THANKSIO_API_URL}/letter/send",
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
            error_text = resp.text[:300]
            logger.error("Thanks.io API error %s: %s", resp.status_code, error_text)
            return {"success": False, "error": f"Thanks.io API {resp.status_code}: {error_text}"}

    except Exception as e:
        logger.error("Thanks.io API request failed: %s", e)
        return {"success": False, "error": f"API request failed: {str(e)}"}
