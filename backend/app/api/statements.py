from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.statement import StatementImport, StatementFormat, CarrierType
from app.services.statement_import import StatementImportService
from app.core.config import settings

router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.post("/upload")
async def upload_statement(
    carrier: CarrierType,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a commission statement file"""
    # Only admins can upload statements
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Manager access required"
        )
    
    # Determine file format
    file_extension = Path(file.filename).suffix.lower()
    
    if file_extension == '.csv':
        file_format = StatementFormat.CSV
    elif file_extension in ['.xlsx', '.xls']:
        file_format = StatementFormat.XLSX
    elif file_extension == '.pdf':
        file_format = StatementFormat.PDF
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Use CSV, XLSX, or PDF"
        )
    
    # Create upload directory
    upload_dir = Path(settings.UPLOAD_DIR) / "statements"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Save file
    file_path = upload_dir / file.filename
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Get file size
    file_size = file_path.stat().st_size
    
    # Create import record
    service = StatementImportService(db)
    import_record = service.create_import_record(
        filename=file.filename,
        file_path=str(file_path),
        carrier=carrier,
        file_format=file_format,
        file_size=file_size
    )
    
    return {
        "message": "File uploaded successfully",
        "import_id": import_record.id,
        "filename": file.filename,
        "carrier": carrier,
        "format": file_format
    }


@router.post("/{import_id}/process")
def process_statement(
    import_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process an uploaded statement"""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Manager access required"
        )
    
    service = StatementImportService(db)
    
    try:
        import_record = service.process_import(import_id)
        
        return {
            "message": "Statement processed",
            "import_id": import_record.id,
            "status": import_record.status,
            "total_rows": import_record.total_rows,
            "matched_rows": import_record.matched_rows,
            "unmatched_rows": import_record.unmatched_rows,
            "error_rows": import_record.error_rows
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing failed: {str(e)}"
        )


@router.get("/", response_model=List[dict])
def list_statement_imports(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all statement imports"""
    imports = db.query(StatementImport).order_by(
        StatementImport.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return [
        {
            "id": imp.id,
            "filename": imp.filename,
            "carrier": imp.carrier,
            "status": imp.status,
            "total_rows": imp.total_rows,
            "matched_rows": imp.matched_rows,
            "unmatched_rows": imp.unmatched_rows,
            "created_at": imp.created_at
        }
        for imp in imports
    ]


@router.get("/{import_id}")
def get_statement_import(
    import_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get details of a specific statement import"""
    import_record = db.query(StatementImport).filter(
        StatementImport.id == import_id
    ).first()
    
    if not import_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import not found"
        )
    
    from app.models.statement import StatementLine
    
    # Get sample unmatched lines
    unmatched_lines = db.query(StatementLine).filter(
        StatementLine.statement_import_id == import_id,
        StatementLine.is_matched == False
    ).limit(10).all()
    
    return {
        "id": import_record.id,
        "filename": import_record.filename,
        "carrier": import_record.carrier,
        "status": import_record.status,
        "total_rows": import_record.total_rows,
        "matched_rows": import_record.matched_rows,
        "unmatched_rows": import_record.unmatched_rows,
        "error_rows": import_record.error_rows,
        "processing_started_at": import_record.processing_started_at,
        "processing_completed_at": import_record.processing_completed_at,
        "error_message": import_record.error_message,
        "sample_unmatched": [
            {
                "policy_number": line.policy_number,
                "premium_amount": str(line.premium_amount) if line.premium_amount else None,
                "commission_amount": str(line.commission_amount) if line.commission_amount else None
            }
            for line in unmatched_lines
        ]
    }
