"""Payroll API — submit, lock, view history, and mark paid."""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.payroll import PayrollRecord, PayrollAgentLine
from app.services.reconciliation import ReconciliationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payroll", tags=["payroll"])


@router.post("/submit/{period}")
def submit_payroll(
    period: str,
    body: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit/finalize payroll for a month. Snapshots current monthly pay data with overrides."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Check if already submitted
    existing = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if existing and existing.is_locked:
        raise HTTPException(status_code=400, detail=f"Payroll for {period} is already locked. Use unlock first.")

    # Parse agent overrides: { "agent_id": { "rate_adjustment": 0.005, "bonus": 100 } }
    agent_overrides = (body or {}).get("agent_overrides", {})

    # Calculate monthly pay
    service = ReconciliationService(db)
    try:
        pay_data = service.calculate_monthly_pay(period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    year, month = map(int, period.split("-"))
    period_display = datetime(year, month, 1).strftime("%B %Y")

    # Delete existing draft if any
    if existing:
        db.query(PayrollAgentLine).filter(PayrollAgentLine.payroll_record_id == existing.id).delete()
        db.delete(existing)
        db.flush()

    # Apply overrides to agent summaries for the snapshot
    total_agent_pay = 0
    for agent in pay_data.get("agent_summaries", []):
        aid = str(agent["agent_id"])
        overrides = agent_overrides.get(aid, {})
        rate_adj = float(overrides.get("rate_adjustment", 0))
        bonus = float(overrides.get("bonus", 0))
        agent["rate_adjustment"] = rate_adj
        agent["bonus"] = bonus

        if rate_adj != 0:
            base_comm = agent.get("net_agent_commission", agent.get("total_agent_commission", 0))
            base_rate = agent.get("commission_rate", 0)
            if base_rate:
                commissionable_premium = base_comm / base_rate
                adjusted_comm = commissionable_premium * (base_rate + rate_adj)
                agent["adjusted_commission"] = round(adjusted_comm, 2)
            else:
                agent["adjusted_commission"] = base_comm
        else:
            agent["adjusted_commission"] = agent.get("net_agent_commission", agent.get("total_agent_commission", 0))

        agent["grand_total"] = round(agent["adjusted_commission"] + bonus, 2)
        total_agent_pay += agent["grand_total"]

    # Create payroll record
    record = PayrollRecord(
        period=period,
        period_display=period_display,
        status="submitted",
        submitted_at=datetime.utcnow(),
        submitted_by_id=current_user.id,
        is_locked=True,
        total_agents=len(pay_data.get("agent_summaries", [])),
        total_premium=pay_data.get("totals", {}).get("total_premium", 0),
        total_agent_pay=total_agent_pay,
        total_chargebacks=pay_data.get("totals", {}).get("total_chargebacks", 0),
        total_carriers=pay_data.get("totals", {}).get("total_carriers", 0),
        snapshot_data=pay_data,
    )
    db.add(record)
    db.flush()

    # Create per-agent lines
    for agent in pay_data.get("agent_summaries", []):
        line = PayrollAgentLine(
            payroll_record_id=record.id,
            agent_id=agent["agent_id"],
            agent_name=agent["agent_name"],
            agent_role=agent.get("agent_role", "producer"),
            tier_level=agent.get("tier_level", 1),
            commission_rate=agent.get("commission_rate", 0),
            total_premium=agent.get("total_premium", 0),
            new_business_premium=agent.get("new_business_premium", 0),
            total_agent_commission=agent.get("adjusted_commission", agent.get("total_agent_commission", 0)),
            chargebacks=agent.get("chargebacks", 0),
            chargeback_premium=agent.get("chargeback_premium", 0),
            chargeback_count=agent.get("chargeback_count", 0),
            net_agent_pay=agent.get("grand_total", agent.get("total_agent_commission", 0)),
            line_count=agent.get("line_count", 0),
            carrier_breakdown=agent.get("carrier_breakdown", []),
            rate_adjustment=agent.get("rate_adjustment", 0),
            bonus=agent.get("bonus", 0),
            grand_total=agent.get("grand_total", agent.get("total_agent_commission", 0)),
            commission_status="pending",
        )
        db.add(line)

    # Mark matched sales as commission pending for this period
    _update_sales_commission_status(db, pay_data, period, "pending")

    db.commit()

    return {
        "success": True,
        "payroll_id": record.id,
        "period": period,
        "period_display": period_display,
        "status": "submitted",
        "total_agents": record.total_agents,
        "total_agent_pay": float(record.total_agent_pay or 0),
    }


@router.post("/unlock/{period}")
def unlock_payroll(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin override: unlock a submitted payroll for re-calculation."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required to unlock payroll")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record found for this period")

    record.is_locked = False
    record.status = "draft"
    db.commit()

    return {"success": True, "period": period, "status": "draft", "is_locked": False}


@router.post("/mark-paid/{period}")
def mark_payroll_paid(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark entire payroll as paid — updates all agent lines and related sales."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record found for this period")

    now = datetime.utcnow()
    record.status = "paid"
    record.paid_at = now

    # Mark all agent lines as paid
    lines = db.query(PayrollAgentLine).filter(PayrollAgentLine.payroll_record_id == record.id).all()
    for line in lines:
        line.commission_status = "paid"
        line.paid_at = now

    # Mark matching sales as commission paid
    if record.snapshot_data:
        _update_sales_commission_status(db, record.snapshot_data, period, "paid")

    db.commit()

    return {"success": True, "period": period, "status": "paid", "agents_paid": len(lines)}


@router.get("/history")
def get_payroll_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all historical payroll records."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    records = (
        db.query(PayrollRecord)
        .order_by(PayrollRecord.period.desc())
        .all()
    )

    return [
        {
            "id": r.id,
            "period": r.period,
            "period_display": r.period_display,
            "status": r.status,
            "is_locked": r.is_locked,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            "total_agents": r.total_agents,
            "total_premium": float(r.total_premium or 0),
            "total_agent_pay": float(r.total_agent_pay or 0),
            "total_chargebacks": float(r.total_chargebacks or 0),
            "total_carriers": r.total_carriers,
        }
        for r in records
    ]


@router.get("/detail/{period}")
def get_payroll_detail(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed payroll record with agent lines."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record found for this period")

    lines = (
        db.query(PayrollAgentLine)
        .filter(PayrollAgentLine.payroll_record_id == record.id)
        .order_by(PayrollAgentLine.net_agent_pay.desc())
        .all()
    )

    return {
        "id": record.id,
        "period": record.period,
        "period_display": record.period_display,
        "status": record.status,
        "is_locked": record.is_locked,
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
        "paid_at": record.paid_at.isoformat() if record.paid_at else None,
        "total_agents": record.total_agents,
        "total_premium": float(record.total_premium or 0),
        "total_agent_pay": float(record.total_agent_pay or 0),
        "total_chargebacks": float(record.total_chargebacks or 0),
        "total_carriers": record.total_carriers,
        "notes": record.notes,
        "agent_lines": [
            {
                "id": l.id,
                "agent_id": l.agent_id,
                "agent_name": l.agent_name,
                "agent_role": l.agent_role,
                "tier_level": l.tier_level,
                "commission_rate": float(l.commission_rate or 0),
                "total_premium": float(l.total_premium or 0),
                "new_business_premium": float(l.new_business_premium or 0),
                "total_agent_commission": float(l.total_agent_commission or 0),
                "chargebacks": float(l.chargebacks or 0),
                "chargeback_premium": float(l.chargeback_premium or 0),
                "chargeback_count": l.chargeback_count,
                "net_agent_pay": float(l.net_agent_pay or 0),
                "line_count": l.line_count,
                "carrier_breakdown": l.carrier_breakdown or [],
                "rate_adjustment": float(l.rate_adjustment or 0),
                "bonus": float(l.bonus or 0),
                "grand_total": float(l.grand_total or 0),
                "commission_status": l.commission_status,
                "paid_at": l.paid_at.isoformat() if l.paid_at else None,
            }
            for l in lines
        ],
    }


def _update_sales_commission_status(db: Session, pay_data: dict, period: str, status: str):
    """Update commission_status on sales that are part of this payroll."""
    from app.models.statement import StatementImport, StatementLine

    # Get all imports for this period
    imports = db.query(StatementImport).filter(StatementImport.statement_period == period).all()
    if not imports:
        return

    import_ids = [imp.id for imp in imports]

    # Get all matched lines with sales
    lines = db.query(StatementLine).filter(
        StatementLine.statement_import_id.in_(import_ids),
        StatementLine.matched_sale_id.isnot(None),
        StatementLine.is_matched == True,
    ).all()

    sale_ids = list(set(l.matched_sale_id for l in lines if l.matched_sale_id))
    if not sale_ids:
        return

    now = datetime.utcnow()
    for sale in db.query(Sale).filter(Sale.id.in_(sale_ids)).all():
        sale.commission_status = status
        if status == "paid":
            sale.commission_paid_date = now
            sale.commission_paid_period = period
