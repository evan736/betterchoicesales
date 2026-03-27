"""
Leads API — Round-robin assignment to producers.
- POST /api/leads/inbound  (no auth — called by quote form)
- GET  /api/leads           (auth — list/filter leads)
- GET  /api/leads/stats     (auth — dashboard stats)
- PATCH /api/leads/{id}     (auth — update status/notes)
- GET  /api/leads/roster    (auth — view/manage round-robin roster)
- POST /api/leads/roster/{user_id}/toggle  (admin — enable/disable agent in rotation)
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text, desc, func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.lead import Lead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/leads", tags=["leads"])

MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
AGENCY_FROM_EMAIL = os.environ.get("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")

# System accounts to exclude from round-robin
EXCLUDED_USERNAMES = {"admin", "beacon.ai"}


# ═══════════════════════════════════════════════════════════════════
# ROUND ROBIN ENGINE
# ═══════════════════════════════════════════════════════════════════

def get_eligible_producers(db: Session) -> list[User]:
    """Get active producers eligible for lead assignment.
    
    Producers are users with role='producer' who are active.
    Excludes system accounts (admin, beacon.ai).
    Also checks round_robin_eligible flag if it exists.
    """
    producers = db.query(User).filter(
        User.role == "producer",
        User.is_active == True,
        User.username.notin_(EXCLUDED_USERNAMES),
    ).order_by(User.id).all()
    
    # Check if any have round_robin_eligible=False (column added later)
    eligible = []
    for p in producers:
        # Default to eligible if column doesn't exist yet
        rr_eligible = getattr(p, "round_robin_eligible", True)
        if rr_eligible is None or rr_eligible:
            eligible.append(p)
    
    return eligible


def assign_round_robin(db: Session) -> Optional[User]:
    """Pick the next producer in round-robin order. Returns None if no producers available."""
    producers = get_eligible_producers(db)
    if not producers:
        logger.warning("No eligible producers for round-robin assignment!")
        return None

    # Get current round-robin state
    state = db.execute(text("SELECT last_assigned_user_id, total_assigned FROM round_robin_state LIMIT 1")).fetchone()
    
    if not state:
        # Create state row if missing
        db.execute(text("INSERT INTO round_robin_state (last_assigned_user_id, total_assigned) VALUES (NULL, 0)"))
        last_id = None
        total = 0
    else:
        last_id = state[0]
        total = state[1] or 0

    # Find next producer after the last assigned one
    producer_ids = [p.id for p in producers]
    
    if last_id is None or last_id not in producer_ids:
        # First assignment or last assigned person left — start from beginning
        next_producer = producers[0]
    else:
        # Find index of last assigned, pick next (wrapping around)
        idx = producer_ids.index(last_id)
        next_idx = (idx + 1) % len(producers)
        next_producer = producers[next_idx]

    # Update state
    db.execute(text(
        "UPDATE round_robin_state SET last_assigned_user_id = :uid, last_assigned_at = NOW(), total_assigned = :total"
    ), {"uid": next_producer.id, "total": total + 1})
    
    return next_producer


def check_duplicate(db: Session, phone: str, name: str) -> Optional[Lead]:
    """Check if a lead with this phone number was submitted in the last 24 hours."""
    if not phone:
        return None
    
    # Normalize phone — strip all non-digits
    clean_phone = "".join(c for c in phone if c.isdigit())
    if len(clean_phone) < 7:
        return None
    
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    # Check for same phone in last 24h
    existing = db.query(Lead).filter(
        Lead.phone.ilike(f"%{clean_phone[-7:]}%"),  # Match last 7 digits
        Lead.created_at >= cutoff,
        Lead.is_duplicate == False,
    ).order_by(desc(Lead.created_at)).first()
    
    return existing


# ═══════════════════════════════════════════════════════════════════
# INBOUND LEAD CAPTURE (NO AUTH — PUBLIC ENDPOINT)
# ═══════════════════════════════════════════════════════════════════

@router.post("/inbound")
async def capture_lead(request: Request, db: Session = Depends(get_db)):
    """Capture a lead from the quote form and assign via round-robin."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    
    if not name or not phone:
        raise HTTPException(status_code=400, detail="Name and phone are required")

    # Check for duplicate
    existing = check_duplicate(db, phone, name)
    is_dup = existing is not None
    
    # Assign via round-robin (even for dupes — they go to same agent for context)
    if is_dup and existing:
        assigned_user = db.query(User).filter(User.id == existing.assigned_to_id).first()
        if not assigned_user:
            assigned_user = assign_round_robin(db)
    else:
        assigned_user = assign_round_robin(db)

    # Create lead record
    lead = Lead(
        name=name,
        phone=phone,
        email=email,
        dob=data.get("dob", ""),
        address=data.get("address", ""),
        city=data.get("city", ""),
        state=data.get("state", ""),
        zip_code=data.get("zip_code") or data.get("zip", ""),
        policy_types=data.get("policy_type") or data.get("policy_types", ""),
        current_carrier=data.get("current_carrier", ""),
        current_premium=data.get("current_premium", ""),
        renewal_date=data.get("renewal_date", ""),
        message=data.get("message", ""),
        roof_year=data.get("roof_year", ""),
        home_year=data.get("home_year", ""),
        sqft=data.get("sqft", ""),
        drivers_info=data.get("drivers_info", ""),
        vehicles_info=data.get("vehicles_info", ""),
        source=data.get("source", "website"),
        utm_campaign=data.get("utm_campaign", ""),
        assigned_to_id=assigned_user.id if assigned_user else None,
        assigned_to_name=assigned_user.full_name if assigned_user else None,
        assigned_at=datetime.utcnow() if assigned_user else None,
        status="new",
        is_duplicate=is_dup,
        duplicate_of_id=existing.id if is_dup and existing else None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Send notification email to assigned agent
    if assigned_user and not is_dup:
        _send_lead_notification(lead, assigned_user)
    elif is_dup:
        logger.info(f"Duplicate lead from {phone} — skipping notification (original lead #{existing.id})")

    # Also notify Evan on every lead (admin visibility)
    if not is_dup:
        _send_admin_lead_notification(lead, assigned_user)

    logger.info(
        f"Lead #{lead.id} captured: {name} / {phone} → assigned to {assigned_user.full_name if assigned_user else 'UNASSIGNED'}"
        f"{' (DUPLICATE of #' + str(existing.id) + ')' if is_dup else ''}"
    )

    return {
        "status": "ok",
        "lead_id": lead.id,
        "assigned_to": assigned_user.full_name if assigned_user else None,
        "is_duplicate": is_dup,
    }


# ═══════════════════════════════════════════════════════════════════
# EMAIL NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════

def _send_lead_notification(lead: Lead, agent: User):
    """Send branded lead alert email to the assigned agent."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        return

    first_name = agent.full_name.split()[0] if agent.full_name else "Team"
    lead_first = lead.name.split()[0] if lead.name else "Lead"
    phone_digits = lead.phone.replace("(", "").replace(")", "").replace("-", "").replace(" ", "")

    # Build detail rows
    rows = [
        ("Name", lead.name, True),
        ("Phone", lead.phone, True),
        ("Email", lead.email, False),
        ("Products", lead.policy_types, False),
        ("Address", f"{lead.address}, {lead.city}, {lead.state} {lead.zip_code}".strip(", ") if lead.address else "", False),
        ("Current Carrier", lead.current_carrier, False),
        ("Current Premium", f"${lead.current_premium}/yr" if lead.current_premium else "", False),
        ("Renewal Date", lead.renewal_date, False),
        ("Source", lead.source, False),
    ]
    
    table_rows = ""
    for label, value, bold in rows:
        if value:
            weight = "font-weight:700;" if bold else ""
            table_rows += f'<tr><td style="padding:8px 0;color:#64748b;width:140px;">{label}</td><td style="padding:8px 0;{weight}">{value}</td></tr>'

    message_block = ""
    if lead.message:
        message_block = f'''
        <div style="margin:16px 0;padding:12px 16px;background:#f0f9ff;border-radius:8px;border:1px solid #bae6fd;">
            <p style="margin:0;font-size:13px;color:#0369a1;white-space:pre-line;"><strong>Details:</strong><br/>{lead.message}</p>
        </div>'''

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;margin:0;padding:20px;background:#f1f5f9;">
    <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <div style="background:linear-gradient(135deg,#2563eb,#3b82f6);padding:20px 28px;">
            <h2 style="margin:0;color:#fff;font-size:18px;">🎯 New Lead Assigned to You</h2>
            <p style="margin:4px 0 0;color:rgba(255,255,255,0.8);font-size:13px;">via Better Choice Insurance quote form</p>
        </div>
        <div style="padding:24px 28px;">
            <p style="margin:0 0 16px;color:#334155;font-size:15px;">
                Hey {first_name}, you've been assigned a new lead!
            </p>
            <table style="width:100%;font-size:14px;color:#334155;" cellpadding="0" cellspacing="0">
                {table_rows}
            </table>
            {message_block}
            <div style="margin-top:20px;display:flex;gap:12px;">
                <a href="tel:{phone_digits}"
                   style="display:inline-block;background:#2563eb;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;">
                    📞 Call {lead_first} Now
                </a>
                <a href="https://orbit.betterchoiceins.com/leads"
                   style="display:inline-block;background:#0f172a;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;">
                    View in ORBIT
                </a>
            </div>
        </div>
        <div style="background:#f8fafc;padding:12px 28px;border-top:1px solid #e2e8f0;">
            <p style="margin:0;color:#94a3b8;font-size:11px;">Better Choice Insurance Group · ORBIT Lead Distribution</p>
        </div>
    </div></body></html>"""

    try:
        httpx.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={
                "from": f"ORBIT Lead Alert <{AGENCY_FROM_EMAIL}>",
                "to": [agent.email],
                "cc": ["evan@betterchoiceins.com"],
                "subject": f"🎯 New Lead: {lead.name} — {lead.phone} ({lead.policy_types or 'Quote'})",
                "html": html,
                "o:tag": ["lead-assignment", "round-robin"],
            },
        )
        logger.info(f"Lead notification sent to {agent.email} for lead #{lead.id}")
    except Exception as e:
        logger.warning(f"Failed to send lead notification to {agent.email}: {e}")


def _send_admin_lead_notification(lead: Lead, assigned_to: Optional[User]):
    """Send lead notification to Evan (admin visibility on all leads)."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        return

    agent_name = assigned_to.full_name if assigned_to else "UNASSIGNED"
    phone_digits = lead.phone.replace("(", "").replace(")", "").replace("-", "").replace(" ", "")
    lead_first = lead.name.split()[0] if lead.name else "Lead"

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;margin:0;padding:20px;background:#f1f5f9;">
    <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <div style="background:linear-gradient(135deg,#059669,#10b981);padding:20px 28px;">
            <h2 style="margin:0;color:#fff;font-size:18px;">🎯 New Lead → {agent_name}</h2>
        </div>
        <div style="padding:24px 28px;">
            <table style="width:100%;font-size:14px;color:#334155;" cellpadding="0" cellspacing="0">
                <tr><td style="padding:8px 0;color:#64748b;width:140px;">Name</td><td style="padding:8px 0;font-weight:700;">{lead.name}</td></tr>
                <tr><td style="padding:8px 0;color:#64748b;">Phone</td><td style="padding:8px 0;font-weight:700;">{lead.phone}</td></tr>
                <tr><td style="padding:8px 0;color:#64748b;">Assigned To</td><td style="padding:8px 0;font-weight:700;color:#2563eb;">{agent_name}</td></tr>
                <tr><td style="padding:8px 0;color:#64748b;">Products</td><td style="padding:8px 0;">{lead.policy_types or 'N/A'}</td></tr>
                <tr><td style="padding:8px 0;color:#64748b;">Source</td><td style="padding:8px 0;">{lead.source or 'website'}</td></tr>
            </table>
            <div style="margin-top:20px;">
                <a href="tel:{phone_digits}"
                   style="display:inline-block;background:#059669;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;">
                    📞 Call {lead_first}
                </a>
            </div>
        </div>
        <div style="background:#f8fafc;padding:12px 28px;border-top:1px solid #e2e8f0;">
            <p style="margin:0;color:#94a3b8;font-size:11px;">Better Choice Insurance Group · ORBIT Round-Robin Lead Distribution</p>
        </div>
    </div></body></html>"""

    try:
        httpx.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={
                "from": f"ORBIT Lead Alert <{AGENCY_FROM_EMAIL}>",
                "to": ["evan@betterchoiceins.com"],
                "subject": f"🎯 New Lead → {agent_name}: {lead.name} — {lead.phone}",
                "html": html,
                "o:tag": ["lead-admin-alert", "round-robin"],
            },
        )
    except Exception as e:
        logger.warning(f"Failed to send admin lead notification: {e}")


# ═══════════════════════════════════════════════════════════════════
# LEAD MANAGEMENT ENDPOINTS (AUTH REQUIRED)
# ═══════════════════════════════════════════════════════════════════

@router.get("")
async def list_leads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """List leads with filters. Producers only see their own leads."""
    q = db.query(Lead)

    # Producers only see their assigned leads
    if current_user.role == "producer":
        q = q.filter(Lead.assigned_to_id == current_user.id)
    elif assigned_to:
        q = q.filter(Lead.assigned_to_id == assigned_to)

    if status:
        q = q.filter(Lead.status == status)
    
    if source:
        q = q.filter(Lead.source == source)

    # Date filter
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = q.filter(Lead.created_at >= cutoff)

    # Exclude duplicates from main view by default
    q = q.filter(Lead.is_duplicate == False)

    if search:
        pattern = f"%{search}%"
        q = q.filter(or_(
            Lead.name.ilike(pattern),
            Lead.phone.ilike(pattern),
            Lead.email.ilike(pattern),
        ))

    total = q.count()
    leads = q.order_by(desc(Lead.created_at)).offset(skip).limit(limit).all()

    return {
        "total": total,
        "leads": [
            {
                "id": l.id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "name": l.name,
                "phone": l.phone,
                "email": l.email,
                "policy_types": l.policy_types,
                "current_carrier": l.current_carrier,
                "current_premium": l.current_premium,
                "source": l.source,
                "status": l.status,
                "assigned_to_id": l.assigned_to_id,
                "assigned_to_name": l.assigned_to_name,
                "message": l.message,
                "address": l.address,
                "city": l.city,
                "state": l.state,
                "zip_code": l.zip_code,
                "notes": l.notes,
            }
            for l in leads
        ],
    }


@router.get("/stats")
async def lead_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=365),
):
    """Lead dashboard stats."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    base = db.query(Lead).filter(Lead.created_at >= cutoff, Lead.is_duplicate == False)

    total = base.count()
    new_count = base.filter(Lead.status == "new").count()
    contacted = base.filter(Lead.status == "contacted").count()
    quoted = base.filter(Lead.status == "quoted").count()
    sold = base.filter(Lead.status == "sold").count()
    lost = base.filter(Lead.status == "lost").count()

    # Per-agent breakdown
    agent_stats = db.execute(text("""
        SELECT l.assigned_to_name, l.assigned_to_id,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE l.status = 'new') as new,
               COUNT(*) FILTER (WHERE l.status = 'contacted') as contacted,
               COUNT(*) FILTER (WHERE l.status = 'quoted') as quoted,
               COUNT(*) FILTER (WHERE l.status = 'sold') as sold,
               COUNT(*) FILTER (WHERE l.status = 'lost') as lost
        FROM leads l
        WHERE l.created_at >= :cutoff AND l.is_duplicate = FALSE
        GROUP BY l.assigned_to_name, l.assigned_to_id
        ORDER BY total DESC
    """), {"cutoff": cutoff}).fetchall()

    # Round-robin state
    rr_state = db.execute(text("SELECT last_assigned_user_id, total_assigned FROM round_robin_state LIMIT 1")).fetchone()

    return {
        "period_days": days,
        "total": total,
        "new": new_count,
        "contacted": contacted,
        "quoted": quoted,
        "sold": sold,
        "lost": lost,
        "by_agent": [
            {
                "name": row[0] or "Unassigned",
                "user_id": row[1],
                "total": row[2],
                "new": row[3],
                "contacted": row[4],
                "quoted": row[5],
                "sold": row[6],
                "lost": row[7],
            }
            for row in agent_stats
        ],
        "round_robin": {
            "last_assigned_user_id": rr_state[0] if rr_state else None,
            "total_assigned": rr_state[1] if rr_state else 0,
        },
    }


@router.get("/roster")
async def get_roster(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get round-robin roster — which producers are in the rotation."""
    producers = db.query(User).filter(
        User.role == "producer",
        User.is_active == True,
        User.username.notin_(EXCLUDED_USERNAMES),
    ).order_by(User.id).all()

    # Get lead counts per agent
    counts = db.execute(text("""
        SELECT assigned_to_id, COUNT(*) FROM leads
        WHERE is_duplicate = FALSE
        GROUP BY assigned_to_id
    """)).fetchall()
    count_map = {row[0]: row[1] for row in counts}

    # Get round-robin state
    rr_state = db.execute(text("SELECT last_assigned_user_id FROM round_robin_state LIMIT 1")).fetchone()
    last_id = rr_state[0] if rr_state else None

    return {
        "roster": [
            {
                "user_id": p.id,
                "name": p.full_name,
                "email": p.email,
                "username": p.username,
                "is_next": _is_next_in_rotation(p.id, [pr.id for pr in producers], last_id),
                "total_leads": count_map.get(p.id, 0),
            }
            for p in producers
        ],
    }


def _is_next_in_rotation(user_id: int, all_ids: list[int], last_assigned_id: Optional[int]) -> bool:
    """Check if this user is next in the round-robin."""
    if not all_ids:
        return False
    if last_assigned_id is None or last_assigned_id not in all_ids:
        return user_id == all_ids[0]
    idx = all_ids.index(last_assigned_id)
    next_idx = (idx + 1) % len(all_ids)
    return user_id == all_ids[next_idx]


@router.get("/{lead_id}")
async def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full lead detail."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Producers can only see their own leads
    if current_user.role == "producer" and lead.assigned_to_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your lead")

    return {
        "id": lead.id,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "dob": lead.dob,
        "address": lead.address,
        "city": lead.city,
        "state": lead.state,
        "zip_code": lead.zip_code,
        "policy_types": lead.policy_types,
        "current_carrier": lead.current_carrier,
        "current_premium": lead.current_premium,
        "renewal_date": lead.renewal_date,
        "message": lead.message,
        "roof_year": lead.roof_year,
        "home_year": lead.home_year,
        "sqft": lead.sqft,
        "drivers_info": lead.drivers_info,
        "vehicles_info": lead.vehicles_info,
        "source": lead.source,
        "utm_campaign": lead.utm_campaign,
        "assigned_to_id": lead.assigned_to_id,
        "assigned_to_name": lead.assigned_to_name,
        "status": lead.status,
        "notes": lead.notes,
        "is_duplicate": lead.is_duplicate,
        "duplicate_of_id": lead.duplicate_of_id,
    }


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update lead status, notes, or reassign."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Producers can only update their own leads
    if current_user.role == "producer" and lead.assigned_to_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your lead")

    data = await request.json()

    if "status" in data:
        old_status = lead.status
        lead.status = data["status"]
        now = datetime.utcnow()
        if data["status"] == "contacted" and not lead.contacted_at:
            lead.contacted_at = now
        elif data["status"] == "quoted" and not lead.quoted_at:
            lead.quoted_at = now
        elif data["status"] in ("sold", "lost") and not lead.closed_at:
            lead.closed_at = now

    if "notes" in data:
        lead.notes = data["notes"]

    # Admin/manager can reassign
    if "assigned_to_id" in data and current_user.role in ("admin", "manager"):
        new_user = db.query(User).filter(User.id == data["assigned_to_id"]).first()
        if new_user:
            lead.assigned_to_id = new_user.id
            lead.assigned_to_name = new_user.full_name
            lead.assigned_at = datetime.utcnow()

    lead.updated_at = datetime.utcnow()
    db.commit()

    return {"status": "ok", "lead_id": lead.id}
