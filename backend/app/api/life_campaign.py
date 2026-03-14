"""Life Cross-Sell Campaign API.

Manages the automated life insurance cross-sell drip campaign.
Endpoints to enroll customers, view campaign status, and trigger sends.
"""
import logging
from datetime import datetime, timedelta, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy
from app.models.sale import Sale
from app.models.life_campaign import LifeCrossSellContact
from app.services.life_crosssell_campaign import (
    TOUCH_BUILDERS, TOUCH_DELAYS, send_life_crosssell_email,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/life-campaign", tags=["life-campaign"])


@router.get("/dashboard")
def campaign_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Campaign overview stats."""
    total = db.query(func.count(LifeCrossSellContact.id)).scalar() or 0
    active = db.query(func.count(LifeCrossSellContact.id)).filter(
        LifeCrossSellContact.status == "active"
    ).scalar() or 0
    completed = db.query(func.count(LifeCrossSellContact.id)).filter(
        LifeCrossSellContact.status == "completed"
    ).scalar() or 0
    opted_out = db.query(func.count(LifeCrossSellContact.id)).filter(
        LifeCrossSellContact.status == "opted_out"
    ).scalar() or 0
    total_clicks = db.query(func.coalesce(func.sum(LifeCrossSellContact.total_clicks), 0)).scalar() or 0
    total_opens = db.query(func.coalesce(func.sum(LifeCrossSellContact.total_opens), 0)).scalar() or 0

    # Touches sent breakdown
    t1 = db.query(func.count(LifeCrossSellContact.id)).filter(LifeCrossSellContact.touch1_sent_at.isnot(None)).scalar()
    t2 = db.query(func.count(LifeCrossSellContact.id)).filter(LifeCrossSellContact.touch2_sent_at.isnot(None)).scalar()
    t3 = db.query(func.count(LifeCrossSellContact.id)).filter(LifeCrossSellContact.touch3_sent_at.isnot(None)).scalar()
    t4 = db.query(func.count(LifeCrossSellContact.id)).filter(LifeCrossSellContact.touch4_sent_at.isnot(None)).scalar()

    # Pending sends today
    now = datetime.utcnow()
    pending_today = db.query(func.count(LifeCrossSellContact.id)).filter(
        LifeCrossSellContact.status == "active",
        LifeCrossSellContact.next_touch_date <= now,
    ).scalar() or 0

    return {
        "total_enrolled": total,
        "active": active,
        "completed": completed,
        "opted_out": opted_out,
        "total_emails_sent": t1 + t2 + t3 + t4,
        "total_opens": total_opens,
        "total_clicks": total_clicks,
        "pending_today": pending_today,
        "touches": {"touch1": t1, "touch2": t2, "touch3": t3, "touch4": t4},
    }


@router.get("/contacts")
def list_contacts(
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List enrolled contacts with filters."""
    query = db.query(LifeCrossSellContact)
    if status:
        query = query.filter(LifeCrossSellContact.status == status)
    if search:
        query = query.filter(
            LifeCrossSellContact.customer_name.ilike(f"%{search}%")
            | LifeCrossSellContact.customer_email.ilike(f"%{search}%")
        )

    total = query.count()
    contacts = query.order_by(LifeCrossSellContact.next_touch_date.asc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "contacts": [{
            "id": c.id,
            "customer_id": c.customer_id,
            "customer_name": c.customer_name,
            "customer_email": c.customer_email,
            "agent_name": c.agent_name,
            "touch_number": c.touch_number,
            "next_touch_date": c.next_touch_date.isoformat() if c.next_touch_date else None,
            "status": c.status,
            "total_opens": c.total_opens,
            "total_clicks": c.total_clicks,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in contacts],
    }


@router.post("/enroll")
def enroll_customer(
    customer_id: int = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually enroll a customer in the life cross-sell campaign."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not customer.email:
        raise HTTPException(status_code=400, detail="Customer has no email address")

    # Check if already enrolled
    existing = db.query(LifeCrossSellContact).filter(
        LifeCrossSellContact.customer_id == customer_id,
        LifeCrossSellContact.status.in_(["queued", "active"]),
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Customer already enrolled in campaign")

    contact = LifeCrossSellContact(
        customer_id=customer_id,
        customer_name=customer.full_name,
        customer_email=customer.email,
        agent_name=customer.agent_name or current_user.full_name,
        agent_email=current_user.email,
        touch_number=0,
        next_touch_date=datetime.utcnow() + timedelta(days=TOUCH_DELAYS[1]),
        status="active",
    )
    db.add(contact)
    db.commit()

    return {"enrolled": True, "contact_id": contact.id, "next_touch": contact.next_touch_date.isoformat()}


@router.post("/enroll-bulk")
def enroll_bulk(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Auto-enroll all eligible customers who aren't already in the campaign.
    
    Eligible = has email, has active P&C policy, not already enrolled or opted out.
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    # Find all customers with email and active policies
    already_enrolled = db.query(LifeCrossSellContact.customer_id).filter(
        LifeCrossSellContact.status.in_(["queued", "active", "completed", "opted_out"])
    ).subquery()

    eligible = db.query(Customer).join(
        CustomerPolicy, Customer.id == CustomerPolicy.customer_id
    ).filter(
        Customer.email.isnot(None),
        Customer.email != "",
        CustomerPolicy.status.in_(["Active", "active", "In Force", "in force"]),
        ~Customer.id.in_(db.query(already_enrolled)),
    ).distinct().all()

    enrolled = 0
    for customer in eligible:
        contact = LifeCrossSellContact(
            customer_id=customer.id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            agent_name=customer.agent_name,
            touch_number=0,
            next_touch_date=datetime.utcnow() + timedelta(days=TOUCH_DELAYS[1]),
            status="active",
        )
        db.add(contact)
        enrolled += 1

    db.commit()
    return {"enrolled": enrolled, "total_eligible": len(eligible)}


@router.post("/send-pending")
def send_pending_touches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send all pending touches that are due."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    now = datetime.utcnow()
    pending = db.query(LifeCrossSellContact).filter(
        LifeCrossSellContact.status == "active",
        LifeCrossSellContact.next_touch_date <= now,
    ).all()

    sent = 0
    errors = 0
    for contact in pending:
        next_touch = contact.touch_number + 1
        if next_touch > 4:
            contact.status = "completed"
            db.commit()
            continue

        builder = TOUCH_BUILDERS.get(next_touch)
        if not builder:
            continue

        first_name = (contact.customer_name or "").split()[0] if contact.customer_name else "there"

        if next_touch == 2:
            subject, html = builder(first_name, contact.agent_name or "", 0, contact.customer_id)
        else:
            subject, html = builder(first_name, contact.agent_name or "", contact.customer_id)

        result = send_life_crosssell_email(
            to_email=contact.customer_email,
            subject=subject,
            html=html,
            agent_email=contact.agent_email or "",
        )

        if result.get("success"):
            setattr(contact, f"touch{next_touch}_sent_at", now)
            contact.touch_number = next_touch

            if next_touch < 4:
                next_delay = TOUCH_DELAYS.get(next_touch + 1, 30)
                contact.next_touch_date = now + timedelta(days=next_delay)
            else:
                contact.status = "completed"
                contact.next_touch_date = None

            sent += 1
        else:
            errors += 1
            logger.warning(f"Life cross-sell send failed for {contact.customer_email}: {result}")

    db.commit()
    return {"sent": sent, "errors": errors, "pending_processed": len(pending)}


@router.post("/opt-out/{contact_id}")
def opt_out(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Opt a customer out of the life cross-sell campaign."""
    contact = db.query(LifeCrossSellContact).filter(LifeCrossSellContact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact.status = "opted_out"
    db.commit()
    return {"opted_out": True}


@router.post("/preview/{touch_number}")
def preview_touch(
    touch_number: int,
    customer_name: str = Body("John Smith"),
    agent_name: str = Body("Evan Larson"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview a touch email (for testing)."""
    builder = TOUCH_BUILDERS.get(touch_number)
    if not builder:
        raise HTTPException(status_code=400, detail=f"Invalid touch number. Must be 1-4.")

    first_name = customer_name.split()[0] if customer_name else "there"
    if touch_number == 2:
        subject, html = builder(first_name, agent_name, 2500, 0)
    else:
        subject, html = builder(first_name, agent_name, 0)

    return {"touch": touch_number, "subject": subject, "html": html}
