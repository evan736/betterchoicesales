"""Claim Map API — customer pins for the disaster-response map.

Endpoints:
  GET  /api/claim-map/customers        — every customer with active policies, + lat/lng if cached
  GET  /api/claim-map/geocode-status   — how many pending / failed / complete
  POST /api/claim-map/geocode-batch    — geocode the next N pending customers
  GET  /api/claim-map/weather-alerts   — proxy current NWS active warnings (cached 60s)

Security: admin/manager/retention_specialist only. No PII exposed in the weather proxy.
"""
import logging
import time
import os
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy
from app.models.geocode import GeocodeCache
from app.services.geocoding import _normalize_address, _hash_address, geocode, bulk_geocode_pending

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/claim-map", tags=["claim-map"])


def _can_access(user: User) -> bool:
    return user.role.lower() in ("admin", "manager", "retention_specialist")


# ── Customer pins ─────────────────────────────────────────────────

@router.get("/customers")
def list_claim_map_customers(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return every customer + their policies in a map-friendly shape.

    Joins against geocode_cache so each customer has lat/lng attached when we've
    already geocoded their address. If we haven't, the customer still appears
    but with lat/lng = null (frontend skips pinning those).
    """
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Pull customers with at least one policy (active by default)
    policy_filter = CustomerPolicy.status.ilike("active")
    if include_inactive:
        policy_filter = True

    # Build the query
    q = (
        db.query(Customer, CustomerPolicy)
        .join(CustomerPolicy, CustomerPolicy.customer_id == Customer.id)
        .filter(policy_filter)
    )
    rows = q.all()

    # Collate per customer
    by_customer: dict[int, dict] = {}
    for c, p in rows:
        if c.id not in by_customer:
            by_customer[c.id] = {
                "customer_id": c.id,
                "client_name": c.full_name or f"{c.first_name or ''} {c.last_name or ''}".strip() or "—",
                "address": c.address,
                "city": c.city,
                "state": c.state,
                "zip": c.zip_code,
                "primary_phone": c.phone or c.mobile_phone,
                "email": c.email,
                "lat": None,
                "lng": None,
                "lob_set": set(),
                "policies": [],
            }
        by_customer[c.id]["policies"].append({
            "policy_number": p.policy_number,
            "carrier": p.carrier,
            "line_of_business": p.line_of_business,
            "status": p.status,
        })
        if p.line_of_business:
            by_customer[c.id]["lob_set"].add(p.line_of_business.lower())

    # Pull matching geocodes in one query
    hashes = []
    for c in by_customer.values():
        full = _normalize_address(c["address"] or "", c["city"] or "", c["state"] or "", c["zip"] or "")
        if full:
            c["_hash"] = _hash_address(full)
            hashes.append(c["_hash"])
    if hashes:
        geos = db.query(GeocodeCache).filter(GeocodeCache.address_hash.in_(hashes)).all()
        geo_by_hash = {g.address_hash: g for g in geos}
        for c in by_customer.values():
            g = geo_by_hash.get(c.get("_hash"))
            if g and not g.failed:
                c["lat"] = g.lat
                c["lng"] = g.lng

    # Finalize — drop internal hash, convert lob_set to list, pick primary LOB
    result = []
    for c in by_customer.values():
        c.pop("_hash", None)
        lobs = sorted(c.pop("lob_set"))
        # Primary LOB for pin color: commercial > home > auto > other
        primary_lob = "other"
        if "commercial" in lobs:
            primary_lob = "commercial"
        elif any(l in lobs for l in ("home", "homeowners", "ho3", "ho6", "dwelling")):
            primary_lob = "home"
        elif any(l in lobs for l in ("auto", "auto_6m", "auto_12m", "pauto", "auto_policy")):
            primary_lob = "auto"
        c["primary_lob"] = primary_lob
        c["lines_of_business"] = lobs
        result.append(c)

    return {
        "count": len(result),
        "geocoded": sum(1 for c in result if c["lat"] is not None),
        "customers": result,
    }


# ── Geocode status + batch ────────────────────────────────────────

@router.get("/geocode-status")
def geocode_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Quick stats: how many addresses geocoded vs pending vs failed."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Unique customer addresses among active-policy holders
    rows = (
        db.query(Customer.address, Customer.city, Customer.state, Customer.zip_code)
        .join(CustomerPolicy, CustomerPolicy.customer_id == Customer.id)
        .filter(CustomerPolicy.status.ilike("active"))
        .filter(Customer.address.isnot(None))
        .distinct()
        .all()
    )
    total = 0
    cached = 0
    failed = 0
    for addr, city, state, zc in rows:
        full = _normalize_address(addr or "", city or "", state or "", zc or "")
        if not full:
            continue
        total += 1
        h = _hash_address(full)
        existing = db.query(GeocodeCache).filter(GeocodeCache.address_hash == h).first()
        if not existing:
            continue
        if existing.failed:
            failed += 1
        else:
            cached += 1

    # Provider configured?
    providers_available = []
    if os.environ.get("MAPBOX_ACCESS_TOKEN") or os.environ.get("MAPBOX_API_KEY"):
        providers_available.append("mapbox")
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        providers_available.append("google")
    providers_available.append("nominatim")  # Always available as fallback

    return {
        "total_addresses": total,
        "geocoded": cached,
        "failed": failed,
        "pending": total - cached - failed,
        "providers_available": providers_available,
    }


@router.post("/geocode-batch")
def geocode_batch(
    limit: int = Query(50, ge=1, le=500),
    retry_failed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Geocode the next N customers that don't yet have a cached result.

    Call repeatedly until pending = 0. Rate-limits itself internally (especially
    when falling back to Nominatim). Admin/manager only.
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    # Find customers with active policies that don't yet have a successful cache entry
    customers = (
        db.query(Customer)
        .join(CustomerPolicy, CustomerPolicy.customer_id == Customer.id)
        .filter(CustomerPolicy.status.ilike("active"))
        .filter(Customer.address.isnot(None))
        .distinct()
        .all()
    )

    # Filter to ones without a cached successful result
    pending = []
    for c in customers:
        full = _normalize_address(c.address or "", c.city or "", c.state or "", c.zip_code or "")
        if not full:
            continue
        h = _hash_address(full)
        existing = db.query(GeocodeCache).filter(GeocodeCache.address_hash == h).first()
        if existing is None:
            pending.append(c)
        elif existing.failed and retry_failed:
            pending.append(c)

    result = bulk_geocode_pending(db, pending, limit=limit)
    result["remaining"] = max(0, len(pending) - limit)
    return result


# ── NWS Weather alerts proxy ──────────────────────────────────────

_alerts_cache: dict = {"fetched_at": 0, "payload": None}
_ALERTS_CACHE_SECONDS = 60


@router.get("/weather-alerts")
def weather_alerts(
    state: Optional[str] = Query(None, description="Two-letter state code, e.g. IL"),
    current_user: User = Depends(get_current_user),
):
    """Proxy NWS active alerts. Cached 60s so we don't hammer the federal server.

    Filters to tornado, severe thunderstorm, and flash flood warnings by default.
    """
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    now = time.time()
    if _alerts_cache["payload"] and now - _alerts_cache["fetched_at"] < _ALERTS_CACHE_SECONDS:
        data = _alerts_cache["payload"]
    else:
        try:
            resp = requests.get(
                "https://api.weather.gov/alerts/active",
                headers={
                    "User-Agent": "ORBIT-ClaimMap/1.0 (service@betterchoiceins.com)",
                    "Accept": "application/geo+json",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"NWS returned {resp.status_code}")
            data = resp.json()
            _alerts_cache["fetched_at"] = now
            _alerts_cache["payload"] = data
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"NWS fetch failed: {str(e)[:200]}")

    # Filter to events we care about for claim response
    target_events = {
        "tornado warning", "severe thunderstorm warning", "flash flood warning",
        "tornado emergency", "severe thunderstorm watch", "flash flood emergency",
        "hurricane warning", "tropical storm warning",
    }
    features = data.get("features", []) or []
    filtered = []
    for f in features:
        props = f.get("properties") or {}
        event = (props.get("event") or "").lower()
        if event not in target_events:
            continue
        if state:
            # affectedZones is array of zone URLs that sometimes include the state;
            # simpler: check the `areaDesc` or `senderName`
            area = (props.get("areaDesc") or "")
            if f", {state.upper()}" not in area and f" {state.upper()}" not in area:
                # State not mentioned — still include if we can't determine
                pass
        filtered.append({
            "id": props.get("id") or f.get("id"),
            "event": props.get("event"),
            "severity": props.get("severity"),
            "urgency": props.get("urgency"),
            "headline": props.get("headline"),
            "description": (props.get("description") or "")[:500],
            "instruction": props.get("instruction"),
            "area_desc": props.get("areaDesc"),
            "sent": props.get("sent"),
            "effective": props.get("effective"),
            "expires": props.get("expires"),
            "geometry": f.get("geometry"),  # GeoJSON Polygon / MultiPolygon
        })

    return {
        "count": len(filtered),
        "cached_age_seconds": int(now - _alerts_cache["fetched_at"]),
        "alerts": filtered,
    }
