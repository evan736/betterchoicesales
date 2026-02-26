"""Lead Provider Control Center — pause/unpause lead sources from one place."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lead-providers", tags=["lead-providers"])


# ── Model ────────────────────────────────────────────────────────

class LeadProvider(Base):
    __tablename__ = "lead_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)                  # "EverQuote"
    slug = Column(String, nullable=False, unique=True)      # "everquote"
    portal_url = Column(String, nullable=True)              # Login URL
    pause_url = Column(String, nullable=True)               # Direct link to pause page
    logo_emoji = Column(String, nullable=True)              # Emoji or icon identifier
    is_paused = Column(Boolean, default=False)              # Current known state
    last_status_change = Column(DateTime, nullable=True)    # When status was last toggled
    last_status_by = Column(String, nullable=True)          # Who toggled it
    notes = Column(Text, nullable=True)                     # Login notes, tips
    sort_order = Column(Integer, default=0)                 # Display order
    is_active = Column(Boolean, default=True)               # Is this provider currently in use
    created_at = Column(DateTime, server_default=func.now())


# ── Default Providers ────────────────────────────────────────────

DEFAULT_PROVIDERS = [
    {
        "name": "EverQuote",
        "slug": "everquote",
        "portal_url": "https://pro.everquote.com",
        "pause_url": "https://pro.everquote.com",
        "logo_emoji": "🟢",
        "notes": "Login → Account Settings → Pause Account. Can schedule auto-resume.",
        "sort_order": 1,
    },
    {
        "name": "QuoteWizard",
        "slug": "quotewizard",
        "portal_url": "https://agents.quotewizard.com/agent-login/",
        "pause_url": "https://agents.quotewizard.com/agent-login/",
        "logo_emoji": "🔮",
        "notes": "Login → Dashboard → Account → Pause. 45 vacation days/yr (standard), unlimited (Elite).",
        "sort_order": 2,
    },
    {
        "name": "Datalot / TransUnion",
        "slug": "datalot",
        "portal_url": "https://www.datalot.com",
        "pause_url": "https://www.datalot.com",
        "logo_emoji": "📊",
        "notes": "Login to dashboard to pause campaigns.",
        "sort_order": 3,
    },
    {
        "name": "InsuranceAgents.ai",
        "slug": "insuranceagents-ai",
        "portal_url": "https://insuranceagents.ai",
        "pause_url": "https://insuranceagents.ai",
        "logo_emoji": "🤖",
        "notes": "Full control to pause account + set daily/monthly budgets. No minimums or contracts.",
        "sort_order": 4,
    },
    {
        "name": "All Web Leads",
        "slug": "allwebleads",
        "portal_url": "https://secure.allwebleads.com/Login",
        "pause_url": "https://secure.allwebleads.com/Login",
        "logo_emoji": "🌐",
        "notes": "Login → Campaign settings → Pause lead flow.",
        "sort_order": 5,
    },
    {
        "name": "AvengeHub",
        "slug": "avengehub",
        "portal_url": "https://avengehub.com/Login",
        "pause_url": "https://avengehub.com/Login",
        "logo_emoji": "⚡",
        "notes": "Login → Dashboard → Pause campaigns.",
        "sort_order": 6,
    },
]


# ── Helpers ──────────────────────────────────────────────────────

def _serialize(p: LeadProvider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "portal_url": p.portal_url,
        "pause_url": p.pause_url,
        "logo_emoji": p.logo_emoji,
        "is_paused": p.is_paused,
        "last_status_change": p.last_status_change.isoformat() if p.last_status_change else None,
        "last_status_by": p.last_status_by,
        "notes": p.notes,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
    }


def _is_admin_or_manager(user: User) -> bool:
    return user.role.lower() in ("admin", "manager", "owner")


def seed_defaults(db: Session):
    """Insert default providers if table is empty, and add any new ones."""
    count = db.query(LeadProvider).count()
    if count == 0:
        for p in DEFAULT_PROVIDERS:
            db.add(LeadProvider(**p))
        db.commit()
        logger.info(f"Seeded {len(DEFAULT_PROVIDERS)} default lead providers")
    else:
        # Add any new providers that don't exist yet
        existing_slugs = {p.slug for p in db.query(LeadProvider.slug).all()}
        added = 0
        for p in DEFAULT_PROVIDERS:
            if p["slug"] not in existing_slugs:
                db.add(LeadProvider(**p))
                added += 1
        if added:
            db.commit()
            logger.info(f"Added {added} new default lead providers")


# ── Endpoints ────────────────────────────────────────────────────

@router.get("")
def list_providers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all lead providers with current status."""
    seed_defaults(db)
    providers = db.query(LeadProvider).filter(
        LeadProvider.is_active == True
    ).order_by(LeadProvider.sort_order).all()
    
    active_count = sum(1 for p in providers if not p.is_paused)
    paused_count = sum(1 for p in providers if p.is_paused)
    
    return {
        "providers": [_serialize(p) for p in providers],
        "summary": {
            "total": len(providers),
            "active": active_count,
            "paused": paused_count,
        }
    }


@router.post("/{provider_id}/toggle")
def toggle_provider(
    provider_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle a single provider's pause state."""
    if not _is_admin_or_manager(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    provider = db.query(LeadProvider).filter(LeadProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    provider.is_paused = not provider.is_paused
    provider.last_status_change = datetime.utcnow()
    provider.last_status_by = current_user.full_name or current_user.username
    db.commit()
    
    status = "PAUSED" if provider.is_paused else "ACTIVE"
    logger.info(f"Lead provider {provider.name} → {status} by {provider.last_status_by}")
    
    # SSE notify
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("dashboard:refresh", {})
    except Exception:
        pass
    
    return _serialize(provider)


@router.post("/{provider_id}/set-status")
def set_provider_status(
    provider_id: int,
    paused: bool = Query(..., description="True to pause, False to unpause"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly set a provider's status (used by Pause All / Unpause All)."""
    if not _is_admin_or_manager(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    provider = db.query(LeadProvider).filter(LeadProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    provider.is_paused = paused
    provider.last_status_change = datetime.utcnow()
    provider.last_status_by = current_user.full_name or current_user.username
    db.commit()
    return _serialize(provider)


@router.post("/pause-all")
def pause_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pause ALL active providers."""
    if not _is_admin_or_manager(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    providers = db.query(LeadProvider).filter(LeadProvider.is_active == True).all()
    changed = 0
    for p in providers:
        if not p.is_paused:
            p.is_paused = True
            p.last_status_change = datetime.utcnow()
            p.last_status_by = current_user.full_name or current_user.username
            changed += 1
    db.commit()
    
    logger.info(f"PAUSE ALL: {changed} providers paused by {current_user.full_name or current_user.username}")
    
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("dashboard:refresh", {})
    except Exception:
        pass
    
    return {"status": "all_paused", "changed": changed, "total": len(providers)}


@router.post("/unpause-all")
def unpause_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unpause ALL active providers."""
    if not _is_admin_or_manager(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    providers = db.query(LeadProvider).filter(LeadProvider.is_active == True).all()
    changed = 0
    for p in providers:
        if p.is_paused:
            p.is_paused = False
            p.last_status_change = datetime.utcnow()
            p.last_status_by = current_user.full_name or current_user.username
            changed += 1
    db.commit()
    
    logger.info(f"UNPAUSE ALL: {changed} providers unpaused by {current_user.full_name or current_user.username}")
    
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("dashboard:refresh", {})
    except Exception:
        pass
    
    return {"status": "all_active", "changed": changed, "total": len(providers)}


@router.put("/{provider_id}")
def update_provider(
    provider_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update provider details (URLs, notes, etc)."""
    if not _is_admin_or_manager(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    provider = db.query(LeadProvider).filter(LeadProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    for field in ("name", "portal_url", "pause_url", "notes", "logo_emoji", "sort_order"):
        if field in data:
            setattr(provider, field, data[field])
    
    db.commit()
    return _serialize(provider)


# ── Automation Job System ────────────────────────────────────────
# The local Playwright worker polls for pending jobs and executes them

class AutomationJob(Base):
    __tablename__ = "lead_automation_jobs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)           # "pause_all" or "unpause_all"
    status = Column(String, default="pending")         # pending, running, completed, failed
    requested_by = Column(String, nullable=True)
    results = Column(Text, nullable=True)              # JSON results per provider
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


def ensure_automation_table():
    from app.core.database import engine
    AutomationJob.__table__.create(bind=engine, checkfirst=True)
    logger.info("lead_automation_jobs table ensured")


@router.get("/automation/pending")
def get_pending_jobs(db: Session = Depends(get_db)):
    """Poll for pending automation jobs (called by local worker)."""
    jobs = db.query(AutomationJob).filter(
        AutomationJob.status == "pending"
    ).order_by(AutomationJob.created_at).all()
    return {
        "jobs": [
            {"id": j.id, "action": j.action, "requested_by": j.requested_by,
             "created_at": j.created_at.isoformat() if j.created_at else None}
            for j in jobs
        ]
    }


@router.post("/automation/jobs/{job_id}/claim")
def claim_job(job_id: int, db: Session = Depends(get_db)):
    """Worker claims a job (marks it as running)."""
    job = db.query(AutomationJob).filter(AutomationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "pending":
        raise HTTPException(status_code=409, detail=f"Job already {job.status}")
    job.status = "running"
    job.started_at = datetime.utcnow()
    db.commit()
    return {"status": "claimed", "id": job_id, "action": job.action}


@router.post("/automation/jobs/{job_id}/complete")
async def complete_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    """Worker reports job completion with per-provider results."""
    import json as _json
    body = await request.json()
    job = db.query(AutomationJob).filter(AutomationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = body.get("status", "completed")
    job.results = _json.dumps(body.get("results", {}))
    job.completed_at = datetime.utcnow()

    # Update provider statuses based on results
    for slug, result in body.get("results", {}).items():
        provider = db.query(LeadProvider).filter(LeadProvider.slug == slug).first()
        if provider and result.get("success"):
            provider.is_paused = (job.action == "pause_all")
            provider.last_status_change = datetime.utcnow()
            provider.last_status_by = f"auto ({job.requested_by or 'worker'})"

    db.commit()
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("dashboard:refresh", {})
    except Exception:
        pass
    return {"status": "ok"}


@router.post("/automation/trigger")
def trigger_automation(
    action: str = Query(..., description="pause_all or unpause_all"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create an automation job (triggered by Chrome extension or ORBIT UI)."""
    if action not in ("pause_all", "unpause_all"):
        raise HTTPException(status_code=400, detail="Action must be pause_all or unpause_all")

    # Cancel existing pending jobs
    for p in db.query(AutomationJob).filter(AutomationJob.status == "pending").all():
        p.status = "cancelled"

    job = AutomationJob(action=action, requested_by=getattr(current_user, "username", "unknown"))
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(f"Automation job #{job.id}: {action} by {job.requested_by}")
    return {"id": job.id, "action": action, "status": "pending"}


@router.get("/automation/status")
def automation_status(db: Session = Depends(get_db)):
    """Latest automation job status (for Chrome extension polling)."""
    import json as _json
    job = db.query(AutomationJob).order_by(AutomationJob.created_at.desc()).first()
    if not job:
        return {"has_job": False}
    return {
        "has_job": True, "id": job.id, "action": job.action,
        "status": job.status, "requested_by": job.requested_by,
        "results": _json.loads(job.results) if job.results else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
