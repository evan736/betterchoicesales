"""Revenue Tracker API - Projected vs Actual renewal commission.

Projects revenue by looking at policies expiring in future months:
  expiring_premium * 1.10 (10% avg rate increase) * 0.13 (13% avg commission) = projected

Compares against actual renewal commission received from carrier statements.
"""
import logging
from datetime import date, datetime as dt_datetime
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.statement import StatementImport, StatementLine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/revenue-tracker", tags=["revenue-tracker"])

RATE_INCREASE = 0.10
COMMISSION_RATE = 0.13


def _get_term_months(policy_type):
    pt = (policy_type or "").lower()
    if "6m" in pt or "6 month" in pt or "auto_6m" in pt:
        return 6
    if "auto" in pt and "12" not in pt:
        return 6
    return 12


def _get_active_sales_with_dates(db):
    """Get active sales filtering out corrupted date records."""
    from sqlalchemy import text
    return db.query(Sale).filter(
        Sale.status == "active",
        Sale.effective_date.isnot(None),
        Sale.effective_date < dt_datetime(2100, 1, 1),
    ).all()



@router.get("/projections")
def get_revenue_projections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    months_ahead: int = Query(default=6, ge=1, le=12),
):
    today = date.today()
    current_month_start = date(today.year, today.month, 1)

    sales = _get_active_sales_with_dates(db)

    months = []
    for i in range(months_ahead):
        month_start = current_month_start + relativedelta(months=i)
        months.append({
            "month": month_start.strftime("%Y-%m"),
            "label": month_start.strftime("%B %Y"),
            "start": month_start,
            "end": month_start + relativedelta(months=1) - relativedelta(days=1),
        })

    projections = {}
    for m in months:
        projections[m["month"]] = {
            "month": m["month"],
            "label": m["label"],
            "expiring_policy_count": 0,
            "expiring_premium": 0.0,
            "projected_renewal_premium": 0.0,
            "projected_commission": 0.0,
            "actual_commission": 0.0,
            "variance": 0.0,
            "variance_pct": 0.0,
        }

    window_end = current_month_start + relativedelta(months=months_ahead)

    for sale in sales:
        eff = sale.effective_date
        if hasattr(eff, "date"):
            eff = eff.date()
        if not eff:
            continue

        term = _get_term_months(sale.policy_type)
        premium = float(sale.written_premium or 0)

        expiration = eff + relativedelta(months=term)
        while expiration < window_end:
            exp_month = expiration.strftime("%Y-%m")
            if exp_month in projections:
                renewed_premium = premium * (1 + RATE_INCREASE)
                proj_commission = renewed_premium * COMMISSION_RATE

                projections[exp_month]["expiring_policy_count"] += 1
                projections[exp_month]["expiring_premium"] += premium
                projections[exp_month]["projected_renewal_premium"] += renewed_premium
                projections[exp_month]["projected_commission"] += proj_commission

            expiration += relativedelta(months=term)

    for m in months:
        period = m["month"]
        actual = db.query(
            func.coalesce(func.sum(StatementLine.commission_amount), 0)
        ).join(StatementImport).filter(
            StatementImport.period == period,
            StatementLine.transaction_type == "renewal",
        ).scalar()

        projections[period]["actual_commission"] = float(actual or 0)
        proj = projections[period]["projected_commission"]
        act = projections[period]["actual_commission"]
        projections[period]["variance"] = round(act - proj, 2)
        if proj > 0:
            projections[period]["variance_pct"] = round((act - proj) / proj * 100, 1)

    result = []
    for m in months:
        p = projections[m["month"]]
        p["expiring_premium"] = round(p["expiring_premium"], 2)
        p["projected_renewal_premium"] = round(p["projected_renewal_premium"], 2)
        p["projected_commission"] = round(p["projected_commission"], 2)
        result.append(p)

    total_proj = sum(r["projected_commission"] for r in result)
    total_actual = sum(r["actual_commission"] for r in result)

    return {
        "months": result,
        "summary": {
            "total_projected_commission": round(total_proj, 2),
            "total_actual_commission": round(total_actual, 2),
            "total_variance": round(total_actual - total_proj, 2),
            "rate_increase_assumption": RATE_INCREASE,
            "commission_rate_assumption": COMMISSION_RATE,
        },
    }


@router.get("/projections/{period}/policies")
def get_month_policies(
    period: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        year, month = map(int, period.split("-"))
        month_start = date(year, month, 1)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
    except ValueError:
        return {"error": "Invalid period format, use YYYY-MM"}

    sales = _get_active_sales_with_dates(db)

    policies = []
    for sale in sales:
        eff = sale.effective_date
        if hasattr(eff, "date"):
            eff = eff.date()
        if not eff:
            continue

        term = _get_term_months(sale.policy_type)
        premium = float(sale.written_premium or 0)

        expiration = eff + relativedelta(months=term)
        while expiration <= month_end:
            if month_start <= expiration <= month_end:
                renewed_premium = premium * (1 + RATE_INCREASE)
                policies.append({
                    "policy_number": sale.policy_number,
                    "client_name": sale.client_name,
                    "carrier": sale.carrier,
                    "policy_type": sale.policy_type,
                    "effective_date": eff.isoformat(),
                    "expiration_date": expiration.isoformat(),
                    "current_premium": premium,
                    "projected_renewal_premium": round(renewed_premium, 2),
                    "projected_commission": round(renewed_premium * COMMISSION_RATE, 2),
                    "term_months": term,
                    "producer_id": sale.producer_id,
                })
                break
            expiration += relativedelta(months=term)

    policies.sort(key=lambda p: -p["current_premium"])

    return {
        "period": period,
        "policy_count": len(policies),
        "total_expiring_premium": round(sum(p["current_premium"] for p in policies), 2),
        "total_projected_commission": round(sum(p["projected_commission"] for p in policies), 2),
        "policies": policies,
    }
