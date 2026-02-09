"""Analytics API — filterable, groupable sales data for dashboards and reports."""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract
from datetime import datetime, date
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


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
    if current_user.role == "producer":
        query = query.filter(Sale.producer_id == current_user.id)
    elif producer_id:
        query = query.filter(Sale.producer_id == producer_id)

    # Time filters
    now = datetime.utcnow()
    if period == "monthly" or (month and year):
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
    if current_user.role == "producer":
        query = query.filter(Sale.producer_id == current_user.id)

    # Time filters
    now = datetime.utcnow()
    if period == "monthly":
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
    if current_user.role == "producer":
        query = query.filter(Sale.producer_id == current_user.id)
    elif producer_id:
        query = query.filter(Sale.producer_id == producer_id)

    # Time filters
    now = datetime.utcnow()
    if period == "monthly":
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
            "policy_type": s.policy_type.value if s.policy_type else None,
            "carrier": s.carrier,
            "state": s.state,
            "written_premium": float(s.written_premium),
            "item_count": s.item_count,
            "lead_source": s.lead_source.value if s.lead_source else None,
            "status": s.status.value,
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
    if current_user.role == "producer":
        query = query.filter(Sale.producer_id == current_user.id)

    carriers = [r[0] for r in query.with_entities(Sale.carrier).distinct().all() if r[0]]
    states = [r[0] for r in query.with_entities(Sale.state).distinct().all() if r[0]]

    # Get producers (admin only)
    producers = []
    if current_user.role == "admin":
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
