"""Reshop Pipeline API — manage customer reshop/rewrite requests.

Role-based access:
- Admin: full access, can see all, assign anyone
- Retention (Salma, Michelle): full access to pipeline, present quotes
- Manager: full access
- Producer (Joseph, Giulian): can create/refer reshops, view own referrals
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, func, desc, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy
from app.models.reshop import Reshop, ReshopActivity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reshops", tags=["reshops"])

# ── Constants ─────────────────────────────────────────────────────

STAGES = ["proactive", "new_request", "quoting", "quote_ready", "presenting", "bound", "lost", "cancelled"]
ACTIVE_STAGES = ["proactive", "new_request", "quoting", "quote_ready", "presenting"]
CLOSED_STAGES = ["bound", "lost", "cancelled"]
SOURCES = ["inbound_call", "inbound_email", "producer_referral", "proactive_renewal", "walk_in", "nonpay_escalation", "other"]
REASONS = ["price_increase", "service_issue", "coverage_change", "shopping", "nonpay", "renewal_increase", "other"]
PRIORITIES = ["low", "normal", "high", "urgent"]


# ── Schemas ───────────────────────────────────────────────────────

class ReshopCreate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    line_of_business: Optional[str] = None
    current_premium: Optional[float] = None
    expiration_date: Optional[str] = None
    source: Optional[str] = None
    source_detail: Optional[str] = None
    reason: Optional[str] = None
    reason_detail: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = "normal"
    stage: Optional[str] = "new_request"


class ReshopUpdate(BaseModel):
    stage: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None
    quoter: Optional[str] = None
    presenter: Optional[str] = None
    quoted_carrier: Optional[str] = None
    quoted_premium: Optional[float] = None
    quote_notes: Optional[str] = None
    outcome: Optional[str] = None
    outcome_notes: Optional[str] = None
    bound_carrier: Optional[str] = None
    bound_premium: Optional[float] = None
    reason: Optional[str] = None
    reason_detail: Optional[str] = None
    notes: Optional[str] = None


class ReshopNote(BaseModel):
    text: str


# ── Helpers ───────────────────────────────────────────────────────

def _can_access(user: User) -> bool:
    """Check if user can access the reshop pipeline."""
    return user.role in ("admin", "retention_specialist", "manager", "producer")


def _can_manage(user: User) -> bool:
    """Check if user can manage reshops (full CRUD, assign, stage changes)."""
    return user.role in ("admin", "retention_specialist", "manager")


def _reshop_to_dict(r: Reshop) -> dict:
    return {
        "id": r.id,
        "customer_id": r.customer_id,
        "customer_name": r.customer_name,
        "customer_phone": r.customer_phone,
        "customer_email": r.customer_email,
        "policy_number": r.policy_number,
        "carrier": r.carrier,
        "line_of_business": r.line_of_business,
        "current_premium": float(r.current_premium) if r.current_premium else None,
        "expiration_date": r.expiration_date.isoformat() if r.expiration_date else None,
        "stage": r.stage,
        "priority": r.priority,
        "source": r.source,
        "source_detail": r.source_detail,
        "referred_by": r.referred_by,
        "assigned_to": r.assigned_to,
        "assignee_name": r.assignee.full_name if r.assignee else None,
        "quoter": r.quoter,
        "presenter": r.presenter,
        "quoted_carrier": r.quoted_carrier,
        "quoted_premium": float(r.quoted_premium) if r.quoted_premium else None,
        "premium_savings": float(r.premium_savings) if r.premium_savings else None,
        "quote_notes": r.quote_notes,
        "outcome": r.outcome,
        "outcome_notes": r.outcome_notes,
        "bound_carrier": r.bound_carrier,
        "bound_premium": float(r.bound_premium) if r.bound_premium else None,
        "bound_date": r.bound_date.isoformat() if r.bound_date else None,
        "reason": r.reason,
        "reason_detail": r.reason_detail,
        "notes": r.notes,
        "is_proactive": r.is_proactive,
        "renewal_premium": float(r.renewal_premium) if r.renewal_premium else None,
        "premium_change_pct": float(r.premium_change_pct) if r.premium_change_pct else None,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "stage_updated_at": r.stage_updated_at.isoformat() if r.stage_updated_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _activity_to_dict(a: ReshopActivity) -> dict:
    return {
        "id": a.id,
        "reshop_id": a.reshop_id,
        "user_name": a.user_name,
        "action": a.action,
        "detail": a.detail,
        "old_value": a.old_value,
        "new_value": a.new_value,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _log_activity(db: Session, reshop_id: int, user: User, action: str,
                   detail: str = None, old_value: str = None, new_value: str = None):
    activity = ReshopActivity(
        reshop_id=reshop_id,
        user_id=user.id,
        user_name=user.full_name or user.username,
        action=action,
        detail=detail,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(activity)


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("")
def list_reshops(
    stage: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    show_closed: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List reshops with filters. Producers see only their referrals."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Reshop)

    # Producers only see reshops they referred
    if current_user.role == "producer":
        query = query.filter(
            or_(
                Reshop.referred_by == current_user.full_name,
                Reshop.referred_by == current_user.username,
            )
        )

    if stage:
        query = query.filter(Reshop.stage == stage)
    elif not show_closed:
        query = query.filter(Reshop.stage.in_(ACTIVE_STAGES))

    if assigned_to:
        query = query.filter(Reshop.assigned_to == assigned_to)
    if priority:
        query = query.filter(Reshop.priority == priority)

    if search:
        q = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(Reshop.customer_name).like(q),
                func.lower(Reshop.policy_number).like(q),
                func.lower(Reshop.carrier).like(q),
                func.lower(Reshop.customer_email).like(q),
                func.lower(Reshop.customer_phone).like(q),
            )
        )

    # Order: urgent first, then by stage_updated_at
    priority_order = case(
        (Reshop.priority == "urgent", 0),
        (Reshop.priority == "high", 1),
        (Reshop.priority == "normal", 2),
        else_=3
    )
    query = query.order_by(priority_order, desc(Reshop.stage_updated_at))

    reshops = query.limit(200).all()
    return {
        "reshops": [_reshop_to_dict(r) for r in reshops],
        "total": len(reshops),
    }


@router.get("/stats")
def reshop_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pipeline stats for the reshop board."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    active = db.query(Reshop).filter(Reshop.stage.in_(ACTIVE_STAGES)).all()

    stage_counts = {}
    for s in STAGES:
        stage_counts[s] = sum(1 for r in active if r.stage == s)

    # Win/loss this month
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    bound_this_month = db.query(Reshop).filter(
        Reshop.stage == "bound",
        Reshop.completed_at >= month_start,
    ).count()
    lost_this_month = db.query(Reshop).filter(
        Reshop.stage == "lost",
        Reshop.completed_at >= month_start,
    ).count()

    # Total savings this month
    savings = db.query(func.sum(Reshop.premium_savings)).filter(
        Reshop.stage == "bound",
        Reshop.completed_at >= month_start,
    ).scalar() or 0

    # Urgency breakdown
    urgent_count = sum(1 for r in active if r.priority in ("urgent", "high"))
    expiring_soon = sum(
        1 for r in active
        if r.expiration_date and r.expiration_date <= datetime.utcnow() + timedelta(days=14)
    )

    return {
        "stage_counts": stage_counts,
        "total_active": len(active),
        "bound_this_month": bound_this_month,
        "lost_this_month": lost_this_month,
        "win_rate": round(bound_this_month / max(bound_this_month + lost_this_month, 1) * 100, 1),
        "savings_this_month": float(savings),
        "urgent_count": urgent_count,
        "expiring_soon": expiring_soon,
    }


@router.get("/team/members")
def get_team_members(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get team members for assignment dropdowns."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    users = db.query(User).filter(User.is_active == True).all()
    return {
        "members": [
            {
                "id": u.id,
                "name": u.full_name or u.username,
                "role": u.role,
                "username": u.username,
            }
            for u in users
        ]
    }


@router.post("")
def create_reshop(
    data: ReshopCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new reshop request. Producers can create (as referrals)."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Parse expiration date
    exp_date = None
    if data.expiration_date:
        try:
            exp_date = datetime.fromisoformat(data.expiration_date.replace("Z", "+00:00"))
        except Exception:
            try:
                exp_date = datetime.strptime(data.expiration_date[:10], "%Y-%m-%d")
            except Exception:
                pass

    reshop = Reshop(
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_email=data.customer_email,
        policy_number=data.policy_number,
        carrier=data.carrier,
        line_of_business=data.line_of_business,
        current_premium=data.current_premium,
        expiration_date=exp_date,
        stage=data.stage or "new_request",
        priority=data.priority or "normal",
        source=data.source,
        source_detail=data.source_detail,
        reason=data.reason,
        reason_detail=data.reason_detail,
        notes=data.notes,
        is_proactive=(data.stage == "proactive"),
        referred_by=current_user.full_name or current_user.username if current_user.role == "producer" else None,
    )
    db.add(reshop)
    db.flush()

    _log_activity(db, reshop.id, current_user, "created",
                  f"Reshop created via {data.source or 'manual entry'}")

    db.commit()
    db.refresh(reshop)
    return _reshop_to_dict(reshop)


@router.get("/{reshop_id}")
def get_reshop(
    reshop_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single reshop with its activity log."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    activities = (
        db.query(ReshopActivity)
        .filter(ReshopActivity.reshop_id == reshop_id)
        .order_by(desc(ReshopActivity.created_at))
        .all()
    )

    return {
        "reshop": _reshop_to_dict(reshop),
        "activities": [_activity_to_dict(a) for a in activities],
    }


@router.patch("/{reshop_id}")
def update_reshop(
    reshop_id: int,
    data: ReshopUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a reshop. Retention/admin can update all fields."""
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to manage reshops")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    # Track stage change
    if data.stage and data.stage != reshop.stage:
        old_stage = reshop.stage
        reshop.stage = data.stage
        reshop.stage_updated_at = datetime.utcnow()

        if data.stage in CLOSED_STAGES:
            reshop.completed_at = datetime.utcnow()
        else:
            reshop.completed_at = None

        _log_activity(db, reshop.id, current_user, "stage_change",
                      f"Stage changed from {old_stage} to {data.stage}",
                      old_stage, data.stage)

    if data.priority and data.priority != reshop.priority:
        _log_activity(db, reshop.id, current_user, "priority_change",
                      f"Priority changed to {data.priority}",
                      reshop.priority, data.priority)
        reshop.priority = data.priority

    if data.assigned_to is not None and data.assigned_to != reshop.assigned_to:
        assignee = db.query(User).filter(User.id == data.assigned_to).first()
        _log_activity(db, reshop.id, current_user, "assigned",
                      f"Assigned to {assignee.full_name if assignee else 'unassigned'}")
        reshop.assigned_to = data.assigned_to

    if data.quoter is not None:
        reshop.quoter = data.quoter
    if data.presenter is not None:
        reshop.presenter = data.presenter

    if data.quoted_carrier is not None:
        reshop.quoted_carrier = data.quoted_carrier
    if data.quoted_premium is not None:
        reshop.quoted_premium = data.quoted_premium
        if reshop.current_premium and data.quoted_premium:
            reshop.premium_savings = float(reshop.current_premium) - float(data.quoted_premium)
        _log_activity(db, reshop.id, current_user, "quoted",
                      f"Quote: {data.quoted_carrier or reshop.quoted_carrier} @ ${data.quoted_premium:,.0f}")
    if data.quote_notes is not None:
        reshop.quote_notes = data.quote_notes

    if data.outcome is not None:
        reshop.outcome = data.outcome
    if data.outcome_notes is not None:
        reshop.outcome_notes = data.outcome_notes
    if data.bound_carrier is not None:
        reshop.bound_carrier = data.bound_carrier
    if data.bound_premium is not None:
        reshop.bound_premium = data.bound_premium
        reshop.bound_date = datetime.utcnow()
        if reshop.current_premium:
            reshop.premium_savings = float(reshop.current_premium) - float(data.bound_premium)

    if data.reason is not None:
        reshop.reason = data.reason
    if data.reason_detail is not None:
        reshop.reason_detail = data.reason_detail
    if data.notes is not None:
        reshop.notes = data.notes

    db.commit()
    db.refresh(reshop)
    return _reshop_to_dict(reshop)


@router.post("/{reshop_id}/note")
def add_reshop_note(
    reshop_id: int,
    data: ReshopNote,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add an activity note to a reshop."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    _log_activity(db, reshop.id, current_user, "note", data.text)
    db.commit()
    return {"status": "ok"}


@router.post("/{reshop_id}/move")
def move_reshop_stage(
    reshop_id: int,
    stage: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Quick stage move endpoint. Producers can move TO new_request (refer).
    Retention/admin can move to any stage."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {stage}")

    # Producers can only refer (move to new_request)
    if current_user.role == "producer" and stage != "new_request":
        raise HTTPException(status_code=403, detail="Producers can only refer reshops")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    old_stage = reshop.stage
    reshop.stage = stage
    reshop.stage_updated_at = datetime.utcnow()

    if stage in CLOSED_STAGES:
        reshop.completed_at = datetime.utcnow()
    else:
        reshop.completed_at = None

    _log_activity(db, reshop.id, current_user, "stage_change",
                  f"Moved from {old_stage} to {stage}", old_stage, stage)
    db.commit()
    return _reshop_to_dict(reshop)




# ── Proactive Detection ──────────────────────────────────────────

@router.post("/detect-proactive")
def detect_proactive_reshops(
    days_out: int = Query(60, description="Look for renewals within N days"),
    increase_threshold: float = Query(10.0, description="Minimum premium increase % to flag"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan upcoming renewals and create proactive reshop entries for policies
    with significant premium increases or other risk factors.
    
    This checks policies expiring within `days_out` days and flags those where
    the renewal premium represents a significant increase.
    
    Admin/retention only.
    """
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_out)

    # Find active policies expiring in the window
    expiring = (
        db.query(CustomerPolicy)
        .filter(
            CustomerPolicy.expiration_date >= now,
            CustomerPolicy.expiration_date <= cutoff,
            func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]),
        )
        .all()
    )

    # Check which ones already have reshops
    existing_policy_nums = set()
    active_reshops = db.query(Reshop).filter(Reshop.stage.in_(ACTIVE_STAGES)).all()
    for r in active_reshops:
        if r.policy_number:
            existing_policy_nums.add(r.policy_number.lower())

    created = 0
    skipped = 0

    for policy in expiring:
        pnum = (policy.policy_number or "").lower()
        if pnum and pnum in existing_policy_nums:
            skipped += 1
            continue

        # Get the customer
        customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()
        if not customer:
            continue

        # Flag reason: upcoming renewal (we don't have renewal premium in our data,
        # but we can flag all renewals for manual review, or those with high premiums)
        reshop = Reshop(
            customer_id=customer.id,
            customer_name=customer.full_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip(),
            customer_phone=customer.phone,
            customer_email=customer.email,
            policy_number=policy.policy_number,
            carrier=policy.carrier,
            line_of_business=policy.line_of_business,
            current_premium=policy.premium,
            expiration_date=policy.expiration_date,
            stage="proactive",
            priority="normal",
            source="proactive_renewal",
            source_detail=f"Renewal in {(policy.expiration_date - now).days} days",
            is_proactive=True,
        )
        db.add(reshop)
        db.flush()
        _log_activity(db, reshop.id, current_user, "created",
                      f"Proactive: renewal in {(policy.expiration_date - now).days} days, "
                      f"current premium ${float(policy.premium or 0):,.0f}")
        created += 1
        existing_policy_nums.add(pnum)

    db.commit()
    return {
        "status": "ok",
        "created": created,
        "skipped": skipped,
        "policies_checked": len(expiring),
    }


# ── Create from Customer Card ────────────────────────────────────

@router.post("/from-customer/{customer_id}")
def create_reshop_from_customer(
    customer_id: int,
    policy_id: Optional[int] = Query(None),
    source: Optional[str] = Query("inbound_call"),
    reason: Optional[str] = Query(None),
    notes: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Quick-create a reshop from the customer card. Pulls customer + policy info automatically."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    policy = None
    if policy_id:
        policy = db.query(CustomerPolicy).filter(CustomerPolicy.id == policy_id).first()

    reshop = Reshop(
        customer_id=customer.id,
        customer_name=customer.full_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip(),
        customer_phone=customer.phone,
        customer_email=customer.email,
        policy_number=policy.policy_number if policy else None,
        carrier=policy.carrier if policy else None,
        line_of_business=policy.line_of_business if policy else None,
        current_premium=policy.premium if policy else None,
        expiration_date=policy.expiration_date if policy else None,
        stage="new_request",
        priority="normal",
        source=source,
        reason=reason,
        notes=notes,
        referred_by=current_user.full_name if current_user.role == "producer" else None,
    )
    db.add(reshop)
    db.flush()

    _log_activity(db, reshop.id, current_user, "created",
                  f"Created from customer card by {current_user.full_name or current_user.username}")
    db.commit()
    db.refresh(reshop)
    return _reshop_to_dict(reshop)
