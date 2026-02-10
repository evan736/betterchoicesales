"""Commission reconciliation API endpoints.

Workflow:
  POST /api/reconciliation/upload     → Upload carrier statement
  POST /api/reconciliation/{id}/match → Run auto-matching
  POST /api/reconciliation/{id}/calculate → Calculate agent commissions
  GET  /api/reconciliation/{id}       → Get reconciliation summary
  GET  /api/reconciliation/           → List all imports
  POST /api/reconciliation/lines/{id}/match → Manually match a line
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.statement import StatementImport, StatementStatus
from app.services.reconciliation import ReconciliationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.post("/upload")
async def upload_statement(
    file: UploadFile = File(...),
    carrier: str = Form(...),
    period: str = Form(...),  # "2026-01"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a carrier commission statement for reconciliation."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    # Validate carrier
    valid_carriers = [
        "national_general", "progressive", "grange",
        "safeco", "travelers", "hartford", "other",
    ]
    if carrier not in valid_carriers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid carrier. Must be one of: {valid_carriers}",
        )

    # Read file
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save file
    upload_dir = os.path.join(settings.UPLOAD_DIR, "statements")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{period}_{carrier}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Parse
    service = ReconciliationService(db)
    try:
        imp = service.create_import(
            filename=file.filename,
            file_path=file_path,
            file_bytes=file_bytes,
            carrier=carrier,
            period=period,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)[:300]}")

    return {
        "id": imp.id,
        "filename": imp.filename,
        "carrier": imp.carrier,
        "period": imp.statement_period,
        "status": imp.status.value,
        "total_rows": imp.total_rows,
        "total_premium": float(imp.total_premium or 0),
        "total_commission": float(imp.total_commission or 0),
    }


@router.post("/{import_id}/match")
def run_matching(
    import_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run auto-matching on a processed statement."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    service = ReconciliationService(db)
    try:
        result = service.run_matching(import_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return result


@router.post("/{import_id}/calculate")
def calculate_commissions(
    import_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calculate agent commissions based on tier from prior month."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    service = ReconciliationService(db)
    try:
        result = service.calculate_agent_commissions(import_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return result


@router.get("/{import_id}")
def get_reconciliation(
    import_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full reconciliation summary with matched/unmatched lines."""
    service = ReconciliationService(db)
    try:
        return service.get_reconciliation_summary(import_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/")
def list_imports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all statement imports."""
    imports = (
        db.query(StatementImport)
        .order_by(StatementImport.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": imp.id,
            "filename": imp.filename,
            "carrier": imp.carrier,
            "period": imp.statement_period,
            "status": imp.status.value,
            "total_rows": imp.total_rows,
            "matched_rows": imp.matched_rows,
            "unmatched_rows": imp.unmatched_rows,
            "total_premium": float(imp.total_premium or 0),
            "total_commission": float(imp.total_commission or 0),
            "created_at": imp.created_at.isoformat() if imp.created_at else None,
        }
        for imp in imports
    ]


@router.post("/lines/{line_id}/match")
def manually_match_line(
    line_id: int,
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually match an unmatched statement line to a sale."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    service = ReconciliationService(db)
    try:
        line = service.manually_match_line(line_id, sale_id)
        return {"success": True, "line_id": line.id, "matched_sale_id": sale_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/monthly-pay/{period}")
def calculate_monthly_pay(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Calculate combined agent pay across ALL carriers for a given month.
    
    Period format: "2026-01"
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    service = ReconciliationService(db)
    try:
        return service.calculate_monthly_pay(period)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/monthly-pay/{period}")
def get_monthly_pay(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get combined agent pay summary for a month."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    service = ReconciliationService(db)
    try:
        return service.get_monthly_pay_summary(period)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/agent-sheet/{period}/{agent_id}")
def get_agent_commission_sheet(
    period: str,
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed commission sheet for a specific agent for a period."""
    if current_user.role.lower() not in ("admin", "manager") and current_user.id != agent_id:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ReconciliationService(db)
    return service.get_agent_commission_sheet(period, agent_id)


@router.get("/agent-sheet/{period}/{agent_id}/pdf")
def download_agent_commission_pdf(
    period: str,
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download PDF commission sheet for a specific agent."""
    if current_user.role.lower() not in ("admin", "manager") and current_user.id != agent_id:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ReconciliationService(db)
    sheet_data = service.get_agent_commission_sheet(period, agent_id)

    from app.services.commission_pdf import generate_commission_pdf
    from fastapi.responses import Response

    pdf_bytes = generate_commission_pdf(sheet_data)

    filename = f"Commission_Sheet_{sheet_data['agent_name'].replace(' ', '_')}_{period}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
