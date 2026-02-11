"""Admin API — employee management, commission plans, lead sources, carriers."""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user, get_password_hash
from app.models.user import User
from app.models.sale import Sale
from app.models.commission import CommissionTier
from app.models.agency_config import AgencyConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user: User):
    if user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


# ── Schemas ──────────────────────────────────────────────────────────

class CreateEmployeeRequest(BaseModel):
    email: str
    username: str
    full_name: str
    password: str
    role: str = "producer"
    producer_code: Optional[str] = None
    commission_tier: int = 1

class UpdateEmployeeRequest(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    producer_code: Optional[str] = None
    commission_tier: Optional[int] = None
    is_active: Optional[bool] = None

class ResetPasswordRequest(BaseModel):
    new_password: str

class CommissionTierRequest(BaseModel):
    tier_level: int
    min_written_premium: float
    max_written_premium: Optional[float] = None
    commission_rate: float
    description: Optional[str] = None

class LeadSourceRequest(BaseModel):
    name: str
    display_name: Optional[str] = None

class CarrierRequest(BaseModel):
    name: str
    display_name: Optional[str] = None


# ── Employee Management ──────────────────────────────────────────────

@router.get("/employees")
def list_employees(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all employees with stats."""
    require_admin(current_user)

    users = db.query(User).order_by(User.full_name).all()
    result = []
    for u in users:
        sale_count = db.query(func.count(Sale.id)).filter(Sale.producer_id == u.id).scalar() or 0
        total_premium = db.query(func.sum(Sale.written_premium)).filter(Sale.producer_id == u.id).scalar() or 0
        result.append({
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role,
            "producer_code": u.producer_code,
            "commission_tier": u.commission_tier,
            "is_active": u.is_active,
            "is_superuser": u.is_superuser,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "sale_count": sale_count,
            "total_premium": float(total_premium),
        })
    return result


@router.post("/employees")
def create_employee(
    data: CreateEmployeeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new employee."""
    require_admin(current_user)

    # Check for duplicates
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if data.producer_code and db.query(User).filter(User.producer_code == data.producer_code).first():
        raise HTTPException(status_code=400, detail="Producer code already exists")

    user = User(
        email=data.email,
        username=data.username,
        full_name=data.full_name,
        hashed_password=get_password_hash(data.password),
        role=data.role,
        producer_code=data.producer_code,
        commission_tier=data.commission_tier,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"Admin {current_user.username} created employee {user.username}")
    return {"success": True, "id": user.id, "username": user.username}


@router.put("/employees/{user_id}")
def update_employee(
    user_id: int,
    data: UpdateEmployeeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an employee's details."""
    require_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")

    if data.email is not None:
        existing = db.query(User).filter(User.email == data.email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = data.email
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.role is not None:
        user.role = data.role
    if data.producer_code is not None:
        existing = db.query(User).filter(User.producer_code == data.producer_code, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Producer code already in use")
        user.producer_code = data.producer_code
    if data.commission_tier is not None:
        user.commission_tier = data.commission_tier
    if data.is_active is not None:
        user.is_active = data.is_active

    db.commit()
    logger.info(f"Admin {current_user.username} updated employee {user.username}")
    return {"success": True}


@router.delete("/employees/{user_id}")
def delete_employee(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an employee. Cannot delete yourself or users with sales."""
    require_admin(current_user)

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")

    sale_count = db.query(func.count(Sale.id)).filter(Sale.producer_id == user_id).scalar() or 0
    if sale_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete {user.full_name} — they have {sale_count} sales. Deactivate instead."
        )

    db.delete(user)
    db.commit()
    logger.info(f"Admin {current_user.username} deleted employee {user.username}")
    return {"success": True}


@router.post("/employees/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: ResetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset an employee's password."""
    require_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.hashed_password = get_password_hash(data.new_password)
    db.commit()
    logger.info(f"Admin {current_user.username} reset password for {user.username}")
    return {"success": True}


# ── Commission Tiers ─────────────────────────────────────────────────

@router.get("/commission-tiers")
def list_commission_tiers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all commission tiers."""
    require_admin(current_user)
    tiers = db.query(CommissionTier).order_by(CommissionTier.tier_level).all()
    return [
        {
            "id": t.id,
            "tier_level": t.tier_level,
            "min_written_premium": float(t.min_written_premium or 0),
            "max_written_premium": float(t.max_written_premium) if t.max_written_premium else None,
            "commission_rate": float(t.commission_rate or 0),
            "description": t.description,
            "is_active": t.is_active,
        }
        for t in tiers
    ]


@router.post("/commission-tiers")
def create_commission_tier(
    data: CommissionTierRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new commission tier."""
    require_admin(current_user)

    existing = db.query(CommissionTier).filter(CommissionTier.tier_level == data.tier_level).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Tier level {data.tier_level} already exists")

    tier = CommissionTier(
        tier_level=data.tier_level,
        min_written_premium=data.min_written_premium,
        max_written_premium=data.max_written_premium,
        commission_rate=data.commission_rate,
        description=data.description or f"Tier {data.tier_level} - {data.commission_rate*100:.1f}%",
        is_active=True,
    )
    db.add(tier)
    db.commit()
    return {"success": True, "id": tier.id}


@router.put("/commission-tiers/{tier_id}")
def update_commission_tier(
    tier_id: int,
    data: CommissionTierRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a commission tier."""
    require_admin(current_user)

    tier = db.query(CommissionTier).filter(CommissionTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    tier.tier_level = data.tier_level
    tier.min_written_premium = data.min_written_premium
    tier.max_written_premium = data.max_written_premium
    tier.commission_rate = data.commission_rate
    tier.description = data.description or tier.description
    db.commit()
    return {"success": True}


@router.delete("/commission-tiers/{tier_id}")
def delete_commission_tier(
    tier_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a commission tier."""
    require_admin(current_user)

    tier = db.query(CommissionTier).filter(CommissionTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    db.delete(tier)
    db.commit()
    return {"success": True}


# ── Lead Sources ─────────────────────────────────────────────────────

# Lead sources are stored as strings on sales — we maintain a config list

@router.get("/lead-sources")
def list_lead_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all lead sources from config table + sales."""
    require_admin(current_user)

    configs = db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "lead_source",
        AgencyConfig.is_active == True,
    ).all()

    in_use = db.query(Sale.lead_source, func.count(Sale.id)).filter(
        Sale.lead_source.isnot(None),
        Sale.lead_source != "",
    ).group_by(Sale.lead_source).all()

    source_map = {}
    for c in configs:
        source_map[c.name] = {"name": c.name, "display_name": c.display_name, "sale_count": 0, "id": c.id}
    for row in in_use:
        raw = row[0]
        key = raw.lower().replace(" ", "_").replace("-", "_")
        if key in source_map:
            source_map[key]["sale_count"] += row[1]
        else:
            source_map[key] = {"name": key, "display_name": raw.replace("_", " ").title(), "sale_count": row[1], "id": None}
            if " " in raw or (raw and raw[0].isupper()):
                source_map[key]["display_name"] = raw

    return sorted(source_map.values(), key=lambda x: x["display_name"])


@router.post("/lead-sources")
def add_lead_source(
    data: LeadSourceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new lead source to the config table."""
    require_admin(current_user)
    name = data.name.lower().replace(" ", "_").replace("-", "_")
    display = data.display_name or data.name.replace("_", " ").title()

    existing = db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "lead_source", AgencyConfig.name == name,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Lead source already exists")

    db.add(AgencyConfig(config_type="lead_source", name=name, display_name=display))
    db.commit()
    return {"success": True, "name": name, "display_name": display}


# ── Carriers ─────────────────────────────────────────────────────────

@router.get("/carriers")
def list_carriers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all carriers from config table + sales/statements."""
    require_admin(current_user)

    configs = db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "carrier",
        AgencyConfig.is_active == True,
    ).all()

    in_use = db.query(Sale.carrier, func.count(Sale.id)).filter(
        Sale.carrier.isnot(None),
        Sale.carrier != "",
    ).group_by(Sale.carrier).all()

    from app.models.statement import StatementImport
    stmt_carriers = db.query(StatementImport.carrier, func.count(StatementImport.id)).group_by(StatementImport.carrier).all()

    carrier_map = {}
    for c in configs:
        carrier_map[c.name] = {"name": c.name, "display_name": c.display_name, "sale_count": 0, "statement_count": 0, "id": c.id}
    for row in in_use:
        raw = row[0]
        key = raw.lower().replace(" ", "_").replace("-", "_")
        if key in carrier_map:
            carrier_map[key]["sale_count"] += row[1]
        else:
            carrier_map[key] = {"name": key, "display_name": raw.replace("_", " ").title(), "sale_count": row[1], "statement_count": 0, "id": None}
            if " " in raw or (raw and raw[0].isupper()):
                carrier_map[key]["display_name"] = raw
    for row in stmt_carriers:
        raw = row[0]
        key = raw.lower().replace(" ", "_").replace("-", "_")
        if key in carrier_map:
            carrier_map[key]["statement_count"] += row[1]
        else:
            carrier_map[key] = {"name": key, "display_name": raw.replace("_", " ").title(), "sale_count": 0, "statement_count": row[1], "id": None}

    return sorted(carrier_map.values(), key=lambda x: x["display_name"])


@router.post("/carriers")
def add_carrier(
    data: CarrierRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new carrier to the config table."""
    require_admin(current_user)
    name = data.name.lower().replace(" ", "_").replace("-", "_")
    display = data.display_name or data.name.replace("_", " ").title()

    existing = db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "carrier", AgencyConfig.name == name,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Carrier already exists")

    db.add(AgencyConfig(config_type="carrier", name=name, display_name=display))
    db.commit()
    return {"success": True, "name": name, "display_name": display}


@router.delete("/carriers/{carrier_name}")
def delete_carrier(
    carrier_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a carrier. Blocks if sales reference it."""
    require_admin(current_user)

    key = carrier_name.lower().replace(" ", "_").replace("-", "_")
    variants = [carrier_name, key, key.replace("_", " "), key.replace("_", " ").title()]

    from sqlalchemy import or_
    sale_count = db.query(func.count(Sale.id)).filter(
        or_(*[Sale.carrier == v for v in variants])
    ).scalar() or 0

    if sale_count > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete " + carrier_name.replace("_", " ").title() + " - it has " + str(sale_count) + " sales linked to it."
        )

    db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "carrier", AgencyConfig.name == key,
    ).delete()
    db.commit()
    return {"success": True, "deleted": carrier_name}


@router.delete("/lead-sources/{source_name}")
def delete_lead_source(
    source_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a lead source. Blocks if sales reference it."""
    require_admin(current_user)

    key = source_name.lower().replace(" ", "_").replace("-", "_")
    variants = [source_name, key, key.replace("_", " "), key.replace("_", " ").title()]

    from sqlalchemy import or_
    sale_count = db.query(func.count(Sale.id)).filter(
        or_(*[Sale.lead_source == v for v in variants])
    ).scalar() or 0

    if sale_count > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete " + source_name.replace("_", " ").title() + " - it has " + str(sale_count) + " sales linked to it."
        )

    db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "lead_source", AgencyConfig.name == key,
    ).delete()
    db.commit()
    return {"success": True, "deleted": source_name}


# ── Survey Stats (for admin dashboard) ───────────────────────────────

@router.get("/survey-stats")
def get_survey_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get welcome email and survey statistics."""
    require_admin(current_user)

    from app.models.survey import SurveyResponse

    total_emails_sent = db.query(func.count(Sale.id)).filter(Sale.welcome_email_sent == True).scalar() or 0
    total_surveys = db.query(func.count(SurveyResponse.id)).scalar() or 0
    avg_rating = db.query(func.avg(SurveyResponse.rating)).scalar()
    five_stars = db.query(func.count(SurveyResponse.id)).filter(SurveyResponse.rating == 5).scalar() or 0

    return {
        "total_emails_sent": total_emails_sent,
        "total_surveys": total_surveys,
        "average_rating": round(float(avg_rating), 1) if avg_rating else 0,
        "five_star_count": five_stars,
    }


# ── Public config endpoints (for dropdowns, any logged-in user) ──────

@router.get("/dropdown-options")
def get_dropdown_options(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get lead sources and carriers for form dropdowns. Any logged-in user."""
    # Lead sources: config table + in-use on sales
    ls_configs = db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "lead_source", AgencyConfig.is_active == True,
    ).all()
    ls_in_use = db.query(Sale.lead_source).filter(
        Sale.lead_source.isnot(None), Sale.lead_source != "",
    ).distinct().all()

    source_map = {}
    for c in ls_configs:
        source_map[c.name] = c.display_name
    for row in ls_in_use:
        raw = row[0]
        key = raw.lower().replace(" ", "_").replace("-", "_")
        if key not in source_map:
            source_map[key] = raw.replace("_", " ").title()
            if " " in raw or (raw and raw[0].isupper()):
                source_map[key] = raw

    # Carriers: config table + in-use
    cr_configs = db.query(AgencyConfig).filter(
        AgencyConfig.config_type == "carrier", AgencyConfig.is_active == True,
    ).all()
    cr_in_use = db.query(Sale.carrier).filter(
        Sale.carrier.isnot(None), Sale.carrier != "",
    ).distinct().all()

    carrier_map = {}
    for c in cr_configs:
        carrier_map[c.name] = c.display_name
    for row in cr_in_use:
        raw = row[0]
        key = raw.lower().replace(" ", "_").replace("-", "_")
        if key not in carrier_map:
            carrier_map[key] = raw.replace("_", " ").title()
            if " " in raw or (raw and raw[0].isupper()):
                carrier_map[key] = raw

    return {
        "lead_sources": sorted([{"value": k, "label": v} for k, v in source_map.items()], key=lambda x: x["label"]),
        "carriers": sorted([{"value": k, "label": v} for k, v in carrier_map.items()], key=lambda x: x["label"]),
    }
