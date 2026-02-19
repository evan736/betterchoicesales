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
        skipped = 0

        for pol in policies:
            pnum = (pol.get("policy_number") or "").strip()
            if not pnum:
                continue
            result = _process_single_policy(
                db=db, notice_id=notice.id, policy_number=pnum,
                carrier=pol.get("carrier", ""), insured_name=pol.get("insured_name", ""),
                amount_due=pol.get("amount_due"), due_date=pol.get("due_date"),
                dry_run=dry_run,
            )
            results.append(result)
            if result.get("matched"): matched += 1
            if result.get("email_sent"): sent += 1
            if result.get("skipped_rate_limit"): skipped += 1

        notice.policies_matched = matched
        notice.emails_sent = sent
        notice.emails_skipped = skipped
        notice.status = "dry_run" if dry_run else "completed"
        db.commit()

        return {
            "notice_id": notice.id, "filename": filename, "dry_run": dry_run,
            "policies_found": len(policies), "policies_matched": matched,
            "emails_sent": sent, "emails_skipped": skipped, "details": results,
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
        skipped = 0

        for pol in policies:
            pnum = (pol.get("policy_number") or "").strip()
            if not pnum:
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
        result["error"] = "Customer has no email address"
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

        results.append({
            "policy_number": pnum,
            "carrier": str(cells[c_col]).strip() if c_col is not None and c_col < len(cells) and cells[c_col] else "",
            "insured_name": str(cells[n_col]).strip() if n_col is not None and n_col < len(cells) and cells[n_col] else "",
            "amount_due": amt,
            "due_date": str(cells[d_col]).strip() if d_col is not None and d_col < len(cells) and cells[d_col] else "",
            "notice_type": "non-pay",
        })

    return results


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
