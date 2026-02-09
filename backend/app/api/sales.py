from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.schemas.sale import SaleCreate, Sale as SaleSchema, SaleUpdate
from app.core.config import settings

router = APIRouter(prefix="/api/sales", tags=["sales"])


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
        producer_id=current_user.id
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
