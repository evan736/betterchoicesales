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


def determine_status(effective_date) -> SaleStatus:
    """Determine sale status based on effective date vs today."""
    if effective_date is None:
        return SaleStatus.ACTIVE
    if isinstance(effective_date, datetime):
        eff_date = effective_date.date()
    elif isinstance(effective_date, date):
        eff_date = effective_date
    else:
        return SaleStatus.ACTIVE
    
    today = date.today()
    if eff_date <= today:
        return SaleStatus.ACTIVE
    else:
        return SaleStatus.PENDING


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

    db.add(sale)
    db.commit()
    db.refresh(sale)

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
    
    db.add(sale)
    db.commit()
    db.refresh(sale)
    
    return sale


@router.get("/", response_model=List[SaleSchema])
def list_sales(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List sales - producers see only their own, admins see all"""
    query = db.query(Sale)
    
    if current_user.role == "producer":
        query = query.filter(Sale.producer_id == current_user.id)
    
    sales = query.offset(skip).limit(limit).all()
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
    """Send a sale's PDF application for electronic signature via BoldSign.
    Accepts optional file upload, or uses the saved application_pdf_path."""
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
        pdf_bytes = await file.read()
    elif sale.application_pdf_path:
        pdf_path = Path(sale.application_pdf_path)
        if pdf_path.exists():
            pdf_bytes = pdf_path.read_bytes()

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="No PDF available. Please upload the application PDF.")

    try:
        from app.services.esign import send_for_signature as boldsign_send

        title = f"Insurance Application - {sale.client_name} ({sale.policy_number})"
        result = await boldsign_send(
            pdf_bytes=pdf_bytes,
            signer_name=sale.client_name,
            signer_email=sale.client_email,
            title=title,
        )

        # Update sale with signature info
        sale.signature_request_id = result.get("documentId")
        sale.signature_status = "sent"
        db.commit()

        return {
            "message": "Signature request sent successfully",
            "document_id": result.get("documentId"),
            "signer_email": sale.client_email,
        }

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send for signature: {str(e)}")


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

        # Update local status based on BoldSign status
        bs_status = doc_status.get("status", "").lower()
        if bs_status in ("completed", "signed"):
            sale.signature_status = "completed"
        elif bs_status in ("declined", "revoked"):
            sale.signature_status = "declined"
        elif bs_status in ("inprogress", "sent"):
            sale.signature_status = "sent"
        db.commit()

        return {
            "status": sale.signature_status,
            "boldsign_status": bs_status,
            "document_id": sale.signature_request_id,
            "details": doc_status,
        }
    except Exception as e:
        return {"status": sale.signature_status, "error": str(e)}
