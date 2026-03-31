"""
Sales Records API — track all-time daily and monthly bests.
- GET  /api/sales-records          — view all records (admin)
- GET  /api/sales-records/current  — current best records
- POST /api/sales-records/scan     — retroactive scan of all historical sales
- check_for_new_records()          — called after each sale to detect new records
"""
import os
import logging
from datetime import datetime, date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text, func, extract, desc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.sales_record import SalesRecord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sales-records", tags=["sales-records"])

MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
AGENCY_FROM_EMAIL = os.environ.get("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")


# ═══════════════════════════════════════════════════════════════════
# CORE RECORD CHECKING — called after every new sale
# ═══════════════════════════════════════════════════════════════════

def check_for_new_records(db: Session):
    """Check if today or this month has set a new all-time record.
    Called after each sale is logged."""
    today = date.today()
    today_str = today.isoformat()
    month_str = today.strftime("%Y-%m")

    # Get today's totals
    daily_result = db.execute(text("""
        SELECT COALESCE(SUM(written_premium), 0) as premium, COUNT(*) as cnt
        FROM sales
        WHERE DATE(sale_date) = :today
        AND sale_date < '2100-01-01'
        AND status != 'cancelled'
    """), {"today": today_str}).fetchone()
    daily_premium = float(daily_result[0])
    daily_count = int(daily_result[1])

    # Get this month's totals
    monthly_result = db.execute(text("""
        SELECT COALESCE(SUM(written_premium), 0) as premium, COUNT(*) as cnt
        FROM sales
        WHERE EXTRACT(YEAR FROM sale_date) = :year
        AND EXTRACT(MONTH FROM sale_date) = :month
        AND sale_date < '2100-01-01'
        AND status != 'cancelled'
    """), {"year": today.year, "month": today.month}).fetchone()
    monthly_premium = float(monthly_result[0])
    monthly_count = int(monthly_result[1])

    # Get current records
    records = _get_current_records(db)

    new_records = []

    # Check daily premium record
    if daily_premium > records.get("daily_premium_best", 0):
        rec = _save_record(
            db, "daily_premium", today_str, daily_premium, daily_count,
            records.get("daily_premium_best", 0), records.get("daily_premium_count", 0),
            records.get("daily_premium_period", ""),
        )
        new_records.append(rec)

    # Check daily count record
    if daily_count > records.get("daily_count_best", 0):
        rec = _save_record(
            db, "daily_count", today_str, daily_premium, daily_count,
            records.get("daily_count_premium", 0), records.get("daily_count_best", 0),
            records.get("daily_count_period", ""),
        )
        new_records.append(rec)

    # Check monthly premium record
    if monthly_premium > records.get("monthly_premium_best", 0):
        rec = _save_record(
            db, "monthly_premium", month_str, monthly_premium, monthly_count,
            records.get("monthly_premium_best", 0), records.get("monthly_premium_count", 0),
            records.get("monthly_premium_period", ""),
        )
        new_records.append(rec)

    # Check monthly count record
    if monthly_count > records.get("monthly_count_best", 0):
        rec = _save_record(
            db, "monthly_count", month_str, monthly_premium, monthly_count,
            records.get("monthly_count_premium", 0), records.get("monthly_count_best", 0),
            records.get("monthly_count_period", ""),
        )
        new_records.append(rec)

    # Send notifications for new records
    for rec in new_records:
        _send_record_notification(rec)

    return new_records


def _get_current_records(db: Session) -> dict:
    """Get the current best for each record type."""
    result = {}
    for rtype in ["daily_premium", "daily_count", "monthly_premium", "monthly_count"]:
        rec = db.query(SalesRecord).filter(
            SalesRecord.record_type == rtype
        ).order_by(desc(SalesRecord.id)).first()

        if rtype == "daily_premium":
            result["daily_premium_best"] = float(rec.premium) if rec else 0
            result["daily_premium_count"] = rec.sale_count if rec else 0
            result["daily_premium_period"] = rec.period_label if rec else ""
        elif rtype == "daily_count":
            result["daily_count_best"] = rec.sale_count if rec else 0
            result["daily_count_premium"] = float(rec.premium) if rec else 0
            result["daily_count_period"] = rec.period_label if rec else ""
        elif rtype == "monthly_premium":
            result["monthly_premium_best"] = float(rec.premium) if rec else 0
            result["monthly_premium_count"] = rec.sale_count if rec else 0
            result["monthly_premium_period"] = rec.period_label if rec else ""
        elif rtype == "monthly_count":
            result["monthly_count_best"] = rec.sale_count if rec else 0
            result["monthly_count_premium"] = float(rec.premium) if rec else 0
            result["monthly_count_period"] = rec.period_label if rec else ""

    return result


def _save_record(db, record_type, period_label, premium, count, prev_premium, prev_count, prev_period):
    """Save a new record to the database."""
    rec = SalesRecord(
        record_type=record_type,
        period_label=period_label,
        premium=premium,
        sale_count=count,
        previous_record_premium=prev_premium,
        previous_record_count=prev_count,
        previous_record_period=prev_period,
        notified="pending",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info(f"NEW RECORD: {record_type} — {period_label}: ${premium:,.2f} ({count} sales)")
    return rec


def _send_record_notification(rec: SalesRecord):
    """Send email notification about a new record."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        return

    type_labels = {
        "daily_premium": "Daily Premium",
        "daily_count": "Daily Sale Count",
        "monthly_premium": "Monthly Premium",
        "monthly_count": "Monthly Sale Count",
    }
    label = type_labels.get(rec.record_type, rec.record_type)
    emoji = "🏆"
    is_daily = "daily" in rec.record_type
    is_premium = "premium" in rec.record_type

    if is_premium:
        new_val = f"${float(rec.premium):,.2f}"
        old_val = f"${float(rec.previous_record_premium or 0):,.2f}" if rec.previous_record_premium else "N/A"
    else:
        new_val = f"{rec.sale_count} sales"
        old_val = f"{rec.previous_record_count or 0} sales" if rec.previous_record_count else "N/A"

    prev_period = rec.previous_record_period or "N/A"

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;margin:0;padding:20px;background:#f1f5f9;">
    <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <div style="background:linear-gradient(135deg,#f59e0b,#eab308);padding:28px;text-align:center;">
            <p style="font-size:48px;margin:0;">{emoji}</p>
            <h1 style="color:#fff;font-size:22px;margin:8px 0 0;">NEW ALL-TIME RECORD!</h1>
            <p style="color:rgba(255,255,255,0.9);font-size:14px;margin:4px 0 0;">{label}</p>
        </div>
        <div style="padding:28px;">
            <div style="background:#FFFBEB;border:2px solid #FDE68A;border-radius:10px;padding:20px;text-align:center;margin-bottom:20px;">
                <p style="margin:0;font-size:32px;font-weight:800;color:#92400E;">{new_val}</p>
                <p style="margin:4px 0 0;font-size:13px;color:#A16207;">{rec.period_label}</p>
            </div>
            <table style="width:100%;font-size:14px;color:#334155;">
                <tr><td style="padding:6px 0;color:#64748b;">Previous Record</td><td style="padding:6px 0;text-align:right;font-weight:600;">{old_val}</td></tr>
                <tr><td style="padding:6px 0;color:#64748b;">Previous Period</td><td style="padding:6px 0;text-align:right;">{prev_period}</td></tr>
                <tr><td style="padding:6px 0;color:#64748b;">{'Sales Today' if is_daily else 'Sales This Month'}</td><td style="padding:6px 0;text-align:right;font-weight:600;">{rec.sale_count}</td></tr>
                <tr><td style="padding:6px 0;color:#64748b;">{'Premium Today' if is_daily else 'Premium This Month'}</td><td style="padding:6px 0;text-align:right;font-weight:600;">${float(rec.premium):,.2f}</td></tr>
            </table>
        </div>
        <div style="background:#f8fafc;padding:12px 28px;border-top:1px solid #e2e8f0;">
            <p style="margin:0;color:#94a3b8;font-size:11px;text-align:center;">Better Choice Insurance Group · ORBIT Sales Records</p>
        </div>
    </div></body></html>"""

    try:
        httpx.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={
                "from": f"ORBIT Records <{AGENCY_FROM_EMAIL}>",
                "to": ["evan@betterchoiceins.com"],
                "subject": f"{emoji} NEW RECORD — {label}: {new_val} ({rec.period_label})",
                "html": html,
                "o:tag": ["sales-record"],
            },
        )
        logger.info(f"Record notification sent for {rec.record_type}")
    except Exception as e:
        logger.warning(f"Failed to send record notification: {e}")


# ═══════════════════════════════════════════════════════════════════
# RETROACTIVE SCAN — build records from all historical data
# ═══════════════════════════════════════════════════════════════════

@router.post("/scan")
def retroactive_scan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Scan all historical sales to establish baseline records. Admin only."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")

    # Get daily totals
    daily_rows = db.execute(text("""
        SELECT DATE(sale_date) as day,
               COALESCE(SUM(written_premium), 0) as premium,
               COUNT(*) as cnt
        FROM sales
        WHERE sale_date >= '2024-01-01' AND sale_date < '2100-01-01'
        AND status != 'cancelled'
        GROUP BY DATE(sale_date)
        ORDER BY day
    """)).fetchall()

    # Get monthly totals
    monthly_rows = db.execute(text("""
        SELECT TO_CHAR(sale_date, 'YYYY-MM') as month,
               COALESCE(SUM(written_premium), 0) as premium,
               COUNT(*) as cnt
        FROM sales
        WHERE sale_date >= '2024-01-01' AND sale_date < '2100-01-01'
        AND status != 'cancelled'
        GROUP BY TO_CHAR(sale_date, 'YYYY-MM')
        ORDER BY month
    """)).fetchall()

    # Clear existing records for clean rebuild
    db.execute(text("DELETE FROM sales_records"))
    db.commit()

    # Track running bests
    best_daily_premium = 0
    best_daily_premium_day = ""
    best_daily_premium_count = 0
    best_daily_count = 0
    best_daily_count_day = ""
    best_daily_count_premium = 0

    best_monthly_premium = 0
    best_monthly_premium_month = ""
    best_monthly_premium_count = 0
    best_monthly_count = 0
    best_monthly_count_month = ""
    best_monthly_count_premium = 0

    daily_records_created = 0
    monthly_records_created = 0

    # Process daily records chronologically
    for row in daily_rows:
        day_str = row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0])
        premium = float(row[1])
        count = int(row[2])

        if premium > best_daily_premium:
            rec = SalesRecord(
                record_type="daily_premium",
                period_label=day_str,
                premium=premium,
                sale_count=count,
                previous_record_premium=best_daily_premium if best_daily_premium > 0 else None,
                previous_record_count=best_daily_premium_count if best_daily_premium > 0 else None,
                previous_record_period=best_daily_premium_day if best_daily_premium_day else None,
                notified="historical",
            )
            db.add(rec)
            best_daily_premium = premium
            best_daily_premium_day = day_str
            best_daily_premium_count = count
            daily_records_created += 1

        if count > best_daily_count:
            rec = SalesRecord(
                record_type="daily_count",
                period_label=day_str,
                premium=premium,
                sale_count=count,
                previous_record_premium=best_daily_count_premium if best_daily_count > 0 else None,
                previous_record_count=best_daily_count if best_daily_count > 0 else None,
                previous_record_period=best_daily_count_day if best_daily_count_day else None,
                notified="historical",
            )
            db.add(rec)
            best_daily_count = count
            best_daily_count_day = day_str
            best_daily_count_premium = premium
            daily_records_created += 1

    # Process monthly records chronologically
    for row in monthly_rows:
        month_str = str(row[0])
        premium = float(row[1])
        count = int(row[2])

        if premium > best_monthly_premium:
            rec = SalesRecord(
                record_type="monthly_premium",
                period_label=month_str,
                premium=premium,
                sale_count=count,
                previous_record_premium=best_monthly_premium if best_monthly_premium > 0 else None,
                previous_record_count=best_monthly_premium_count if best_monthly_premium > 0 else None,
                previous_record_period=best_monthly_premium_month if best_monthly_premium_month else None,
                notified="historical",
            )
            db.add(rec)
            best_monthly_premium = premium
            best_monthly_premium_month = month_str
            best_monthly_premium_count = count
            monthly_records_created += 1

        if count > best_monthly_count:
            rec = SalesRecord(
                record_type="monthly_count",
                period_label=month_str,
                premium=premium,
                sale_count=count,
                previous_record_premium=best_monthly_count_premium if best_monthly_count > 0 else None,
                previous_record_count=best_monthly_count if best_monthly_count > 0 else None,
                previous_record_period=best_monthly_count_month if best_monthly_count_month else None,
                notified="historical",
            )
            db.add(rec)
            best_monthly_count = count
            best_monthly_count_month = month_str
            best_monthly_count_premium = premium
            monthly_records_created += 1

    db.commit()

    return {
        "daily_records_created": daily_records_created,
        "monthly_records_created": monthly_records_created,
        "current_records": {
            "best_daily_premium": {"date": best_daily_premium_day, "premium": best_daily_premium, "sales": best_daily_premium_count},
            "best_daily_count": {"date": best_daily_count_day, "sales": best_daily_count, "premium": best_daily_count_premium},
            "best_monthly_premium": {"month": best_monthly_premium_month, "premium": best_monthly_premium, "sales": best_monthly_premium_count},
            "best_monthly_count": {"month": best_monthly_count_month, "sales": best_monthly_count, "premium": best_monthly_count_premium},
        },
        "days_analyzed": len(daily_rows),
        "months_analyzed": len(monthly_rows),
    }


# ═══════════════════════════════════════════════════════════════════
# VIEW RECORDS
# ═══════════════════════════════════════════════════════════════════

@router.get("/current")
def get_current_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current all-time bests."""
    records = _get_current_records(db)

    # Also get today and this month for context
    today = date.today()
    daily = db.execute(text("""
        SELECT COALESCE(SUM(written_premium), 0), COUNT(*)
        FROM sales WHERE DATE(sale_date) = :today AND sale_date < '2100-01-01' AND status != 'cancelled'
    """), {"today": today.isoformat()}).fetchone()

    monthly = db.execute(text("""
        SELECT COALESCE(SUM(written_premium), 0), COUNT(*)
        FROM sales WHERE EXTRACT(YEAR FROM sale_date) = :y AND EXTRACT(MONTH FROM sale_date) = :m
        AND sale_date < '2100-01-01' AND status != 'cancelled'
    """), {"y": today.year, "m": today.month}).fetchone()

    return {
        "records": records,
        "today": {"premium": float(daily[0]), "count": int(daily[1]), "date": today.isoformat()},
        "this_month": {"premium": float(monthly[0]), "count": int(monthly[1]), "month": today.strftime("%Y-%m")},
    }


@router.get("")
def list_all_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    record_type: Optional[str] = None,
):
    """List all historical records. Admin/manager only."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")

    q = db.query(SalesRecord)
    if record_type:
        q = q.filter(SalesRecord.record_type == record_type)

    recs = q.order_by(desc(SalesRecord.id)).all()

    return {
        "records": [
            {
                "id": r.id,
                "record_type": r.record_type,
                "period_label": r.period_label,
                "premium": float(r.premium),
                "sale_count": r.sale_count,
                "previous_record_premium": float(r.previous_record_premium) if r.previous_record_premium else None,
                "previous_record_count": r.previous_record_count,
                "previous_record_period": r.previous_record_period,
                "notified": r.notified,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recs
        ],
    }
