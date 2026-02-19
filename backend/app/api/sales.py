from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import extract as sql_extract, func
from pathlib import Path
import shutil
from datetime import datetime, date
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale, SaleStatus
from app.schemas.sale import SaleCreate, Sale as SaleSchema, SaleUpdate
from app.core.config import settings

router = APIRouter(prefix="/api/sales", tags=["sales"])

# Carrier name normalization — maps alternate names to canonical carrier names
CARRIER_NORMALIZE = {
    "obsidian": "Steadily",
    "obsedian": "Steadily",
    "obsidian insurance": "Steadily",
    "obsedian insurance": "Steadily",
    "trustgard": "Grange",
    "trust gard": "Grange",
    "trustgard mutual": "Grange",
    "integon": "National General",
    "integon national": "National General",
    "integon national insurance": "National General",
    "integon national insurance company": "National General",
    "upcic": "Universal Property",
    "amig": "American Modern",
}


def _normalize_carrier(carrier: str) -> str:
    """Normalize carrier name to canonical form."""
    if not carrier:
        return carrier
    key = carrier.strip().lower()
    return CARRIER_NORMALIZE.get(key, carrier.strip())


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


def _trigger_hooray_email(sale: Sale, producer: User, db: Session):
    """Send Hooray notification to all producers in background after sale creation."""
    import threading
    import logging
    logger = logging.getLogger(__name__)

    if not settings.MAILGUN_API_KEY:
        logger.info("Mailgun not configured — skipping hooray email")
        return

    def _send():
        try:
            from app.services.hooray_email import send_hooray_email
            from app.core.database import SessionLocal
            new_db = SessionLocal()
            try:
                result = send_hooray_email(
                    sale=sale,
                    producer_name=producer.full_name if producer else "Team Member",
                    db=new_db,
                )
                if result.get("success"):
                    logger.info(f"Hooray email sent for sale {sale.id} to {result.get('recipients', 0)} recipients")
                else:
                    logger.warning(f"Hooray email failed for sale {sale.id}: {result}")
            finally:
                new_db.close()
        except Exception as e:
            logger.error(f"Hooray email error for sale {sale.id}: {e}")

    # Fire and forget in background thread
    threading.Thread(target=_send, daemon=True).start()


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
    sale.carrier = _normalize_carrier(sale.carrier)

    db.add(sale)
    db.commit()
    db.refresh(sale)

    # Welcome email is now sent manually from the frontend after save,
    # so the agent can choose whether to attach a PDF.

    # Send Hooray notification to all producers
    _trigger_hooray_email(sale, current_user, db)

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
    sale.carrier = _normalize_carrier(sale.carrier)
    
    db.add(sale)
    db.commit()
    db.refresh(sale)
    
    # Welcome email is now sent manually from the frontend after save,
    # so the agent can choose whether to attach a PDF.
    
    # Send Hooray notification to all producers
    _trigger_hooray_email(sale, current_user, db)
    
    return sale


@router.get("/", response_model=List[SaleSchema])
def list_sales(
    skip: int = 0,
    limit: int = 5000,
    date_from: str = None,  # "2026-01-01"
    date_to: str = None,    # "2026-01-31"
    producer_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List sales - producers see only their own, admins see all"""
    query = db.query(Sale)
    
    if current_user.role.lower() == "producer" or current_user.role.lower() == "retention_specialist":
        query = query.filter(Sale.producer_id == current_user.id)
    elif producer_id:
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
    return sales


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
    
    # Update fields
    for field, value in sale_update.model_dump(exclude_unset=True).items():
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
    
    # Create upload directory if it doesn't exist
    upload_dir = Path(settings.UPLOAD_DIR) / "applications"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Save file
    file_path = upload_dir / f"sale_{sale_id}_{file.filename}"
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update sale record
    sale.application_pdf_path = str(file_path)
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

    # Get PDF bytes — from upload or saved path
    pdf_bytes = None
    if file and file.filename:
        logger.info(f"Reading uploaded file: {file.filename}, size={file.size}")
        pdf_bytes = await file.read()
        logger.info(f"Read {len(pdf_bytes)} bytes from upload")
    elif sale.application_pdf_path:
        pdf_path = Path(sale.application_pdf_path)
        logger.info(f"Trying saved path: {pdf_path}, exists={pdf_path.exists()}")
        if pdf_path.exists():
            pdf_bytes = pdf_path.read_bytes()

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


@router.get("/{sale_id}/signature-status")
async def get_signature_status(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check the status of a signature request."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if not sale.signature_request_id:
        return {"status": "not_sent", "message": "No signature request sent yet"}

    try:
        from app.services.esign import get_document_status
        doc_status = await get_document_status(sale.signature_request_id)

        bs_status = doc_status.get("status", "").lower()
        if bs_status in ("completed", "signed"):
            sale.signature_status = "completed"
        elif bs_status in ("declined", "revoked", "expired"):
            sale.signature_status = "declined"
        elif bs_status in ("inprogress", "sent", "pending"):
            sale.signature_status = "sent"
        db.commit()

        return {
            "status": sale.signature_status,
            "boldsign_status": bs_status,
            "document_id": sale.signature_request_id,
        }
    except Exception as e:
        return {"status": sale.signature_status, "error": str(e)}


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

    return {
        "created": created,
        "skipped": skipped,
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
