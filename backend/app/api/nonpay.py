"""Non-pay / past-due automation API.

Upload PDF or CSV of non-pay notices → Claude extracts policy numbers →
Match to customers in DB → Send carrier-branded past-due emails.
One email per policy per 7 days max.
"""
import csv
import io
import json
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy
from app.models.nonpay import NonPayNotice, NonPayEmail
from app.services.nonpay_email import send_nonpay_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nonpay", tags=["nonpay"])


@router.get("/diag")
def nonpay_diagnostic():
    """Diagnostic endpoint - no auth required."""
    diag = {"status": "ok", "xlrd": False, "openpyxl": False, "tables": False}
    try:
        import xlrd
        diag["xlrd"] = True
        diag["xlrd_version"] = xlrd.__VERSION__
    except ImportError as e:
        diag["xlrd_error"] = str(e)
    try:
        import openpyxl
        diag["openpyxl"] = True
    except ImportError as e:
        diag["openpyxl_error"] = str(e)
    try:
        from app.core.database import get_db, engine
        from sqlalchemy import inspect
        insp = inspect(engine)
        tables = insp.get_table_names()
        diag["tables"] = "nonpay_notices" in tables and "nonpay_emails" in tables
        diag["all_tables"] = [t for t in tables if "nonpay" in t]
    except Exception as e:
        diag["table_error"] = str(e)
    return diag


@router.post("/test-extract")
async def test_extract(payload: dict = Body(...)):
    """Test file extraction without auth or DB. Returns extracted policies."""
    try:
        data_b64 = payload.get("data", "")
        filename = payload.get("filename", "test.csv")
        if not data_b64:
            return {"error": "No data provided"}

        file_bytes = base64.b64decode(data_b64)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in ("xlsx", "xls"):
            policies = _extract_from_excel(file_bytes, ext)
        elif ext == "pdf":
            policies = await _extract_from_pdf(file_bytes)
        else:
            policies = _extract_from_csv(file_bytes)

        return {"filename": filename, "ext": ext, "policies_found": len(policies), "policies": policies[:5]}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}

# ── Extraction prompt for Claude ──────────────────────────────────────

NONPAY_EXTRACTION_PROMPT = """You are an expert insurance document parser. This document is a non-pay / past-due / cancellation notice from an insurance carrier or agency management system.

Extract ALL policy numbers and associated details. Return ONLY a valid JSON array:

[
  {
    "policy_number": "The policy number exactly as shown",
    "carrier": "Insurance carrier name if visible",
    "insured_name": "Policyholder name if visible",
    "amount_due": 123.45,
    "due_date": "MM/DD/YYYY or as shown, or null",
    "notice_type": "non-pay|cancellation|reinstatement|past-due|other"
  }
]

IMPORTANT:
- Extract EVERY policy listed in the document, even if there are hundreds
- Policy numbers may appear in columns, tables, or lists
- Amount may be labeled as "amount due", "balance", "premium due", "past due amount"
- If the document is a CSV/spreadsheet, extract from the appropriate columns
- Return ONLY the JSON array, no markdown, no explanation
- If no policies found, return an empty array: []"""


# ── Upload + Process ─────────────────────────────────────────────────

@router.post("/upload-b64")
async def upload_nonpay_b64(
    payload: dict = Body(...),
    dry_run: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fallback upload via base64 JSON body instead of multipart form."""
    filename = payload.get("filename", "upload.csv")
    data_b64 = payload.get("data", "")
    if not data_b64:
        raise HTTPException(status_code=400, detail="No file data provided")

    file_bytes = base64.b64decode(data_b64)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "csv", "tsv", "txt", "xlsx", "xls"):
        raise HTTPException(status_code=400, detail="Supported formats: PDF, CSV, XLS, XLSX")

    if len(file_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25MB)")

    try:
        # Create notice record
        notice = NonPayNotice(
            filename=filename,
            upload_type=ext,
            uploaded_by=current_user.full_name or current_user.username,
            status="processing",
        )
        db.add(notice)
        db.commit()
        db.refresh(notice)
    except Exception as e:
        db.rollback()
        import traceback
        raise HTTPException(status_code=500, detail=f"DB error creating notice: {str(e)}\n{traceback.format_exc()[-500:]}")

    try:
        if ext == "pdf":
            policies = await _extract_from_pdf(file_bytes)
        elif ext in ("xlsx", "xls"):
            policies = _extract_from_excel(file_bytes, ext)
        else:
            policies = _extract_from_csv(file_bytes)

        notice.raw_extracted = policies
        notice.policies_found = len(policies)

        # Carrier inference from filename
        FILENAME_CARRIER_MAP = {
            "trv": "travelers", "travelers": "travelers",
            "prog": "progressive", "progressive": "progressive",
            "safeco": "safeco", "geico": "geico", "grange": "grange",
            "hippo": "hippo", "branch": "branch", "next": "next",
            "gainsco": "gainsco", "steadily": "steadily",
            "integrity": "integrity", "clearcover": "clearcover",
            "openly": "openly", "bristol": "bristol_west",
            "natgen": "national_general", "national_general": "national_general",
            "universal": "universal_property", "upcic": "universal_property",
            "american_modern": "american_modern", "covertree": "covertree",
        }
        has_any_carrier = any(p.get("carrier") for p in policies)
        if not has_any_carrier and filename:
            fn_lower = filename.lower()
            for pattern, carrier_key in FILENAME_CARRIER_MAP.items():
                if pattern in fn_lower:
                    for p in policies:
                        p["carrier"] = carrier_key
                    break

        results = []
        matched = 0
        sent = 0
        letters = 0
        skipped = 0

        for pol in policies:
            pnum = (pol.get("policy_number") or "").strip()
            if not pnum:
                continue

            # Filter by cancellation reason — only process non-pay/NSF
            notice_type = pol.get("notice_type", "non-pay")
            cancel_reason = pol.get("cancel_reason", "")

            if notice_type not in ("non-pay",):
                # Skip non-actionable reasons
                results.append({
                    "policy_number": pnum,
                    "insured_name": pol.get("insured_name", ""),
                    "cancel_reason": cancel_reason,
                    "notice_type": notice_type,
                    "skipped_reason": True,
                    "error": f"Skipped — {cancel_reason}" if cancel_reason else f"Skipped — {notice_type}",
                })
                continue

            result = _process_single_policy(
                db=db, notice_id=notice.id, policy_number=pnum,
                carrier=pol.get("carrier", ""), insured_name=pol.get("insured_name", ""),
                amount_due=pol.get("amount_due"), due_date=pol.get("due_date"),
                dry_run=dry_run,
            )
            result["cancel_reason"] = cancel_reason
            result["notice_type"] = notice_type
            results.append(result)
            if result.get("matched"): matched += 1
            if result.get("email_sent"): sent += 1
            if result.get("letter_sent"): letters += 1
            if result.get("skipped_rate_limit"): skipped += 1

        notice.policies_matched = matched
        notice.emails_sent = sent + letters
        notice.emails_skipped = skipped
        notice.status = "dry_run" if dry_run else "completed"
        db.commit()

        return {
            "notice_id": notice.id, "filename": filename, "dry_run": dry_run,
            "policies_found": len(policies), "policies_matched": matched,
            "emails_sent": sent, "letters_sent": letters, "emails_skipped": skipped, "details": results,
        }
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        try:
            notice.status = "error"
            notice.error_message = str(e)[:500]
            db.commit()
        except Exception:
            db.rollback()
        logger.error("Non-pay processing error: %s\n%s", e, tb)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}\n{tb[-500:]}")


@router.post("/upload")
async def upload_nonpay_file(
    file: UploadFile = File(...),
    dry_run: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a non-pay PDF or CSV. Extracts policy info, matches customers, sends emails.
    Set dry_run=true to preview matches without sending any emails."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "csv", "tsv", "txt", "xlsx", "xls"):
        raise HTTPException(status_code=400, detail="Supported formats: PDF, CSV, XLS, XLSX")

    file_bytes = await file.read()
    if len(file_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25MB)")

    # Create notice record
    try:
        notice = NonPayNotice(
            filename=file.filename,
            upload_type=ext,
            uploaded_by=current_user.full_name or current_user.username,
            status="processing",
        )
        db.add(notice)
        db.commit()
        db.refresh(notice)
    except Exception as e:
        db.rollback()
        import traceback
        raise HTTPException(status_code=500, detail=f"DB error creating notice: {str(e)}\n{traceback.format_exc()[-500:]}")

    try:
        # Extract policies from file
        if ext == "pdf":
            policies = await _extract_from_pdf(file_bytes)
        elif ext in ("xlsx", "xls"):
            policies = _extract_from_excel(file_bytes, ext)
        else:
            policies = _extract_from_csv(file_bytes)

        notice.raw_extracted = policies
        notice.policies_found = len(policies)

        # If no carrier was extracted, try to infer from filename
        FILENAME_CARRIER_MAP = {
            "trv": "travelers", "travelers": "travelers",
            "prog": "progressive", "progressive": "progressive",
            "safeco": "safeco", "geico": "geico", "grange": "grange",
            "hippo": "hippo", "branch": "branch", "next": "next",
            "gainsco": "gainsco", "steadily": "steadily",
            "integrity": "integrity", "clearcover": "clearcover",
            "openly": "openly", "bristol": "bristol_west",
            "natgen": "national_general", "national_general": "national_general",
            "universal": "universal_property", "upcic": "universal_property",
            "american_modern": "american_modern", "covertree": "covertree",
        }
        has_any_carrier = any(p.get("carrier") for p in policies)
        if not has_any_carrier and file.filename:
            fn_lower = file.filename.lower()
            for pattern, carrier_key in FILENAME_CARRIER_MAP.items():
                if pattern in fn_lower:
                    for p in policies:
                        p["carrier"] = carrier_key
                    break

        # Process each policy
        results = []
        matched = 0
        sent = 0
        letters = 0
        skipped = 0

        for pol in policies:
            pnum = (pol.get("policy_number") or "").strip()
            if not pnum:
                continue

            # Filter by cancellation reason
            notice_type = pol.get("notice_type", "non-pay")
            cancel_reason = pol.get("cancel_reason", "")

            if notice_type not in ("non-pay",):
                results.append({
                    "policy_number": pnum,
                    "insured_name": pol.get("insured_name", ""),
                    "cancel_reason": cancel_reason,
                    "notice_type": notice_type,
                    "skipped_reason": True,
                    "error": f"Skipped — {cancel_reason}" if cancel_reason else f"Skipped — {notice_type}",
                })
                continue

            result = _process_single_policy(
                db=db,
                notice_id=notice.id,
                policy_number=pnum,
                carrier=pol.get("carrier", ""),
                insured_name=pol.get("insured_name", ""),
                amount_due=pol.get("amount_due"),
                due_date=pol.get("due_date"),
                dry_run=dry_run,
            )
            result["cancel_reason"] = cancel_reason
            result["notice_type"] = notice_type
            results.append(result)
            if result.get("matched"):
                matched += 1
            if result.get("email_sent"):
                sent += 1
            if result.get("skipped_rate_limit"):
                skipped += 1

        notice.policies_matched = matched
        notice.emails_sent = sent
        notice.emails_skipped = skipped
        notice.status = "dry_run" if dry_run else "completed"
        db.commit()

        return {
            "notice_id": notice.id,
            "filename": file.filename,
            "dry_run": dry_run,
            "policies_found": len(policies),
            "policies_matched": matched,
            "emails_sent": sent,
            "emails_skipped": skipped,
            "details": results,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        try:
            notice.status = "error"
            notice.error_message = str(e)[:500]
            db.commit()
        except Exception:
            db.rollback()
        logger.error("Non-pay processing error: %s\n%s", e, tb)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}\n{tb[-500:]}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


def _process_single_policy(
    db: Session,
    notice_id: int,
    policy_number: str,
    carrier: str,
    insured_name: str,
    amount_due: Optional[float],
    due_date: Optional[str],
    dry_run: bool = False,
) -> dict:
    """Match a policy to a customer and send email if within rate limit."""
    result = {
        "policy_number": policy_number,
        "carrier": carrier,
        "matched": False,
        "customer_name": None,
        "customer_email": None,
        "email_sent": False,
        "skipped_rate_limit": False,
        "error": None,
    }

    # Find policy in our DB
    policy = db.query(CustomerPolicy).filter(
        CustomerPolicy.policy_number == policy_number
    ).first()

    if not policy:
        # Try partial match (some reports truncate policy numbers)
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number.ilike(f"%{policy_number}%")
        ).first()

    if not policy:
        # Try base number (strip suffix like 618207668-653-1 → 618207668)
        base_number = policy_number.split("-")[0].strip()
        if base_number and base_number != policy_number:
            policy = db.query(CustomerPolicy).filter(
                CustomerPolicy.policy_number.ilike(f"%{base_number}%")
            ).first()

    if not policy:
        # Try reverse: maybe DB has longer number that contains our extracted number
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number.ilike(f"{policy_number.replace('-', '%')}%")
        ).first()

    if not policy:
        # Try matching by customer name if we have insured_name
        if insured_name:
            parts = insured_name.strip().split()
            if len(parts) >= 2:
                # Try last name match on customers
                last_name = parts[-1]
                customer = db.query(Customer).filter(
                    Customer.last_name.ilike(f"%{last_name}%")
                ).first()
                if customer:
                    result["matched"] = True
                    result["customer_name"] = customer.full_name
                    result["customer_email"] = customer.email
                    result["customer_id"] = customer.id
                    result["match_type"] = "name"
                    if not customer.email:
                        # Try Thanks.io letter for name-matched customers without email
                        if customer.address and customer.city and customer.state and customer.zip_code:
                            if dry_run:
                                result["would_send_letter"] = True
                                result["letter_address"] = f"{customer.address}, {customer.city}, {customer.state} {customer.zip_code}"
                                result["dry_run"] = True
                                return result
                            from app.services.thanksio_letter import send_thanksio_letter
                            letter_result = send_thanksio_letter(
                                client_name=customer.full_name,
                                address=customer.address,
                                city=customer.city,
                                state=customer.state,
                                zip_code=customer.zip_code,
                                policy_number=policy_number,
                                carrier=carrier,
                                amount_due=float(amount_due) if amount_due else None,
                                due_date=due_date,
                            )
                            letter_record = NonPayEmail(
                                notice_id=notice_id, policy_number=policy_number,
                                customer_id=customer.id, customer_name=customer.full_name,
                                customer_email=None, carrier=carrier,
                                amount_due=amount_due, due_date=due_date,
                                email_status="letter_sent" if letter_result.get("success") else "letter_failed",
                                mailgun_message_id=letter_result.get("order_id"),
                                error_message=letter_result.get("error"),
                            )
                            db.add(letter_record)
                            db.commit()
                            result["letter_sent"] = letter_result.get("success", False)
                            return result
                        else:
                            result["error"] = "No email and incomplete mailing address"
                            return result
                    # Skip rate limit check and sending for name matches in case of ambiguity
                    if dry_run:
                        result["would_send"] = True
                        result["dry_run"] = True
                        return result
                    # For live mode, proceed to send
                    effective_carrier = carrier or ""
                    email_result = send_nonpay_email(
                        to_email=customer.email,
                        client_name=customer.full_name,
                        policy_number=policy_number,
                        carrier=effective_carrier,
                        amount_due=amount_due,
                        due_date=due_date,
                    )
                    email_record = NonPayEmail(
                        notice_id=notice_id,
                        policy_number=policy_number,
                        customer_id=customer.id,
                        customer_name=customer.full_name,
                        customer_email=customer.email,
                        carrier=effective_carrier,
                        amount_due=amount_due,
                        due_date=due_date,
                        email_status="sent" if email_result.get("success") else "failed",
                        mailgun_message_id=email_result.get("message_id"),
                        error_message=email_result.get("error"),
                    )
                    db.add(email_record)
                    db.commit()
                    result["email_sent"] = email_result.get("success", False)
                    return result

    if not policy:
        result["error"] = "Policy not found in database"
        return result

    # Get customer
    customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()
    if not customer:
        result["error"] = "Customer not found"
        return result

    result["matched"] = True
    result["customer_name"] = customer.full_name
    result["customer_email"] = customer.email
    result["customer_id"] = customer.id

    if not customer.email:
        # No email — try sending a physical letter via Thanks.io
        if customer.address and customer.city and customer.state and customer.zip_code:
            if dry_run:
                result["would_send_letter"] = True
                result["letter_address"] = f"{customer.address}, {customer.city}, {customer.state} {customer.zip_code}"
                result["dry_run"] = True
                return result

            # Check 1x/week rate limit for letters too
            one_week_ago = datetime.utcnow() - timedelta(days=7)
            recent_letter = db.query(NonPayEmail).filter(
                NonPayEmail.policy_number == policy_number,
                NonPayEmail.email_status == "letter_sent",
                NonPayEmail.sent_at >= one_week_ago,
            ).first()
            if recent_letter:
                result["skipped_rate_limit"] = True
                result["error"] = "Letter already sent this week"
                return result

            from app.services.thanksio_letter import send_thanksio_letter
            letter_result = send_thanksio_letter(
                client_name=customer.full_name,
                address=customer.address,
                city=customer.city,
                state=customer.state,
                zip_code=customer.zip_code,
                policy_number=policy_number,
                carrier=carrier,
                amount_due=float(amount_due) if amount_due else None,
                due_date=due_date,
            )

            # Record the letter
            letter_record = NonPayEmail(
                notice_id=notice_id,
                policy_number=policy_number,
                customer_id=customer.id,
                customer_name=customer.full_name,
                customer_email=None,
                carrier=carrier,
                amount_due=amount_due,
                due_date=due_date,
                email_status="letter_sent" if letter_result.get("success") else "letter_failed",
                mailgun_message_id=letter_result.get("order_id"),
                error_message=letter_result.get("error"),
            )
            db.add(letter_record)
            db.commit()

            result["letter_sent"] = letter_result.get("success", False)
            result["letter_order_id"] = letter_result.get("order_id")
            if not letter_result.get("success"):
                result["error"] = letter_result.get("error")
            return result
        else:
            result["error"] = "No email and incomplete mailing address"
            return result

    # Check 1x/week rate limit for this policy
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    recent_email = db.query(NonPayEmail).filter(
        NonPayEmail.policy_number == policy_number,
        NonPayEmail.email_status == "sent",
        NonPayEmail.sent_at >= one_week_ago,
    ).first()

    if recent_email:
        result["skipped_rate_limit"] = True
        result["last_sent"] = recent_email.sent_at.isoformat() if recent_email.sent_at else None
        return result

    # Use carrier from policy record if not in the upload
    effective_carrier = carrier or policy.carrier or ""

    # In dry_run mode, report what WOULD happen but don't send
    if dry_run:
        result["email_sent"] = False
        result["would_send"] = True
        result["dry_run"] = True
        return result

    # Send the email
    email_result = send_nonpay_email(
        to_email=customer.email,
        client_name=customer.full_name,
        policy_number=policy_number,
        carrier=effective_carrier,
        amount_due=amount_due,
        due_date=due_date,
    )

    # Record the email
    email_record = NonPayEmail(
        notice_id=notice_id,
        policy_number=policy_number,
        customer_id=customer.id,
        customer_name=customer.full_name,
        customer_email=customer.email,
        carrier=effective_carrier,
        amount_due=amount_due,
        due_date=due_date,
        email_status="sent" if email_result.get("success") else "failed",
        mailgun_message_id=email_result.get("message_id"),
        error_message=email_result.get("error"),
    )
    db.add(email_record)
    db.commit()

    result["email_sent"] = email_result.get("success", False)
    if not email_result.get("success"):
        result["error"] = email_result.get("error")

    return result


# ── File Extraction ──────────────────────────────────────────────────

async def _extract_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """Use Claude API to extract policy info from a PDF."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    # Truncate large PDFs
    try:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) > 50:
            writer = PdfWriter()
            for i in range(50):
                writer.add_page(reader.pages[i])
            buf = io.BytesIO()
            writer.write(buf)
            pdf_bytes = buf.getvalue()
    except Exception:
        pass

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4000,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                        {"type": "text", "text": NONPAY_EXTRACTION_PROMPT},
                    ],
                }],
            },
        )

    if response.status_code != 200:
        raise ValueError(f"Claude API error ({response.status_code}): {response.text[:300]}")

    text = ""
    for block in response.json().get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    text = text.strip()
    for fence in ["```json", "```"]:
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse extraction: {e}\nRaw: {text[:500]}")


def _extract_from_csv(file_bytes: bytes) -> list[dict]:
    """Parse CSV/TSV to extract policy numbers and amounts."""
    text = file_bytes.decode("utf-8", errors="replace")

    # Detect delimiter
    if "\t" in text.split("\n")[0]:
        delimiter = "\t"
    else:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    results = []

    # Common column name patterns
    policy_cols = ["policy_number", "policynumber", "policy #", "policy#", "policy no",
                   "policyno", "policy", "pol_number", "pol_num", "pol#", "number"]
    carrier_cols = ["carrier", "carrier_name", "carriername", "company", "insurer", "insurance_company"]
    name_cols = ["insured_name", "insuredname", "name", "client", "customer", "policyholder",
                 "insured", "named_insured", "named insured", "first name", "first_name"]
    amount_cols = ["amount_due", "amountdue", "amount", "balance", "premium_due", "premiumdue",
                   "past_due", "pastdue", "total_due", "totaldue", "premium",
                   "minimum_due", "remaining_balance", "amount_to_reinstate"]
    date_cols = ["due_date", "duedate", "cancel_date", "canceldate", "effective_date",
                 "cancellation_date", "cancellationdate",
                 "payment_due_date", "cancellation_effective_date"]

    def _find_col(fieldnames, patterns):
        for f in (fieldnames or []):
            fl = f.lower().strip().replace(" ", "_")
            if fl in patterns:
                return f
        return None

    fields = reader.fieldnames or []
    p_col = _find_col(fields, policy_cols)
    c_col = _find_col(fields, carrier_cols)
    n_col = _find_col(fields, name_cols)
    a_col = _find_col(fields, amount_cols)
    d_col = _find_col(fields, date_cols)

    for row in reader:
        pnum = row.get(p_col, "").strip() if p_col else ""
        if not pnum:
            continue

        amt = None
        if a_col and row.get(a_col):
            try:
                amt = float(row[a_col].replace(",", "").replace("$", "").strip())
            except (ValueError, AttributeError):
                pass

        results.append({
            "policy_number": pnum,
            "carrier": row.get(c_col, "").strip() if c_col else "",
            "insured_name": row.get(n_col, "").strip() if n_col else "",
            "amount_due": amt,
            "due_date": row.get(d_col, "").strip() if d_col else "",
            "notice_type": "non-pay",
        })

    return results


def _extract_from_excel(file_bytes: bytes, ext: str) -> list[dict]:
    """Extract policy data from .xlsx or .xls files."""
    import io

    # Column name patterns (same as CSV)
    policy_pats = ["policy_number", "policynumber", "policy #", "policy#", "policy no",
                   "policyno", "policy", "pol_number", "pol_num", "pol#", "number"]
    carrier_pats = ["carrier", "carrier_name", "carriername", "company", "insurer", "insurance_company"]
    name_pats = ["insured_name", "insuredname", "name", "client", "customer", "policyholder",
                 "insured", "named_insured", "named insured", "first name", "first_name"]
    amount_pats = ["amount_due", "amountdue", "amount", "balance", "premium_due", "premiumdue",
                   "past_due", "pastdue", "total_due", "totaldue", "premium",
                   "minimum_due", "remaining_balance", "amount_to_reinstate"]
    date_pats = ["due_date", "duedate", "cancel_date", "canceldate", "effective_date",
                 "cancellation_date", "cancellationdate",
                 "payment_due_date", "cancellation_effective_date"]
    reason_pats = ["reason", "cancel_reason", "cancellation_reason", "cancel_type",
                   "notice_reason", "status", "cancellation_status"]
    phone_pats = ["phone", "phone_#", "phone_number", "phonenumber", "phone_no",
                  "telephone", "cell", "mobile"]

    def _match_col(headers, patterns):
        for i, h in enumerate(headers):
            if h and str(h).lower().strip().replace(" ", "_") in patterns:
                return i
        return None

    results = []

    if ext == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    else:  # xls
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=file_bytes)
            ws = wb.sheet_by_index(0)
            rows = [ws.row_values(r) for r in range(ws.nrows)]
        except ImportError:
            # xlrd not installed — try reading as CSV (some .xls are actually HTML/CSV)
            try:
                text = file_bytes.decode("utf-8", errors="ignore")
                reader = csv.reader(io.StringIO(text), delimiter="\t")
                rows = [row for row in reader]
            except Exception:
                raise ValueError("XLS support requires xlrd package. Please convert to XLSX or CSV.")
        except Exception as e:
            raise ValueError(f"Failed to read XLS file: {str(e)}")

    if not rows:
        return results

    headers = [str(c).strip() if c else "" for c in rows[0]]
    p_col = _match_col(headers, policy_pats)
    c_col = _match_col(headers, carrier_pats)
    n_col = _match_col(headers, name_pats)
    a_col = _match_col(headers, amount_pats)
    d_col = _match_col(headers, date_pats)
    r_col = _match_col(headers, reason_pats)
    ph_col = _match_col(headers, phone_pats)

    for row in rows[1:]:
        cells = list(row)
        pnum = str(cells[p_col]).strip() if p_col is not None and p_col < len(cells) and cells[p_col] else ""
        if not pnum or pnum.lower() == "none":
            continue

        amt = None
        if a_col is not None and a_col < len(cells) and cells[a_col]:
            try:
                val = cells[a_col]
                if isinstance(val, (int, float)):
                    amt = float(val)
                else:
                    amt = float(str(val).replace(",", "").replace("$", "").strip())
            except (ValueError, TypeError):
                pass

        # Extract cancellation reason
        reason_raw = ""
        if r_col is not None and r_col < len(cells) and cells[r_col]:
            reason_raw = str(cells[r_col]).strip()

        # Classify the reason
        reason_lower = reason_raw.lower()
        if any(kw in reason_lower for kw in ["non payment", "non-payment", "nonpayment", "nsf",
                                              "non pay", "non-pay", "nonpay",
                                              "insufficient funds", "returned payment"]):
            notice_type = "non-pay"
        elif any(kw in reason_lower for kw in ["underwriting", "uw reason"]):
            notice_type = "underwriting"
        elif any(kw in reason_lower for kw in ["policyholder", "insured request", "customer request",
                                                "rewrite", "replacement", "policyholder's request"]):
            notice_type = "voluntary"
        elif reason_raw:
            notice_type = "other"
        else:
            notice_type = "non-pay"  # default if no reason column

        # Extract phone
        phone = ""
        if ph_col is not None and ph_col < len(cells) and cells[ph_col]:
            phone = str(cells[ph_col]).strip()

        results.append({
            "policy_number": pnum,
            "carrier": str(cells[c_col]).strip() if c_col is not None and c_col < len(cells) and cells[c_col] else "",
            "insured_name": str(cells[n_col]).strip() if n_col is not None and n_col < len(cells) and cells[n_col] else "",
            "amount_due": amt,
            "due_date": str(cells[d_col]).strip() if d_col is not None and d_col < len(cells) and cells[d_col] else "",
            "notice_type": notice_type,
            "cancel_reason": reason_raw,
            "phone": phone,
        })

    return results


# ── Inbound Email (Mailgun webhook) ─────────────────────────────────

import os
import re
from fastapi import Request, Form

# Env var to control mode: "dry_run" or "live"
# Start with dry_run, switch to live after first week
INBOUND_NONPAY_MODE = os.environ.get("INBOUND_NONPAY_MODE", "dry_run")

# Subject line keywords that indicate non-pay notices
NONPAY_SUBJECT_KEYWORDS = ["non pay", "non-pay", "nonpay", "nsf", "non payment", "non-payment"]
SKIP_SUBJECT_KEYWORDS = ["underwriting", "policyholder request", "rewrite", "replacement"]


def _parse_grangewire_html(html_body: str) -> list[dict]:
    """Parse GrangeWire Alerts HTML table into policy records."""
    from html.parser import HTMLParser

    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_table = False
            self.in_row = False
            self.in_cell = False
            self.current_row = []
            self.current_cell = ""
            self.rows = []
            self.table_count = 0

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.in_table = True
                self.table_count += 1
            elif tag == "tr" and self.in_table:
                self.in_row = True
                self.current_row = []
            elif tag in ("td", "th") and self.in_row:
                self.in_cell = True
                self.current_cell = ""
            elif tag == "br" and self.in_cell:
                self.current_cell += " "

        def handle_endtag(self, tag):
            if tag == "table":
                self.in_table = False
            elif tag == "tr" and self.in_row:
                self.in_row = False
                if self.current_row:
                    self.rows.append(self.current_row)
            elif tag in ("td", "th") and self.in_cell:
                self.in_cell = False
                self.current_row.append(self.current_cell.strip())

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data

    parser = TableParser()
    parser.feed(html_body)

    if not parser.rows:
        return []

    # Find the header row — look for one containing "POLICY" or "ACCT"
    header_idx = None
    for i, row in enumerate(parser.rows):
        row_text = " ".join(row).upper()
        if "POLICY" in row_text or "ACCT" in row_text:
            header_idx = i
            break

    if header_idx is None:
        return []

    headers = [h.upper().strip() for h in parser.rows[header_idx]]

    # Map columns
    def _find_col(headers, keywords):
        for i, h in enumerate(headers):
            for kw in keywords:
                if kw in h:
                    return i
        return None

    p_col = _find_col(headers, ["POLICY", "ACCT", "NUMBER"])
    n_col = _find_col(headers, ["INSURED", "NAME"])
    d_col = _find_col(headers, ["CANCEL", "DATE"])
    max_col = _find_col(headers, ["MAX DUE", "MAX"])
    min_col = _find_col(headers, ["MIN DUE", "MIN"])
    msg_col = _find_col(headers, ["MESSAGE"])
    phone_col = _find_col(headers, ["PHONE", "EMAIL"])

    results = []
    for row in parser.rows[header_idx + 1:]:
        if not row or len(row) <= (p_col or 0):
            continue

        pnum = row[p_col].strip() if p_col is not None and p_col < len(row) else ""
        if not pnum:
            continue

        # Parse amount — prefer MAX DUE
        amount = None
        for col in [max_col, min_col]:
            if col is not None and col < len(row) and row[col]:
                try:
                    amount = float(row[col].replace(",", "").replace("$", "").strip())
                    break
                except (ValueError, TypeError):
                    pass

        # Parse message to determine notice type
        message = row[msg_col].strip() if msg_col is not None and msg_col < len(row) else ""
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in ["non pay", "non-pay", "nsf"]):
            notice_type = "non-pay"
        elif any(kw in msg_lower for kw in ["underwriting"]):
            notice_type = "underwriting"
        elif any(kw in msg_lower for kw in ["policyholder", "rewrite"]):
            notice_type = "voluntary"
        else:
            notice_type = "non-pay"  # default for Grange non-pay alerts

        results.append({
            "policy_number": pnum,
            "carrier": "grange",
            "insured_name": row[n_col].strip() if n_col is not None and n_col < len(row) else "",
            "amount_due": amount,
            "due_date": row[d_col].strip() if d_col is not None and d_col < len(row) else "",
            "notice_type": notice_type,
            "cancel_reason": message,
            "phone": row[phone_col].strip() if phone_col is not None and phone_col < len(row) else "",
        })

    return results


def _parse_generic_email_html(html_body: str, carrier: str = "") -> list[dict]:
    """Fallback parser for non-Grange carrier email tables."""
    # Try the same table parsing approach
    policies = _parse_grangewire_html(html_body)
    if policies and not carrier:
        # Try to detect carrier from email body
        body_lower = html_body.lower()
        for key in ["travelers", "progressive", "safeco", "national general",
                     "bristol west", "hippo", "branch", "clearcover"]:
            if key in body_lower:
                carrier = key.replace(" ", "_")
                break
    for p in policies:
        if carrier and not p.get("carrier"):
            p["carrier"] = carrier
    return policies


@router.post("/inbound-email")
async def inbound_email_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Mailgun inbound webhook. Receives parsed email data and processes non-pay notices.

    Mailgun POSTs form data with fields: sender, from, subject, body-html, body-plain,
    attachment-count, attachment-1, etc.

    No auth required — Mailgun calls this directly. We validate by checking sender domain.
    """
    try:
        form = await request.form()
    except Exception as e:
        logger.error("Inbound email: failed to parse form data: %s", e)
        return {"status": "error", "message": str(e)}

    sender = form.get("sender", "") or form.get("from", "")
    subject = form.get("subject", "")
    html_body = form.get("body-html", "")
    plain_body = form.get("body-plain", "")

    logger.info("Inbound email from=%s subject=%s", sender, subject[:80])

    # Determine if this is a non-pay notice
    # Check subject line first, then fall back to scanning the HTML body
    # (Forwarded emails often have generic subjects like "Fwd: GrangeWire Alerts")
    subject_lower = subject.lower()
    html_lower = (html_body or "").lower()
    plain_lower = (plain_body or "").lower()
    all_text = f"{subject_lower} {html_lower} {plain_lower}"

    # Check for skip keywords in subject
    if any(kw in subject_lower for kw in SKIP_SUBJECT_KEYWORDS):
        # But only skip if the body doesn't ALSO contain non-pay content
        if not any(kw in html_lower for kw in NONPAY_SUBJECT_KEYWORDS):
            logger.info("Inbound email skipped (subject keyword): %s", subject[:80])
            return {"status": "skipped", "reason": "Subject indicates non-actionable notice type"}

    # Check for non-pay keywords in subject OR body
    is_nonpay = any(kw in all_text for kw in NONPAY_SUBJECT_KEYWORDS)
    if not is_nonpay:
        logger.info("Inbound email skipped (no non-pay keyword in subject or body): %s", subject[:80])
        return {"status": "skipped", "reason": "No non-pay keywords found in subject or body"}

    # Detect carrier from sender, forwarded-from headers, or body content
    sender_lower = sender.lower()
    carrier = ""

    # Check the actual sender and also the forwarded message headers in the body
    carrier_checks = f"{sender_lower} {html_lower}"
    if "grange" in carrier_checks:
        carrier = "grange"
    elif "travelers" in carrier_checks:
        carrier = "travelers"
    elif "progressive" in carrier_checks:
        carrier = "progressive"
    elif "safeco" in carrier_checks:
        carrier = "safeco"
    elif "national" in carrier_checks and "general" in carrier_checks:
        carrier = "national_general"

    # Parse the HTML body for policy data
    if not html_body:
        logger.warning("Inbound email has no HTML body")
        return {"status": "error", "message": "No HTML body in email"}

    if "grange" in carrier:
        policies = _parse_grangewire_html(html_body)
    else:
        policies = _parse_generic_email_html(html_body, carrier)

    if not policies:
        logger.warning("Inbound email: no policies extracted from body")
        return {"status": "error", "message": "Could not extract policy data from email"}

    # Determine mode
    mode = INBOUND_NONPAY_MODE
    dry_run = (mode != "live")

    # Create a notice record
    notice = NonPayNotice(
        filename=f"inbound-email-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        upload_type="inbound-email",
        uploaded_by=f"inbound:{sender[:60]}",
        policies_found=len(policies),
        status="processing",
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)

    # Process each policy (same logic as file upload)
    results = []
    matched = 0
    sent = 0
    letters = 0
    skipped = 0

    for pol in policies:
        pnum = (pol.get("policy_number") or "").strip()
        if not pnum:
            continue

        notice_type = pol.get("notice_type", "non-pay")
        cancel_reason = pol.get("cancel_reason", "")

        if notice_type not in ("non-pay",):
            results.append({
                "policy_number": pnum,
                "insured_name": pol.get("insured_name", ""),
                "cancel_reason": cancel_reason,
                "notice_type": notice_type,
                "skipped_reason": True,
                "error": f"Skipped — {cancel_reason}" if cancel_reason else f"Skipped — {notice_type}",
            })
            continue

        result = _process_single_policy(
            db=db,
            notice_id=notice.id,
            policy_number=pnum,
            carrier=pol.get("carrier", carrier),
            insured_name=pol.get("insured_name", ""),
            amount_due=pol.get("amount_due"),
            due_date=pol.get("due_date"),
            dry_run=dry_run,
        )
        result["cancel_reason"] = cancel_reason
        result["notice_type"] = notice_type
        results.append(result)
        if result.get("matched"):
            matched += 1
        if result.get("email_sent"):
            sent += 1
        if result.get("letter_sent"):
            letters += 1
        if result.get("skipped_rate_limit"):
            skipped += 1

    notice.policies_matched = matched
    notice.emails_sent = sent + letters
    notice.emails_skipped = skipped
    notice.status = "dry_run" if dry_run else "completed"
    db.commit()

    summary = {
        "status": "processed",
        "mode": "dry_run" if dry_run else "live",
        "notice_id": notice.id,
        "carrier": carrier,
        "subject": subject[:100],
        "policies_found": len(policies),
        "policies_matched": matched,
        "emails_sent": sent,
        "letters_sent": letters,
        "skipped": skipped,
        "details": results,
    }

    logger.info("Inbound email processed: %s policies, %s matched, %s sent (mode=%s)",
                len(policies), matched, sent, mode)

    return summary


# ── History / Status ─────────────────────────────────────────────────

@router.get("/history")
def nonpay_history(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get recent non-pay notice upload history."""
    notices = (
        db.query(NonPayNotice)
        .order_by(NonPayNotice.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "notices": [{
            "id": n.id,
            "filename": n.filename,
            "upload_type": n.upload_type,
            "uploaded_by": n.uploaded_by,
            "policies_found": n.policies_found,
            "policies_matched": n.policies_matched,
            "emails_sent": n.emails_sent,
            "emails_skipped": n.emails_skipped,
            "status": n.status,
            "error_message": n.error_message,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in notices]
    }


@router.get("/emails")
def nonpay_emails(
    policy_number: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get non-pay email send history, optionally filtered by policy."""
    query = db.query(NonPayEmail).order_by(NonPayEmail.sent_at.desc())
    if policy_number:
        query = query.filter(NonPayEmail.policy_number == policy_number)
    emails = query.limit(limit).all()

    return {
        "emails": [{
            "id": e.id,
            "policy_number": e.policy_number,
            "customer_name": e.customer_name,
            "customer_email": e.customer_email,
            "carrier": e.carrier,
            "amount_due": float(e.amount_due) if e.amount_due else None,
            "due_date": e.due_date,
            "email_status": e.email_status,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
        } for e in emails]
    }


@router.get("/preview")
def preview_nonpay_email(
    carrier: str = "progressive",
    client_name: str = "John Smith",
    policy_number: str = "AUT-12345678",
    amount_due: float = 247.50,
    due_date: str = "02/28/2026",
    current_user: User = Depends(get_current_user),
):
    """Preview a non-pay email template. Returns subject + raw HTML."""
    from app.services.nonpay_email import build_nonpay_email_html
    subject, html = build_nonpay_email_html(
        client_name=client_name,
        policy_number=policy_number,
        carrier=carrier,
        amount_due=amount_due,
        due_date=due_date,
    )
    return {"subject": subject, "html": html, "carrier": carrier}


@router.get("/carriers")
def list_nonpay_carriers(
    current_user: User = Depends(get_current_user),
):
    """List all carriers that have custom email templates."""
    from app.services.welcome_email import CARRIER_INFO
    carriers = []
    for key, info in CARRIER_INFO.items():
        carriers.append({
            "key": key,
            "display_name": info.get("display_name", key),
            "accent_color": info.get("accent_color", "#1a2b5f"),
            "has_payment_url": bool(info.get("payment_url")),
        })
    carriers.sort(key=lambda c: c["display_name"])
    return {"carriers": carriers}


@router.post("/send-test")
def send_test_nonpay_email(
    to_email: str,
    carrier: str = "progressive",
    client_name: str = "John Smith",
    policy_number: str = "AUT-12345678",
    amount_due: float = 247.50,
    due_date: str = "02/28/2026",
    current_user: User = Depends(get_current_user),
):
    """Send a test non-pay email to a specific address."""
    result = send_nonpay_email(
        to_email=to_email,
        client_name=client_name,
        policy_number=policy_number,
        carrier=carrier,
        amount_due=amount_due,
        due_date=due_date,
    )
    return {"success": result.get("success", False), "to": to_email, "carrier": carrier, "error": result.get("error")}
