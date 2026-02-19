"""Commission reconciliation API endpoints.

IMPORTANT: Specific path routes (agent-sheet, monthly-pay, lines, upload)
must be defined BEFORE the catch-all /{import_id} routes, otherwise
FastAPI will try to match "agent-sheet" as an integer import_id.
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


# ── Specific-path routes FIRST ───────────────────────────────────────

@router.post("/upload")
async def upload_statement(
    file: UploadFile = File(...),
    carrier: str = Form(...),
    period: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a carrier commission statement for reconciliation."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    valid_carriers = [
        "national_general", "progressive", "grange",
        "safeco", "travelers", "geico", "first_connect",
        "universal", "nbs", "hartford", "other",
    ]
    if carrier not in valid_carriers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid carrier. Must be one of: {valid_carriers}",
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    from app.services.carrier_parsers import detect_carrier
    detected = detect_carrier(file_bytes, file.filename)
    actual_carrier = carrier
    carrier_overridden = False
    if detected and detected != carrier:
        logger.warning(f"Carrier override: user selected '{carrier}' but detected '{detected}'")
        actual_carrier = detected
        carrier_overridden = True

    upload_dir = os.path.join(settings.UPLOAD_DIR, "statements")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{period}_{actual_carrier}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    service = ReconciliationService(db)
    try:
        imp = service.create_import(
            filename=file.filename,
            file_path=file_path,
            file_bytes=file_bytes,
            carrier=actual_carrier,
            period=period,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)[:300]}")

    result = {
        "id": imp.id,
        "filename": imp.filename,
        "carrier": imp.carrier,
        "period": imp.statement_period,
        "status": imp.status.value,
        "total_rows": imp.total_rows,
        "total_premium": float(imp.total_premium or 0),
        "total_commission": float(imp.total_commission or 0),
    }
    if carrier_overridden:
        result["carrier_detected"] = detected
        result["carrier_selected"] = carrier
        result["carrier_overridden"] = True

    return result


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
    """Calculate combined agent pay across ALL carriers for a given month."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    service = ReconciliationService(db)
    try:
        return service.calculate_monthly_pay(period)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import logging, traceback
        logging.error(f"Monthly pay calc error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Calculation error: {type(e).__name__}: {str(e)[:300]}")


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
    rate_adjustment: float = 0.0,
    bonus: float = 0.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed commission sheet for a specific agent for a period.
    
    rate_adjustment: Manual override adjustment to commission rate (+/-0.005 = +/-0.5%)
    bonus: Flat dollar bonus to add to commission total
    """
    if current_user.role.lower() not in ("admin", "manager") and current_user.id != agent_id:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ReconciliationService(db)
    try:
        return service.get_agent_commission_sheet(period, agent_id, rate_adjustment=rate_adjustment, bonus=bonus)
    except Exception as e:
        import traceback
        logging.error(f"Agent sheet error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Agent sheet error: {type(e).__name__}: {str(e)[:300]}")


@router.get("/agent-sheet/{period}/{agent_id}/pdf")
def download_agent_commission_pdf(
    period: str,
    agent_id: int,
    rate_adjustment: float = 0.0,
    bonus: float = 0.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download PDF commission sheet for a specific agent."""
    if current_user.role.lower() not in ("admin", "manager") and current_user.id != agent_id:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ReconciliationService(db)
    sheet_data = service.get_agent_commission_sheet(period, agent_id, rate_adjustment=rate_adjustment, bonus=bonus)

    from app.services.commission_pdf import generate_commission_pdf
    from fastapi.responses import Response

    pdf_bytes = generate_commission_pdf(sheet_data)

    filename = f"Commission_Sheet_{sheet_data['agent_name'].replace(' ', '_')}_{period}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Parameterized {import_id} routes LAST ────────────────────────────

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


@router.delete("/{import_id}")
def delete_import(
    import_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a statement import and all its lines."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    imp = db.query(StatementImport).filter(StatementImport.id == import_id).first()
    if not imp:
        raise HTTPException(status_code=404, detail="Import not found")

    from app.models.statement import StatementLine
    db.query(StatementLine).filter(
        StatementLine.statement_import_id == import_id
    ).delete()
    db.delete(imp)
    db.commit()

    logger.info(f"Deleted import {import_id} ({imp.carrier} / {imp.statement_period})")
    return {"success": True, "deleted_id": import_id}


@router.get("/debug-agent-lines/{period}/{agent_id}")
def debug_agent_lines(
    period: str,
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Debug: show all statement lines for an agent with effective_date info."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")

    from app.models.statement import StatementImport, StatementLine
    from app.models.sale import Sale

    imports = db.query(StatementImport).filter(
        StatementImport.statement_period == period
    ).all()
    import_ids = [imp.id for imp in imports]

    lines = db.query(StatementLine).filter(
        StatementLine.statement_import_id.in_(import_ids),
        StatementLine.assigned_agent_id == agent_id,
        StatementLine.is_matched == True,
    ).all()

    results = []
    null_eff_count = 0
    for line in lines:
        eff = None
        eff_source = None
        if line.effective_date:
            eff = str(line.effective_date)[:10]
            eff_source = "line"
        elif line.matched_sale_id:
            sale = db.query(Sale).filter(Sale.id == line.matched_sale_id).first()
            if sale and sale.effective_date:
                eff = str(sale.effective_date)[:10]
                eff_source = "sale"

        sale_eff = None
        if line.matched_sale_id:
            sale = db.query(Sale).filter(Sale.id == line.matched_sale_id).first()
            if sale and sale.effective_date:
                sale_eff = str(sale.effective_date)[:10]

        if not eff and not sale_eff:
            null_eff_count += 1

        imp = next((i for i in imports if i.id == line.statement_import_id), None)
        results.append({
            "id": line.id,
            "carrier": imp.carrier if imp else "?",
            "policy_number": line.policy_number,
            "insured_name": line.insured_name,
            "tx_type": line.transaction_type,
            "premium": float(line.premium_amount or 0),
            "effective_date": eff,
            "eff_source": eff_source,
            "sale_effective_date": sale_eff,
            "term_months": getattr(line, 'term_months', None),
        })

    return {
        "agent_id": agent_id,
        "period": period,
        "total_lines": len(results),
        "null_effective_date_count": null_eff_count,
        "lines": sorted(results, key=lambda x: x["carrier"]),
    }
