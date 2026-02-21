"""Quotes API — full quote-to-close pipeline.

Features:
- Create quote with prospect info
- Upload quote PDFs (drag-and-drop on frontend)
- Send carrier-branded quote email with PDF attachment
- Auto-create prospect in NowCerts
- Follow-up tracking (3/7/14/90 day)
- Conversion detection (link quote → sale)
- Remarket pipeline entry at 90 days
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.campaign import Quote

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/quotes", tags=["Quotes"])


# ── Schemas ──

class QuoteCreate(BaseModel):
    prospect_name: str
    prospect_email: Optional[str] = None
    prospect_phone: Optional[str] = None
    prospect_address: Optional[str] = None
    prospect_city: Optional[str] = None
    prospect_state: Optional[str] = None
    prospect_zip: Optional[str] = None
    carrier: str
    policy_type: str
    quoted_premium: Optional[float] = None
    premium_term: Optional[str] = "6 months"
    effective_date: Optional[str] = None
    notes: Optional[str] = None


class QuoteSendEmail(BaseModel):
    additional_notes: Optional[str] = None
    premium_term: Optional[str] = None


class QuoteUpdate(BaseModel):
    status: Optional[str] = None
    quoted_premium: Optional[float] = None
    carrier: Optional[str] = None
    policy_type: Optional[str] = None
    lost_reason: Optional[str] = None
    prospect_email: Optional[str] = None
    prospect_phone: Optional[str] = None


# ── Helper: Create NowCerts prospect ──

def _create_nowcerts_prospect(quote: Quote):
    """Create a prospect in NowCerts from quote data."""
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if not nc.is_configured:
            return None

        parts = quote.prospect_name.strip().split(maxsplit=1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""

        insured_data = {
            "firstName": first,
            "lastName": last,
            "email": quote.prospect_email or "",
            "phone": quote.prospect_phone or "",
            "address1": quote.prospect_address or "",
            "city": quote.prospect_city or "",
            "state": quote.prospect_state or "",
            "zipCode": quote.prospect_zip or "",
            "insuredType": "Prospect",
        }
        result = nc.insert_insured(insured_data)
        if result:
            logger.info(f"NowCerts prospect created for {quote.prospect_name}")
            # Add a note with quote details
            nc.insert_note({
                "subject": (
                    f"Quote Sent — {(quote.carrier or '').title()} {(quote.policy_type or '').title()} | "
                    f"Premium: ${float(quote.quoted_premium):,.2f} | "
                    f"Sent via BCI CRM"
                ),
                "insured_email": quote.prospect_email or "",
                "insured_first_name": first,
                "insured_last_name": last,
                "type": "Email",
                "creator_name": quote.producer_name or "BCI Quote System",
                "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
            })
            return result
        return None
    except Exception as e:
        logger.error(f"NowCerts prospect creation failed: {e}")
        return None


# ── Endpoints ──

@router.post("/")
def create_quote(
    data: QuoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new quote record."""
    eff_date = None
    if data.effective_date:
        try:
            eff_date = datetime.strptime(data.effective_date, "%Y-%m-%d")
        except ValueError:
            pass

    quote = Quote(
        prospect_name=data.prospect_name,
        prospect_email=data.prospect_email,
        prospect_phone=data.prospect_phone,
        prospect_address=data.prospect_address,
        prospect_city=data.prospect_city,
        prospect_state=data.prospect_state,
        prospect_zip=data.prospect_zip,
        carrier=data.carrier,
        policy_type=data.policy_type,
        quoted_premium=data.quoted_premium,
        effective_date=eff_date,
        producer_id=current_user.id,
        producer_name=f"{current_user.first_name} {current_user.last_name}".strip() or current_user.username,
        status="quoted",
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)

    return _quote_to_dict(quote)



# ── Quote PDF Extraction ─────────────────────────────────────────
@router.post("/extract-pdf")
async def extract_quote_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a quote PDF and extract prospect/quote info via Claude."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    pdf_bytes = await file.read()

    try:
        from app.services.pdf_extract import extract_pdf_data
        raw = await extract_pdf_data(pdf_bytes)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Map extracted data to quote form fields
    policies = raw.get("policies") or []
    first_policy = policies[0] if policies else {}

    result = {
        "prospect_name": raw.get("client_name") or "",
        "prospect_email": raw.get("client_email") or "",
        "prospect_phone": raw.get("client_phone") or "",
        "prospect_address": raw.get("client_address") or "",
        "prospect_city": raw.get("client_city") or "",
        "prospect_state": raw.get("state") or "",
        "prospect_zip": raw.get("client_zip") or "",
        "carrier": (raw.get("carrier") or "").lower().replace(" ", "_"),
        "policy_type": first_policy.get("policy_type") or "other",
        "quoted_premium": str(first_policy.get("written_premium") or raw.get("total_premium") or ""),
        "effective_date": first_policy.get("effective_date") or "",
        "notes": first_policy.get("notes") or "",
        "policy_number": first_policy.get("policy_number") or "",
        "all_policies": policies,
        "extraction_raw": raw,
    }

    return result


@router.post("/{quote_id}/upload-pdf")
async def upload_quote_pdf(
    quote_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a quote PDF (drag-and-drop)."""
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Create upload directory
    upload_dir = Path(settings.UPLOAD_DIR) / "quotes"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Save file
    safe_name = f"quote_{quote_id}_{int(datetime.utcnow().timestamp())}_{file.filename}"
    file_path = upload_dir / safe_name
    pdf_bytes = await file.read()

    with open(file_path, "wb") as f:
        f.write(pdf_bytes)

    quote.quote_pdf_path = str(file_path)
    quote.quote_pdf_filename = file.filename
    db.commit()

    return {
        "id": quote.id,
        "pdf_uploaded": True,
        "filename": file.filename,
        "size_kb": round(len(pdf_bytes) / 1024, 1),
    }


@router.post("/{quote_id}/send-email")
def send_quote_email_endpoint(
    quote_id: int,
    data: QuoteSendEmail = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send the carrier-branded quote email with PDF attached."""
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if not quote.prospect_email:
        raise HTTPException(status_code=400, detail="No email address for this prospect")

    if not quote.quoted_premium:
        raise HTTPException(status_code=400, detail="No premium amount set")

    from app.services.quote_email import send_quote_email

    premium_str = f"${float(quote.quoted_premium):,.2f}"
    premium_term = (data.premium_term if data and data.premium_term else "6 months")
    eff_str = ""
    if quote.effective_date:
        eff_str = quote.effective_date.strftime("%B %d, %Y")

    producer_name = quote.producer_name or current_user.username
    producer_email = getattr(current_user, 'email', '') or "service@betterchoiceins.com"

    result = send_quote_email(
        to_email=quote.prospect_email,
        prospect_name=quote.prospect_name,
        carrier=quote.carrier,
        policy_type=quote.policy_type,
        premium=premium_str,
        premium_term=premium_term,
        effective_date=eff_str,
        agent_name=producer_name,
        agent_email=producer_email,
        agent_phone="(847) 908-5665",
        additional_notes=(data.additional_notes if data else "") or "",
        pdf_path=quote.quote_pdf_path,
        pdf_filename=quote.quote_pdf_filename,
    )

    if result.get("success"):
        quote.email_sent = True
        quote.email_sent_at = datetime.utcnow()
        quote.status = "sent"

        # Create NowCerts prospect if not already done
        if not quote.nowcerts_prospect_created:
            nc_result = _create_nowcerts_prospect(quote)
            if nc_result:
                quote.nowcerts_prospect_created = True
                quote.nowcerts_note_added = True

        # Fire GHL webhook
        try:
            from app.services.ghl_webhook import get_ghl_service
            ghl = get_ghl_service()
            ghl.fire_quote_sent(
                prospect_name=quote.prospect_name,
                email=quote.prospect_email or "",
                phone=quote.prospect_phone or "",
                carrier=quote.carrier,
                policy_type=quote.policy_type,
                premium=premium_str,
                producer_name=producer_name,
            )
            quote.ghl_webhook_sent = True
        except Exception as e:
            logger.debug(f"GHL webhook failed: {e}")

        db.commit()

    return {
        "email_sent": result.get("success", False),
        "message_id": result.get("message_id"),
        "error": result.get("error"),
        "nowcerts_prospect_created": quote.nowcerts_prospect_created,
    }


@router.get("/")
def list_quotes(
    status: Optional[str] = None,
    producer_id: Optional[int] = None,
    carrier: Optional[str] = None,
    days: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List quotes with filters."""
    query = db.query(Quote)

    # Producers see their own quotes, admins see all
    if current_user.role.lower() not in ("admin", "manager"):
        query = query.filter(Quote.producer_id == current_user.id)
    elif producer_id:
        query = query.filter(Quote.producer_id == producer_id)

    if status:
        query = query.filter(Quote.status == status)
    if carrier:
        query = query.filter(Quote.carrier.ilike(f"%{carrier}%"))
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Quote.created_at >= cutoff)

    quotes = query.order_by(Quote.created_at.desc()).limit(200).all()

    return {
        "total": len(quotes),
        "quotes": [_quote_to_dict(q) for q in quotes],
    }


@router.get("/{quote_id}")
def get_quote(
    quote_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single quote with all details."""
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    return _quote_to_dict(quote)


@router.patch("/{quote_id}")
def update_quote(
    quote_id: int,
    data: QuoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a quote (status, premium, etc.)."""
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if data.status:
        quote.status = data.status
    if data.quoted_premium is not None:
        quote.quoted_premium = data.quoted_premium
    if data.carrier:
        quote.carrier = data.carrier
    if data.policy_type:
        quote.policy_type = data.policy_type
    if data.lost_reason:
        quote.lost_reason = data.lost_reason
        quote.status = "lost"
    if data.prospect_email:
        quote.prospect_email = data.prospect_email
    if data.prospect_phone:
        quote.prospect_phone = data.prospect_phone

    db.commit()
    return _quote_to_dict(quote)


@router.post("/{quote_id}/mark-converted")
def mark_converted(
    quote_id: int,
    sale_id: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a quote as converted to a sale."""
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    quote.status = "converted"
    quote.converted_sale_id = sale_id
    db.commit()

    return {"id": quote.id, "status": "converted", "sale_id": sale_id}


@router.post("/{quote_id}/mark-lost")
def mark_lost(
    quote_id: int,
    reason: str = Query(default="unknown"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a quote as lost with reason."""
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    quote.status = "lost"
    quote.lost_reason = reason
    db.commit()

    return {"id": quote.id, "status": "lost", "reason": reason}


@router.post("/check-followups")
def check_followups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check for quotes needing follow-up (3/7/14 day) and fire actions.

    Run this daily via cron or manual trigger.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    now = datetime.utcnow()
    results = {"day3": 0, "day7": 0, "day14": 0, "day90": 0}

    # Get all sent quotes that haven't been converted or lost
    active_quotes = db.query(Quote).filter(
        Quote.status.in_(["sent", "following_up"]),
        Quote.email_sent == True,
        Quote.email_sent_at.isnot(None),
    ).all()

    for quote in active_quotes:
        days_since = (now - quote.email_sent_at).days

        # 3-day follow-up
        if days_since >= 3 and not quote.followup_3day_sent:
            quote.followup_3day_sent = True
            quote.status = "following_up"
            results["day3"] += 1

            # Fire GHL webhook for follow-up sequence
            try:
                from app.services.ghl_webhook import get_ghl_service
                ghl = get_ghl_service()
                ghl.fire_quote_followup(
                    prospect_name=quote.prospect_name,
                    email=quote.prospect_email or "",
                    phone=quote.prospect_phone or "",
                    carrier=quote.carrier,
                    policy_type=quote.policy_type,
                    days_since=3,
                    producer_name=quote.producer_name or "",
                )
            except Exception:
                pass

        # 7-day follow-up
        elif days_since >= 7 and not quote.followup_7day_sent:
            quote.followup_7day_sent = True
            results["day7"] += 1

            try:
                from app.services.ghl_webhook import get_ghl_service
                ghl = get_ghl_service()
                ghl.fire_quote_followup(
                    prospect_name=quote.prospect_name,
                    email=quote.prospect_email or "",
                    phone=quote.prospect_phone or "",
                    carrier=quote.carrier,
                    policy_type=quote.policy_type,
                    days_since=7,
                    producer_name=quote.producer_name or "",
                )
            except Exception:
                pass

        # 14-day follow-up
        elif days_since >= 14 and not quote.followup_14day_sent:
            quote.followup_14day_sent = True
            results["day14"] += 1

            try:
                from app.services.ghl_webhook import get_ghl_service
                ghl = get_ghl_service()
                ghl.fire_quote_followup(
                    prospect_name=quote.prospect_name,
                    email=quote.prospect_email or "",
                    phone=quote.prospect_phone or "",
                    carrier=quote.carrier,
                    policy_type=quote.policy_type,
                    days_since=14,
                    producer_name=quote.producer_name or "",
                )
            except Exception:
                pass

        # 90-day → enter remarket
        elif days_since >= 90 and not quote.entered_remarket:
            quote.entered_remarket = True
            quote.remarket_start_date = now
            quote.status = "remarket"
            results["day90"] += 1

    db.commit()

    return {
        "checked": len(active_quotes),
        "followups_triggered": results,
    }


@router.get("/stats/summary")
def quote_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get quote pipeline stats."""
    # Current month quotes
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    query = db.query(Quote)
    if current_user.role.lower() not in ("admin", "manager"):
        query = query.filter(Quote.producer_id == current_user.id)

    all_quotes = query.all()
    mtd_quotes = [q for q in all_quotes if q.created_at and q.created_at >= month_start]

    total = len(all_quotes)
    sent = len([q for q in all_quotes if q.email_sent])
    converted = len([q for q in all_quotes if q.status == "converted"])
    lost = len([q for q in all_quotes if q.status == "lost"])
    active = len([q for q in all_quotes if q.status in ("quoted", "sent", "following_up")])
    remarket = len([q for q in all_quotes if q.status == "remarket"])

    return {
        "total_quotes": total,
        "mtd_quotes": len(mtd_quotes),
        "sent": sent,
        "converted": converted,
        "lost": lost,
        "active_pipeline": active,
        "remarket": remarket,
        "conversion_rate": round(converted / sent * 100, 1) if sent > 0 else 0,
    }


def _quote_to_dict(q: Quote) -> dict:
    days_since_sent = None
    if q.email_sent_at:
        days_since_sent = (datetime.utcnow() - q.email_sent_at).days

    return {
        "id": q.id,
        "prospect_name": q.prospect_name,
        "prospect_email": q.prospect_email,
        "prospect_phone": q.prospect_phone,
        "prospect_address": q.prospect_address,
        "prospect_city": q.prospect_city,
        "prospect_state": q.prospect_state,
        "prospect_zip": q.prospect_zip,
        "carrier": q.carrier,
        "policy_type": q.policy_type,
        "quoted_premium": float(q.quoted_premium) if q.quoted_premium else None,
        "effective_date": q.effective_date.isoformat() if q.effective_date else None,
        "status": q.status,
        "pdf_uploaded": bool(q.quote_pdf_path),
        "pdf_filename": q.quote_pdf_filename,
        "email_sent": q.email_sent,
        "email_sent_at": q.email_sent_at.isoformat() if q.email_sent_at else None,
        "days_since_sent": days_since_sent,
        "followup_3day_sent": q.followup_3day_sent,
        "followup_7day_sent": q.followup_7day_sent,
        "followup_14day_sent": q.followup_14day_sent,
        "entered_remarket": q.entered_remarket,
        "converted_sale_id": q.converted_sale_id,
        "lost_reason": q.lost_reason,
        "nowcerts_prospect_created": q.nowcerts_prospect_created,
        "producer_id": q.producer_id,
        "producer_name": q.producer_name,
        "created_at": q.created_at.isoformat() if q.created_at else None,
    }


