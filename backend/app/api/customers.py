"""Customers API — internal customer directory with NowCerts integration."""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

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
            query = query.filter(
                or_(
                    Customer.full_name.ilike(search),
                    Customer.email.ilike(search),
                    Customer.phone.ilike(search),
                    Customer.mobile_phone.ilike(search),
                    Customer.address.ilike(search),
                    Customer.city.ilike(search),
                )
            )
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
            nc_results = client.search_insureds(q.strip() if q.strip() else "", limit=page_size)
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

    return {
        "total_customers": total_customers,
        "active_customers": active_customers,
        "active_policies": active_policies,
        "total_policies": total_policies,
        "total_active_premium_annualized": float(total_premium),
        "last_sync": last_sync.isoformat() if last_sync else None,
    }


# ── Duplicate Detection ──────────────────────────────────────────

@router.get("/duplicates")
def find_duplicates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find potential duplicate customers by name, phone, or email."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    all_customers = db.query(Customer).order_by(Customer.full_name).all()

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

    policies = (
        db.query(CustomerPolicy)
        .filter(CustomerPolicy.customer_id == customer_id)
        .order_by(CustomerPolicy.effective_date.desc())
        .all()
    )

    return {
        "customer": _customer_to_dict(customer),
        "policies": [_policy_to_dict(p) for p in policies],
    }


# ── Sync from NowCerts ────────────────────────────────────────────

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
