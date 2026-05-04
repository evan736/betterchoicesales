"""Cold Prospect Outreach — Allstate X-date prospects.

Separate from the WinBackCampaign system because:
  - These are NOT former customers — they are prospects from the
    Allstate territorial X-date export. We have no prior relationship.
  - Email copy must NOT reference "you previously were insured with us"
  - Stop condition is sale-uploaded (became client), not "won-back"
  - Need bounce handling (cold list → high bounce risk)
  - Need DNC compliance flags from source data

Lifecycle:
  1. Import CSV → cold_prospects rows with status='active', phase='cold_wakeup'
  2. Validate emails (regex + DNS-MX)
  3. Phase 1 cold_wakeup → first email, paced over 90 days
  4. Phase 2 x_date_prep → -30/-21/-14/-7 day pre-renewal sequence
  5. After cycle 4 emails complete → next_x_date += 365 days, cycle++
  6. Continue forever (no auto-stop on cycle count)
  7. Stop on: sale uploaded matching email/name, reply, hard bounce, opt-out

Email content rotation:
  - 4 distinct copy variants per producer (joseph/evan/giulian)
  - last_email_variant tracks which was used last
  - Next contact picks a different variant

Compliance:
  - Skip records with Mail Status='Do Not Mail' from source
  - Skip records that fail email validation
  - List-Unsubscribe header on every send (mailer hook handles this)
  - Honor STOP replies via Smart Inbox webhook → set status='paused_unsubscribed'
"""
import csv
import io
import re
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, func as sa_func

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.campaign import ColdProspect, WinBackCampaign
from app.models.customer import Customer
from app.models.sale import Sale
from app.services.email_validator import validate_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cold-prospects", tags=["cold-prospects"])


# ─────────────────────────────────────────────────────────────────────
# Round-Robin Producer Assignment
# ─────────────────────────────────────────────────────────────────────
# Same three producers as winback. ID-based assignment so the same
# prospect always gets the same producer (continuity on follow-ups).
COLD_ROUND_ROBIN = [
    {
        "username": "joseph.rivera",
        "full_name": "Joseph Rivera",
        "first_name": "Joseph",
        "email": "joseph@betterchoiceins.com",
    },
    {
        "username": "evan.larson",
        "full_name": "Evan Larson",
        "first_name": "Evan",
        "email": "evan@betterchoiceins.com",
    },
    {
        "username": "giulian.baez",
        "full_name": "Giulian Baez",
        "first_name": "Giulian",
        "email": "giulian@betterchoiceins.com",
    },
]


def _get_assigned_producer(prospect: ColdProspect) -> dict:
    """Return the round-robin producer assigned to this prospect."""
    if prospect.assigned_producer:
        for p in COLD_ROUND_ROBIN:
            if prospect.assigned_producer.lower() in (
                p["username"], p["full_name"].lower(), p["first_name"].lower()
            ):
                return p
    idx = (prospect.id or 0) % len(COLD_ROUND_ROBIN)
    return COLD_ROUND_ROBIN[idx]


# ─────────────────────────────────────────────────────────────────────
# Email Content (4 rotating variants per producer)
# ─────────────────────────────────────────────────────────────────────

def _build_cold_email(prospect: ColdProspect, variant: str = "v1") -> tuple[str, str]:
    """Build (subject, html) for a cold-prospect email.

    Subject lines lean heavily on the rate-decrease hook because that's
    the actual "why you should open this" value prop. ~80% of subjects
    mention rates explicitly. Variety across producer × variant
    combinations so the same prospect doesn't see two identical
    subjects across follow-ups.

    Body intentionally avoids:
      - Stacked "Mind if... Mind sending..." asks (one ask only)
      - Defensive hedging ("actually", "I think")
      - Generic closes ("whatever's easier")
      - Marketing-speak ("at Better Choice Insurance, we...")
    """
    first_name = prospect.first_name.title() if prospect.first_name else "there"
    producer = _get_assigned_producer(prospect)

    # LOB phrasing
    pt = (prospect.policy_type or "").lower()
    if "auto" in pt and "home" not in pt:
        scope_short = "auto"
        scope_long = "your auto"
        verify = "Send over the year/make/model on the cars and I'll dig in."
    elif "home" in pt and "auto" not in pt:
        scope_short = "home"
        scope_long = "your home"
        verify = "If you can ballpark when the roof was last replaced, I can run a few options."
    elif pt:
        scope_short = "insurance"
        scope_long = "your insurance"
        verify = "Send over a quick snapshot of what you've got now and I'll match it up."
    else:
        scope_short = "insurance"
        scope_long = "your home and auto"
        verify = "Send the year/make/model on the cars and a rough year on the roof — I'll handle the rest."

    # Their current carrier — gives the email specificity if we have it
    current_carrier = (prospect.company or "").strip()
    # Strip generic suffixes for cleaner inline use
    for suffix in (" insurance", " ins", " prop & cas", " property & casualty"):
        if current_carrier.lower().endswith(suffix):
            current_carrier = current_carrier[: -len(suffix)].strip()
    # Title-case if all-caps
    if current_carrier.isupper():
        current_carrier = current_carrier.title()

    # ─────── PER-PRODUCER, PER-VARIANT CONTENT ───────

    if producer["first_name"] == "Joseph":
        if variant == "v1":
            subject = "rates dropped — worth a quick look?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Joseph Rivera over at Better Choice Insurance. Quick reason for the email — "
                f"a bunch of carriers we work with (NatGen, Progressive, GEICO, Travelers) "
                f"filed rate decreases over the last few months. Doesn't always happen, so "
                f"figured I'd reach out.<br><br>"
                f"Want me to take a fresh look at {scope_long}? {verify}<br><br>"
                f"Easy text or call too: (847) 908-5665."
            )
        elif variant == "v2":
            subject = f"{first_name} — carriers came down on rates"
            body = (
                f"Hey {first_name},<br><br>"
                f"Joseph at Better Choice. Several carriers have cut rates recently — "
                f"first time in a couple years. Wanted to flag it.<br><br>"
                f"If you're up for me running fresh quotes on {scope_long}, "
                f"{verify.lower()}<br><br>"
                f"Or hop on the phone for 5 minutes."
            )
        elif variant == "v3":
            current_ref = f" (saw you're with {current_carrier} now)" if current_carrier else ""
            subject = "saw rates moved — quick check?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Joseph Rivera, independent agent in Saint Charles. "
                f"Reaching out{current_ref} because rates have come down enough lately "
                f"that it's worth a side-by-side.<br><br>"
                f"Quick quote on {scope_long}? {verify}<br><br>"
                f"Reply works, so does a call: (847) 908-5665."
            )
        else:  # v4
            subject = f"quote you up, {first_name}?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Joseph at Better Choice Insurance. Carriers have been cutting rates the "
                f"last few months. If you haven't shopped {scope_long} recently, this is "
                f"a decent window to do it.<br><br>"
                f"{verify}<br><br>"
                f"Reply or call me direct."
            )

    elif producer["first_name"] == "Evan":
        if variant == "v1":
            subject = "rates came back down — worth a look"
            body = (
                f"Hey {first_name},<br><br>"
                f"Evan Larson at Better Choice Insurance Group. Independent agency in "
                f"Saint Charles. Reason for the email: most of our carriers filed rate "
                f"decreases over the last couple of months and I'd hate for you to miss it.<br><br>"
                f"Want me to put a fresh quote together for {scope_long}? {verify}<br><br>"
                f"Or 5 minutes on the phone works: (847) 908-5665."
            )
        elif variant == "v2":
            subject = f"{first_name}, rate decreases worth flagging"
            body = (
                f"Hey {first_name},<br><br>"
                f"Evan Larson over at Better Choice. Several carriers (Progressive, NatGen, "
                f"Travelers, GEICO) have come down on rates recently. After two years of "
                f"increases, this is the first real reversal.<br><br>"
                f"Worth a quick comparison on {scope_long}? {verify}<br><br>"
                f"Talk soon."
            )
        elif variant == "v3":
            current_ref = f"with {current_carrier}" if current_carrier else "wherever you are"
            subject = "carriers filed rate decreases — quick check?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Evan from Better Choice Insurance. Whether you're {current_ref} now, "
                f"worth knowing that several carriers have cut rates recently. "
                f"That doesn't last forever.<br><br>"
                f"Mind if I run a few options on {scope_long}? {verify}<br><br>"
                f"Reply with your dec page or grab a phone call — easier on the phone."
            )
        else:  # v4
            subject = f"hi {first_name} — fresh quote?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Evan Larson at Better Choice. Rates have moved meaningfully on a few "
                f"carriers recently. I track this stuff and figured I'd reach out.<br><br>"
                f"{verify} I'll pull options and send something over.<br><br>"
                f"Or call: (847) 908-5665."
            )

    else:  # Giulian
        if variant == "v1":
            subject = "rates are dropping — quick look?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Giulian Baez at Better Choice Insurance, independent agency in Saint "
                f"Charles. Reaching out because rates have come back down with a handful "
                f"of our carriers — first time in a while.<br><br>"
                f"Want me to take a fresh look at {scope_long}? {verify}<br><br>"
                f"Reply or text/call: (847) 908-5665."
            )
        elif variant == "v2":
            subject = f"{first_name} — carriers cut rates recently"
            body = (
                f"Hey {first_name},<br><br>"
                f"Giulian over at Better Choice. NatGen, Progressive, Travelers all came "
                f"down on rates over the last few months. Worth a re-shop.<br><br>"
                f"Take 5 minutes? {verify}<br><br>"
                f"Or hop on a quick call."
            )
        elif variant == "v3":
            current_ref = f"saw you're with {current_carrier}, " if current_carrier else ""
            subject = "rates moved — figured you'd want to know"
            body = (
                f"Hey {first_name},<br><br>"
                f"Giulian Baez, Better Choice Insurance. {current_ref.capitalize()}"
                f"and a few carriers we work with have cut rates lately. Felt like a "
                f"reasonable reason to reach out.<br><br>"
                f"Quick quote on {scope_long}? {verify}<br><br>"
                f"Reply or call works."
            )
        else:  # v4
            subject = f"fresh quotes, {first_name}?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Giulian at Better Choice. Carriers have come down on rates recently. "
                f"If you've been with the same carrier for a few years, probably worth "
                f"taking a look.<br><br>"
                f"{verify}<br><br>"
                f"Reply or call me direct."
            )

    # Headshot only for Evan's emails (per Evan)
    from app.services.producer_signatures import producer_headshot_html
    headshot_html = producer_headshot_html(producer["first_name"], size_px=96)

    body_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1a1a1a;">
<div style="max-width:560px;margin:0 auto;padding:24px 20px;">
<p style="margin:0 0 16px 0;">{body}</p>
<div style="margin:0 0 4px 0;">{headshot_html}— {producer['first_name']}</div>
<p style="margin:0 0 2px 0;color:#666;font-size:13px;">{producer['full_name']}</p>
<p style="margin:0 0 2px 0;color:#666;font-size:13px;">Better Choice Insurance Group</p>
<p style="margin:0 0 2px 0;color:#666;font-size:13px;">(847) 908-5665 &middot; {producer['email']}</p>
<p style="margin:24px 0 0 0;color:#a3a3a3;font-size:11px;border-top:1px solid #eee;padding-top:12px;">
<img src="https://www.betterchoiceins.com/images/logo.png" alt="Better Choice Insurance Group" width="140" style="display:block;margin:0 0 8px 0;max-width:140px;height:auto;" /><br>
Better Choice Insurance Group &middot; 300 Cardinal Dr Suite 220, Saint Charles, IL 60175<br>
Don't want these? Just reply STOP and I'll take you off the list.
</p>
</div>
</body></html>"""

    return subject, body_html


def _next_variant(last: Optional[str]) -> str:
    """Pick the next variant in rotation. Cycle: v1 → v2 → v3 → v4 → v1."""
    order = ["v1", "v2", "v3", "v4"]
    if not last or last not in order:
        return "v1"
    idx = (order.index(last) + 1) % len(order)
    return order[idx]


def _send_cold_email(prospect: ColdProspect, db: Session) -> bool:
    """Send a cold-outreach email via Mailgun."""
    from app.core.config import settings
    import requests

    if not prospect.email:
        return False
    if prospect.do_not_email:
        return False
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Cold prospect send blocked — Mailgun not configured")
        return False

    producer = _get_assigned_producer(prospect)
    variant = _next_variant(prospect.last_email_variant)
    subject, html = _build_cold_email(prospect, variant=variant)
    from_header = f"{producer['full_name']} <sales@betterchoiceins.com>"

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": from_header,
                "to": [prospect.email],
                "subject": subject,
                "html": html,
                "h:Reply-To": producer["email"],
                "v:email_type": "cold_prospect",
                "v:cold_prospect_id": str(prospect.id),
                "v:variant": variant,
                "v:assigned_producer": producer["username"],
            },
            timeout=15,
        )
        if resp.status_code == 200:
            prospect.last_email_variant = variant
            logger.info(
                "Cold email sent: id=%s variant=%s to=%s producer=%s",
                prospect.id, variant, prospect.email, producer["username"],
            )
            return True
        logger.error(
            "Cold email failed: id=%s status=%s body=%s",
            prospect.id, resp.status_code, resp.text[:200],
        )
        return False
    except Exception as e:
        logger.error(f"Cold email error: id={prospect.id} {e}")
        return False


# ─────────────────────────────────────────────────────────────────────
# CSV Import
# ─────────────────────────────────────────────────────────────────────

# CSV column maps for the two known formats. Both Allstate exports.
F1_FIELD_MAP = {
    "first_name": "First Name",
    "last_name": "Last Name",
    "email": "Email",
    "home_phone": "Home Phone",
    "work_phone": "Work Phone",
    "mobile_phone": "Mobile Phone",
    "street": "Street1",
    "city": "City",
    "state": "State",
    "zip_code": "Zip",
    "policy_type": "Policy Type",
    "company": "Company",
    "premium": "Premium",
    "quoted_company": "Quoted Company",
    "quoted_premium": "Quoted Premium",
    "x_date": "XDate",
    "status": "Status",
}

F2_FIELD_MAP = {
    "first_name": "First Name",
    "last_name": "Last Name",
    "email": "Email",
    "home_phone": "Phone",  # File 2 uses "Phone" not "Home Phone"
    "work_phone": "Work Phone",
    "mobile_phone": "Mobile Phone",
    "street": "Street Address",  # File 2 differs
    "city": "City",
    "state": "State",
    "zip_code": "Zip",
    "policy_type": "Policy Type",
    "company": "Company",
    "premium": "Premium",
    "quoted_company": "Quoted Company",
    "quoted_premium": "Quoted Premium",
    "x_date": "XDate",
    "mail_status": "Mail Status",
    "call_status": "Call Status",
    "customer_status": "Customer Status",
}


def _parse_premium(raw) -> Optional[Decimal]:
    if raw is None:
        return None
    s = str(raw).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
        return d if d > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _parse_us_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _project_x_date_forward(original: datetime) -> datetime:
    """Advance an X-date in 12-month increments until it's in the future.

    The CSV X-dates are historical (mostly 2017-2022). Customers presumably
    renew annually, so their CURRENT renewal anniversary is N years later
    where N puts the result in the future.
    """
    target = original
    now = datetime.utcnow()
    while target < now:
        target = target + timedelta(days=365)
    return target


def _detect_csv_format(reader_fieldnames: list) -> str:
    """Return 'f1' or 'f2' based on which expected columns are present.

    F2 has 'Mail Status' / 'Call Status' / 'Customer Status' — F1 doesn't.
    F2 has 'Street Address' — F1 has 'Street1'.
    """
    if "Mail Status" in reader_fieldnames or "Customer Status" in reader_fieldnames:
        return "f2"
    if "Street1" in reader_fieldnames:
        return "f1"
    # Default to f1 if we can't tell
    return "f1"


def _normalize_phone(s: str) -> str:
    """Strip non-digits."""
    if not s:
        return ""
    return re.sub(r"\D+", "", s)


@router.post("/import-csv")
async def import_cold_prospects_csv(
    file: UploadFile = File(...),
    source_label: str = Form(..., description="e.g. 'allstate_xdate_2026'"),
    skip_header_lines: int = Form(0, description="For files with preamble (File 2 has 17)"),
    dry_run: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a cold-prospect CSV (Allstate X-date export format).

    Auto-detects the two known formats:
      - F1: ALL_LINES_ALL_SE_X_DATES_UNSCRUBBED (no Customer Status column)
      - F2: XDATE_FILE_USE_FOR_2026 (has Customer Status, Mail Status, Call Status)

    Dedup logic:
      1. Skip if email already in cold_prospects table
      2. Skip if email matches an active customer (Customers.email)
      3. Skip if email matches an open winback campaign
      4. Skip if Mail Status='Do Not Mail' (compliance)
      5. Skip if Customer Status in ('Customer', 'Claim Contact') — F2 only
      6. Skip if email fails local syntax validation (DNS check happens
         in a separate endpoint to avoid timing out the import)

    dry_run=True (default) shows what WOULD happen without writing.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    raw = await file.read()
    if len(raw) > 100_000_000:
        raise HTTPException(status_code=400, detail="File too large")

    text_data = raw.decode("utf-8-sig", errors="replace")
    if skip_header_lines > 0:
        # Drop preamble lines
        lines = text_data.split("\n")
        text_data = "\n".join(lines[skip_header_lines:])

    reader = csv.DictReader(io.StringIO(text_data))
    fieldnames = reader.fieldnames or []
    fmt = _detect_csv_format(fieldnames)
    fmap = F2_FIELD_MAP if fmt == "f2" else F1_FIELD_MAP

    # Pre-load suppression sets
    existing_emails = set(
        e.lower()
        for (e,) in db.query(ColdProspect.email).filter(ColdProspect.email.isnot(None)).all()
        if e
    )
    customer_emails = set(
        e.lower()
        for (e,) in db.query(Customer.email).filter(Customer.email.isnot(None)).all()
        if e
    )
    winback_emails = set(
        e.lower()
        for (e,) in db.query(WinBackCampaign.customer_email)
        .filter(WinBackCampaign.customer_email.isnot(None))
        .all()
        if e
    )

    counts = {
        "total_rows": 0,
        "would_insert": 0,
        "skipped_no_email": 0,
        "skipped_invalid_email_syntax": 0,
        "skipped_already_in_cold": 0,
        "skipped_already_customer": 0,
        "skipped_already_in_winback": 0,
        "skipped_do_not_mail": 0,
        "skipped_active_customer_status": 0,
        "skipped_claim_contact": 0,
    }
    by_state: dict[str, int] = {}
    by_year: dict[int, int] = {}
    by_customer_status: dict[str, int] = {}

    rows_to_insert = []
    seen_in_csv = set()

    for raw_row in reader:
        counts["total_rows"] += 1

        # Parse fields
        email_raw = (raw_row.get(fmap.get("email", "Email"), "") or "").strip()
        if not email_raw:
            counts["skipped_no_email"] += 1
            continue

        # Quick syntax check (no DNS — that's a separate validation pass)
        v = validate_email(email_raw, check_mx=False)
        if not v["valid"]:
            counts["skipped_invalid_email_syntax"] += 1
            continue
        email = v["normalized"]

        # Dedup within CSV itself
        if email in seen_in_csv:
            continue
        seen_in_csv.add(email)

        # Cross-table dedup
        if email in existing_emails:
            counts["skipped_already_in_cold"] += 1
            continue
        if email in customer_emails:
            counts["skipped_already_customer"] += 1
            continue
        if email in winback_emails:
            counts["skipped_already_in_winback"] += 1
            continue

        # Compliance flags
        mail_status = (raw_row.get("Mail Status") or "").strip()
        call_status = (raw_row.get("Call Status") or "").strip()
        customer_status = (raw_row.get("Customer Status") or "").strip()

        if mail_status.lower() == "do not mail":
            counts["skipped_do_not_mail"] += 1
            continue
        if customer_status == "Customer":
            counts["skipped_active_customer_status"] += 1
            continue
        if customer_status == "Claim Contact":
            counts["skipped_claim_contact"] += 1
            continue

        # Parse remaining fields
        first = (raw_row.get(fmap["first_name"], "") or "").strip().title()
        last = (raw_row.get(fmap["last_name"], "") or "").strip().title()
        full_name = f"{first} {last}".strip()
        original_xd = _parse_us_date(raw_row.get(fmap.get("x_date", "XDate"), ""))
        next_xd = _project_x_date_forward(original_xd) if original_xd else None
        if not next_xd:
            # Default to ~6 months out if no X-date, so we still queue
            # them but with low priority
            next_xd = datetime.utcnow() + timedelta(days=180)

        prospect_data = {
            "first_name": first,
            "last_name": last,
            "full_name": full_name,
            "email": email,
            "home_phone": _normalize_phone(raw_row.get(fmap.get("home_phone", "Home Phone"), "") or "")[:20] or None,
            "work_phone": _normalize_phone(raw_row.get(fmap.get("work_phone", "Work Phone"), "") or "")[:20] or None,
            "mobile_phone": _normalize_phone(raw_row.get(fmap.get("mobile_phone", "Mobile Phone"), "") or "")[:20] or None,
            "street": (raw_row.get(fmap.get("street", "Street1"), "") or "").strip()[:200] or None,
            "city": (raw_row.get(fmap.get("city", "City"), "") or "").strip().title()[:100] or None,
            "state": (raw_row.get(fmap.get("state", "State"), "") or "").strip().upper()[:2] or None,
            "zip_code": (raw_row.get(fmap.get("zip_code", "Zip"), "") or "").strip()[:10] or None,
            "policy_type": (raw_row.get(fmap.get("policy_type", "Policy Type"), "") or "").strip()[:100] or None,
            "company": (raw_row.get(fmap.get("company", "Company"), "") or "").strip()[:100] or None,
            "premium": _parse_premium(raw_row.get(fmap.get("premium", "Premium"), "")),
            "quoted_company": (raw_row.get(fmap.get("quoted_company", "Quoted Company"), "") or "").strip()[:100] or None,
            "quoted_premium": _parse_premium(raw_row.get(fmap.get("quoted_premium", "Quoted Premium"), "")),
            "customer_status": customer_status[:50] or None,
            "original_x_date": original_xd,
            "next_x_date": next_xd,
            "mail_status": mail_status[:50] or None,
            "call_status": call_status[:50] or None,
            "do_not_email": False,  # Mail Status doesn't apply to email
            "do_not_text": call_status.lower() == "do not call",
            "do_not_call": call_status.lower() == "do not call",
            "phase": "cold_wakeup",
            "status": "active",
            "source": source_label,
        }

        if next_xd:
            yr = next_xd.year
            by_year[yr] = by_year.get(yr, 0) + 1
        if customer_status:
            by_customer_status[customer_status] = by_customer_status.get(customer_status, 0) + 1
        if prospect_data["state"]:
            by_state[prospect_data["state"]] = by_state.get(prospect_data["state"], 0) + 1

        counts["would_insert"] += 1

        if not dry_run:
            rows_to_insert.append(ColdProspect(**prospect_data))
            existing_emails.add(email)  # avoid intra-batch dup

    if not dry_run and rows_to_insert:
        # Bulk insert in batches of 1000 to keep transactions short
        for i in range(0, len(rows_to_insert), 1000):
            batch = rows_to_insert[i:i + 1000]
            db.add_all(batch)
            db.flush()
        db.commit()

    return {
        "dry_run": dry_run,
        "format_detected": fmt,
        "source_label": source_label,
        **counts,
        "by_year": dict(sorted(by_year.items())),
        "by_customer_status": by_customer_status,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: -kv[1])[:20]),
    }


# ─────────────────────────────────────────────────────────────────────
# Email Validation Pass (DNS-MX)
# ─────────────────────────────────────────────────────────────────────

@router.post("/validate-emails")
def validate_emails_batch(
    batch_size: int = Query(500, description="How many to validate this call"),
    only_unvalidated: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run DNS-MX validation on cold_prospects emails.

    Idempotent — sets email_validated=True and email_valid based on result.
    Designed to be called repeatedly (each call processes batch_size).

    Records that fail validation get status='excluded' with reason.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    query = db.query(ColdProspect).filter(
        ColdProspect.email.isnot(None),
    )
    if only_unvalidated:
        query = query.filter(ColdProspect.email_validated == False)
    query = query.limit(batch_size)

    prospects = query.all()
    if not prospects:
        return {"checked": 0, "remaining_unvalidated": 0, "message": "no records to validate"}

    valid_count = 0
    invalid_count = 0
    by_reason: dict[str, int] = {}

    for p in prospects:
        result = validate_email(p.email, check_mx=True)
        p.email_validated = True
        p.email_valid = result["valid"]
        p.email_validation_reason = result["reason"]
        p.email_validated_at = datetime.utcnow()
        if not result["valid"]:
            invalid_count += 1
            by_reason[result["reason"]] = by_reason.get(result["reason"], 0) + 1
            # Auto-suppress invalid emails
            p.status = "excluded"
            p.excluded = True
            p.excluded_reason = f"email_invalid:{result['reason']}"
        else:
            valid_count += 1

    db.commit()

    remaining = db.query(sa_func.count(ColdProspect.id)).filter(
        ColdProspect.email_validated == False,
        ColdProspect.email.isnot(None),
    ).scalar()

    return {
        "checked": len(prospects),
        "valid": valid_count,
        "invalid": invalid_count,
        "by_invalid_reason": by_reason,
        "remaining_unvalidated": remaining,
    }


# ─────────────────────────────────────────────────────────────────────
# Round-Robin Assignment
# ─────────────────────────────────────────────────────────────────────

@router.post("/assign-round-robin")
def assign_cold_round_robin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign all unassigned active cold_prospects to round-robin producer."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    candidates = db.query(ColdProspect).filter(
        ColdProspect.excluded == False,
        ColdProspect.status == "active",
        ColdProspect.assigned_producer.is_(None),
    ).all()

    counts = {p["username"]: 0 for p in COLD_ROUND_ROBIN}
    for c in candidates:
        idx = (c.id or 0) % len(COLD_ROUND_ROBIN)
        producer = COLD_ROUND_ROBIN[idx]
        c.assigned_producer = producer["username"]
        counts[producer["username"]] += 1

    db.commit()
    return {"assigned": len(candidates), "by_producer": counts}


# ─────────────────────────────────────────────────────────────────────
# Stats / List
# ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
def cold_prospect_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Quick cohort stats."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    total = db.query(sa_func.count(ColdProspect.id)).scalar()

    by_status = {}
    for status, count in db.query(
        ColdProspect.status, sa_func.count(ColdProspect.id)
    ).group_by(ColdProspect.status).all():
        by_status[status or "null"] = count

    by_phase = {}
    for phase, count in db.query(
        ColdProspect.phase, sa_func.count(ColdProspect.id)
    ).group_by(ColdProspect.phase).all():
        by_phase[phase or "null"] = count

    by_validation = {
        "validated": db.query(sa_func.count(ColdProspect.id)).filter(ColdProspect.email_validated == True).scalar(),
        "valid": db.query(sa_func.count(ColdProspect.id)).filter(ColdProspect.email_valid == True).scalar(),
        "invalid": db.query(sa_func.count(ColdProspect.id)).filter(
            ColdProspect.email_validated == True,
            ColdProspect.email_valid == False,
        ).scalar(),
        "unvalidated": db.query(sa_func.count(ColdProspect.id)).filter(ColdProspect.email_validated == False).scalar(),
    }

    by_customer_status = {}
    for cs, count in db.query(
        ColdProspect.customer_status, sa_func.count(ColdProspect.id)
    ).group_by(ColdProspect.customer_status).all():
        by_customer_status[cs or "null"] = count

    sendable = db.query(sa_func.count(ColdProspect.id)).filter(
        ColdProspect.excluded == False,
        ColdProspect.status == "active",
        ColdProspect.email_valid == True,
        ColdProspect.do_not_email == False,
        ColdProspect.email.isnot(None),
    ).scalar()

    sent_count = db.query(sa_func.count(ColdProspect.id)).filter(
        ColdProspect.touchpoint_count > 0,
    ).scalar()

    converted = db.query(sa_func.count(ColdProspect.id)).filter(
        ColdProspect.status == "converted",
    ).scalar()

    return {
        "total": total,
        "by_status": by_status,
        "by_phase": by_phase,
        "by_email_validation": by_validation,
        "by_customer_status": by_customer_status,
        "sendable_now": sendable,
        "ever_emailed": sent_count,
        "converted": converted,
    }


@router.get("/")
def list_cold_prospects(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None, description="Match against name or email"),
    status: Optional[str] = Query(None, description="Filter by status (active, paused_bounced, paused_replied, converted, ...)"),
    customer_status: Optional[str] = Query(None, description="Filter by source customer_status (Prospect, Former Customer, ...)"),
    assigned_producer: Optional[str] = Query(None, description="Filter by assigned producer username"),
    contacted: Optional[bool] = Query(None, description="True = touchpoint_count > 0; False = never contacted"),
    sort_by: str = Query("id", description="One of: id, name, email, premium, touchpoint_count, last_touchpoint_at"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paginated list of cold prospects with search + filter support.

    Returns:
      - items: page of records
      - total: total count matching filters (for pagination UI)
      - page_total: count of items on this page

    Designed for the /winback page's Cold Prospects tab. Default sort
    by id desc gives the most-recently-imported first.
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    q = db.query(ColdProspect)

    # ── Filters ────────────────────────────────────────────────────
    if status:
        q = q.filter(ColdProspect.status == status)

    if customer_status:
        # Allow special value 'null' for records with no customer_status
        if customer_status.lower() == "null":
            q = q.filter(ColdProspect.customer_status.is_(None))
        else:
            q = q.filter(ColdProspect.customer_status == customer_status)

    if assigned_producer:
        if assigned_producer.lower() == "unassigned":
            q = q.filter(ColdProspect.assigned_producer.is_(None))
        else:
            q = q.filter(ColdProspect.assigned_producer == assigned_producer)

    if contacted is not None:
        if contacted:
            q = q.filter(ColdProspect.touchpoint_count > 0)
        else:
            q = q.filter(
                (ColdProspect.touchpoint_count == 0) | (ColdProspect.touchpoint_count.is_(None))
            )

    if search:
        like = f"%{search.lower()}%"
        q = q.filter(
            sa_func.lower(ColdProspect.full_name).like(like)
            | sa_func.lower(ColdProspect.email).like(like)
            | sa_func.lower(ColdProspect.first_name).like(like)
            | sa_func.lower(ColdProspect.last_name).like(like)
        )

    # ── Total before pagination ────────────────────────────────────
    total = q.count()

    # ── Sorting ────────────────────────────────────────────────────
    sort_col_map = {
        "id": ColdProspect.id,
        "name": ColdProspect.full_name,
        "email": ColdProspect.email,
        "premium": ColdProspect.premium,
        "touchpoint_count": ColdProspect.touchpoint_count,
        "last_touchpoint_at": ColdProspect.last_touchpoint_at,
    }
    sort_col = sort_col_map.get(sort_by, ColdProspect.id)
    if sort_dir == "asc":
        q = q.order_by(sort_col.asc().nulls_last())
    else:
        q = q.order_by(sort_col.desc().nulls_last())

    rows = q.offset(skip).limit(limit).all()

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "full_name": r.full_name,
            "first_name": r.first_name,
            "last_name": r.last_name,
            "email": r.email,
            "phone": r.mobile_phone or r.home_phone or r.work_phone,
            "city": r.city,
            "state": r.state,
            "zip_code": r.zip_code,
            "policy_type": r.policy_type,
            "company": r.company,
            "premium": float(r.premium) if r.premium else None,
            "customer_status": r.customer_status,
            "next_x_date": r.next_x_date.isoformat() if r.next_x_date else None,
            "phase": r.phase,
            "status": r.status,
            "touchpoint_count": r.touchpoint_count or 0,
            "last_touchpoint_at": r.last_touchpoint_at.isoformat() if r.last_touchpoint_at else None,
            "last_email_variant": r.last_email_variant,
            "assigned_producer": r.assigned_producer,
            "email_valid": r.email_valid,
            "do_not_email": r.do_not_email,
            "bounce_count": r.bounce_count or 0,
            "excluded": r.excluded,
            "excluded_reason": r.excluded_reason,
            "converted_at": r.converted_at.isoformat() if r.converted_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page_total": len(items),
        "skip": skip,
        "limit": limit,
    }


# ─────────────────────────────────────────────────────────────────────
# Scheduler Tick
# ─────────────────────────────────────────────────────────────────────

@router.post("/scheduler-tick")
def cold_prospect_scheduler_tick(
    max_emails_per_tick: int = Query(20),
    require_business_hours: bool = Query(True),
    phase_1_enabled: bool = Query(True),
    phase_2_enabled: bool = Query(True),
    dry_run: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send the next batch of cold-prospect emails.

    Same Phase 1 + Phase 2 priority logic as the winback scheduler:
      Phase 2 (X-date prep) runs first — time-sensitive
      Phase 1 (cold wake-up) fills remaining capacity

    Filters that exclude a record from sending:
      - excluded=True
      - status != 'active'
      - email_valid != True (must have passed validation)
      - do_not_email=True
      - last_reply_at is set
      - bounce_count >= 2 (auto-suppress after 2 bounces)
      - email is None

    Variant rotation handled inside _send_cold_email.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    from zoneinfo import ZoneInfo
    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    now_ct = now_utc.astimezone(ZoneInfo("America/Chicago"))

    if require_business_hours and not dry_run:
        weekday = now_ct.weekday()
        hour = now_ct.hour
        # Per Evan: 9 AM - 3 PM CT, M-F
        if weekday >= 5 or hour < 9 or hour >= 15:
            return {
                "skipped": "outside_business_hours",
                "now_ct": now_ct.isoformat(),
                "current_weekday": weekday,
                "current_hour": hour,
            }

    sent = 0
    failed = 0
    phase_2_actions: list[dict] = []
    phase_1_actions: list[dict] = []
    remaining = max_emails_per_tick

    base_filter = [
        ColdProspect.excluded == False,
        ColdProspect.status == "active",
        ColdProspect.email_valid == True,
        ColdProspect.do_not_email == False,
        ColdProspect.email.isnot(None),
        ColdProspect.last_reply_at.is_(None),
        ColdProspect.bounce_count < 2,
    ]

    # ── PHASE 2: X-DATE PREP ──
    if phase_2_enabled and remaining > 0:
        offset_map = {0: 30, 1: 21, 2: 14, 3: 7}
        candidates = db.query(ColdProspect).filter(
            *base_filter,
            ColdProspect.next_x_date.isnot(None),
            ColdProspect.next_x_date <= datetime.utcnow() + timedelta(days=35),
            ColdProspect.next_x_date >= datetime.utcnow() - timedelta(days=2),
            ColdProspect.cycle_touchpoint_count < 4,
        ).order_by(
            ColdProspect.next_x_date.asc(),
            ColdProspect.premium.desc().nullslast(),
        ).limit(remaining * 3).all()

        for c in candidates:
            if remaining <= 0:
                break
            cycle_tc = c.cycle_touchpoint_count or 0
            offset_days = offset_map.get(cycle_tc, 7)
            due_at = c.next_x_date - timedelta(days=offset_days)
            due_naive = due_at.replace(tzinfo=None) if due_at.tzinfo else due_at
            if datetime.utcnow() < due_naive:
                continue
            if c.last_touchpoint_at:
                lt = c.last_touchpoint_at.replace(tzinfo=None) if c.last_touchpoint_at.tzinfo else c.last_touchpoint_at
                if (datetime.utcnow() - lt).days < 5:
                    continue

            if dry_run:
                phase_2_actions.append({
                    "id": c.id,
                    "name": c.full_name,
                    "cycle_t": cycle_tc + 1,
                    "offset_days": offset_days,
                    "next_x_date": c.next_x_date.isoformat() if c.next_x_date else None,
                    "agent": _get_assigned_producer(c)["username"],
                })
                remaining -= 1
                continue

            ok = _send_cold_email(c, db)
            if ok:
                c.touchpoint_count = (c.touchpoint_count or 0) + 1
                c.cycle_touchpoint_count = cycle_tc + 1
                c.last_touchpoint_at = datetime.utcnow()
                c.phase = "x_date_prep"
                if c.cycle_touchpoint_count >= 4:
                    c.next_x_date = c.next_x_date + timedelta(days=365)
                    c.cycle_touchpoint_count = 0
                    c.x_date_cycle_count = (c.x_date_cycle_count or 0) + 1
                    c.phase = "dormant"
                sent += 1
                remaining -= 1
            else:
                failed += 1

    # ── PHASE 1: COLD WAKE-UP ──
    if phase_1_enabled and remaining > 0:
        candidates = db.query(ColdProspect).filter(
            *base_filter,
            ColdProspect.touchpoint_count == 0,
        ).filter(
            (ColdProspect.phase == "cold_wakeup") | (ColdProspect.phase.is_(None))
        ).order_by(
            ColdProspect.premium.desc().nullslast(),
            ColdProspect.created_at.asc(),
        ).limit(remaining).all()

        for c in candidates:
            # Skip cold-wakeup if X-date is within 60 days (Phase 2 will handle)
            if c.next_x_date:
                nx = c.next_x_date.replace(tzinfo=None) if c.next_x_date.tzinfo else c.next_x_date
                days_until = (nx - datetime.utcnow()).days
                if 0 < days_until < 60:
                    if not dry_run:
                        c.phase = "x_date_prep"
                    continue

            if dry_run:
                phase_1_actions.append({
                    "id": c.id,
                    "name": c.full_name,
                    "agent": _get_assigned_producer(c)["username"],
                })
                remaining -= 1
                continue

            ok = _send_cold_email(c, db)
            if ok:
                c.touchpoint_count = 1
                c.last_touchpoint_at = datetime.utcnow()
                c.phase = "dormant"
                sent += 1
                remaining -= 1
            else:
                failed += 1

    if not dry_run:
        db.commit()

    return {
        "dry_run": dry_run,
        "now_ct": now_ct.isoformat(),
        "emails_sent": sent,
        "failed": failed,
        "phase_2_actions": phase_2_actions if dry_run else len(phase_2_actions),
        "phase_1_actions": phase_1_actions if dry_run else len(phase_1_actions),
    }


# ─────────────────────────────────────────────────────────────────────
# Test send (preview)
# ─────────────────────────────────────────────────────────────────────

@router.post("/test-send-to/{recipient_email}")
def test_send_cold_email(
    recipient_email: str,
    prospect_id: int = Query(..., description="ID of an existing cold prospect to use as template data"),
    variant: str = Query("v1", description="v1, v2, v3, or v4"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview a cold-prospect email by sending to a different address.

    Doesn't mutate the prospect record. Customer is NOT contacted.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    p = db.query(ColdProspect).filter(ColdProspect.id == prospect_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prospect not found")

    from app.core.config import settings
    import requests

    producer = _get_assigned_producer(p)
    subject, html = _build_cold_email(p, variant=variant)
    from_header = f"{producer['full_name']} <sales@betterchoiceins.com>"

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")

    resp = requests.post(
        f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data={
            "from": from_header,
            "to": [recipient_email],
            "subject": f"[TEST {variant}] {subject}",
            "html": html,
            "h:Reply-To": producer["email"],
            "v:email_type": "cold_prospect_test",
        },
        timeout=15,
    )
    return {
        "success": resp.status_code == 200,
        "status": resp.status_code,
        "prospect_used": {
            "id": p.id, "name": p.full_name, "policy_type": p.policy_type, "agent": producer["username"],
        },
        "variant": variant,
        "rendered_subject": subject,
    }
