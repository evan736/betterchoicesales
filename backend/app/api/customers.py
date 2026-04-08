"""Customers API — internal customer directory with NowCerts integration."""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Form, UploadFile, File, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, distinct

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy
from app.services.nowcerts import (
    get_nowcerts_client,
    normalize_insured,
    normalize_policy,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/customers", tags=["customers"])


# ── Search / List ──────────────────────────────────────────────────

@router.get("/search")
def search_customers(
    q: str = Query("", description="Search by name, email, or phone"),
    source: str = Query("local", description="'local' for cached, 'nowcerts' for live API, 'both' for combined"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search customers. Supports local cache, live NowCerts, or both."""
    results = []

    # Local database search
    if source in ("local", "both"):
        query = db.query(Customer)
        if q.strip():
            search = f"%{q.strip()}%"
            # Find customer IDs matching by policy number
            policy_customer_ids = db.query(CustomerPolicy.customer_id).filter(
                CustomerPolicy.policy_number.ilike(search)
            ).distinct().all()
            policy_cids = [cid for (cid,) in policy_customer_ids]

            filters = [
                Customer.full_name.ilike(search),
                Customer.email.ilike(search),
                Customer.phone.ilike(search),
                Customer.mobile_phone.ilike(search),
                Customer.address.ilike(search),
                Customer.city.ilike(search),
                Customer.zip_code.ilike(search),
            ]

            # Phone normalization: strip non-digits and search against stripped DB values
            import re
            digits_only = re.sub(r'\D', '', q.strip())
            if len(digits_only) >= 7:
                # Search DB phone fields with formatting stripped
                from sqlalchemy import func as sqlfunc
                stripped_phone = f"%{digits_only}%"
                filters.append(sqlfunc.regexp_replace(Customer.phone, '[^0-9]', '', 'g').ilike(stripped_phone))
                filters.append(sqlfunc.regexp_replace(Customer.mobile_phone, '[^0-9]', '', 'g').ilike(stripped_phone))

            if policy_cids:
                filters.append(Customer.id.in_(policy_cids))

            query = query.filter(or_(*filters))
        query = query.order_by(Customer.full_name)
        total = query.count()
        customers = query.offset((page - 1) * page_size).limit(page_size).all()

        # Enrich with active policy status
        results = []
        for c in customers:
            d = _customer_to_dict(c)
            has_active = db.query(CustomerPolicy).filter(
                CustomerPolicy.customer_id == c.id,
                func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"])
            ).first() is not None
            pol_count = db.query(func.count(CustomerPolicy.id)).filter(
                CustomerPolicy.customer_id == c.id
            ).scalar() or 0
            d["has_active_policy"] = has_active
            d["policy_count"] = pol_count
            results.append(d)

        if source == "local":
            return {"customers": results, "total": total, "page": page, "source": "local"}

    # NowCerts live search
    if source in ("nowcerts", "both"):
        client = get_nowcerts_client()
        if not client.is_configured:
            if source == "nowcerts":
                raise HTTPException(status_code=400, detail="NowCerts not configured. Add NOWCERTS_USERNAME and NOWCERTS_PASSWORD to environment variables.")
            # If 'both', just return local results
            return {"customers": results, "total": len(results), "page": page, "source": "local_only"}

        try:
            nc_results = []
            q_stripped = q.strip() if q else ""

            # Detect if query looks like a policy number (mostly digits, or short alphanumeric)
            is_policy_like = q_stripped and (
                q_stripped.replace(" ", "").replace("-", "").isdigit() or
                (len(q_stripped) >= 5 and sum(c.isdigit() for c in q_stripped) >= len(q_stripped) * 0.5)
            )

            if is_policy_like:
                # Try policy number search first
                try:
                    nc_results = client.search_by_policy_number(q_stripped)
                except Exception as pe:
                    logger.warning("NowCerts policy number search failed: %s", pe)

            if not nc_results:
                # Standard name/email/phone search
                nc_results = client.search_insureds(q_stripped, limit=page_size)

            if not nc_results and q_stripped and not is_policy_like:
                # Last resort: try as policy number anyway
                try:
                    nc_results = client.search_by_policy_number(q_stripped)
                except Exception as pe:
                    logger.warning("NowCerts policy number fallback failed: %s", pe)

            nc_customers = []
            for raw in nc_results:
                normalized = normalize_insured(raw)
                nc_customers.append({
                    **normalized,
                    "id": None,
                    "source": "nowcerts",
                    "policy_count": 0,
                })

            if source == "nowcerts":
                return {"customers": nc_customers, "total": len(nc_customers), "page": 1, "source": "nowcerts"}

            # Merge: deduplicate by nowcerts_insured_id
            existing_ids = {c.get("nowcerts_insured_id") for c in results if c.get("nowcerts_insured_id")}
            for nc in nc_customers:
                if nc.get("nowcerts_insured_id") and nc["nowcerts_insured_id"] not in existing_ids:
                    results.append(nc)
                    existing_ids.add(nc["nowcerts_insured_id"])

            return {"customers": results, "total": len(results), "page": page, "source": "both"}

        except Exception as e:
            logger.error("NowCerts search error: %s", e)
            if source == "nowcerts":
                raise HTTPException(status_code=502, detail=f"NowCerts API error: {str(e)}")
            # If 'both', return local results with warning
            return {"customers": results, "total": len(results), "page": page, "source": "local_only", "warning": str(e)}

    return {"customers": results, "total": len(results), "page": page, "source": source}


# ══════════════════════════════════════════════════════════════════
# STATIC ROUTES — must come before /{customer_id} to avoid conflicts
# ══════════════════════════════════════════════════════════════════

@router.get("/nowcerts/status")
def nowcerts_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check NowCerts connection status and local cache stats."""
    client = get_nowcerts_client()
    configured = client.is_configured

    connected = False
    auth_error = None
    if configured:
        try:
            client._token = None
            client._token_expiry = None
            client._authenticate()
            connected = True
        except Exception as e:
            auth_error = str(e)
            logger.error("NowCerts connection test failed: %s", e)

    total_customers = db.query(func.count(Customer.id)).scalar() or 0
    total_policies = db.query(func.count(CustomerPolicy.id)).scalar() or 0
    last_sync = db.query(func.max(Customer.last_synced_at)).scalar()

    return {
        "configured": configured,
        "connected": connected,
        "auth_error": auth_error,
        "auth_details": client._last_auth_errors if not connected else [],
        "local_customers": total_customers,
        "local_policies": total_policies,
        "last_sync": last_sync.isoformat() if last_sync else None,
    }


@router.get("/nowcerts/debug")
def nowcerts_debug(
    current_user: User = Depends(get_current_user),
):
    """Debug endpoint: shows raw API responses from NowCerts. Admin only."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    client = get_nowcerts_client()
    if not client.is_configured:
        return {"error": "NowCerts not configured"}

    import requests as req
    results = {}

    # Test auth
    try:
        client._token = None
        client._token_expiry = None
        client._authenticate()
        results["auth"] = "OK"
    except Exception as e:
        results["auth"] = f"FAILED: {str(e)[:300]}"
        return results

    # Test GetInsureds
    try:
        resp = req.get(
            f"{client.base_url}/api/Zapier/GetInsureds",
            headers=client._headers(),
            timeout=30,
        )
        results["get_insureds_status"] = resp.status_code
        try:
            data = resp.json()
            if isinstance(data, list):
                results["get_insureds_count"] = len(data)
                results["get_insureds_sample"] = data[0] if data else None
            else:
                results["get_insureds_response"] = str(data)[:500]
        except Exception:
            results["get_insureds_raw"] = resp.text[:500]
    except Exception as e:
        results["get_insureds_error"] = str(e)[:300]

    # Test InsuredDetailList (OData - the real paginated endpoint)
    try:
        resp = req.get(
            f"{client.base_url}/api/InsuredDetailList?$count=true&$orderby=id%20asc&$skip=0&$top=5",
            headers=client._headers(),
            timeout=30,
        )
        results["insured_detail_list_status"] = resp.status_code
        try:
            data = resp.json()
            results["insured_detail_list_total"] = data.get("@odata.count", "N/A")
            values = data.get("value", [])
            results["insured_detail_list_batch"] = len(values)
            if values:
                results["insured_detail_list_sample"] = values[0]
        except Exception:
            results["insured_detail_list_raw"] = resp.text[:500]
    except Exception as e:
        results["insured_detail_list_error"] = str(e)[:300]

    # Test GetPolicies
    try:
        resp = req.get(
            f"{client.base_url}/api/Zapier/GetPolicies",
            headers=client._headers(),
            timeout=30,
        )
        results["get_policies_status"] = resp.status_code
        try:
            data = resp.json()
            if isinstance(data, list):
                results["get_policies_count"] = len(data)
                results["get_policies_sample"] = data[0] if data else None
                unique_insureds = set(p.get("insured_database_id", "") for p in data if p.get("insured_database_id"))
                results["get_policies_unique_insureds"] = len(unique_insureds)
            else:
                results["get_policies_response"] = str(data)[:500]
        except Exception:
            results["get_policies_raw"] = resp.text[:500]
    except Exception as e:
        results["get_policies_error"] = str(e)[:300]

    return results


# ── Agency Stats ──────────────────────────────────────────────────

@router.get("/agency-stats")
def agency_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get agency-level statistics: active customers, total premium, etc."""
    from app.core.cache import get as cache_get, set as cache_set
    cached = cache_get("agency_stats")
    if cached is not None:
        return cached

    from sqlalchemy import distinct
    from decimal import Decimal

    total_customers = db.query(func.count(Customer.id)).scalar() or 0

    # Customers with at least one active policy
    active_subq = (
        db.query(distinct(CustomerPolicy.customer_id))
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .subquery()
    )
    active_customers = db.query(func.count()).select_from(active_subq).scalar() or 0

    active_policies = (
        db.query(func.count(CustomerPolicy.id))
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .scalar() or 0
    )

    total_policies = db.query(func.count(CustomerPolicy.id)).scalar() or 0

    # Total active premium — annualize 6-month auto policies
    active_rows = (
        db.query(CustomerPolicy)
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .all()
    )
    total_premium = Decimal("0")
    for p in active_rows:
        if not p.premium:
            continue
        prem = Decimal(str(p.premium))
        lob = (p.line_of_business or "").lower()
        ptype = (p.policy_type or "").lower()
        is_auto = any(kw in lob or kw in ptype for kw in ["auto", "vehicle", "car", "motorcycle"])
        if is_auto and p.effective_date and p.expiration_date:
            try:
                eff = p.effective_date.replace(tzinfo=None) if hasattr(p.effective_date, 'replace') else p.effective_date
                exp = p.expiration_date.replace(tzinfo=None) if hasattr(p.expiration_date, 'replace') else p.expiration_date
                term_days = (exp - eff).days
                if 150 <= term_days <= 200:
                    prem = prem * 2
            except Exception:
                pass
        total_premium += prem

    last_sync = db.query(func.max(Customer.last_synced_at)).scalar()

    # Monthly customer growth — compare to last month's snapshot
    monthly_growth = None
    try:
        from app.models.agency_snapshot import AgencySnapshot
        from datetime import date, timedelta
        today = date.today()
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        # Get the latest snapshot from last month
        last_month_snap = (
            db.query(AgencySnapshot)
            .filter(AgencySnapshot.snapshot_date >= last_month_start,
                    AgencySnapshot.snapshot_date <= last_month_end)
            .order_by(AgencySnapshot.snapshot_date.desc())
            .first()
        )
        if last_month_snap:
            monthly_growth = active_customers - last_month_snap.active_customers
    except Exception:
        pass

    _stats_result = {
        "total_customers": total_customers,
        "active_customers": active_customers,
        "active_policies": active_policies,
        "total_policies": total_policies,
        "total_active_premium_annualized": float(total_premium),
        "monthly_customer_growth": monthly_growth,
        "last_sync": last_sync.isoformat() if last_sync else None,
    }
    cache_set("agency_stats", _stats_result, ttl_seconds=120)
    return _stats_result


@router.post("/capture-snapshot")
def capture_snapshot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture a point-in-time snapshot of agency metrics for growth tracking."""
    from sqlalchemy import distinct
    from decimal import Decimal
    from datetime import date
    from app.models.agency_snapshot import AgencySnapshot
    from app.models.sale import Sale

    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    today = date.today()
    period = today.strftime("%Y-%m")

    # Check if snapshot already exists for today
    existing = db.query(AgencySnapshot).filter(AgencySnapshot.snapshot_date == today).first()

    total_customers = db.query(func.count(Customer.id)).scalar() or 0

    active_subq = (
        db.query(distinct(CustomerPolicy.customer_id))
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .subquery()
    )
    active_customers = db.query(func.count()).select_from(active_subq).scalar() or 0

    active_policies = (
        db.query(func.count(CustomerPolicy.id))
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .scalar() or 0
    )
    total_policies = db.query(func.count(CustomerPolicy.id)).scalar() or 0

    # Annualized premium
    active_rows = (
        db.query(CustomerPolicy)
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .all()
    )
    total_premium = Decimal("0")
    for p in active_rows:
        if not p.premium:
            continue
        prem = Decimal(str(p.premium))
        lob = (p.line_of_business or "").lower()
        ptype = (p.policy_type or "").lower()
        is_auto = any(kw in lob or kw in ptype for kw in ["auto", "vehicle", "car", "motorcycle"])
        if is_auto and p.effective_date and p.expiration_date:
            try:
                eff = p.effective_date.replace(tzinfo=None) if hasattr(p.effective_date, 'replace') else p.effective_date
                exp = p.expiration_date.replace(tzinfo=None) if hasattr(p.expiration_date, 'replace') else p.expiration_date
                term_days = (exp - eff).days
                if 150 <= term_days <= 200:
                    prem = prem * 2
            except Exception:
                pass
        total_premium += prem

    # Monthly sales
    from sqlalchemy import extract as sql_ext
    month_sales = (
        db.query(func.count(Sale.id), func.coalesce(func.sum(Sale.written_premium), 0))
        .filter(sql_ext("year", Sale.sale_date) == today.year,
                sql_ext("month", Sale.sale_date) == today.month)
        .first()
    )
    new_sales_count = month_sales[0] if month_sales else 0
    new_sales_premium = float(month_sales[1]) if month_sales else 0

    # Cancellations this month
    cancel_count = (
        db.query(func.count(Sale.id))
        .filter(Sale.status == "cancelled",
                sql_ext("year", Sale.cancelled_date) == today.year,
                sql_ext("month", Sale.cancelled_date) == today.month)
        .scalar() or 0
    )

    if existing:
        existing.active_customers = active_customers
        existing.total_customers = total_customers
        existing.active_policies = active_policies
        existing.total_policies = total_policies
        existing.active_premium_annualized = float(total_premium)
        existing.new_sales_count = new_sales_count
        existing.new_sales_premium = new_sales_premium
        existing.cancellations_count = cancel_count
        snapshot = existing
    else:
        snapshot = AgencySnapshot(
            snapshot_date=today,
            period=period,
            active_customers=active_customers,
            total_customers=total_customers,
            active_policies=active_policies,
            total_policies=total_policies,
            active_premium_annualized=float(total_premium),
            new_sales_count=new_sales_count,
            new_sales_premium=new_sales_premium,
            cancellations_count=cancel_count,
        )
        db.add(snapshot)

    db.commit()

    return {
        "snapshot_date": str(today),
        "period": period,
        "active_customers": active_customers,
        "active_policies": active_policies,
        "active_premium": float(total_premium),
        "new_sales": new_sales_count,
        "cancellations": cancel_count,
    }


@router.get("/growth-data")
def growth_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get growth data for charts — customer count and premium over time."""
    from app.models.agency_snapshot import AgencySnapshot

    snapshots = (
        db.query(AgencySnapshot)
        .order_by(AgencySnapshot.snapshot_date.asc())
        .all()
    )

    data = []
    for s in snapshots:
        data.append({
            "date": str(s.snapshot_date),
            "period": s.period,
            "active_customers": s.active_customers,
            "total_customers": s.total_customers,
            "active_policies": s.active_policies,
            "active_premium": float(s.active_premium_annualized or 0),
            "new_sales": s.new_sales_count or 0,
            "new_sales_premium": float(s.new_sales_premium or 0),
            "cancellations": s.cancellations_count or 0,
        })

    # Also compute MoM and YoY changes
    monthly = {}
    for d in data:
        p = d["period"]
        if p not in monthly or d["date"] > monthly[p]["date"]:
            monthly[p] = d

    periods = sorted(monthly.keys())
    growth_summary = []
    for i, p in enumerate(periods):
        entry = {**monthly[p]}
        if i > 0:
            prev = monthly[periods[i-1]]
            entry["customer_change"] = entry["active_customers"] - prev["active_customers"]
            entry["premium_change"] = entry["active_premium"] - prev["active_premium"]
            entry["customer_change_pct"] = round((entry["customer_change"] / prev["active_customers"] * 100), 1) if prev["active_customers"] else 0
            entry["premium_change_pct"] = round((entry["premium_change"] / prev["active_premium"] * 100), 1) if prev["active_premium"] else 0
        # YoY: compare to same month last year
        yoy_period = str(int(p[:4]) - 1) + p[4:]
        if yoy_period in monthly:
            yoy = monthly[yoy_period]
            entry["yoy_customer_change"] = entry["active_customers"] - yoy["active_customers"]
            entry["yoy_premium_change"] = entry["active_premium"] - yoy["active_premium"]
            entry["yoy_customer_pct"] = round((entry["yoy_customer_change"] / yoy["active_customers"] * 100), 1) if yoy["active_customers"] else 0
            entry["yoy_premium_pct"] = round((entry["yoy_premium_change"] / yoy["active_premium"] * 100), 1) if yoy["active_premium"] else 0

        growth_summary.append(entry)

    return {
        "snapshots": data,
        "growth_summary": growth_summary,
    }


@router.get("/state-distribution")
def state_distribution(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get active customer count by state for heatmap display."""
    # Only count customers who have at least one active policy
    active_customer_ids = (
        db.query(distinct(CustomerPolicy.customer_id))
        .filter(func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
        .subquery()
    )
    rows = (
        db.query(Customer.state, func.count(Customer.id))
        .filter(
            Customer.state.isnot(None),
            Customer.state != "",
            Customer.id.in_(active_customer_ids),
        )
        .group_by(Customer.state)
        .all()
    )
    return _states_to_abbr({row[0].upper().strip(): row[1] for row in rows if row[0]})


_STATE_NAME_TO_ABBR = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME",
    "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE",
    "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
    "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}

def _states_to_abbr(raw: dict) -> dict:
    result = {}
    for key, count in raw.items():
        if len(key) == 2:
            result[key] = result.get(key, 0) + count
        else:
            abbr = _STATE_NAME_TO_ABBR.get(key)
            if abbr:
                result[abbr] = result.get(abbr, 0) + count
    return result


# ── Duplicate Detection ──────────────────────────────────────────

@router.get("/duplicates")
def find_duplicates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find potential duplicate customers by name, phone, or email."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    all_customers = db.query(Customer).order_by(Customer.full_name).limit(10000).all()  # Capped for safety

    name_groups: dict[str, list] = {}
    phone_groups: dict[str, list] = {}
    email_groups: dict[str, list] = {}

    for c in all_customers:
        nk = (c.full_name or "").strip().lower()
        if nk and len(nk) > 2:
            name_groups.setdefault(nk, []).append(c)

        for phone in [c.phone, c.mobile_phone]:
            if phone:
                digits = ''.join(d for d in phone if d.isdigit())
                if len(digits) >= 7:
                    phone_groups.setdefault(digits[-10:], []).append(c)

        ek = (c.email or "").strip().lower()
        if ek and "@" in ek:
            email_groups.setdefault(ek, []).append(c)

    duplicate_sets = []
    seen_sets = set()

    for label, groups in [("name", name_groups), ("phone", phone_groups), ("email", email_groups)]:
        for key, members in groups.items():
            if len(members) < 2:
                continue
            member_ids = frozenset(m.id for m in members)
            if member_ids in seen_sets:
                continue
            seen_sets.add(member_ids)

            member_data = []
            for m in members:
                pol_count = db.query(func.count(CustomerPolicy.id)).filter(
                    CustomerPolicy.customer_id == m.id
                ).scalar() or 0
                has_active = db.query(CustomerPolicy).filter(
                    CustomerPolicy.customer_id == m.id,
                    func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"])
                ).first() is not None
                member_data.append({
                    **_customer_to_dict(m),
                    "policy_count": pol_count,
                    "has_active_policy": has_active,
                })

            duplicate_sets.append({
                "match_type": label,
                "match_value": key,
                "customers": member_data,
            })

    return {"duplicate_sets": duplicate_sets[:100], "total_sets": len(duplicate_sets)}


@router.post("/merge")
def merge_customers(
    keep_id: int = Query(..., description="Customer ID to keep"),
    merge_ids: str = Query(..., description="Comma-separated IDs to merge"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Merge duplicates: move policies to keep_id, delete others."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    keep = db.query(Customer).filter(Customer.id == keep_id).first()
    if not keep:
        raise HTTPException(status_code=404, detail="Keep customer not found")

    ids_to_merge = [int(x.strip()) for x in merge_ids.split(",") if x.strip()]
    policies_moved = 0
    customers_deleted = 0

    for mid in ids_to_merge:
        if mid == keep_id:
            continue
        mc = db.query(Customer).filter(Customer.id == mid).first()
        if not mc:
            continue
        for p in db.query(CustomerPolicy).filter(CustomerPolicy.customer_id == mid).all():
            p.customer_id = keep_id
            policies_moved += 1
        for field in ["email", "phone", "mobile_phone", "address", "city", "state", "zip_code", "agent_name"]:
            if not getattr(keep, field) and getattr(mc, field):
                setattr(keep, field, getattr(mc, field))
        db.delete(mc)
        customers_deleted += 1

    db.commit()
    return {"kept": _customer_to_dict(keep), "policies_moved": policies_moved, "customers_deleted": customers_deleted}


# ── Customer Detail ────────────────────────────────────────────────


# ── Import from NowCerts (save live result to local cache) ─────────

@router.post("/import-from-nowcerts")
def import_from_nowcerts(
    nowcerts_insured_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a specific NowCerts insured into the local database."""
    client = get_nowcerts_client()
    if not client.is_configured:
        raise HTTPException(status_code=400, detail="NowCerts not configured")

    # Check if already imported
    existing = db.query(Customer).filter(
        Customer.nowcerts_insured_id == nowcerts_insured_id
    ).first()
    if existing:
        return {"customer": _customer_to_dict(existing), "already_existed": True}

    try:
        raw = client.get_insured(nowcerts_insured_id)
        if not raw:
            raise HTTPException(status_code=404, detail="Insured not found in NowCerts")

        normalized = normalize_insured(raw)
        customer = Customer(**normalized, last_synced_at=datetime.utcnow())
        db.add(customer)
        db.commit()
        db.refresh(customer)

        # Import policies too
        raw_policies = client.get_insured_policies(nowcerts_insured_id)
        for raw_pol in raw_policies:
            norm = normalize_policy(raw_pol, customer.id)
            policy = CustomerPolicy(**norm, last_synced_at=datetime.utcnow())
            db.add(policy)
        db.commit()

        return {"customer": _customer_to_dict(customer), "already_existed": False}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Import failed: %s", e)
        raise HTTPException(status_code=502, detail=f"NowCerts import failed: {str(e)}")



# ── Bulk sync ──────────────────────────────────────────────────────

@router.post("/sync-all")
def sync_all_customers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull all insureds + policies from NowCerts and upsert into local cache. Admin only."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    client = get_nowcerts_client()
    if not client.is_configured:
        raise HTTPException(status_code=400, detail="NowCerts not configured")

    imported = 0
    updated = 0
    policies_imported = 0
    policies_updated = 0
    errors = []

    try:
        # Step 1: Sync all insureds via OData pagination (handles 3000+)
        logger.info("Starting full NowCerts sync...")
        all_insureds = client.get_all_insureds_paginated(page_size=200)
        logger.info("Fetched %d insureds from NowCerts", len(all_insureds))

        for raw in all_insureds:
            try:
                normalized = normalize_insured(raw)
                nc_id = normalized.get("nowcerts_insured_id")
                if not nc_id:
                    continue

                existing = db.query(Customer).filter(
                    Customer.nowcerts_insured_id == nc_id
                ).first()

                if existing:
                    for k, v in normalized.items():
                        if v is not None:
                            setattr(existing, k, v)
                    existing.last_synced_at = datetime.utcnow()
                    updated += 1
                else:
                    customer = Customer(**normalized, last_synced_at=datetime.utcnow())
                    db.add(customer)
                    imported += 1

                # Commit in batches of 200
                if (imported + updated) % 200 == 0:
                    db.commit()
            except Exception as e:
                errors.append(f"Insured: {str(e)[:80]}")

        db.commit()
        logger.info("Insureds synced: %d imported, %d updated", imported, updated)

        # Step 2: Sync policies via OData PolicyDetailList (paginated)
        try:
            all_policies = client.get_all_policies_paginated(page_size=200)
            logger.info("Fetched %d policies from NowCerts PolicyDetailList", len(all_policies))

            for raw_pol in all_policies:
                try:
                    iid = raw_pol.get("insuredDatabaseId", "")
                    if not iid:
                        continue

                    customer = db.query(Customer).filter(
                        Customer.nowcerts_insured_id == iid
                    ).first()
                    if not customer:
                        # Create minimal customer from policy's embedded insured data
                        cust_data = {
                            "nowcerts_insured_id": iid,
                            "first_name": raw_pol.get("insuredFirstName", ""),
                            "last_name": raw_pol.get("insuredLastName", ""),
                            "full_name": raw_pol.get("insuredCommercialName") or f"{raw_pol.get('insuredFirstName', '')} {raw_pol.get('insuredLastName', '')}".strip() or "Unknown",
                            "email": raw_pol.get("insuredEmail", ""),
                            "phone": raw_pol.get("insuredPhoneNumber", ""),
                            "mobile_phone": raw_pol.get("insuredCellPhone", ""),
                            "address": raw_pol.get("insuredAddressLine1", ""),
                            "city": raw_pol.get("insuredCity", ""),
                            "state": raw_pol.get("insuredState", ""),
                            "zip_code": raw_pol.get("insuredZipCode", ""),
                            "last_synced_at": datetime.utcnow(),
                        }
                        customer = Customer(**cust_data)
                        db.add(customer)
                        db.flush()
                        imported += 1

                    norm_pol = client._normalize_odata_policy(raw_pol, customer.id)
                    nc_pol_id = norm_pol.get("nowcerts_policy_id")
                    if nc_pol_id:
                        existing_pol = db.query(CustomerPolicy).filter(
                            CustomerPolicy.nowcerts_policy_id == nc_pol_id
                        ).first()
                        if existing_pol:
                            for k, v in norm_pol.items():
                                if v is not None:
                                    setattr(existing_pol, k, v)
                            existing_pol.last_synced_at = datetime.utcnow()
                            policies_updated += 1
                        else:
                            policy = CustomerPolicy(**norm_pol, last_synced_at=datetime.utcnow())
                            db.add(policy)
                            policies_imported += 1

                    # Commit in batches
                    if (policies_imported + policies_updated) % 200 == 0:
                        db.commit()
                except Exception as e:
                    errors.append(f"Policy: {str(e)[:80]}")

            db.commit()
        except Exception as e:
            errors.append(f"Policy sync: {str(e)[:100]}")

    except Exception as e:
        logger.error("Bulk sync error: %s", e)
        errors.append(str(e))

    logger.info("Sync complete: %d customers imported, %d updated, %d policies imported, %d policies updated",
                imported, updated, policies_imported, policies_updated)

    return {
        "imported": imported,
        "updated": updated,
        "policies_imported": policies_imported,
        "policies_updated": policies_updated,
        "total_fetched": len(all_insureds) if 'all_insureds' in dir() else 0,
        "errors": errors[:20],
    }



@router.post("/quick-email")
def send_quick_email(
    to_email: str = Form(...),
    to_name: str = Form(""),
    cc_emails: str = Form(""),  # comma-separated additional emails
    subject: str = Form(...),
    body: str = Form(...),
    send_as: str = Form("service"),  # "personal" or "service"
    customer_id: Optional[int] = Form(None),  # for NowCerts note
    attachments: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a quick freeform email to a customer via Mailgun with optional attachments."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")

    if not to_email or not subject or not body:
        raise HTTPException(status_code=400, detail="Email, subject, and body are required")

    # Build recipient list
    all_to = [f"{to_name} <{to_email}>" if to_name else to_email]
    cc_list = [e.strip() for e in cc_emails.split(",") if e.strip()] if cc_emails else []

    # Determine sender identity
    if send_as == "personal" and current_user.email:
        from_email = current_user.email
        reply_to = current_user.email
    else:
        from_email = "service@betterchoiceins.com"
        reply_to = "service@betterchoiceins.com"

    from_str = f"{current_user.full_name} <{from_email}>"

    # Build branded HTML using shared template
    from app.api.email_inbox import _build_branded_email
    html_body = body.replace('\n', '<br>')
    html = _build_branded_email(html_body, current_user.full_name, from_email)

    try:
        # Build multipart form data for Mailgun
        data = {
            "from": from_str,
            "to": all_to,
            "subject": subject,
            "html": html,
            "h:Reply-To": reply_to,
        }
        if cc_list:
            data["cc"] = cc_list

        files = []
        att_names = []
        logger.info(f"📎 Quick email: {len(attachments)} attachments received")
        for att in attachments:
            # Skip empty/placeholder upload entries (FastAPI sends empty UploadFile when no files attached)
            if not att.filename or att.filename == '':
                continue
            att.file.seek(0)
            content = att.file.read()
            if len(content) == 0:
                logger.warning(f"📎 Skipping empty file: {att.filename}")
                continue
            # Map common extensions to MIME types if content_type is missing/generic
            ct = att.content_type or "application/octet-stream"
            if ct == "application/octet-stream" and att.filename:
                ext = att.filename.rsplit('.', 1)[-1].lower() if '.' in att.filename else ''
                mime_map = {
                    'doc': 'application/msword',
                    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'xls': 'application/vnd.ms-excel',
                    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'csv': 'text/csv',
                    'pdf': 'application/pdf',
                    'png': 'image/png',
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg',
                    'gif': 'image/gif',
                    'txt': 'text/plain',
                    'rtf': 'application/rtf',
                    'eml': 'message/rfc822',
                }
                ct = mime_map.get(ext, ct)
            logger.info(f"📎 File: {att.filename} ({len(content)} bytes, {ct})")
            files.append(("attachment", (att.filename, content, ct)))
            att_names.append(att.filename)

        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=data,
            files=files if files else None,
        )
        resp.raise_for_status()
        att_count = len(files)
        all_recipients = [to_email] + cc_list
        logger.info(f"Quick email sent to {', '.join(all_recipients)} by {current_user.username} as {from_email}: {subject} ({att_count} attachments)")

        # Push note to NowCerts for this customer
        _log_email_to_nowcerts(
            db=db,
            customer_id=customer_id,
            customer_email=to_email,
            customer_name=to_name,
            direction="outbound",
            subject=subject,
            body_summary=body[:500],
            sender=current_user.full_name,
            cc_list=cc_list,
            att_names=att_names,
        )

        return {"status": "sent", "to": to_email, "cc": cc_list, "subject": subject, "attachments": att_count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quick email failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send: {str(e)}")


@router.get("/{customer_id}")
def get_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single customer with their policies."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Only show policies from the last 2 years (active or expired within 2 years)
    from datetime import datetime, timedelta
    two_years_ago = datetime.utcnow() - timedelta(days=730)

    policies = (
        db.query(CustomerPolicy)
        .filter(
            CustomerPolicy.customer_id == customer_id,
            or_(
                CustomerPolicy.expiration_date.is_(None),
                CustomerPolicy.expiration_date >= two_years_ago,
                func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]),
            ),
        )
        .order_by(CustomerPolicy.effective_date.desc())
        .all()
    )

    # Enrich policies with first-term sale producer info
    from app.models.sale import Sale
    from app.models.user import User as UserModel
    policy_dicts = []
    now = datetime.utcnow()

    for p in policies:
        pd = _policy_to_dict(p)
        pd["first_term_producer"] = None

        if p.policy_number:
            # Normalize: strip spaces, dashes for comparison
            nowcerts_pn = p.policy_number.replace(" ", "").replace("-", "").strip()
            
            # 1) Exact match
            sale = db.query(Sale).filter(
                Sale.policy_number == p.policy_number,
                Sale.status != "cancelled",
            ).first()

            # 2) ilike match on first 10 chars (handles NatGen term suffixes like 203352764100 vs 2033527641)
            if not sale and nowcerts_pn and len(nowcerts_pn) >= 8:
                prefix = nowcerts_pn[:10]
                sale = db.query(Sale).filter(
                    Sale.policy_number.ilike(f"{prefix}%"),
                    Sale.status != "cancelled",
                ).first()

            # 3) Reverse: NowCerts pn starts with sale policy number (sale=2033527641, nowcerts=203352764100)
            if not sale and nowcerts_pn and len(nowcerts_pn) >= 10:
                # Narrow by customer name to avoid full table scan
                cust_name = (customer.full_name or "").strip()
                name_filter = Sale.client_name.ilike(f"%{cust_name.split()[-1]}%") if cust_name else Sale.id > 0
                possible_sales = db.query(Sale).filter(
                    Sale.status != "cancelled",
                    name_filter,
                ).limit(50).all()
                for s in possible_sales:
                    sale_pn_clean = (s.policy_number or "").replace(" ", "").replace("-", "").strip()
                    if sale_pn_clean and len(sale_pn_clean) >= 8 and nowcerts_pn.startswith(sale_pn_clean):
                        sale = s
                        break

            if sale:
                # Check if still in first term: policy hasn't reached its first expiration date
                exp = p.expiration_date
                if exp and now < exp:
                    # Still in first term — show the producer
                    producer = db.query(UserModel).filter(UserModel.id == sale.producer_id).first()
                    if producer:
                        pd["first_term_producer"] = producer.full_name or producer.username
                        pd["first_term_sale_date"] = sale.sale_date.isoformat() if sale.sale_date else None

        policy_dicts.append(pd)

    return {
        "customer": _customer_to_dict(customer),
        "policies": policy_dicts,
    }


@router.patch("/{customer_id}")
def update_customer(
    customer_id: int,
    body: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update customer fields locally and optionally push to NowCerts.
    
    Body: { fields: {email, phone, mobile_phone, address, city, state, zip_code}, push_to_nowcerts: true }
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    fields = body.get("fields", {})
    push_to_nowcerts = body.get("push_to_nowcerts", False)

    # Allowed editable fields → local DB column mapping
    ALLOWED = {
        "email": "email",
        "phone": "phone",
        "mobile_phone": "mobile_phone",
        "address": "address",
        "city": "city",
        "state": "state",
        "zip_code": "zip_code",
    }

    updated = {}
    for key, col in ALLOWED.items():
        if key in fields:
            val = (fields[key] or "").strip()
            setattr(customer, col, val if val else None)
            updated[key] = val

    db.commit()
    db.refresh(customer)

    nc_result = None
    if push_to_nowcerts and customer.nowcerts_insured_id and updated:
        try:
            from app.services.nowcerts import get_nowcerts_client
            nc = get_nowcerts_client()

            # Map our field names → NowCerts API camelCase field names
            NC_MAP = {
                "email": "eMail",
                "phone": "phone",
                "mobile_phone": "cellPhone",
                "address": "addressLine1",
                "city": "city",
                "state": "state",
                "zip_code": "zipCode",
            }
            nc_data = {"databaseId": customer.nowcerts_insured_id}
            for key, val in updated.items():
                if key in NC_MAP:
                    nc_data[NC_MAP[key]] = val or ""

            result = nc.update_insured(nc_data)
            nc_result = {"success": result is not None, "data": str(result)[:200] if result else None}
        except Exception as e:
            nc_result = {"success": False, "error": str(e)}

    return {
        "customer": _customer_to_dict(customer),
        "nowcerts_update": nc_result,
        "updated_fields": list(updated.keys()),
    }


# ── Sync from NowCerts ────────────────────────────────────────────

@router.get("/{customer_id}/drivers")
def get_customer_drivers(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get drivers and contacts for a customer from NowCerts.
    
    Fetches from two NowCerts endpoints:
    1. Policy/PolicyDrivers - drivers linked to the customer's policies
    2. Insured/InsuredContacts - contacts on the insured record (with isDriver flag, DL info)
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    client = get_nowcerts_client()
    if not client.is_configured:
        raise HTTPException(status_code=400, detail="NowCerts not configured")

    drivers = []
    contacts = []

    # Get policy database IDs for this customer
    policies = (
        db.query(CustomerPolicy)
        .filter(CustomerPolicy.customer_id == customer_id)
        .all()
    )
    policy_db_ids = [
        p.nowcerts_policy_id for p in policies
        if p.nowcerts_policy_id
    ]

    # Fetch drivers from policies
    if policy_db_ids:
        try:
            drivers = client.get_policy_drivers(policy_db_ids)
        except Exception as e:
            logger.warning("Failed to fetch policy drivers: %s", e)

    # Fetch contacts from insured record
    if customer.nowcerts_insured_id:
        try:
            contacts = client.get_insured_contacts([customer.nowcerts_insured_id])
        except Exception as e:
            logger.warning("Failed to fetch insured contacts: %s", e)

    # Deduplicate: merge contacts that are also drivers by matching name
    # Build a combined list with all available info
    seen = set()
    combined = []

    # Contacts first (they have more complete info like DL#)
    for c in contacts:
        key = f"{(c.get('first_name') or '').lower()}_{(c.get('last_name') or '').lower()}"
        if key and key != "_" and key not in seen:
            seen.add(key)
            combined.append({
                "first_name": c.get("first_name", ""),
                "middle_name": c.get("middle_name", ""),
                "last_name": c.get("last_name", ""),
                "birthday": c.get("birthday"),
                "gender": c.get("gender"),
                "is_driver": c.get("is_driver", False),
                "license_number": c.get("dl_number", ""),
                "license_state": c.get("dl_state", ""),
                "license_year": c.get("dl_year"),
                "phone": c.get("cell_phone") or c.get("home_phone") or c.get("office_phone") or "",
                "email": c.get("personal_email") or c.get("business_email") or "",
                "primary_contact": c.get("primary_contact", False),
                "source": "contact",
            })

    # Then add drivers that weren't already in contacts
    for d in drivers:
        key = f"{(d.get('first_name') or '').lower()}_{(d.get('last_name') or '').lower()}"
        if key and key != "_" and key not in seen:
            seen.add(key)
            combined.append({
                "first_name": d.get("first_name", ""),
                "middle_name": "",
                "last_name": d.get("last_name", ""),
                "birthday": d.get("birthday"),
                "gender": d.get("gender"),
                "is_driver": True,
                "license_number": d.get("license_number", ""),
                "license_state": d.get("license_state", ""),
                "license_year": d.get("license_year"),
                "phone": "",
                "email": "",
                "primary_contact": False,
                "source": "policy_driver",
            })
        elif key in seen:
            # Merge: fill in missing driver fields from policy driver data
            for existing in combined:
                ekey = f"{(existing.get('first_name') or '').lower()}_{(existing.get('last_name') or '').lower()}"
                if ekey == key:
                    if not existing.get("license_number") and d.get("license_number"):
                        existing["license_number"] = d["license_number"]
                    if not existing.get("license_state") and d.get("license_state"):
                        existing["license_state"] = d["license_state"]
                    if not existing.get("birthday") and d.get("birthday"):
                        existing["birthday"] = d["birthday"]
                    existing["is_driver"] = True
                    break

    return {
        "customer_id": customer_id,
        "people": combined,
        "raw_drivers": drivers,
        "raw_contacts": contacts,
    }


@router.post("/{customer_id}/sync")
def sync_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh a customer's data from NowCerts."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    if not customer.nowcerts_insured_id:
        raise HTTPException(status_code=400, detail="Customer has no NowCerts ID — cannot sync")

    client = get_nowcerts_client()
    if not client.is_configured:
        raise HTTPException(status_code=400, detail="NowCerts not configured")

    try:
        # Refresh insured data
        raw_insured = client.get_insured(customer.nowcerts_insured_id)
        if raw_insured:
            normalized = normalize_insured(raw_insured)
            for key, val in normalized.items():
                if key != "nowcerts_raw" or val:
                    setattr(customer, key, val)
            customer.last_synced_at = datetime.utcnow()

        # Refresh policies
        raw_policies = client.get_insured_policies(customer.nowcerts_insured_id)
        for raw_pol in raw_policies:
            norm = normalize_policy(raw_pol, customer.id)
            nc_id = norm.get("nowcerts_policy_id")
            if nc_id:
                existing = db.query(CustomerPolicy).filter(
                    CustomerPolicy.nowcerts_policy_id == nc_id
                ).first()
                if existing:
                    for k, v in norm.items():
                        if v is not None:
                            setattr(existing, k, v)
                    existing.last_synced_at = datetime.utcnow()
                else:
                    policy = CustomerPolicy(**norm, last_synced_at=datetime.utcnow())
                    db.add(policy)

        db.commit()
        db.refresh(customer)

        policies = db.query(CustomerPolicy).filter(
            CustomerPolicy.customer_id == customer.id
        ).order_by(CustomerPolicy.effective_date.desc()).all()

        return {
            "customer": _customer_to_dict(customer),
            "policies": [_policy_to_dict(p) for p in policies],
            "synced": True,
        }

    except Exception as e:
        logger.error("Sync failed for customer %s: %s", customer_id, e)
        raise HTTPException(status_code=502, detail=f"NowCerts sync failed: {str(e)}")


def sync_all_customers_internal(db: Session):
    """Internal version of sync_all_customers for background scheduler. No auth required.
    Processes in batches to limit memory usage."""
    from app.services.nowcerts import get_nowcerts_client, normalize_insured
    import gc

    client = get_nowcerts_client()
    if not client.is_configured:
        return {"error": "NowCerts not configured"}

    imported = 0
    updated = 0
    policies_imported = 0
    policies_updated = 0
    errors = []

    try:
        # Process insureds in pages instead of loading all at once
        skip = 0
        page_size = 200
        while True:
            try:
                data = client._odata_get("InsuredDetailList", skip=skip, top=page_size)
                batch = data.get("value", [])
                if not batch:
                    break
                for raw in batch:
                    try:
                        normalized = normalize_insured(raw)
                        nc_id = normalized.get("nowcerts_insured_id")
                        if not nc_id:
                            continue
                        existing = db.query(Customer).filter(Customer.nowcerts_insured_id == nc_id).first()
                        if existing:
                            for k, v in normalized.items():
                                if v is not None:
                                    setattr(existing, k, v)
                            existing.last_synced_at = datetime.utcnow()
                            updated += 1
                        else:
                            customer = Customer(**normalized, last_synced_at=datetime.utcnow())
                            db.add(customer)
                            imported += 1
                    except Exception as e:
                        errors.append(f"Insured: {str(e)[:80]}")
                db.commit()
                # Expire loaded objects to free memory
                db.expire_all()
                skip += len(batch)
                total = data.get("@odata.count", 0)
                if total and skip >= total:
                    break
                if skip > 10000:
                    break
            except Exception as e:
                logger.error("Insured sync page failed at skip=%d: %s", skip, e)
                break
        gc.collect()
        logger.info("Auto-sync insureds: %d imported, %d updated", imported, updated)

        # Process policies in pages
        skip = 0
        while True:
            try:
                data = client._odata_get("PolicyDetailList", skip=skip, top=page_size)
                batch = data.get("value", [])
                if not batch:
                    break
                for raw_pol in batch:
                    try:
                        iid = raw_pol.get("insuredDatabaseId", "")
                        if not iid:
                            continue
                        customer = db.query(Customer).filter(Customer.nowcerts_insured_id == iid).first()
                        if not customer:
                            cust_data = {
                                "nowcerts_insured_id": iid,
                                "first_name": raw_pol.get("insuredFirstName", ""),
                                "last_name": raw_pol.get("insuredLastName", ""),
                                "full_name": raw_pol.get("insuredCommercialName") or f"{raw_pol.get('insuredFirstName', '')} {raw_pol.get('insuredLastName', '')}".strip() or "Unknown",
                                "email": raw_pol.get("insuredEmail", ""),
                                "phone": raw_pol.get("insuredPhoneNumber", ""),
                                "last_synced_at": datetime.utcnow(),
                            }
                            customer = Customer(**cust_data)
                            db.add(customer)
                            db.flush()
                            imported += 1
                        norm_pol = client._normalize_odata_policy(raw_pol, customer.id)
                        nc_pol_id = norm_pol.get("nowcerts_policy_id")
                        if nc_pol_id:
                            existing_pol = db.query(CustomerPolicy).filter(CustomerPolicy.nowcerts_policy_id == nc_pol_id).first()
                            if existing_pol:
                                for k, v in norm_pol.items():
                                    if v is not None:
                                        setattr(existing_pol, k, v)
                                existing_pol.last_synced_at = datetime.utcnow()
                                policies_updated += 1
                            else:
                                policy = CustomerPolicy(**norm_pol, last_synced_at=datetime.utcnow())
                                db.add(policy)
                                policies_imported += 1
                    except Exception as e:
                        errors.append(f"Policy: {str(e)[:80]}")
                db.commit()
                db.expire_all()
                skip += len(batch)
                total = data.get("@odata.count", 0)
                if total and skip >= total:
                    break
                if skip > 15000:
                    break
            except Exception as e:
                logger.error("Policy sync page failed at skip=%d: %s", skip, e)
                break
        gc.collect()

    except Exception as e:
        logger.error("Auto-sync error: %s", e)
        errors.append(str(e))

    result = {
        "imported": imported, "updated": updated,
        "policies_imported": policies_imported, "policies_updated": policies_updated,
        "errors": errors[:20],
    }
    logger.info("Auto-sync complete: %d imported, %d updated, %d pol imported, %d pol updated",
                imported, updated, policies_imported, policies_updated)
    return result



# ── Helpers ────────────────────────────────────────────────────────

def _customer_to_dict(c: Customer) -> dict:
    return {
        "id": c.id,
        "nowcerts_insured_id": c.nowcerts_insured_id,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "full_name": c.full_name,
        "email": c.email,
        "phone": c.phone,
        "mobile_phone": c.mobile_phone,
        "address": c.address,
        "city": c.city,
        "state": c.state,
        "zip_code": c.zip_code,
        "is_prospect": c.is_prospect,
        "is_active": c.is_active,
        "agent_name": c.agent_name,
        "tags": c.tags or [],
        "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
        "source": "local",
    }


def _policy_to_dict(p: CustomerPolicy) -> dict:
    return {
        "id": p.id,
        "nowcerts_policy_id": p.nowcerts_policy_id,
        "policy_number": p.policy_number,
        "carrier": p.carrier,
        "line_of_business": p.line_of_business,
        "policy_type": p.policy_type,
        "status": p.status,
        "effective_date": p.effective_date.isoformat() if p.effective_date else None,
        "expiration_date": p.expiration_date.isoformat() if p.expiration_date else None,
        "premium": float(p.premium) if p.premium else None,
        "agent_name": p.agent_name,
        "last_synced_at": p.last_synced_at.isoformat() if p.last_synced_at else None,
    }


# ── Debug / Diagnostic (route defined above, near top) ─────────────


# ── Quick Email from Customer Card ─────────────────────────────────
import requests as http_requests
from app.core.config import settings

def _log_email_to_nowcerts(
    db: Session,
    customer_id: Optional[int],
    customer_email: str,
    customer_name: str,
    direction: str,  # "outbound" or "inbound"
    subject: str,
    body_summary: str,
    sender: str,
    cc_list: list = None,
    att_names: list = None,
):
    """Push an email summary note to NowCerts for the customer profile."""
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if not nc or not nc.is_configured:
            logger.warning("NowCerts not configured — skipping email note")
            return

        # Look up customer for NowCerts insured ID
        customer = None
        if customer_id:
            customer = db.query(Customer).filter(Customer.id == customer_id).first()

        # Build note subject
        arrow = "📤 Sent" if direction == "outbound" else "📥 Received"
        note_subject = f"{arrow}: {subject}"

        # Build note body
        lines = [f"Subject: {subject}"]
        if direction == "outbound":
            lines.append(f"From: {sender}")
            lines.append(f"To: {customer_email}")
        else:
            lines.append(f"From: {customer_email}")
            lines.append(f"To: {sender}")
        if cc_list:
            lines.append(f"CC: {', '.join(cc_list)}")
        if att_names:
            lines.append(f"Attachments: {', '.join(att_names)}")
        lines.append("")
        # Truncate body for note
        summary = body_summary.replace('<br>', '\n').replace('<br/>', '\n')
        if len(summary) > 300:
            summary = summary[:300] + "..."
        lines.append(summary)

        note_text = "\n".join(lines)

        # Parse name
        name_parts = (customer_name or "").strip().split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        note_data = {
            "subject": note_subject[:200],
            "insured_email": customer_email,
            "insured_first_name": first_name,
            "insured_last_name": last_name,
            "insured_commercial_name": customer_name,
            "type": "Email",
            "description": note_text,
            "creator_name": f"ORBIT ({sender})",
        }

        if customer and customer.nowcerts_insured_id:
            note_data["insured_database_id"] = str(customer.nowcerts_insured_id)

        nc.insert_note(note_data)
        logger.info(f"NowCerts note logged for {customer_email}: {direction} email - {subject[:60]}")
    except Exception as e:
        # Don't fail the email send if note logging fails
        logger.error(f"Failed to log email to NowCerts: {e}")


# ── Customer Notes (2-way NowCerts sync) ──

@router.get("/{customer_id}/notes")
def get_customer_notes(
    customer_id: int,
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get recent notes from NowCerts for a customer."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return []

    if customer.nowcerts_insured_id:
        try:
            from app.services.nowcerts import get_nowcerts_client
            nc = get_nowcerts_client()
            if nc and nc.is_configured:
                nc_notes = nc.get_insured_notes([str(customer.nowcerts_insured_id)], top=limit)
                if nc_notes:
                    return [
                        {
                            "id": i,
                            "subject": n.get("subject", "(No subject)"),
                            "body": n.get("description", ""),
                            "source": n.get("type") or "NowCerts",
                            "created_by": n.get("creator_name", ""),
                            "created_at": n.get("date_created", ""),
                        }
                        for i, n in enumerate(nc_notes)
                    ]
        except Exception as e:
            logger.warning(f"NowCerts notes fetch failed: {e}")

    return []


@router.post("/{customer_id}/notes")
def add_customer_note(
    customer_id: int,
    subject: str = Form(...),
    body: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a note and push to NowCerts."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    pushed = "failed"
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if nc and nc.is_configured:
            name_parts = (customer.full_name or "").strip().split()
            first_name = name_parts[0] if name_parts else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            note_data = {
                "subject": subject[:200],
                "insured_email": customer.email,
                "insured_first_name": first_name,
                "insured_last_name": last_name,
                "insured_commercial_name": customer.full_name,
                "type": "Note",
                "description": body,
                "creator_name": f"ORBIT ({current_user.username})",
            }
            if customer.nowcerts_insured_id:
                note_data["insured_database_id"] = str(customer.nowcerts_insured_id)
            nc.insert_note(note_data)
            pushed = "yes"
            logger.info(f"Note pushed to NowCerts for {customer.full_name}: {subject[:60]}")
    except Exception as e:
        logger.warning(f"Failed to push note to NowCerts: {e}")

    return {"subject": subject, "pushed_to_nowcerts": pushed}
