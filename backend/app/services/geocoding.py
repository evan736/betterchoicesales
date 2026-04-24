"""Geocoding service.

Tries providers in order of preference:
  1. MapBox (if MAPBOX_ACCESS_TOKEN set) — $5 per 1000 after 100k/month free
  2. Google (if GOOGLE_MAPS_API_KEY set) — fallback
  3. Nominatim (OpenStreetMap) — free but rate-limited to ~1/sec

Results cached in geocode_cache table keyed by normalized address hash.
Re-geocoding only happens when the address string changes.
"""
import hashlib
import logging
import os
import time
import json
from typing import Optional

import requests
from sqlalchemy.orm import Session

from app.models.geocode import GeocodeCache

logger = logging.getLogger(__name__)

USER_AGENT = "ORBIT-ClaimMap/1.0 (service@betterchoiceins.com)"


def _normalize_address(address: str, city: str, state: str, zip_code: str) -> str:
    """Build a canonical address string for hashing & geocoding."""
    parts = [
        (address or "").strip(),
        (city or "").strip(),
        (state or "").strip(),
        (zip_code or "").strip(),
    ]
    return ", ".join(p for p in parts if p)


def _hash_address(full: str) -> str:
    """Deterministic hash of the normalized address."""
    normalized = full.upper().replace("  ", " ").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── Provider implementations ─────────────────────────────────────

def _geocode_mapbox(full_address: str) -> Optional[dict]:
    token = os.environ.get("MAPBOX_ACCESS_TOKEN") or os.environ.get("MAPBOX_API_KEY")
    if not token:
        return None
    try:
        resp = requests.get(
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/{requests.utils.quote(full_address)}.json",
            params={
                "access_token": token,
                "country": "us",
                "limit": 1,
                "types": "address",
            },
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return {"error": f"mapbox HTTP {resp.status_code}"}
        data = resp.json()
        features = data.get("features") or []
        if not features:
            return {"error": "mapbox no match"}
        f = features[0]
        lng, lat = f["center"]
        return {"lat": lat, "lng": lng, "provider": "mapbox", "raw": f}
    except Exception as e:
        return {"error": f"mapbox exception: {e}"}


def _geocode_google(full_address: str) -> Optional[dict]:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": full_address, "key": key},
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return {"error": f"google {data.get('status','?')}"}
        loc = data["results"][0]["geometry"]["location"]
        return {"lat": loc["lat"], "lng": loc["lng"], "provider": "google", "raw": data["results"][0]}
    except Exception as e:
        return {"error": f"google exception: {e}"}


def _geocode_nominatim(full_address: str) -> Optional[dict]:
    # Nominatim — must rate-limit to 1 req/sec and use a descriptive User-Agent.
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": full_address, "format": "json", "limit": 1, "countrycodes": "us"},
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            return {"error": f"nominatim HTTP {resp.status_code}"}
        results = resp.json() or []
        if not results:
            return {"error": "nominatim no match"}
        r = results[0]
        return {"lat": float(r["lat"]), "lng": float(r["lon"]), "provider": "nominatim", "raw": r}
    except Exception as e:
        return {"error": f"nominatim exception: {e}"}


# Provider order: try MapBox first, then Google, then Nominatim fallback
_PROVIDERS = [_geocode_mapbox, _geocode_google, _geocode_nominatim]


def geocode(
    db: Session,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    force: bool = False,
) -> Optional[GeocodeCache]:
    """Geocode a single address, using the cache.

    Returns the GeocodeCache row (success or failure). Caller should check .lat/.lng
    and .failed. Missing/empty address returns None without touching cache.
    """
    if not address or not any((address, city, state, zip_code)):
        return None

    full = _normalize_address(address, city, state, zip_code)
    if not full:
        return None

    h = _hash_address(full)
    existing = db.query(GeocodeCache).filter(GeocodeCache.address_hash == h).first()
    if existing and not force:
        return existing

    # Try providers in order
    for provider_fn in _PROVIDERS:
        result = provider_fn(full)
        if result is None:
            # Provider not configured (no API key) — skip
            continue
        if "error" in result:
            logger.warning("Geocode miss via %s: %s", provider_fn.__name__, result["error"])
            # If this was Nominatim, sleep to respect their rate limit before any caller retries
            if provider_fn is _geocode_nominatim:
                time.sleep(1.1)
            continue
        # Success
        if existing:
            existing.lat = result["lat"]
            existing.lng = result["lng"]
            existing.provider = result["provider"]
            existing.failed = False
            existing.failure_reason = None
            existing.raw_response = json.dumps(result.get("raw"))[:8000] if result.get("raw") else None
            db.commit()
            db.refresh(existing)
            if provider_fn is _geocode_nominatim:
                time.sleep(1.1)
            return existing
        entry = GeocodeCache(
            address_hash=h,
            address_full=full,
            lat=result["lat"],
            lng=result["lng"],
            provider=result["provider"],
            failed=False,
            raw_response=json.dumps(result.get("raw"))[:8000] if result.get("raw") else None,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        if provider_fn is _geocode_nominatim:
            time.sleep(1.1)
        return entry

    # All providers failed — record failure
    if existing:
        existing.failed = True
        existing.failure_reason = "All providers failed"
        db.commit()
        db.refresh(existing)
        return existing
    entry = GeocodeCache(
        address_hash=h,
        address_full=full,
        failed=True,
        failure_reason="All providers failed",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def bulk_geocode_pending(db: Session, customers: list, limit: int = 50) -> dict:
    """Geocode up to `limit` customers that don't yet have a cached result.

    Designed to be called from a batch-geocode admin endpoint. Safe to call
    repeatedly — already-cached addresses are skipped instantly.

    Returns {attempted, succeeded, failed, skipped_no_address}.
    """
    attempted = 0
    succeeded = 0
    failed = 0
    skipped = 0
    for c in customers:
        if attempted >= limit:
            break
        if not (c.address and c.city and c.state):
            skipped += 1
            continue
        attempted += 1
        entry = geocode(db, c.address, c.city, c.state, c.zip_code or "")
        if entry is None:
            skipped += 1
        elif entry.failed:
            failed += 1
        else:
            succeeded += 1
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "skipped_no_address": skipped,
    }
