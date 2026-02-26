"""BEACON Property Lookup — multi-source property data for insurance quoting.

Free sources:
- Cook County Assessor (IL) — year built, sq ft, assessed value, property class
- FEMA NFHL ArcGIS — flood zone determination (nationwide, free, no API key)
- Zillow deep links — link to Zillow property page (free)

Low-cost sources (require Google API key):
- Google Geocoding — address to lat/lng ($0.005/request, 10K free/month)
- Google Street View Static — property photo ($0.007/request, 10K free/month)
"""
import logging
import os
import re
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any

import httpx
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.database import Base

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")


# ── Cache Model ──────────────────────────────────────────────────

class PropertyLookupCache(Base):
    __tablename__ = "property_lookup_cache"

    id = Column(Integer, primary_key=True, index=True)
    address_hash = Column(String, unique=True, index=True)  # SHA256 of normalized address
    address_raw = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Geocoded address components
    street = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    county = Column(String, nullable=True)

    # Property data
    year_built = Column(Integer, nullable=True)
    square_footage = Column(Integer, nullable=True)
    assessed_value = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)
    property_class = Column(String, nullable=True)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Float, nullable=True)
    stories = Column(Integer, nullable=True)
    lot_size_sqft = Column(Integer, nullable=True)

    # Flood data
    flood_zone = Column(String, nullable=True)
    flood_zone_desc = Column(String, nullable=True)
    in_sfha = Column(String, nullable=True)  # Special Flood Hazard Area (yes/no)

    # Street View
    street_view_url = Column(String, nullable=True)

    # Zillow link
    zillow_url = Column(String, nullable=True)

    # Source tracking
    data_sources = Column(JSON, nullable=True)  # List of sources that contributed data
    raw_data = Column(JSON, nullable=True)  # Raw API responses for debugging

    looked_up_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())


# ── Address Helpers ──────────────────────────────────────────────

def _normalize_address(address: str) -> str:
    """Normalize an address for consistent hashing."""
    return re.sub(r'\s+', ' ', address.strip().lower())

def _hash_address(address: str) -> str:
    return hashlib.sha256(_normalize_address(address).encode()).hexdigest()

def _extract_address_from_query(query: str) -> Optional[str]:
    """Try to extract a street address from a natural language query."""
    # Common patterns: "look up 123 Main St, Chicago IL" or "property at 456 Oak Ave"
    patterns = [
        r'(?:look\s*up|search|find|check|property\s+(?:at|for|on))\s+(.+?)(?:\?|$)',
        r'(\d+\s+[A-Za-z][\w\s]+(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|ct|court|pl|place|way|cir|circle|pkwy|parkway)[\w\s,]*)',
    ]
    for pat in patterns:
        m = re.search(pat, query, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip('.,?!')
    return None


# ── Google Geocoding ─────────────────────────────────────────────

def _geocode_address(address: str) -> Dict[str, Any]:
    """Geocode an address using Google Maps API. Returns lat/lng and components."""
    if not GOOGLE_API_KEY:
        return {}
    
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": address, "key": GOOGLE_API_KEY},
            )
            data = resp.json()
            
            if data.get("status") != "OK" or not data.get("results"):
                logger.warning(f"Geocode failed for '{address}': {data.get('status')}")
                return {}
            
            result = data["results"][0]
            loc = result["geometry"]["location"]
            
            # Extract components
            components = {}
            for comp in result.get("address_components", []):
                types = comp.get("types", [])
                if "street_number" in types:
                    components["street_number"] = comp["short_name"]
                elif "route" in types:
                    components["route"] = comp["short_name"]
                elif "locality" in types:
                    components["city"] = comp["short_name"]
                elif "administrative_area_level_1" in types:
                    components["state"] = comp["short_name"]
                elif "administrative_area_level_2" in types:
                    components["county"] = comp["short_name"]
                elif "postal_code" in types:
                    components["zip_code"] = comp["short_name"]
            
            street = f"{components.get('street_number', '')} {components.get('route', '')}".strip()
            
            return {
                "latitude": loc["lat"],
                "longitude": loc["lng"],
                "formatted_address": result.get("formatted_address", ""),
                "street": street,
                "city": components.get("city", ""),
                "state": components.get("state", ""),
                "county": components.get("county", ""),
                "zip_code": components.get("zip_code", ""),
            }
    except Exception as e:
        logger.error(f"Geocode error: {e}")
        return {}


# ── Google Street View ───────────────────────────────────────────

def _get_street_view_url(lat: float, lng: float, address: str = "") -> str:
    """Generate a Google Street View Static API URL."""
    if not GOOGLE_API_KEY:
        return ""
    
    # Use address for better accuracy, fallback to lat/lng
    location = address if address else f"{lat},{lng}"
    return (
        f"https://maps.googleapis.com/maps/api/streetview"
        f"?size=640x480&location={location}&key={GOOGLE_API_KEY}"
    )


# ── FEMA Flood Zone (Free ArcGIS REST API) ──────────────────────

def _get_flood_zone(lat: float, lng: float) -> Dict[str, Any]:
    """Query FEMA's NFHL ArcGIS REST service for flood zone data. FREE, no API key."""
    try:
        with httpx.Client(timeout=15) as client:
            # FEMA NFHL MapServer — Layer 28 = Flood Hazard Zones (S_Fld_Haz_Ar)
            resp = client.get(
                "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query",
                params={
                    "geometry": f"{lng},{lat}",
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,FIRM_PAN",
                    "returnGeometry": "false",
                    "f": "json",
                },
            )
            data = resp.json()
            
            features = data.get("features", [])
            if not features:
                return {"flood_zone": "X (Not mapped)", "flood_zone_desc": "No FEMA flood data available for this location", "in_sfha": "Unknown"}
            
            attrs = features[0].get("attributes", {})
            zone = attrs.get("FLD_ZONE", "Unknown")
            subtype = attrs.get("ZONE_SUBTY", "")
            sfha = attrs.get("SFHA_TF", "")
            
            # Describe the zone
            zone_descriptions = {
                "A": "100-year floodplain (high risk, flood insurance required)",
                "AE": "100-year floodplain with base flood elevation (high risk)",
                "AH": "100-year floodplain, shallow flooding 1-3 feet (high risk)",
                "AO": "100-year floodplain, sheet flow 1-3 feet (high risk)",
                "V": "Coastal 100-year floodplain with wave action (highest risk)",
                "VE": "Coastal 100-year floodplain with base flood elevation (highest risk)",
                "X": "Minimal flood risk (outside 100/500-year floodplain)",
                "D": "Undetermined risk — no flood hazard analysis performed",
            }
            
            desc = zone_descriptions.get(zone, f"Flood zone {zone}")
            if subtype:
                desc += f" — {subtype}"
            
            is_sfha = "Yes" if sfha == "T" or zone.startswith(("A", "V")) else "No"
            
            return {
                "flood_zone": zone,
                "flood_zone_desc": desc,
                "in_sfha": is_sfha,
            }
    except Exception as e:
        logger.error(f"FEMA flood lookup error: {e}")
        return {"flood_zone": "Error", "flood_zone_desc": f"Lookup failed: {str(e)[:80]}", "in_sfha": "Unknown"}


# ── Cook County Assessor (Free) ──────────────────────────────────

def _cook_county_lookup(address: str, city: str = "") -> Dict[str, Any]:
    """Look up property data from Cook County Assessor's open data."""
    try:
        with httpx.Client(timeout=15) as client:
            # Use the Cook County property tax portal search
            # Their Socrata open data API is free
            # Dataset: Property Tax Assessor - Parcel Universe
            resp = client.get(
                "https://datacatalog.cookcountyil.gov/resource/tx2p-k2g9.json",
                params={
                    "$where": f"lower(addr) like lower('%{address[:30]}%')",
                    "$limit": 3,
                },
            )
            
            if resp.status_code != 200:
                return {}
            
            results = resp.json()
            if not results:
                return {}
            
            prop = results[0]
            
            return {
                "year_built": int(prop.get("year_built", 0)) or None,
                "square_footage": int(float(prop.get("bldg_sf", 0))) or None,
                "assessed_value": float(prop.get("assessed_value", 0)) or None,
                "market_value": float(prop.get("market_value", 0)) or None,
                "property_class": prop.get("property_class", ""),
                "source": "cook_county_assessor",
            }
    except Exception as e:
        logger.warning(f"Cook County lookup error: {e}")
        return {}


# ── Zillow Link (Free) ──────────────────────────────────────────

def _get_zillow_url(address: str) -> str:
    """Generate a Zillow search URL for the property."""
    clean = re.sub(r'[^\w\s,-]', '', address)
    slug = clean.replace(' ', '-').replace(',', '').replace('--', '-').strip('-')
    return f"https://www.zillow.com/homes/{slug}_rb/"


# ── Main Lookup Function ────────────────────────────────────────

def lookup_property(address: str, db: Session) -> Dict[str, Any]:
    """Full property lookup — checks cache first, then queries all sources.
    
    Returns a dict with all available property data.
    """
    addr_hash = _hash_address(address)
    
    # Check cache (lookups within 30 days)
    cached = db.query(PropertyLookupCache).filter(
        PropertyLookupCache.address_hash == addr_hash,
    ).first()
    
    if cached and cached.looked_up_at:
        age_days = (datetime.utcnow() - cached.looked_up_at).days
        if age_days < 30:
            logger.info(f"Property cache hit for '{address}' (age: {age_days}d)")
            return _cache_to_dict(cached)
    
    logger.info(f"Property lookup starting for '{address}'")
    
    result = {
        "address_raw": address,
        "data_sources": [],
    }
    
    # 1. Geocode the address
    geo = _geocode_address(address)
    if geo:
        result.update({
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "street": geo.get("street"),
            "city": geo.get("city"),
            "state": geo.get("state"),
            "county": geo.get("county"),
            "zip_code": geo.get("zip_code"),
            "formatted_address": geo.get("formatted_address"),
        })
        result["data_sources"].append("google_geocoding")
    
    lat = result.get("latitude")
    lng = result.get("longitude")
    state = (result.get("state") or "").upper()
    
    # 2. FEMA Flood Zone (free, nationwide)
    if lat and lng:
        flood = _get_flood_zone(lat, lng)
        result.update(flood)
        result["data_sources"].append("fema_nfhl")
    
    # 3. Cook County Assessor (free, IL only)
    county = (result.get("county") or "").lower()
    if state == "IL" and "cook" in county:
        street = result.get("street", address.split(",")[0])
        cook_data = _cook_county_lookup(street)
        if cook_data:
            for k, v in cook_data.items():
                if v and k != "source":
                    result[k] = v
            result["data_sources"].append("cook_county_assessor")
    
    # 4. Google Street View URL
    if lat and lng:
        result["street_view_url"] = _get_street_view_url(lat, lng, address)
        result["data_sources"].append("google_street_view")
    
    # 5. Zillow link (always free)
    result["zillow_url"] = _get_zillow_url(address)
    result["data_sources"].append("zillow_link")
    
    # Cache the result
    try:
        if cached:
            for key, val in result.items():
                if hasattr(cached, key) and val is not None:
                    setattr(cached, key, val)
            cached.looked_up_at = datetime.utcnow()
            cached.raw_data = result
        else:
            cache_entry = PropertyLookupCache(
                address_hash=addr_hash,
                address_raw=address,
                latitude=result.get("latitude"),
                longitude=result.get("longitude"),
                street=result.get("street"),
                city=result.get("city"),
                state=result.get("state"),
                zip_code=result.get("zip_code"),
                county=result.get("county"),
                year_built=result.get("year_built"),
                square_footage=result.get("square_footage"),
                assessed_value=result.get("assessed_value"),
                market_value=result.get("market_value"),
                property_class=result.get("property_class"),
                flood_zone=result.get("flood_zone"),
                flood_zone_desc=result.get("flood_zone_desc"),
                in_sfha=result.get("in_sfha"),
                street_view_url=result.get("street_view_url"),
                zillow_url=result.get("zillow_url"),
                data_sources=result.get("data_sources"),
                raw_data=result,
            )
            db.add(cache_entry)
        db.commit()
    except Exception as e:
        logger.warning(f"Cache save error: {e}")
        db.rollback()
    
    return result


def _cache_to_dict(cached: PropertyLookupCache) -> dict:
    """Convert cache entry to response dict."""
    return {
        "address_raw": cached.address_raw,
        "latitude": cached.latitude,
        "longitude": cached.longitude,
        "street": cached.street,
        "city": cached.city,
        "state": cached.state,
        "county": cached.county,
        "zip_code": cached.zip_code,
        "year_built": cached.year_built,
        "square_footage": cached.square_footage,
        "assessed_value": cached.assessed_value,
        "market_value": cached.market_value,
        "property_class": cached.property_class,
        "flood_zone": cached.flood_zone,
        "flood_zone_desc": cached.flood_zone_desc,
        "in_sfha": cached.in_sfha,
        "street_view_url": cached.street_view_url,
        "zillow_url": cached.zillow_url,
        "data_sources": cached.data_sources or [],
        "cached": True,
    }


def format_property_for_beacon(data: Dict[str, Any]) -> str:
    """Format property lookup data as context for BEACON's prompt."""
    if not data:
        return ""
    
    lines = ["\n## Property Lookup Results\n"]
    
    addr = data.get("formatted_address") or data.get("address_raw", "Unknown")
    lines.append(f"**Address:** {addr}")
    
    if data.get("city") or data.get("state"):
        lines.append(f"**Location:** {data.get('city', '')}, {data.get('state', '')} {data.get('zip_code', '')}")
    
    if data.get("county"):
        lines.append(f"**County:** {data['county']}")
    
    # Property characteristics
    chars = []
    if data.get("year_built"):
        chars.append(f"Year Built: {data['year_built']}")
    if data.get("square_footage"):
        chars.append(f"Square Footage: {data['square_footage']:,}")
    if data.get("assessed_value"):
        chars.append(f"Assessed Value: ${data['assessed_value']:,.0f}")
    if data.get("market_value"):
        chars.append(f"Market Value: ${data['market_value']:,.0f}")
    if data.get("property_class"):
        chars.append(f"Property Class: {data['property_class']}")
    if data.get("bedrooms"):
        chars.append(f"Bedrooms: {data['bedrooms']}")
    if data.get("bathrooms"):
        chars.append(f"Bathrooms: {data['bathrooms']}")
    
    if chars:
        lines.append("\n**Property Details:**")
        for c in chars:
            lines.append(f"- {c}")
    
    # Flood zone
    if data.get("flood_zone"):
        lines.append(f"\n**FEMA Flood Zone:** {data['flood_zone']} — {data.get('flood_zone_desc', '')}")
        if data.get("in_sfha") == "Yes":
            lines.append("⚠️ **This property IS in a Special Flood Hazard Area — flood insurance is likely required for mortgaged properties.**")
        elif data.get("in_sfha") == "No":
            lines.append("✅ This property is NOT in a Special Flood Hazard Area.")
    
    # Links
    if data.get("street_view_url"):
        lines.append(f"\n**Google Street View:** {data['street_view_url']}")
    if data.get("zillow_url"):
        lines.append(f"**Zillow:** {data['zillow_url']}")
    
    sources = data.get("data_sources", [])
    if sources:
        lines.append(f"\n*Data from: {', '.join(sources)}*")
    
    return "\n".join(lines)
