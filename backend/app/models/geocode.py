"""Geocode cache — addresses are looked up once and the result is cached forever.

Re-geocoding a customer only happens when their address actually changes. The
`address_hash` is a deterministic hash of the full normalized address so we can
lookup without joining to the customer table.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Index
from sqlalchemy.sql import func
from app.core.database import Base


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"

    id = Column(Integer, primary_key=True, index=True)

    # Hash of the normalized address string — the primary lookup key
    address_hash = Column(String(64), unique=True, nullable=False, index=True)

    # The full address string used to geocode (for debugging / audit)
    address_full = Column(String, nullable=False)

    # Result
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    # "mapbox", "google", "nominatim", or "manual"
    provider = Column(String, nullable=True)

    # If the geocoder returned low confidence or failed
    failed = Column(Boolean, default=False, index=True)
    failure_reason = Column(String, nullable=True)

    # Raw response payload (JSON string, optional)
    raw_response = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
