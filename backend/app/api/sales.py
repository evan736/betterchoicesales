from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import extract as sql_extract, func
from pathlib import Path
import shutil
from datetime import datetime, date, timedelta
from app.core.database import get_db, SessionLocal
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale, SaleStatus
from app.schemas.sale import SaleCreate, Sale as SaleSchema, SaleUpdate
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sales", tags=["sales"])


def _safe_str(val):
    """Safely convert a value to a clean UTF-8 string."""
    if val is None:
        return None
    try:
        s = str(val)
        s.encode('utf-8')  # Test it's valid UTF-8
        return s
    except (UnicodeDecodeError, UnicodeEncodeError):
        return str(val).encode('utf-8', errors='replace').decode('utf-8')

# Carrier name normalization — maps alternate names to canonical carrier names
CARRIER_NORMALIZE = {
    # Travelers
    "travelers": "Travelers",
    "travelers personal insurance company": "Travelers",
    "travelers personal insurance": "Travelers",
    "travelers personal insura": "Travelers",
    "travelers home and marine insurance company": "Travelers",
    "travelers home and marine insurance": "Travelers",
    "travelers home and marine": "Travelers",
    "travelers casualty insurance company of america": "Travelers",
    "travelers indemnity company": "Travelers",
    "the travelers": "Travelers",
    "travco": "Travelers",
    "travco insurance": "Travelers",
    "travco insurance company": "Travelers",
    "the standard fire insurance company": "Travelers",
    "standard fire insurance company": "Travelers",
    "standard fire insurance": "Travelers",
    "standard fire": "Travelers",
    # Progressive
    "progressive": "Progressive",
    "progressive insurance": "Progressive",
    "progressive northern insurance co": "Progressive",
    "progressive northern insurance company": "Progressive",
    "progressive northern": "Progressive",
    "progressive preferred insurance company": "Progressive",
    "progressive preferred ins co": "Progressive",
    "progressive preferred": "Progressive",
    "progressive casualty insurance company": "Progressive",
    "progressive casualty": "Progressive",
    "progressive specialty insurance company": "Progressive",
    # National General
    "national general": "National General",
    "national general insurance": "National General",
    "national general, an allstate company": "National General",
    "national general an allstate company": "National General",
    "integon": "National General",
    "integon national": "National General",
    "integon national insurance": "National General",
    "integon national insurance company": "National General",
    "integon natl": "National General",
    "integon natl ins": "National General",
    "encompass": "National General",
    "encompass insurance": "National General",
    "encompass insurance company": "National General",
    # Grange / Integrity
    "grange": "Grange",
    "grange insurance": "Grange",
    "grange mutual casualty company": "Grange",
    "grange indemnity insurance co": "Grange",
    "grange indemnity": "Grange",
    "integrity insurance": "Grange",
    "integrity insurance company": "Grange",
    "integrity": "Grange",
    "trustgard": "Grange",
    "trust gard": "Grange",
    "trustgard mutual": "Grange",
    "trustgard insurance": "Grange",
    # Safeco
    "safeco": "Safeco",
    "safeco insurance": "Safeco",
    "safeco insurance company of america": "Safeco",
    "safeco insurance company of oregon": "Safeco",
    "american economy": "Safeco",
    "american economy insurance": "Safeco",
    "american economy insurance company": "Safeco",
    "american states preferred insurance company": "Safeco",
    "american states preferred ins co": "Safeco",
    "american states preferred": "Safeco",
    "general insurance company of america": "Safeco",
    # GEICO
    "geico": "GEICO",
    "geico insurance": "GEICO",
    "geico general insurance company": "GEICO",
    "geico casualty company": "GEICO",
    "geico indemnity company": "GEICO",
    "geico marine insurance company": "GEICO",
    "geico texas county mutual insurance company": "GEICO",
    "geico county mutual insurance company": "GEICO",
    "government employees insurance company": "GEICO",
    # Steadily / Obsidian / Canopius
    "steadily": "Steadily",
    "obsidian": "Steadily",
    "obsedian": "Steadily",
    "obsidian insurance": "Steadily",
    "obsedian insurance": "Steadily",
    "obsidian insurance company": "Steadily",
    "canopius": "Steadily",
    "canopius us": "Steadily",
    "canopius us insurance": "Steadily",
    "canopius us insurance, inc": "Steadily",
    "canopius us insurance, inc.": "Steadily",
    "canopius us insurance inc": "Steadily",
    "canopius insurance": "Steadily",
    # Universal Property
    "universal property": "Universal Property",
    "universal property & casualty insurance company": "Universal Property",
    "universal property and casualty insurance company": "Universal Property",
    "universal property & casualty": "Universal Property",
    "upcic": "Universal Property",
    "american platinum property and casualty insurance company": "Universal Property",
    # Openly / Rock Ridge
    "openly": "Openly",
    "openly insurance": "Openly",
    "rock ridge insurance company": "Openly",
    "rock ridge": "Openly",
    # First Connect
    "first connect": "First Connect",
    "first connect insurance": "First Connect",
    # American Modern
    "american modern": "American Modern",
    "american modern insurance": "American Modern",
    "american modern insurance company": "American Modern",
    "amig": "American Modern",
    # Bristol West
    "bristol west": "Bristol West",
    "bristol west insurance": "Bristol West",
    "bristol west insurance group": "Bristol West",
    # Hippo / Spinnaker
    "hippo": "Hippo",
    "hippo insurance": "Hippo",
    "spinnaker": "Hippo",
    "spinnaker insurance": "Hippo",
    "spinnaker insurance company": "Hippo",
    # Branch
    "branch": "Branch",
    "branch insurance": "Branch",
    # Clearcover
    "clearcover": "Clearcover",
    "clearcover insurance": "Clearcover",
    "clearcover insurance company": "Clearcover",
    # Chubb
    "chubb": "Chubb",
    # Gainsco
    "gainsco": "Gainsco",
    "gainsco auto": "Gainsco",
    # Hartford
    "hartford": "Hartford",
    "the hartford": "Hartford",
    # CoverTree
    "covertree": "CoverTree",
    "cover tree": "CoverTree",
    "covertree insurance": "CoverTree",
}


def _normalize_carrier(carrier: str, policy_number: str = None) -> str:
    """Normalize carrier name to canonical form."""
    if not carrier:
        # Check policy number prefix as fallback
        if policy_number and policy_number.upper().startswith("SP3"):
            return "Steadily"
        return carrier
    key = carrier.strip().lower()
    # Exact match
    if key in CARRIER_NORMALIZE:
        return CARRIER_NORMALIZE[key]
    # Partial match — check if any known key is contained in the carrier name
    for pattern, canonical in CARRIER_NORMALIZE.items():
        if pattern in key or key in pattern:
            return canonical
    # Policy number prefix fallback
    if policy_number and policy_number.upper().startswith("SP3"):
        return "Steadily"
    # Return cleaned original
    return carrier.strip()


def determine_status(effective_date) -> str:
    """Determine sale status based on effective date vs today."""
    if effective_date is None:
        return "active"
    if isinstance(effective_date, datetime):
        eff_date = effective_date.date()
    elif isinstance(effective_date, date):
        eff_date = effective_date
    else:
        return "active"
    
    today = date.today()
    if eff_date <= today:
        return "active"
    else:
        return "pending"


def _trigger_welcome_email(sale: Sale, producer: User, db: Session):
    """Send welcome email in background after sale creation."""
    import threading
    import logging
    logger = logging.getLogger(__name__)
    
    if not sale.client_email:
        logger.info(f"No email for sale {sale.id} — skipping welcome email")
        return
    
    if not settings.MAILGUN_API_KEY:
        logger.info("Mailgun not configured — skipping welcome email")
        return

    def _send():
        try:
            from app.services.welcome_email import send_welcome_email
            result = send_welcome_email(
                to_email=sale.client_email,
                client_name=sale.client_name,
                policy_number=sale.policy_number,
                carrier=sale.carrier or "",
                producer_name=producer.full_name if producer else "Your Agent",
                sale_id=sale.id,
                policy_type=sale.policy_type,
                producer_email=producer.email if producer else None,
            )
            if result.get("success"):
                # Update sale in a new session
                from app.core.database import SessionLocal
                new_db = SessionLocal()
                try:
                    s = new_db.query(Sale).filter(Sale.id == sale.id).first()
                    if s:
                        s.welcome_email_sent = True
                        s.welcome_email_sent_at = datetime.utcnow()
                        new_db.commit()
                finally:
                    new_db.close()
                logger.info(f"Welcome email sent for sale {sale.id}")
            else:
                logger.warning(f"Welcome email failed for sale {sale.id}: {result}")
        except Exception as e:
            logger.error(f"Welcome email error for sale {sale.id}: {e}")

    # Fire and forget in background thread
    threading.Thread(target=_send, daemon=True).start()






def _auto_close_reshop_on_rewrite(sale: Sale, db: Session):
    """If a rewrite sale matches a customer in the reshop pipeline, auto-close the reshop as bound."""
    import logging
    _logger = logging.getLogger(__name__)
    
    if not sale.lead_source or sale.lead_source.lower() != "rewrite":
        return
    
    try:
        from app.models.reshop import Reshop
        from sqlalchemy import func
        
        ACTIVE_STAGES = ["proactive", "new_request", "quoting", "quote_ready", "presenting"]
        client_name = (sale.client_name or "").strip()
        policy_number = (sale.policy_number or "").strip()
        
        if not client_name and not policy_number:
            return

        # Try to match by policy number first (most precise)
        matched_reshop = None
        if policy_number:
            matched_reshop = db.query(Reshop).filter(
                Reshop.policy_number == policy_number,
                Reshop.stage.in_(ACTIVE_STAGES),
            ).first()
        
        # Then try by customer name
        if not matched_reshop and client_name:
            matched_reshop = db.query(Reshop).filter(
                func.lower(Reshop.customer_name) == client_name.lower(),
                Reshop.stage.in_(ACTIVE_STAGES),
            ).first()

        if matched_reshop:
            old_stage = matched_reshop.stage
            matched_reshop.stage = "bound"
            matched_reshop.quoted_carrier = sale.carrier
            matched_reshop.quoted_premium = float(sale.written_premium or 0)
            if matched_reshop.current_premium:
                matched_reshop.premium_savings = float(matched_reshop.current_premium) - float(sale.written_premium or 0)
            
            # Log activity
            from app.models.reshop import ReshopActivity
            activity = ReshopActivity(
                reshop_id=matched_reshop.id,
                action="stage_change",
                details=f"Auto-closed: rewrite sale created (policy {policy_number}, {sale.carrier}). Moved from {old_stage} → bound.",
                user_name="ORBIT Auto",
            )
            db.add(activity)
            db.commit()
            
            _logger.info(f"Auto-closed reshop {matched_reshop.id} ({matched_reshop.customer_name}) as bound — rewrite sale {sale.id} ({sale.carrier})")
            
            # Also close any other active reshops for the same customer
            other_reshops = db.query(Reshop).filter(
                Reshop.customer_id == matched_reshop.customer_id,
                Reshop.id != matched_reshop.id,
                Reshop.stage.in_(ACTIVE_STAGES),
            ).all()
            for r in other_reshops:
                r.stage = "bound"
                r.quoted_carrier = sale.carrier
                r.quoted_premium = float(sale.written_premium or 0)
                act = ReshopActivity(
                    reshop_id=r.id,
                    action="stage_change",
                    details=f"Auto-closed: same customer rewrite ({sale.carrier}). Linked to reshop #{matched_reshop.id}.",
                    user_name="ORBIT Auto",
                )
                db.add(act)
                _logger.info(f"Auto-closed related reshop {r.id} ({r.customer_name} / {r.policy_number})")
            
            if other_reshops:
                db.commit()
    except Exception as e:
        _logger.warning(f"Auto-close reshop failed for sale {sale.id}: {e}")
        try:
            db.rollback()
        except:
            pass

def _auto_enroll_life_campaign(sale: Sale, producer: User, db: Session):
    """Auto-enroll new customer into life insurance cross-sell campaign."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        if not sale.client_email:
            return
        
        from app.models.life_campaign import LifeCrossSellContact
        from datetime import datetime, timedelta
        
        # Check if already enrolled
        existing = db.query(LifeCrossSellContact).filter(
            LifeCrossSellContact.customer_email == sale.client_email,
            LifeCrossSellContact.status.in_(["queued", "active"]),
        ).first()
        if existing:
            return
        
        # Also check opted out
        opted_out = db.query(LifeCrossSellContact).filter(
            LifeCrossSellContact.customer_email == sale.client_email,
            LifeCrossSellContact.status == "opted_out",
        ).first()
        if opted_out:
            return
        
        contact = LifeCrossSellContact(
            customer_id=sale.id,  # Use sale ID as reference
            customer_name=sale.client_name,
            customer_email=sale.client_email,
            agent_name=producer.full_name if producer else None,
            agent_email=producer.email if producer else None,
            touch_number=0,
            next_touch_date=datetime.utcnow() + timedelta(days=3),
            status="active",
            source_sale_id=sale.id,
            source_policy_type=sale.policy_type or "",
        )
        db.add(contact)
        db.commit()
        logger.info(f"Auto-enrolled {sale.client_name} ({sale.client_email}) in life cross-sell campaign")
    except Exception as e:
        logger.warning(f"Life campaign auto-enroll failed for {sale.client_name}: {e}")
        try:
            db.rollback()
        except:
            pass

def _trigger_hooray_email(sale: Sale, producer: User, db: Session):
    """Send Hooray notification to all producers after sale creation."""
    import logging
    logger = logging.getLogger(__name__)

    if not settings.MAILGUN_API_KEY:
        logger.info("Mailgun not configured — skipping hooray email")
        return

    # Capture sale data while session is active
    sale_data = {
        "id": sale.id,
        "client_name": sale.client_name or "New Customer",
        "carrier": sale.carrier or "",
        "policy_type": sale.policy_type or "other",
        "written_premium": float(sale.written_premium or 0),
        "lead_source": sale.lead_source or "",
    }
    producer_name = producer.full_name if producer else "Team Member"

    # Send inline (not background thread) — Render can kill background threads
    # before they complete if the response finishes first
    try:
        from app.services.hooray_email import send_hooray_email_from_data
        result = send_hooray_email_from_data(
            sale_data=sale_data,
            producer_name=producer_name,
            db=db,
        )
        if result.get("success"):
            logger.info(f"Hooray email sent for sale {sale_data['id']} to {result.get('recipients', 0)} recipients")
        else:
            logger.warning(f"Hooray email failed for sale {sale_data['id']}: {result}")
    except Exception as e:
        logger.error(f"Hooray email error for sale {sale_data['id']}: {e}")






@router.post("/normalize-carriers")
def normalize_all_carriers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One-time cleanup: normalize all carrier names in existing sales."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")
    
    # Use raw SQL to avoid loading problematic timestamp columns
    from sqlalchemy import text
    result = db.execute(text("SELECT id, carrier FROM sales WHERE carrier IS NOT NULL"))
    rows = result.fetchall()
    
    updated = 0
    changes = []
    for row in rows:
        sale_id, original = row[0], row[1]
        normalized = _normalize_carrier(original)
        if normalized != original:
            db.execute(text("UPDATE sales SET carrier = :carrier WHERE id = :id"), {"carrier": normalized, "id": sale_id})
            updated += 1
            changes.append({"id": sale_id, "old": original, "new": normalized})
    
    db.commit()
    return {"total_sales": len(rows), "updated": updated, "sample_changes": changes[:30]}

@router.post("/test-hooray/{sale_id}")
def test_hooray_email(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test the hooray email for a specific sale (admin only)."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")
    
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    producer = db.query(User).filter(User.id == sale.producer_id).first()
    
    # Call the hooray function directly and capture any errors
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        sale_data = {
            "id": sale.id,
            "client_name": sale.client_name or "New Customer",
            "carrier": sale.carrier or "",
            "policy_type": sale.policy_type or "other",
            "written_premium": float(sale.written_premium or 0),
            "lead_source": sale.lead_source or "",
        }
        producer_name = producer.full_name if producer else "Team Member"
        
        from app.services.hooray_email import send_hooray_email_from_data
        result = send_hooray_email_from_data(
            sale_data=sale_data,
            producer_name=producer_name,
            db=db,
        )
        return {"sale_id": sale_id, "result": result}
    except Exception as e:
        import traceback
        return {"sale_id": sale_id, "error": str(e), "traceback": traceback.format_exc()}

@router.post("/extract-pdf")
async def extract_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a PDF and extract insurance application data using AI."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )

    # Read file bytes
    pdf_bytes = await file.read()

    if len(pdf_bytes) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 50MB)"
        )

    try:
        from app.services.pdf_extract import extract_pdf_data
        extracted = await extract_pdf_data(pdf_bytes)
        return {"status": "success", "data": extracted, "filename": file.filename}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process PDF: {str(e)}"
        )


@router.post("/create-from-pdf")
def create_from_pdf(
    sale_data: SaleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a sale from extracted PDF data, with household grouping logic."""
    from datetime import datetime

    # Check for duplicate policy number
    existing = db.query(Sale).filter(Sale.policy_number == sale_data.policy_number).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sale with this policy number already exists"
        )

    sale = Sale(
        **sale_data.model_dump(),
        producer_id=current_user.id,
        status=determine_status(sale_data.effective_date),
    )
    # Normalize carrier name (e.g. "Obsidian" → "Steadily")
    sale.carrier = _normalize_carrier(sale.carrier, sale.policy_number)

    db.add(sale)
    db.commit()
    db.refresh(sale)

    # Welcome email is now sent manually from the frontend after save,
    # so the agent can choose whether to attach a PDF.

    # Send Hooray notification to all producers
    _trigger_hooray_email(sale, current_user, db)
    _auto_enroll_life_campaign(sale, current_user, db)
    _auto_close_reshop_on_rewrite(sale, db)

    # Check for household grouping — same client name, same month
    sale_month = sale.sale_date.month if sale.sale_date else datetime.utcnow().month
    sale_year = sale.sale_date.year if sale.sale_date else datetime.utcnow().year

    household_sales = (
        db.query(Sale)
        .filter(
            Sale.producer_id == current_user.id,
            Sale.client_name == sale.client_name,
            sql_extract("year", Sale.sale_date) == sale_year,
            sql_extract("month", Sale.sale_date) == sale_month,
        )
        .all()
    )

    household_items = sum(s.item_count or 1 for s in household_sales)
    household_premium = sum(float(s.written_premium) for s in household_sales)

    return {
        "sale": SaleSchema.model_validate(sale),
        "household": {
            "client_name": sale.client_name,
            "total_policies": len(household_sales),
            "total_items": household_items,
            "total_premium": household_premium,
            "is_bundle": len(household_sales) > 1,
        }
    }


@router.post("/create-bundle")
def create_bundle(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a single bundled sale with line items from multiple policy lines.

    Expects: {
        "base_policy_number": "2033884202",
        "client_name": "Jack Liesen",
        "client_email": "...",
        "client_phone": "...",
        "carrier": "Encompass",
        "state": "IL",
        "lead_source": "call_in",
        "effective_date": "2026-03-06T00:00:00",
        "lines": [
            {"policy_type": "home", "premium": 1362.00, "item_count": 1, "policy_suffix": "", "notes": "..."},
            {"policy_type": "auto", "premium": 1335.32, "item_count": 1, "policy_suffix": "AUT", "notes": "..."}
        ]
    }
    """
    from datetime import datetime
    from app.models.sale import SaleLineItem

    base_pn = str(request.get("base_policy_number", "")).strip()
    if not base_pn:
        raise HTTPException(status_code=400, detail="base_policy_number is required")

    lines = request.get("lines", [])
    if not lines:
        raise HTTPException(status_code=400, detail="At least one line item is required")

    # Check for duplicate
    existing = db.query(Sale).filter(Sale.policy_number == base_pn).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Sale with policy number {base_pn} already exists")

    total_premium = sum(float(l.get("premium", 0)) for l in lines)
    total_items = sum(int(l.get("item_count", 1)) for l in lines)

    # Parse effective_date
    eff_date = None
    eff_str = request.get("effective_date")
    if eff_str:
        try:
            eff_date = datetime.fromisoformat(str(eff_str).replace("Z", "+00:00"))
        except Exception:
            pass

    policy_type = "bundled" if len(lines) > 1 else (lines[0].get("policy_type") or "other")

    sale = Sale(
        policy_number=base_pn,
        policy_type=policy_type,
        carrier=_normalize_carrier(str(request.get("carrier", "")).strip()),
        written_premium=total_premium,
        recognized_premium=total_premium,
        producer_id=current_user.id,
        lead_source=request.get("lead_source"),
        item_count=total_items,
        client_name=str(request.get("client_name", "")).strip(),
        client_email=request.get("client_email"),
        client_phone=request.get("client_phone"),
        state=request.get("state"),
        status=determine_status(eff_date),
        effective_date=eff_date,
        notes=request.get("notes"),
    )
    db.add(sale)
    db.flush()  # Get sale.id

    # Create line items
    for l in lines:
        li = SaleLineItem(
            sale_id=sale.id,
            policy_type=l.get("policy_type", "other"),
            policy_suffix=l.get("policy_suffix") or None,
            premium=float(l.get("premium", 0)),
            description=l.get("notes") or f"{l.get('policy_type', 'other').replace('_', ' ').title()}",
        )
        db.add(li)

    db.commit()
    db.refresh(sale)

    # Send Hooray notification
    _trigger_hooray_email(sale, current_user, db)

    _auto_close_reshop_on_rewrite(sale, db)
    return {
        "sale": SaleSchema.model_validate(sale),
        "household": {
            "client_name": sale.client_name,
            "total_policies": 1,
            "total_items": total_items,
            "total_premium": total_premium,
            "is_bundle": len(lines) > 1,
        }
    }


@router.post("/", response_model=SaleSchema)
def create_sale(
    sale_data: SaleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new sale"""
    # Check for duplicate policy number
    existing = db.query(Sale).filter(Sale.policy_number == sale_data.policy_number).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sale with this policy number already exists"
        )
    
    sale = Sale(
        **sale_data.model_dump(),
        producer_id=current_user.id,
        status=determine_status(sale_data.effective_date),
    )
    # Normalize carrier name (e.g. "Obsidian" → "Steadily")
    sale.carrier = _normalize_carrier(sale.carrier, sale.policy_number)
    
    db.add(sale)
    db.commit()
    db.refresh(sale)

    # Broadcast live update
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("sales:new", {"id": sale.id, "customer_name": sale.customer_name})
        event_bus.publish_sync("dashboard:refresh", {})
    except Exception:
        pass
    
    # Welcome email is now sent manually from the frontend after save,
    # so the agent can choose whether to attach a PDF.
    
    # Send Hooray notification to all producers
    _trigger_hooray_email(sale, current_user, db)
    _auto_close_reshop_on_rewrite(sale, db)

    # Auto-convert matching quotes (same customer name)
    try:
        from app.models.campaign import Quote
        matching_quotes = db.query(Quote).filter(
            Quote.status.in_(["sent", "following_up", "quoted"]),
        ).all()
        for q in matching_quotes:
            if sale.customer_name.lower().strip() == q.prospect_name.lower().strip():
                q.status = "converted"
                q.converted_sale_id = sale.id
                logger.info(f"Auto-converted quote {q.id} ({q.prospect_name}) -> sale {sale.id}")
        db.commit()
    except Exception as e:
        logger.warning(f"Quote auto-conversion check failed: {e}")

    # Check if this sale sets a new daily/monthly record
    try:
        from app.api.sales_records import check_for_new_records
        new_records = check_for_new_records(db)
        if new_records:
            logger.info(f"🏆 {len(new_records)} new sales record(s) set!")
    except Exception as e:
        logger.warning(f"Sales record check failed: {e}")
    
    return sale


@router.get("/")
def list_sales(
    skip: int = 0,
    limit: int = 500,
    date_from: str = None,  # "2026-01-01"
    date_to: str = None,    # "2026-01-31"
    producer_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List sales - agents/producers see only their own. Admin/manager/Andrey see all."""
    query = db.query(Sale)
    
    # Role-based filtering: producers only see their own sales
    # Andrey Dayson (retention_specialist) has full visibility like admin
    FULL_ACCESS_USERNAMES = {"andrey.dayson"}
    is_privileged = (
        current_user.role.lower() in ("admin", "manager")
        or (current_user.username or "").lower() in FULL_ACCESS_USERNAMES
    )
    if not is_privileged:
        query = query.filter(Sale.producer_id == current_user.id)
    elif producer_id:
        # Optional producer filter (for admin/manager filtering UI)
        query = query.filter(Sale.producer_id == producer_id)
    
    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Sale.sale_date >= from_dt)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            # Include the full end day
            to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(Sale.sale_date <= to_dt)
        except ValueError:
            pass
    
    sales = query.order_by(Sale.sale_date.desc()).offset(skip).limit(limit).all()
    
    # Commission fields already controlled by is_privileged set above
    result = []
    for sale in sales:
        try:
            if is_privileged:
                sale_dict = SaleSchema.model_validate(sale).model_dump()
            else:
                sale_dict = SaleSchema.model_validate(sale).model_dump()
                sale_dict.pop("commission_status", None)
                sale_dict.pop("commission_paid_date", None)
                sale_dict.pop("commission_paid_period", None)
            result.append(sale_dict)
        except Exception as e:
            # Handle bad data (e.g. invalid UTF-8 from PDF extraction)
            logger.warning(f"Error serializing sale {sale.id}: {e}")
            try:
                # Build a safe fallback dict with sanitized strings
                safe_dict = {
                    "id": sale.id,
                    "policy_number": _safe_str(sale.policy_number),
                    "client_name": _safe_str(sale.client_name),
                    "client_email": _safe_str(sale.client_email),
                    "client_phone": _safe_str(sale.client_phone),
                    "policy_type": _safe_str(sale.policy_type),
                    "carrier": _safe_str(sale.carrier),
                    "state": _safe_str(sale.state),
                    "written_premium": float(sale.written_premium or 0),
                    "recognized_premium": float(sale.recognized_premium or 0) if sale.recognized_premium else None,
                    "status": _safe_str(sale.status),
                    "commission_status": _safe_str(sale.commission_status) if is_privileged else None,
                    "producer_id": sale.producer_id,
                    "item_count": sale.item_count or 1,
                    "sale_date": sale.sale_date.isoformat() if sale.sale_date else None,
                    "effective_date": sale.effective_date.isoformat() if sale.effective_date else None,
                    "created_at": sale.created_at.isoformat() if sale.created_at else None,
                    "updated_at": sale.updated_at.isoformat() if sale.updated_at else None,
                    "welcome_email_sent": sale.welcome_email_sent,
                    "notes": _safe_str(sale.notes),
                    "lead_source": _safe_str(sale.lead_source),
                    "signature_status": _safe_str(sale.signature_status),
                    "line_items": [],
                    "producer_name": None,
                    "producer_code": None,
                }
                result.append(safe_dict)
            except Exception as e2:
                logger.error(f"Could not even build fallback for sale {sale.id}: {e2}")
    return result



@router.post("/import-csv")
async def import_sales_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import sales from a CSV file.
    
    Expected columns: Sale Date, Effective Date, Policy #, Customer,
    Policy Type, Company, Items, Premium, Source, Producer
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    import pandas as pd
    import io
    from decimal import Decimal

    file_bytes = await file.read()
    df = pd.read_csv(io.BytesIO(file_bytes))

    # Build producer name -> user ID mapping
    users = db.query(User).filter(User.is_active == True).all()
    producer_map = {}
    for u in users:
        if u.full_name:
            producer_map[u.full_name.lower()] = u.id
            # Also map common variations
            parts = u.full_name.split()
            if len(parts) >= 2:
                # "Giulian Baez" also matches "Guilian Baez"
                producer_map[f"{parts[0].lower()} {parts[-1].lower()}"] = u.id

    # Special mappings for CSV name variations
    producer_map["guilian baez"] = producer_map.get("giulian baez", None)

    # Find Evan Larson's ID for Missy Hall reassignment
    evan_id = None
    for u in users:
        if u.full_name and "evan" in u.full_name.lower() and "larson" in u.full_name.lower():
            evan_id = u.id
            break
    if not evan_id:
        # Fall back to admin
        admin = db.query(User).filter(User.role == "admin").first()
        evan_id = admin.id if admin else users[0].id

    created = 0
    skipped = 0
    errors = []

    for _, row in df.iterrows():
        try:
            policy_number = str(row.get("Policy #", "")).strip()
            if not policy_number or policy_number == "nan":
                skipped += 1
                continue

            # Check if policy already exists
            existing = db.query(Sale).filter(Sale.policy_number == policy_number).first()
            if existing:
                skipped += 1
                continue

            # Resolve producer
            producer_name = str(row.get("Producer", "")).strip()
            producer_id = producer_map.get(producer_name.lower())

            # Handle Missy Hall -> Evan Larson
            if not producer_id and "missy" in producer_name.lower():
                producer_id = evan_id

            if not producer_id:
                # Try partial match
                for name, uid in producer_map.items():
                    if name and producer_name.lower() in name or name in producer_name.lower():
                        producer_id = uid
                        break

            if not producer_id:
                errors.append(f"No producer match for '{producer_name}' on policy {policy_number}")
                producer_id = evan_id  # Default to Evan

            # Parse premium
            premium_str = str(row.get("Premium", "0")).replace("$", "").replace(",", "").strip()
            try:
                premium = Decimal(premium_str)
            except Exception:
                premium = Decimal("0")

            # Parse dates
            sale_date = None
            eff_date = None
            try:
                sale_date = pd.to_datetime(row.get("Sale Date"))
            except Exception:
                pass
            try:
                eff_date = pd.to_datetime(row.get("Effective Date"))
            except Exception:
                pass

            # Map source
            source_raw = str(row.get("Source", "other")).strip().lower()
            source_map = {
                "rewrite": "rewrite",
                "insurance ai call": "insurance_ai_call",
                "quote wizard": "quote_wizard",
                "call in": "call_in",
                "customer referral": "customer_referral",
                "family & friends": "referral",
                "everquote call": "other",
                "avenge digital": "other",
                "datalot": "other",
                "mortgage lender": "referral",
                "cross sell - all other": "other",
                "tribe": "other",
            }
            lead_source = source_map.get(source_raw, "other")
            # Check if it starts with a known prefix
            for prefix, mapped in source_map.items():
                if source_raw.startswith(prefix):
                    lead_source = mapped
                    break

            # Map policy type - keep term info
            policy_raw = str(row.get("Policy Type", "")).strip().lower()
            if "bundled" in policy_raw:
                policy_type = "bundled"
            elif "auto" in policy_raw and "6m" in policy_raw:
                policy_type = "auto_6m"
            elif "auto" in policy_raw and "12m" in policy_raw:
                policy_type = "auto_12m"
            elif "auto" in policy_raw:
                policy_type = "auto"
            elif "home" in policy_raw:
                policy_type = "home"
            elif "renter" in policy_raw:
                policy_type = "renters"
            elif "condo" in policy_raw:
                policy_type = "condo"
            elif "motorcycle" in policy_raw:
                policy_type = "motorcycle"
            elif "dwelling" in policy_raw:
                policy_type = "home"
            elif "mobile" in policy_raw:
                policy_type = "other"
            elif "trailer" in policy_raw:
                policy_type = "other"
            else:
                policy_type = "other"

            # Items count
            try:
                items = int(row.get("Items", 1))
            except Exception:
                items = 1

            sale = Sale(
                policy_number=policy_number,
                policy_type=policy_type,
                carrier=_normalize_carrier(str(row.get("Company", "")).strip()),
                written_premium=premium,
                recognized_premium=premium,
                producer_id=producer_id,
                lead_source=lead_source,
                item_count=items,
                client_name=str(row.get("Customer", "")).strip(),
                status="active",
                sale_date=sale_date,
                effective_date=eff_date,
            )
            db.add(sale)
            created += 1

            # Batch commit every 100 rows to avoid timeout
            if created % 100 == 0:
                db.commit()

        except Exception as e:
            errors.append(f"Error on row: {str(e)[:100]}")

    db.commit()

    # ── Bundle Detection & Merging ──
    # Find newly created sales that share the same base policy number + client + effective date
    # e.g. 2033884202 (home) + 2033884202-AUT (auto) → merge into one bundled sale
    import re
    from app.models.sale import SaleLineItem

    def _base_policy(pn: str) -> str:
        """Strip suffix like -AUT, -01, -HOM from policy number."""
        return re.sub(r'[- ]+(AUT|HOM|HOME|AUTO|RNT|RENT|01|02|03|04|05)$', '', pn.upper()).strip()

    try:
        # Get all sales just created (in this import batch) — those without line_items yet
        import_cutoff = datetime.utcnow() - timedelta(minutes=5)
        recent_sales = db.query(Sale).filter(
            Sale.id > 0
        ).order_by(Sale.id.desc()).limit(created + skipped + 10).all()

        # Group by (base_policy, client_name_upper, effective_date)
        from collections import defaultdict
        groups = defaultdict(list)
        for s in recent_sales:
            base = _base_policy(s.policy_number or "")
            client = (s.client_name or "").upper().strip()
            eff = str(s.effective_date)[:10] if s.effective_date else ""
            key = (base, client, eff)
            groups[key].append(s)

        merged_count = 0
        for key, group_sales in groups.items():
            if len(group_sales) < 2:
                continue

            # Sort by id to keep the first-created as the primary
            group_sales.sort(key=lambda s: s.id)
            primary = group_sales[0]

            # Create line items for each sale in the group
            total_premium = 0
            total_items = 0
            types_found = []
            for s in group_sales:
                suffix = (s.policy_number or "").replace(_base_policy(s.policy_number or ""), "").strip(" -")
                line = SaleLineItem(
                    sale_id=primary.id,
                    policy_type=s.policy_type or "other",
                    policy_suffix=suffix or None,
                    premium=float(s.written_premium or 0),
                    description=f"{(s.policy_type or 'other').replace('_', ' ').title()} — {s.policy_number}",
                )
                db.add(line)
                total_premium += float(s.written_premium or 0)
                total_items += (s.item_count or 1)
                types_found.append(s.policy_type or "other")

            # Update primary sale
            primary.policy_type = "bundled"
            primary.written_premium = total_premium
            primary.recognized_premium = total_premium
            primary.item_count = total_items
            # Use the base policy number (no suffix)
            primary.policy_number = _base_policy(primary.policy_number)

            # Delete the secondary sales (not the primary)
            for s in group_sales[1:]:
                db.delete(s)
                merged_count += 1

        if merged_count > 0:
            db.commit()
            logger.info(f"Merged {merged_count} duplicate policies into bundles")

    except Exception as bundle_err:
        logger.warning(f"Bundle detection failed (sales still imported): {bundle_err}")
        merged_count = 0
        try:
            db.rollback()
            db.commit()  # Re-commit the sales that were already added
        except Exception:
            pass

    # Invalidate cached dashboard data since sales changed
    try:
        from app.core.cache import invalidate
        invalidate()  # Clear all caches
    except Exception:
        pass

    return {
        "created": created - merged_count,
        "skipped": skipped,
        "merged_into_bundles": merged_count,
        "errors": errors,
        "total_rows": len(df),
    }



@router.get("/debug-counts")
def debug_sale_counts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug: count sales by year-month."""
    from sqlalchemy import func, extract as sql_ext
    results = db.query(
        sql_ext("year", Sale.sale_date).label("y"),
        sql_ext("month", Sale.sale_date).label("m"),
        func.count(Sale.id).label("cnt"),
        func.sum(Sale.written_premium).label("premium"),
    ).group_by("y", "m").order_by("y", "m").all()
    
    total = db.query(func.count(Sale.id)).scalar()
    null_dates = db.query(func.count(Sale.id)).filter(Sale.sale_date.is_(None)).scalar()
    return {
        "total_sales": total,
        "null_sale_dates": null_dates,
        "by_month": [{"year": r.y, "month": r.m, "count": r.cnt, "premium": float(r.premium or 0)} for r in results],
    }



# ── NatGen Summer Promo tracker ────────────────────────────────────────
# Promo window: April 20, 2026 through September 30, 2026.
# Team goal: 250 NatGen policies. Individual goals:
#   Joseph Rivera, Giulian Baez: 75 each
#   Salma Marquez, Michelle Robles, April Wilson: 50 each
#   Evan Larson: tracked but no personal goal (leaderboard visibility only)
# Only NatGen policies sold AND effective within the promo window count.
# Returns per-producer progress plus team aggregate. Available to any
# logged-in user so producers can see their own progress on the sales page.
NATGEN_PROMO_WINDOW_START = "2026-04-20"
NATGEN_PROMO_WINDOW_END = "2026-09-30"
NATGEN_PROMO_TEAM_GOAL = 250
NATGEN_PROMO_PRODUCER_GOALS = {
    # username → goal (None = tracked in leaderboard but no personal target)
    "joseph.rivera": 75,
    "giulian.baez": 75,
    "salma.marquez": 50,
    "michelle.robles": 50,
    "april.wilson": 50,
    "evan.larson": None,
}


@router.get("/natgen-promo-progress")
def natgen_promo_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Progress tracker for the NatGen Summer Promo.

    Counts NatGen policies where BOTH sale_date AND effective_date fall inside
    the promo window (April 20 - September 30, 2026). Returns individual
    progress for the four promo participants plus the team total.

    Visible to all authenticated users. Role-based visibility of *other
    producers' numbers* is handled on the frontend so every team member can
    see the leaderboard.
    """
    from sqlalchemy import func

    window_start = datetime.strptime(NATGEN_PROMO_WINDOW_START, "%Y-%m-%d")
    window_end = datetime.strptime(NATGEN_PROMO_WINDOW_END, "%Y-%m-%d") + timedelta(days=1)  # inclusive

    # Load the promo participants up front
    participants = (
        db.query(User)
        .filter(func.lower(User.username).in_(list(NATGEN_PROMO_PRODUCER_GOALS.keys())))
        .all()
    )

    # Base filter: NatGen, in window on BOTH sale_date and effective_date
    base_query = (
        db.query(Sale.producer_id, func.count(Sale.id))
        .filter(Sale.carrier == "National General")
        .filter(Sale.sale_date >= window_start)
        .filter(Sale.sale_date < window_end)
        .filter(Sale.effective_date >= window_start)
        .filter(Sale.effective_date < window_end)
        .group_by(Sale.producer_id)
    )
    counts_by_producer = {pid: cnt for pid, cnt in base_query.all()}

    producers_out = []
    for p in participants:
        # goal of None means "in leaderboard but no personal target"
        goal = NATGEN_PROMO_PRODUCER_GOALS.get((p.username or "").lower(), 0)
        current = counts_by_producer.get(p.id, 0)
        has_goal = goal is not None and goal > 0
        pct = round((current / goal) * 100, 1) if has_goal else None
        producers_out.append({
            "id": p.id,
            "name": p.full_name or p.username,
            "username": p.username,
            "goal": goal,  # int or None
            "current": current,
            "pct": min(pct, 100.0) if pct is not None else None,
            "hit_goal": (current >= goal) if has_goal else False,
        })

    # Sort by current descending so the leaderboard ranks by production
    producers_out.sort(key=lambda x: (-x["current"], x["name"]))

    # Team total includes ALL NatGen sales in window, not just the 4 promo participants —
    # because if Evan or anyone else writes one, it still contributes to the office goal.
    # Per Evan's latest instruction the team goal is 250 total NatGen policies.
    team_total_query = (
        db.query(func.count(Sale.id))
        .filter(Sale.carrier == "National General")
        .filter(Sale.sale_date >= window_start)
        .filter(Sale.sale_date < window_end)
        .filter(Sale.effective_date >= window_start)
        .filter(Sale.effective_date < window_end)
    )
    team_current = team_total_query.scalar() or 0
    team_pct = round((team_current / NATGEN_PROMO_TEAM_GOAL) * 100, 1) if NATGEN_PROMO_TEAM_GOAL else 0

    return {
        "window": {
            "start": NATGEN_PROMO_WINDOW_START,
            "end": NATGEN_PROMO_WINDOW_END,
        },
        "team_goal": NATGEN_PROMO_TEAM_GOAL,
        "team_current": team_current,
        "team_pct": min(team_pct, 100.0),
        "team_hit_goal": team_current >= NATGEN_PROMO_TEAM_GOAL,
        "producers": producers_out,
    }



@router.post("/merge-duplicate-policies")
def merge_duplicate_policies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find and merge sales that share the same base policy number + client + effective date.
    
    e.g. 2033884202 (home) + 2033884202-AUT (auto) → one bundled sale with line items.
    Admin only.
    """
    import re
    from app.models.sale import SaleLineItem

    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    def _base_policy(pn: str) -> str:
        return re.sub(r'[-\s]+(AUT|HOM|HOME|AUTO|RNT|RENT|01|02|03|04|05)$', '', pn.upper()).strip()

    all_sales = db.query(Sale).order_by(Sale.id).limit(10000).all()  # Capped for safety

    from collections import defaultdict
    groups = defaultdict(list)
    for s in all_sales:
        base = _base_policy(s.policy_number or "")
        client = (s.client_name or "").upper().strip()
        eff = str(s.effective_date)[:10] if s.effective_date else ""
        carrier = (s.carrier or "").upper().strip()
        key = (base, client, eff, carrier)
        groups[key].append(s)

    merged = []
    for key, group_sales in groups.items():
        if len(group_sales) < 2:
            continue

        # Pick the sale whose policy_number IS the base as primary (avoids unique constraint)
        base_pn = key[0]  # the base policy number from grouping key
        group_sales.sort(key=lambda s: (0 if s.policy_number.upper().strip() == base_pn else 1, s.id))
        primary = group_sales[0]

        # Skip if primary already has line items (already merged)
        existing_lines = db.query(SaleLineItem).filter(SaleLineItem.sale_id == primary.id).count()
        if existing_lines > 0:
            continue

        total_premium = 0
        total_items = 0
        for s in group_sales:
            base = _base_policy(s.policy_number or "")
            suffix = (s.policy_number or "").upper().replace(base, "").strip(" -")
            li = SaleLineItem(
                sale_id=primary.id,
                policy_type=s.policy_type or "other",
                policy_suffix=suffix or None,
                premium=float(s.written_premium or 0),
                description=f"{(s.policy_type or 'other').replace('_', ' ').title()} — {s.policy_number}",
            )
            db.add(li)
            total_premium += float(s.written_premium or 0)
            total_items += (s.item_count or 1)

        primary.policy_type = "bundled"
        primary.written_premium = total_premium
        primary.recognized_premium = total_premium
        primary.item_count = total_items
        # Only rename if it's not already the base
        if primary.policy_number.upper().strip() != base_pn:
            # Check no other sale has this base number
            conflict = db.query(Sale).filter(Sale.policy_number == base_pn, Sale.id != primary.id).first()
            if not conflict:
                primary.policy_number = base_pn

        deleted_ids = []
        for s in group_sales[1:]:
            deleted_ids.append(s.id)
            db.delete(s)

        merged.append({
            "primary_id": primary.id,
            "policy_number": primary.policy_number,
            "client": primary.client_name,
            "merged_count": len(group_sales),
            "total_premium": total_premium,
            "deleted_sale_ids": deleted_ids,
        })

    db.commit()

    return {
        "merged_groups": len(merged),
        "details": merged,
    }
@router.get("/{sale_id}", response_model=SaleSchema)
def get_sale(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific sale"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found"
        )
    
    # Producers can only view their own sales
    if current_user.role == "producer" and sale.producer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this sale"
        )
    
    return sale


@router.patch("/{sale_id}", response_model=SaleSchema)
def update_sale(
    sale_id: int,
    sale_update: SaleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a sale"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found"
        )
    
    # Producers can only update their own sales
    if current_user.role == "producer" and sale.producer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this sale"
        )
    
    # Only admin/manager can change producer_id (reassign sales)
    update_data = sale_update.model_dump(exclude_unset=True)
    if "producer_id" in update_data and update_data["producer_id"] is not None:
        if current_user.role.lower() not in ("admin", "manager"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin/manager can reassign sales to another producer"
            )
        logger.info(f"Sale {sale_id} reassigned from producer {sale.producer_id} to {update_data['producer_id']} by {current_user.full_name}")

    # Update fields
    for field, value in update_data.items():
        setattr(sale, field, value)
    
    db.commit()
    db.refresh(sale)
    
    return sale


@router.post("/{sale_id}/upload-application")
async def upload_application(
    sale_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload application PDF for a sale"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found"
        )
    
    if current_user.role == "producer" and sale.producer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized"
        )
    
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )
    
    # Read file bytes
    pdf_bytes = await file.read()
    
    # Save to filesystem (best-effort, may not survive deploys)
    upload_dir = Path(settings.UPLOAD_DIR) / "applications"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"sale_{sale_id}_{file.filename}"
    with file_path.open("wb") as buffer:
        buffer.write(pdf_bytes)
    
    # Save to database (survives deploys)
    sale.application_pdf_path = str(file_path)
    sale.application_pdf_data = pdf_bytes
    sale.application_pdf_name = file.filename
    db.commit()
    
    return {
        "message": "File uploaded successfully",
        "file_path": str(file_path),
        "sale_id": sale_id
    }


@router.delete("/{sale_id}")
def delete_sale(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a sale (admin can delete any, producers can delete their own)"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found"
        )
    
    # Producers can only delete their own sales
    if current_user.role == "producer" and sale.producer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this sale"
        )
    
    # Clean up related records first to avoid FK violations
    from sqlalchemy import text
    try:
        db.execute(text("DELETE FROM survey_responses WHERE sale_id = :sid"), {"sid": sale_id})
        db.execute(text("DELETE FROM sale_line_items WHERE sale_id = :sid"), {"sid": sale_id})
        db.execute(text("DELETE FROM life_cross_sells WHERE sale_id = :sid"), {"sid": sale_id})
    except Exception:
        pass  # Tables might not exist
    
    # Nullify statement line references
    try:
        db.execute(text("UPDATE statement_lines SET matched_sale_id = NULL WHERE matched_sale_id = :sid"), {"sid": sale_id})
    except Exception:
        pass
    
    db.delete(sale)
    db.commit()
    
    return {"message": "Sale deleted successfully"}


@router.post("/{sale_id}/send-for-signature")
async def send_for_signature_endpoint(
    sale_id: int,
    file: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a BoldSign embedded request for e-signature.

    Uploads the PDF to BoldSign and returns a URL where the agent
    can place signature fields manually, then hit Send.
    The frontend should open this URL in a new tab.
    """
    import logging
    logger = logging.getLogger(__name__)

    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if current_user.role == "producer" and sale.producer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not sale.client_email:
        raise HTTPException(status_code=400, detail="Client email is required to send for signature")

    # Get PDF bytes — from upload, saved path, or database blob
    pdf_bytes = None
    if file and file.filename:
        logger.info(f"Reading uploaded file: {file.filename}, size={file.size}")
        pdf_bytes = await file.read()
        logger.info(f"Read {len(pdf_bytes)} bytes from upload")
        # Also save to DB for future use
        sale.application_pdf_data = pdf_bytes
        sale.application_pdf_name = file.filename
        sale.application_pdf_path = file.filename
        db.commit()
    elif sale.application_pdf_path:
        pdf_path = Path(sale.application_pdf_path)
        logger.info(f"Trying saved path: {pdf_path}, exists={pdf_path.exists()}")
        if pdf_path.exists():
            pdf_bytes = pdf_path.read_bytes()
    
    # Fall back to database-stored PDF (survives Render deploys)
    if not pdf_bytes and sale.application_pdf_data:
        logger.info(f"Using DB-stored PDF ({len(sale.application_pdf_data)} bytes)")
        pdf_bytes = sale.application_pdf_data

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="No PDF available. Please upload the application PDF when clicking Send for Signature.")

    logger.info(f"Creating signature request: sale_id={sale_id}, client={sale.client_name}, email={sale.client_email}, pdf_size={len(pdf_bytes)}")

    try:
        from app.services.esign import create_signature_request

        title = f"Insurance Application - {sale.client_name}"
        result = await create_signature_request(
            pdf_bytes=pdf_bytes,
            signer_name=sale.client_name,
            signer_email=sale.client_email,
            title=title,
            carrier=sale.carrier,
        )

        logger.info(f"BoldSign embedded request created: {result}")

        # Update sale — status is "draft" until agent places fields and clicks Send
        sale.signature_request_id = result.get("documentId")
        sale.signature_status = "draft"
        db.commit()

        return {
            "message": "Document ready — place signature fields and click Send",
            "document_id": result.get("documentId"),
            "send_url": result.get("sendUrl"),
            "signer_email": sale.client_email,
        }

    except ValueError as e:
        logger.error(f"BoldSign ValueError: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"BoldSign Exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create signature request: {str(e)}")


# In-process cache for BoldSign status checks.
# Keyed by signature_request_id → (unix_ts, status_string).
# Prevents mass-polling (e.g., sales page rendering 25+ cards on mount) from
# fanning out parallel BoldSign API calls and exhausting the DB pool.
# Terminal states cached longer since they can't change.
import time as _time
_SIG_STATUS_CACHE: dict[str, tuple[float, str]] = {}
_SIG_STATUS_TTL_ACTIVE = 30.0   # seconds — for "sent"/"draft"
_SIG_STATUS_TTL_TERMINAL = 3600.0  # seconds — for "completed"/"declined"


def _sig_cache_ttl_for(status: str) -> float:
    return _SIG_STATUS_TTL_TERMINAL if status in ("completed", "declined") else _SIG_STATUS_TTL_ACTIVE


@router.get("/{sale_id}/signature-status")
async def get_signature_status(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check the status of a signature request.

    CRITICAL: Releases the DB connection BEFORE calling BoldSign so that a
    slow/hung external API call cannot hold a pooled DB connection. Previously,
    a burst of ~25 parallel calls from the sales page on mount could drain the
    entire pool (8 + 15 overflow = 23) and 502 the whole service.
    """
    # --- Phase 1: quick DB read, then release the connection --------------
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    signature_request_id = sale.signature_request_id
    current_status = sale.signature_status

    if not signature_request_id:
        return {"status": "not_sent", "message": "No signature request sent yet"}

    # Short-circuit on terminal states — no need to hit BoldSign ever again
    if current_status in ("completed", "declined"):
        return {
            "status": current_status,
            "document_id": signature_request_id,
            "cached": True,
        }

    # Check in-process cache before reaching out to BoldSign
    cached = _SIG_STATUS_CACHE.get(signature_request_id)
    if cached:
        ts, cached_status = cached
        if (_time.time() - ts) < _sig_cache_ttl_for(cached_status):
            return {
                "status": cached_status,
                "document_id": signature_request_id,
                "cached": True,
            }

    # Release the DB session before the external call. FastAPI's Depends()
    # will still call db.close() at the end of the request, but closing early
    # returns the connection to the pool NOW so BoldSign latency doesn't block
    # every other endpoint in the service.
    db.close()

    # --- Phase 2: external BoldSign call without holding a DB connection --
    try:
        from app.services.esign import get_document_status
        doc_status = await get_document_status(signature_request_id)
        bs_status = doc_status.get("status", "").lower()
    except Exception as e:
        logger.warning(f"BoldSign status check failed for sale {sale_id}: {e}")
        return {"status": current_status, "error": str(e)}

    if bs_status in ("completed", "signed"):
        new_status = "completed"
    elif bs_status in ("declined", "revoked", "expired"):
        new_status = "declined"
    elif bs_status in ("inprogress", "sent", "pending"):
        new_status = "sent"
    else:
        new_status = current_status

    # Cache before we try to write — even if the DB write fails we've still
    # served a fresh answer to this caller and nearby callers won't re-poll.
    _SIG_STATUS_CACHE[signature_request_id] = (_time.time(), new_status)

    # --- Phase 3: short-lived write session, only if status actually changed
    if new_status != current_status:
        write_db = SessionLocal()
        try:
            sale_row = write_db.query(Sale).filter(Sale.id == sale_id).first()
            if sale_row is not None:
                sale_row.signature_status = new_status
                write_db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist signature status for sale {sale_id}: {e}")
            write_db.rollback()
        finally:
            write_db.close()

    return {
        "status": new_status,
        "boldsign_status": bs_status,
        "document_id": signature_request_id,
    }


@router.post("/signature-statuses")
async def get_signature_statuses_batch(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Batch signature-status read — DB only, no BoldSign calls.

    The sales page uses this on mount to hydrate status badges for many sale
    cards in a single round-trip. For the live freshness check, the per-card
    UI can still call GET /{sale_id}/signature-status (which goes to BoldSign,
    but is cached + pool-safe).

    Body: {"ids": [1, 2, 3, ...]}  (max 200 ids per call)
    Returns: {"statuses": {"1": "sent", "2": "completed", ...}}
    """
    ids = payload.get("ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="ids must be a list")
    # Cap batch size so a runaway client can't pull the whole sales table
    ids = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()][:200]
    if not ids:
        return {"statuses": {}}

    rows = (
        db.query(Sale.id, Sale.signature_status)
        .filter(Sale.id.in_(ids))
        .all()
    )
    return {"statuses": {str(sid): (status or "not_sent") for sid, status in rows}}


@router.post("/{sale_id}/remind-signature")
async def remind_signature_endpoint(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Push BoldSign to resend the existing signature request email.

    Unlike /send-for-signature (which creates a fresh document and
    requires re-placing signature fields), this endpoint just asks
    BoldSign to re-notify the signer on the SAME document that was
    already prepared and sent. No PDF re-upload, no new prepare page.

    Preconditions:
    - Sale must have a signature_request_id from a prior send.
    - BoldSign document must still be in a pending state (sent/in-progress).

    BoldSign rate limit: only one manual reminder per document per day.
    """
    import logging
    logger = logging.getLogger(__name__)

    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if current_user.role == "producer" and sale.producer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not sale.signature_request_id:
        raise HTTPException(
            status_code=400,
            detail="No existing signature request to remind — use Send for Signature first.",
        )

    if not sale.client_email:
        raise HTTPException(status_code=400, detail="Client email is missing")

    # If the doc is already completed/declined/revoked, a reminder won't help.
    # The /send-for-signature path should be used for those cases.
    if sale.signature_status in ("completed", "declined"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot remind — document is {sale.signature_status}. "
                   f"Use Send for Signature to start a new request.",
        )

    try:
        from app.services.esign import remind_document

        message = (
            f"Hi {sale.client_name or 'there'}, "
            f"just a quick reminder to sign your {sale.carrier or 'insurance'} "
            f"application when you have a moment. Thanks!"
        )

        result = await remind_document(
            document_id=sale.signature_request_id,
            receiver_emails=[sale.client_email],
            message=message,
        )

        # Bump status back to "sent" if it was lingering as "draft" for some reason
        if sale.signature_status == "draft":
            sale.signature_status = "sent"
            db.commit()

        logger.info(
            "BoldSign reminder sent: sale_id=%s doc_id=%s signer=%s",
            sale_id, sale.signature_request_id, sale.client_email,
        )

        return {
            "success": True,
            "message": "Reminder sent to signer",
            "document_id": sale.signature_request_id,
            "signer_email": sale.client_email,
        }

    except ValueError as e:
        # BoldSign returns 403 for "manual reminders limit reached" (also sometimes 400).
        # Surface a friendly rate-limit message to the user.
        err = str(e)
        err_lower = err.lower()
        logger.warning("BoldSign reminder failed: %s", err)
        # Detect the daily-limit response regardless of whether BoldSign tagged it 400 or 403.
        is_rate_limit = (
            ("403" in err or "400" in err)
            and (
                "reminder" in err_lower
                or "reminders limit" in err_lower
                or "already" in err_lower
                or "today" in err_lower
                or "per day" in err_lower
            )
        )
        if is_rate_limit:
            raise HTTPException(
                status_code=429,
                detail="BoldSign only allows one reminder per document per day. Try again tomorrow.",
            )
        raise HTTPException(status_code=400, detail=err)
    except Exception as e:
        logger.error("BoldSign reminder error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reminder failed: {str(e)}")

