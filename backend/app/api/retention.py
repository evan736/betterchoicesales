"""Retention analytics — early termination tracking and retention metrics."""
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, extract

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.statement import StatementImport, StatementLine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/retention", tags=["retention"])


@router.get("/overview")
def get_retention_overview(
    period: Optional[str] = Query(None, description="Filter to specific period e.g. 2026-01"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get overall retention metrics — cancellation rates by 30/60/90/120 day buckets."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # First, update days_to_cancel for any sales with cancellations
    _sync_cancellation_data(db, period)

    # Base query: all sales with effective dates
    query = db.query(Sale).filter(Sale.effective_date.isnot(None))

    if period:
        year, month = map(int, period.split("-"))
        query = query.filter(
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        )

    total_sales = query.count()
    total_cancelled = query.filter(Sale.status == "cancelled").count()
    total_active = query.filter(Sale.status == "active").count()

    # Bucket cancellations by days_to_cancel
    cancelled_sales = query.filter(
        Sale.status == "cancelled",
        Sale.days_to_cancel.isnot(None),
    ).all()

    buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "91-120": 0, "120+": 0}
    for sale in cancelled_sales:
        d = sale.days_to_cancel
        if d <= 30:
            buckets["0-30"] += 1
        elif d <= 60:
            buckets["31-60"] += 1
        elif d <= 90:
            buckets["61-90"] += 1
        elif d <= 120:
            buckets["91-120"] += 1
        else:
            buckets["120+"] += 1

    retention_rate = ((total_sales - total_cancelled) / total_sales * 100) if total_sales > 0 else 0

    return {
        "total_sales": total_sales,
        "total_active": total_active,
        "total_cancelled": total_cancelled,
        "retention_rate": round(retention_rate, 1),
        "cancellation_buckets": buckets,
        "bucket_chart_data": [
            {"name": "0-30 days", "count": buckets["0-30"]},
            {"name": "31-60 days", "count": buckets["31-60"]},
            {"name": "61-90 days", "count": buckets["61-90"]},
            {"name": "91-120 days", "count": buckets["91-120"]},
            {"name": "120+ days", "count": buckets["120+"]},
        ],
    }


@router.get("/by-agent")
def get_retention_by_agent(
    period: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retention metrics broken down by agent/producer."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    _sync_cancellation_data(db, period)

    query = db.query(
        Sale.producer_id,
        User.full_name,
        func.count(Sale.id).label("total_sales"),
        func.count(case((Sale.status == "cancelled", 1))).label("cancelled"),
        func.count(case((Sale.status == "active", 1))).label("active"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel <= 30), 1
        ))).label("cancel_30"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 30, Sale.days_to_cancel <= 60), 1
        ))).label("cancel_60"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 60, Sale.days_to_cancel <= 90), 1
        ))).label("cancel_90"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 90, Sale.days_to_cancel <= 120), 1
        ))).label("cancel_120"),
    ).join(User, Sale.producer_id == User.id).filter(
        Sale.effective_date.isnot(None)
    )

    if period:
        year, month = map(int, period.split("-"))
        query = query.filter(
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        )

    results = query.group_by(Sale.producer_id, User.full_name).all()

    agents = []
    for r in results:
        total = r.total_sales or 1
        retention = ((total - r.cancelled) / total * 100) if total > 0 else 100
        agents.append({
            "agent_id": r.producer_id,
            "agent_name": r.full_name or "Unknown",
            "total_sales": r.total_sales,
            "active": r.active,
            "cancelled": r.cancelled,
            "retention_rate": round(retention, 1),
            "cancel_30": r.cancel_30,
            "cancel_60": r.cancel_60,
            "cancel_90": r.cancel_90,
            "cancel_120": r.cancel_120,
        })

    agents.sort(key=lambda x: x["retention_rate"])
    return agents


@router.get("/by-carrier")
def get_retention_by_carrier(
    period: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retention metrics broken down by carrier."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    _sync_cancellation_data(db, period)

    query = db.query(
        Sale.carrier,
        func.count(Sale.id).label("total_sales"),
        func.count(case((Sale.status == "cancelled", 1))).label("cancelled"),
        func.count(case((Sale.status == "active", 1))).label("active"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel <= 30), 1
        ))).label("cancel_30"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 30, Sale.days_to_cancel <= 60), 1
        ))).label("cancel_60"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 60, Sale.days_to_cancel <= 90), 1
        ))).label("cancel_90"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 90, Sale.days_to_cancel <= 120), 1
        ))).label("cancel_120"),
    ).filter(
        Sale.effective_date.isnot(None),
        Sale.carrier.isnot(None),
    )

    if period:
        year, month = map(int, period.split("-"))
        query = query.filter(
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        )

    results = query.group_by(Sale.carrier).all()

    carriers = []
    for r in results:
        total = r.total_sales or 1
        retention = ((total - r.cancelled) / total * 100) if total > 0 else 100
        carriers.append({
            "carrier": r.carrier,
            "total_sales": r.total_sales,
            "active": r.active,
            "cancelled": r.cancelled,
            "retention_rate": round(retention, 1),
            "cancel_30": r.cancel_30,
            "cancel_60": r.cancel_60,
            "cancel_90": r.cancel_90,
            "cancel_120": r.cancel_120,
        })

    carriers.sort(key=lambda x: x["retention_rate"])
    return carriers


@router.get("/by-source")
def get_retention_by_lead_source(
    period: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retention metrics broken down by lead source."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    _sync_cancellation_data(db, period)

    query = db.query(
        Sale.lead_source,
        func.count(Sale.id).label("total_sales"),
        func.count(case((Sale.status == "cancelled", 1))).label("cancelled"),
        func.count(case((Sale.status == "active", 1))).label("active"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel <= 30), 1
        ))).label("cancel_30"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 30, Sale.days_to_cancel <= 60), 1
        ))).label("cancel_60"),
        func.count(case((
            and_(Sale.status == "cancelled", Sale.days_to_cancel > 60, Sale.days_to_cancel <= 90), 1
        ))).label("cancel_90"),
    ).filter(
        Sale.effective_date.isnot(None),
        Sale.lead_source.isnot(None),
    )

    if period:
        year, month = map(int, period.split("-"))
        query = query.filter(
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        )

    results = query.group_by(Sale.lead_source).all()

    sources = []
    for r in results:
        total = r.total_sales or 1
        retention = ((total - r.cancelled) / total * 100) if total > 0 else 100
        sources.append({
            "lead_source": r.lead_source or "Unknown",
            "total_sales": r.total_sales,
            "active": r.active,
            "cancelled": r.cancelled,
            "retention_rate": round(retention, 1),
            "cancel_30": r.cancel_30,
            "cancel_60": r.cancel_60,
            "cancel_90": r.cancel_90,
        })

    sources.sort(key=lambda x: x["retention_rate"])
    return sources


@router.get("/trend")
def get_retention_trend(
    months: int = Query(6, description="Number of months to look back"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Monthly retention rate trend over time."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    today = date.today()
    trend = []

    for i in range(months - 1, -1, -1):
        d = today.replace(day=1) - timedelta(days=i * 30)
        year, month = d.year, d.month

        total = db.query(func.count(Sale.id)).filter(
            Sale.effective_date.isnot(None),
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        ).scalar() or 0

        cancelled = db.query(func.count(Sale.id)).filter(
            Sale.effective_date.isnot(None),
            Sale.status == "cancelled",
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        ).scalar() or 0

        retention = ((total - cancelled) / total * 100) if total > 0 else 100

        trend.append({
            "period": f"{year}-{month:02d}",
            "month": datetime(year, month, 1).strftime("%b %Y"),
            "total_sales": total,
            "cancelled": cancelled,
            "retained": total - cancelled,
            "retention_rate": round(retention, 1),
        })

    return trend


@router.get("/early-cancellations")
def get_early_cancellations(
    days: int = Query(90, description="Show cancellations within this many days"),
    period: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List policies that cancelled within the first N days."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    _sync_cancellation_data(db, period)

    query = db.query(Sale).join(User, Sale.producer_id == User.id).filter(
        Sale.status == "cancelled",
        Sale.days_to_cancel.isnot(None),
        Sale.days_to_cancel <= days,
    )

    if period:
        year, month = map(int, period.split("-"))
        query = query.filter(
            extract("year", Sale.sale_date) == year,
            extract("month", Sale.sale_date) == month,
        )

    sales = query.order_by(Sale.days_to_cancel.asc()).limit(200).all()

    return [
        {
            "id": s.id,
            "policy_number": s.policy_number,
            "client_name": s.client_name,
            "carrier": s.carrier,
            "producer": s.producer.full_name if s.producer else "Unknown",
            "lead_source": s.lead_source,
            "written_premium": float(s.written_premium or 0),
            "effective_date": s.effective_date.strftime("%Y-%m-%d") if s.effective_date else None,
            "cancelled_date": s.cancelled_date.strftime("%Y-%m-%d") if s.cancelled_date else None,
            "days_to_cancel": s.days_to_cancel,
            "commission_status": s.commission_status or "pending",
        }
        for s in sales
    ]


def _sync_cancellation_data(db: Session, period: Optional[str] = None):
    """Sync cancellation data from statement lines back to sales.
    
    When a carrier statement shows a cancellation for a matched sale,
    update the sale's status, cancelled_date, and days_to_cancel.
    """
    from app.models.statement import StatementLine, StatementImport

    # Find all cancellation lines matched to sales
    query = db.query(StatementLine).filter(
        StatementLine.is_matched == True,
        StatementLine.matched_sale_id.isnot(None),
        StatementLine.transaction_type.in_(["cancellation", "cancel", "Cancel-INS", "CANCEL"]),
    )

    # Also check transaction_type_raw for cancel keywords
    cancel_lines = db.query(StatementLine).filter(
        StatementLine.is_matched == True,
        StatementLine.matched_sale_id.isnot(None),
    ).all()

    for line in cancel_lines:
        tx = (line.transaction_type or "").lower()
        tx_raw = (line.transaction_type_raw or "").lower()
        if "cancel" not in tx and "cancel" not in tx_raw:
            continue

        sale = db.query(Sale).filter(Sale.id == line.matched_sale_id).first()
        if not sale:
            continue

        # Only update if not already marked
        if sale.status != "cancelled":
            sale.status = "cancelled"

        if not sale.cancelled_date and line.effective_date:
            sale.cancelled_date = line.effective_date
        elif not sale.cancelled_date and line.transaction_date:
            sale.cancelled_date = line.transaction_date

        # Calculate days to cancel
        if sale.effective_date and sale.cancelled_date and not sale.days_to_cancel:
            eff = sale.effective_date
            canc = sale.cancelled_date
            if hasattr(eff, 'date'):
                eff = eff.date()
            if hasattr(canc, 'date'):
                canc = canc.date()
            sale.days_to_cancel = max(0, (canc - eff).days)

    try:
        db.commit()
    except Exception:
        db.rollback()


