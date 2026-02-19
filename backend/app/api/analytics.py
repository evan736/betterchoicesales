"""Analytics API — filterable, groupable sales data for dashboards and reports."""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract
from datetime import datetime, date, timedelta
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def count_business_days(start_date: date, end_date: date) -> int:
    """Count weekdays (Mon-Fri) between two dates, inclusive."""
    if end_date < start_date:
        return 0
    days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            days += 1
        current += timedelta(days=1)
    return days


def count_business_days_in_range(year: int, month: int) -> int:
    """Count total business days in a month."""
    first = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return count_business_days(first, last)


@router.get("/trending")
def get_trending_projection(
    target_date: Optional[str] = Query(None, description="Target date YYYY-MM-DD, defaults to end of current month"),
    period: Optional[str] = Query(None, description="monthly, annual, last_year"),
    producer_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Project sales to a target date based on daily business-day pace.
    Supports monthly (current month), annual (this year), and last_year views.
    """
    now = datetime.utcnow()
    today = now.date()

    # Build base user filter
    user_filters = []
    if current_user.role.lower() in ("producer", "retention_specialist"):
        user_filters.append(Sale.producer_id == current_user.id)
    elif producer_id:
        user_filters.append(Sale.producer_id == producer_id)

    # Handle last_year — purely historical, no projections
    if period == "last_year":
        last_year = today.year - 1
        ly_premium = float(
            db.query(func.coalesce(func.sum(Sale.written_premium), 0)).filter(
                extract("year", Sale.sale_date) == last_year,
                *user_filters,
            ).scalar() or 0
        )
        ly_sales = db.query(func.count(Sale.id)).filter(
            extract("year", Sale.sale_date) == last_year,
            *user_filters,
        ).scalar() or 0

        # Monthly breakdown for last year
        monthly_breakdown = []
        for m in range(1, 13):
            mp = float(
                db.query(func.coalesce(func.sum(Sale.written_premium), 0)).filter(
                    extract("year", Sale.sale_date) == last_year,
                    extract("month", Sale.sale_date) == m,
                    *user_filters,
                ).scalar() or 0
            )
            monthly_breakdown.append({"month": m, "premium": mp})

        return {
            "mode": "last_year",
            "year": last_year,
            "current_premium": ly_premium,
            "ytd_premium": ly_premium,
            "projected_premium": ly_premium,
            "daily_pace": 0,
            "biz_days_elapsed": 0,
            "biz_days_remaining": 0,
            "total_biz_days": 0,
            "target_date": f"{last_year}-12-31",
            "total_sales": ly_sales,
            "monthly_breakdown": monthly_breakdown,
            "current_tier": None,
            "goals": [],
            "period": str(last_year),
        }

    # Determine period start and premium window
    if period == "annual":
        period_start = date(today.year, 1, 1)
        default_target = date(today.year, 12, 31)
    elif period == "last_month":
        if today.month == 1:
            period_start = date(today.year - 1, 12, 1)
            default_target = date(today.year - 1, 12, 31)
        else:
            period_start = date(today.year, today.month - 1, 1)
            default_target = date(today.year, today.month, 1) - timedelta(days=1)
    else:
        # monthly (default)
        period_start = date(today.year, today.month, 1)
        if today.month == 12:
            default_target = date(today.year, 12, 31)
        else:
            default_target = date(today.year, today.month + 1, 1) - timedelta(days=1)

    # Determine target date
    if target_date:
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            target = default_target
    else:
        target = default_target

    # Get premium for the period
    period_query = db.query(func.coalesce(func.sum(Sale.written_premium), 0)).filter(
        Sale.sale_date >= datetime.combine(period_start, datetime.min.time()),
        *user_filters,
    )

    if period == "last_month":
        lm_year = today.year if today.month > 1 else today.year - 1
        lm_month = today.month - 1 if today.month > 1 else 12
        period_query = period_query.filter(
            extract("year", Sale.sale_date) == lm_year,
            extract("month", Sale.sale_date) == lm_month,
        )
    elif period != "annual":
        # Monthly — filter to current month
        period_query = period_query.filter(
            extract("year", Sale.sale_date) == today.year,
            extract("month", Sale.sale_date) == today.month,
        )
    else:
        # Annual — filter to this year
        period_query = period_query.filter(
            extract("year", Sale.sale_date) == today.year,
        )

    current_premium = float(period_query.scalar() or 0)

    # YTD premium (always this year total)
    ytd_premium = float(
        db.query(func.coalesce(func.sum(Sale.written_premium), 0)).filter(
            extract("year", Sale.sale_date) == today.year,
            *user_filters,
        ).scalar() or 0
    )

    # Business days elapsed (period start to today)
    biz_days_elapsed = count_business_days(period_start, today)

    # Daily pace
    daily_pace = current_premium / biz_days_elapsed if biz_days_elapsed > 0 else 0

    # Business days remaining to target
    biz_days_remaining = count_business_days(today + timedelta(days=1), target)

    # Total business days (period start to target)
    total_biz_days = count_business_days(period_start, target)

    # Projected premium
    projected_premium = current_premium + (daily_pace * biz_days_remaining)

    # --- Tier goals (use current month premium for tier calc) ---
    from app.models.commission import CommissionTier as TierModel

    # For tier purposes, always use current month
    current_month_premium = float(
        db.query(func.coalesce(func.sum(Sale.written_premium), 0)).filter(
            extract("year", Sale.sale_date) == today.year,
            extract("month", Sale.sale_date) == today.month,
            *user_filters,
        ).scalar() or 0
    )

    month_end = date(today.year, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else date(today.year, 12, 31)
    month_biz_remaining = count_business_days(today + timedelta(days=1), month_end)
    month_daily_pace = current_month_premium / count_business_days(date(today.year, today.month, 1), today) if count_business_days(date(today.year, today.month, 1), today) > 0 else 0
    month_projected = current_month_premium + (month_daily_pace * month_biz_remaining)

    all_tiers = (
        db.query(TierModel)
        .filter(TierModel.is_active == True)
        .order_by(TierModel.tier_level)
        .all()
    )

    current_tier = None
    next_tier = None
    for t in all_tiers:
        if float(t.min_written_premium) <= current_month_premium:
            if t.max_written_premium is None or float(t.max_written_premium) >= current_month_premium:
                current_tier = t

    if current_tier:
        for t in all_tiers:
            if t.tier_level == current_tier.tier_level + 1:
                next_tier = t
                break

    goals = []

    if next_tier:
        next_min = float(next_tier.min_written_premium)
        remaining_to_tier = max(0, next_min - current_month_premium)
        daily_needed = remaining_to_tier / month_biz_remaining if month_biz_remaining > 0 else 0
        on_pace = month_projected >= next_min
        goals.append({
            "label": f"Tier {next_tier.tier_level} ({int(next_tier.commission_rate * 100)}%)",
            "target": next_min,
            "remaining": remaining_to_tier,
            "daily_needed": daily_needed,
            "on_pace": on_pace,
            "progress": min(100, (current_month_premium / next_min * 100)) if next_min > 0 else 100,
        })

    goal_100k = 100000
    remaining_100k = max(0, goal_100k - current_month_premium)
    daily_needed_100k = remaining_100k / month_biz_remaining if month_biz_remaining > 0 else 0
    goals.append({
        "label": "$100K Goal",
        "target": goal_100k,
        "remaining": remaining_100k,
        "daily_needed": daily_needed_100k,
        "on_pace": month_projected >= goal_100k,
        "progress": min(100, (current_month_premium / goal_100k * 100)),
    })

    return {
        "mode": period or "monthly",
        "current_premium": current_premium,
        "ytd_premium": ytd_premium,
        "projected_premium": round(projected_premium, 2),
        "daily_pace": round(daily_pace, 2),
        "biz_days_elapsed": biz_days_elapsed,
        "biz_days_remaining": biz_days_remaining,
        "total_biz_days": total_biz_days,
        "target_date": target.isoformat(),
        "current_tier": {
            "level": current_tier.tier_level if current_tier else 1,
            "rate": float(current_tier.commission_rate) if current_tier else 0.03,
            "description": current_tier.description if current_tier else "",
        } if current_tier else None,
        "goals": goals,
        "period": today.strftime("%Y-%m"),
    }


@router.get("/summary")
def get_sales_summary(
    period: Optional[str] = Query(None, description="monthly, annual, or all-time"),
    year: Optional[int] = None,
    month: Optional[int] = None,
    producer_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get high-level sales summary with optional filters."""
    query = db.query(Sale)

    # Producers only see their own data
    if current_user.role.lower() in ("producer", "retention_specialist"):
        query = query.filter(Sale.producer_id == current_user.id)
    elif producer_id:
        query = query.filter(Sale.producer_id == producer_id)

    # Time filters
    now = datetime.utcnow()
    if period == "last_month":
        lm_year = now.year if now.month > 1 else now.year - 1
        lm_month = now.month - 1 if now.month > 1 else 12
        query = query.filter(
            extract("year", Sale.sale_date) == lm_year,
            extract("month", Sale.sale_date) == lm_month,
        )
    elif period == "monthly" or (month and year):
        y = year or now.year
        m = month or now.month
        query = query.filter(
            extract("year", Sale.sale_date) == y,
            extract("month", Sale.sale_date) == m,
        )
    elif period == "annual" or (year and not month):
        y = year or now.year
        query = query.filter(extract("year", Sale.sale_date) == y)

    sales = query.all()

    total_premium = sum(float(s.written_premium) for s in sales)
    total_items = sum(s.item_count or 1 for s in sales)
    total_policies = len(sales)

    return {
        "total_premium": total_premium,
        "total_items": total_items,
        "total_policies": total_policies,
        "total_sales": len(sales),
    }


@router.get("/by-group")
def get_sales_by_group(
    group_by: str = Query(..., description="lead_source, producer, state, policy_type, carrier"),
    period: Optional[str] = Query(None, description="monthly, annual, all-time"),
    year: Optional[int] = None,
    month: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Group sales by a field and return premium totals per group."""
    # Map group_by to column
    group_map = {
        "lead_source": Sale.lead_source,
        "producer": Sale.producer_id,
        "state": Sale.state,
        "policy_type": Sale.policy_type,
        "carrier": Sale.carrier,
    }

    if group_by not in group_map:
        return {"error": f"Invalid group_by. Choose from: {list(group_map.keys())}"}

    group_col = group_map[group_by]

    query = db.query(
        group_col.label("group"),
        func.sum(Sale.written_premium).label("total_premium"),
        func.count(Sale.id).label("count"),
        func.sum(Sale.item_count).label("total_items"),
    )

    # Producers only see their own
    if current_user.role.lower() in ("producer", "retention_specialist"):
        query = query.filter(Sale.producer_id == current_user.id)

    # Time filters
    now = datetime.utcnow()
    if period == "last_month":
        lm_year = now.year if now.month > 1 else now.year - 1
        lm_month = now.month - 1 if now.month > 1 else 12
        query = query.filter(
            extract("year", Sale.sale_date) == lm_year,
            extract("month", Sale.sale_date) == lm_month,
        )
    elif period == "monthly":
        y = year or now.year
        m = month or now.month
        query = query.filter(
            extract("year", Sale.sale_date) == y,
            extract("month", Sale.sale_date) == m,
        )
    elif period == "annual":
        y = year or now.year
        query = query.filter(extract("year", Sale.sale_date) == y)

    rows = query.group_by(group_col).order_by(func.sum(Sale.written_premium).desc()).all()

    # If grouped by producer, resolve names
    results = []
    if group_by == "producer":
        producer_ids = [r.group for r in rows]
        producers = {u.id: u for u in db.query(User).filter(User.id.in_(producer_ids)).all()}
        for r in rows:
            p = producers.get(r.group)
            results.append({
                "group": p.full_name if p else f"Producer {r.group}",
                "producer_id": r.group,
                "total_premium": float(r.total_premium),
                "count": r.count,
                "total_items": r.total_items or r.count,
            })
    else:
        for r in rows:
            label = str(r.group).replace("_", " ").title() if r.group else "Not Set"
            results.append({
                "group": label,
                "total_premium": float(r.total_premium),
                "count": r.count,
                "total_items": r.total_items or r.count,
            })

    return {"group_by": group_by, "results": results}


@router.get("/sales-table")
def get_sales_table(
    period: Optional[str] = Query(None),
    year: Optional[int] = None,
    month: Optional[int] = None,
    lead_source: Optional[str] = None,
    policy_type: Optional[str] = None,
    carrier: Optional[str] = None,
    state: Optional[str] = None,
    producer_id: Optional[int] = None,
    sort_by: str = Query("sale_date", description="sale_date, written_premium, client_name, effective_date"),
    sort_order: str = Query("desc", description="asc or desc"),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get filterable, sortable sales table data."""
    query = db.query(Sale)

    # Producers only see their own
    if current_user.role.lower() in ("producer", "retention_specialist"):
        query = query.filter(Sale.producer_id == current_user.id)
    elif producer_id:
        query = query.filter(Sale.producer_id == producer_id)

    # Time filters
    now = datetime.utcnow()
    if period == "last_month":
        lm_year = now.year if now.month > 1 else now.year - 1
        lm_month = now.month - 1 if now.month > 1 else 12
        query = query.filter(
            extract("year", Sale.sale_date) == lm_year,
            extract("month", Sale.sale_date) == lm_month,
        )
    elif period == "monthly":
        y = year or now.year
        m = month or now.month
        query = query.filter(
            extract("year", Sale.sale_date) == y,
            extract("month", Sale.sale_date) == m,
        )
    elif period == "annual":
        y = year or now.year
        query = query.filter(extract("year", Sale.sale_date) == y)

    # Field filters
    if lead_source:
        query = query.filter(Sale.lead_source == lead_source)
    if policy_type:
        query = query.filter(Sale.policy_type == policy_type)
    if carrier:
        query = query.filter(Sale.carrier == carrier)
    if state:
        query = query.filter(Sale.state == state)

    # Sorting
    sort_col_map = {
        "sale_date": Sale.sale_date,
        "written_premium": Sale.written_premium,
        "client_name": Sale.client_name,
        "effective_date": Sale.effective_date,
        "policy_type": Sale.policy_type,
        "carrier": Sale.carrier,
    }
    sort_col = sort_col_map.get(sort_by, Sale.sale_date)
    if sort_order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    total = query.count()
    sales = query.offset(skip).limit(limit).all()

    # Resolve producer names
    producer_ids = list(set(s.producer_id for s in sales))
    producers = {u.id: u for u in db.query(User).filter(User.id.in_(producer_ids)).all()}

    results = []
    for s in sales:
        p = producers.get(s.producer_id)
        results.append({
            "id": s.id,
            "sale_date": s.sale_date.isoformat() if s.sale_date else None,
            "effective_date": s.effective_date.isoformat() if s.effective_date else None,
            "policy_number": s.policy_number,
            "client_name": s.client_name,
            "policy_type": s.policy_type,
            "carrier": s.carrier,
            "state": s.state,
            "written_premium": float(s.written_premium),
            "item_count": s.item_count,
            "lead_source": s.lead_source,
            "status": s.status,
            "producer_name": p.full_name if p else "Unknown",
            "producer_id": s.producer_id,
        })

    return {"total": total, "sales": results}


@router.get("/filter-options")
def get_filter_options(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get available filter values for dropdowns."""
    query = db.query(Sale)
    if current_user.role.lower() in ("producer", "retention_specialist"):
        query = query.filter(Sale.producer_id == current_user.id)

    carriers = [r[0] for r in query.with_entities(Sale.carrier).distinct().all() if r[0]]
    states = [r[0] for r in query.with_entities(Sale.state).distinct().all() if r[0]]

    # Get producers (admin only)
    producers = []
    if current_user.role.lower() == "admin":
        all_producers = db.query(User).all()
        producers = [{"id": u.id, "name": u.full_name, "code": u.producer_code} for u in all_producers]

    return {
        "carriers": sorted(carriers),
        "states": sorted(states),
        "producers": producers,
        "lead_sources": [
            "referral", "customer_referral", "website", "cold_call", "call_in",
            "social_media", "email_campaign", "walk_in", "quote_wizard",
            "insurance_ai_call", "rewrite", "other"
        ],
        "policy_types": [
            "auto", "home", "renters", "condo", "landlord", "umbrella",
            "motorcycle", "boat", "rv", "life", "health", "bundled",
            "commercial", "other"
        ],
    }
