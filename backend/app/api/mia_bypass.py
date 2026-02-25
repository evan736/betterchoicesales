"""MIA AI Receptionist bypass management API.

Framework-only — NOT wired into the live inbound webhook yet.
Will be activated when MIA moves from overflow to front-end receptionist.

Endpoints:
  VIP Bypass:
    GET    /api/mia/vip              - List all VIP entries
    POST   /api/mia/vip              - Add a VIP entry
    DELETE /api/mia/vip/{id}         - Remove a VIP entry
    PATCH  /api/mia/vip/{id}         - Toggle active status

  Temp Authorization:
    GET    /api/mia/auth             - List active temp authorizations
    POST   /api/mia/auth             - Create a temp authorization
    DELETE /api/mia/auth/{id}        - Revoke a temp authorization

  Bypass Check (for future webhook integration):
    GET    /api/mia/check-bypass/{phone} - Check if phone should bypass MIA
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.mia_bypass import VipBypass, TempAuthorization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mia", tags=["mia-bypass"])


# ── Helpers ─────────────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Strip a phone number to last 10 digits."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


# ── Pydantic Schemas ────────────────────────────────────────────────

class VipCreateRequest(BaseModel):
    phone: str
    customer_name: Optional[str] = None
    reason: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        digits = re.sub(r"\D", "", v or "")
        if len(digits) < 10:
            raise ValueError("Phone number must be at least 10 digits")
        return digits[-10:]


class TempAuthCreateRequest(BaseModel):
    phone: str
    customer_name: Optional[str] = None
    reason: Optional[str] = None
    duration_minutes: int = 60  # default 1 hour

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        digits = re.sub(r"\D", "", v or "")
        if len(digits) < 10:
            raise ValueError("Phone number must be at least 10 digits")
        return digits[-10:]

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v):
        allowed = [30, 60, 120, 480]  # 30min, 1hr, 2hr, end of day (~8hr)
        if v not in allowed:
            raise ValueError(f"Duration must be one of: {allowed}")
        return v


# ── VIP Bypass Endpoints ────────────────────────────────────────────

@router.get("/vip")
async def list_vip(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all VIP bypass entries."""
    entries = (
        db.query(VipBypass)
        .order_by(VipBypass.created_at.desc())
        .all()
    )
    return {
        "entries": [
            {
                "id": e.id,
                "phone": e.phone,
                "customer_name": e.customer_name,
                "reason": e.reason,
                "added_by": e.added_by,
                "is_active": e.is_active,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.post("/vip")
async def add_vip(
    req: VipCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a phone number to the permanent VIP bypass list."""
    phone = req.phone  # already normalized by validator

    # Check for duplicates
    existing = db.query(VipBypass).filter(VipBypass.phone == phone).first()
    if existing:
        if not existing.is_active:
            # Re-activate
            existing.is_active = True
            existing.customer_name = req.customer_name or existing.customer_name
            existing.reason = req.reason or existing.reason
            existing.added_by = current_user.name if hasattr(current_user, 'name') else str(current_user.id)
            db.commit()
            db.refresh(existing)
            return {"status": "reactivated", "id": existing.id, "phone": phone}
        raise HTTPException(status_code=409, detail="Phone number already in VIP list")

    entry = VipBypass(
        phone=phone,
        customer_name=req.customer_name,
        reason=req.reason,
        added_by=current_user.name if hasattr(current_user, 'name') else str(current_user.id),
        is_active=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(f"VIP bypass added: {phone} by {entry.added_by}")
    return {"status": "added", "id": entry.id, "phone": phone}


@router.patch("/vip/{entry_id}")
async def toggle_vip(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle a VIP entry active/inactive."""
    entry = db.query(VipBypass).filter(VipBypass.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="VIP entry not found")

    entry.is_active = not entry.is_active
    db.commit()
    return {"status": "toggled", "id": entry.id, "is_active": entry.is_active}


@router.delete("/vip/{entry_id}")
async def remove_vip(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently remove a VIP bypass entry."""
    entry = db.query(VipBypass).filter(VipBypass.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="VIP entry not found")

    db.delete(entry)
    db.commit()
    logger.info(f"VIP bypass removed: {entry.phone} by user {current_user.id}")
    return {"status": "removed", "id": entry_id}


# ── Temp Authorization Endpoints ────────────────────────────────────

@router.get("/auth")
async def list_temp_auth(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List temp authorizations. Default: active & non-expired only."""
    now = datetime.now(timezone.utc)
    query = db.query(TempAuthorization)
    if active_only:
        query = query.filter(
            TempAuthorization.is_active == True,
            TempAuthorization.expires_at > now,
        )
    entries = query.order_by(TempAuthorization.created_at.desc()).all()
    return {
        "entries": [
            {
                "id": e.id,
                "phone": e.phone,
                "customer_name": e.customer_name,
                "authorized_by": e.authorized_by,
                "reason": e.reason,
                "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                "is_active": e.is_active,
                "is_expired": e.expires_at < now if e.expires_at else True,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.post("/auth")
async def create_temp_auth(
    req: TempAuthCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Grant temporary direct-line authorization for a phone number."""
    phone = req.phone  # already normalized by validator
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=req.duration_minutes)

    # Deactivate any existing active auths for this phone
    existing = (
        db.query(TempAuthorization)
        .filter(
            TempAuthorization.phone == phone,
            TempAuthorization.is_active == True,
            TempAuthorization.expires_at > now,
        )
        .all()
    )
    for e in existing:
        e.is_active = False

    staff_name = current_user.name if hasattr(current_user, 'name') else str(current_user.id)

    entry = TempAuthorization(
        phone=phone,
        customer_name=req.customer_name,
        authorized_by=staff_name,
        reason=req.reason,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    logger.info(f"Temp auth granted: {phone} for {req.duration_minutes}min by {staff_name}")
    return {
        "status": "authorized",
        "id": entry.id,
        "phone": phone,
        "expires_at": expires_at.isoformat(),
        "duration_minutes": req.duration_minutes,
    }


@router.delete("/auth/{entry_id}")
async def revoke_temp_auth(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a temp authorization early."""
    entry = db.query(TempAuthorization).filter(TempAuthorization.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Temp auth entry not found")

    entry.is_active = False
    db.commit()
    logger.info(f"Temp auth revoked: {entry.phone} by user {current_user.id}")
    return {"status": "revoked", "id": entry_id}


# ── Bypass Check (for future webhook integration) ───────────────────

@router.get("/check-bypass/{phone}")
async def check_bypass(
    phone: str,
    db: Session = Depends(get_db),
):
    """Check if a phone number should bypass MIA.

    This endpoint is NOT authenticated — it will be called by the
    Retell inbound webhook (which has its own auth).

    Returns:
        bypass: bool — whether the caller should skip MIA
        reason: str — "vip", "temp_auth", or "none"
        customer_name: str | None
    """
    digits = normalize_phone(phone)
    if len(digits) < 10:
        return {"bypass": False, "reason": "invalid_phone", "customer_name": None}

    # 1. Check permanent VIP list
    vip = (
        db.query(VipBypass)
        .filter(VipBypass.phone == digits, VipBypass.is_active == True)
        .first()
    )
    if vip:
        logger.info(f"Bypass check: {digits} → VIP match ({vip.customer_name})")
        return {
            "bypass": True,
            "reason": "vip",
            "customer_name": vip.customer_name,
        }

    # 2. Check active temp authorizations
    now = datetime.now(timezone.utc)
    temp = (
        db.query(TempAuthorization)
        .filter(
            TempAuthorization.phone == digits,
            TempAuthorization.is_active == True,
            TempAuthorization.expires_at > now,
        )
        .first()
    )
    if temp:
        logger.info(f"Bypass check: {digits} → temp auth match (expires {temp.expires_at})")
        return {
            "bypass": True,
            "reason": "temp_auth",
            "customer_name": temp.customer_name,
            "expires_at": temp.expires_at.isoformat(),
        }

    # 3. No bypass
    return {"bypass": False, "reason": "none", "customer_name": None}


# ── Bypass Status for Customer Card ─────────────────────────────────

@router.get("/bypass-status/{phone}")
async def bypass_status(
    phone: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full bypass status for a phone number (for ORBIT customer card).

    Returns both VIP and temp auth status so the UI can show the right controls.
    """
    digits = normalize_phone(phone)
    if len(digits) < 10:
        return {"vip": None, "temp_auth": None}

    vip = (
        db.query(VipBypass)
        .filter(VipBypass.phone == digits)
        .first()
    )
    now = datetime.now(timezone.utc)
    temp = (
        db.query(TempAuthorization)
        .filter(
            TempAuthorization.phone == digits,
            TempAuthorization.is_active == True,
            TempAuthorization.expires_at > now,
        )
        .order_by(TempAuthorization.expires_at.desc())
        .first()
    )

    return {
        "vip": {
            "id": vip.id,
            "is_active": vip.is_active,
            "customer_name": vip.customer_name,
            "reason": vip.reason,
            "added_by": vip.added_by,
            "created_at": vip.created_at.isoformat() if vip.created_at else None,
        } if vip else None,
        "temp_auth": {
            "id": temp.id,
            "expires_at": temp.expires_at.isoformat(),
            "authorized_by": temp.authorized_by,
            "reason": temp.reason,
            "minutes_remaining": max(0, int((temp.expires_at - now).total_seconds() / 60)),
        } if temp else None,
    }
