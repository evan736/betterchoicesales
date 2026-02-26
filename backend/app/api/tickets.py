"""
Support Tickets API — internal issue reporting for agents.
  POST /api/tickets           — Create ticket (with screenshot + description)
  GET  /api/tickets           — List tickets (filterable)
  GET  /api/tickets/{id}      — Get ticket detail
  PATCH /api/tickets/{id}     — Update status/priority/resolution
  GET  /api/tickets/{id}/screenshot — Get screenshot image
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tickets", tags=["tickets"])


# ── Self-healing migration ───────────────────────────────────────────────────

def ensure_tickets_table():
    """Create tickets table if it doesn't exist."""
    from app.core.database import engine
    from app.models.ticket import Ticket
    Ticket.__table__.create(bind=engine, checkfirst=True)
    logger.info("support_tickets table ensured")


# ── Create Ticket ────────────────────────────────────────────────────────────

@router.post("")
async def create_ticket(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new support ticket with optional screenshot."""
    body = await request.json()

    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    page_url = (body.get("page_url") or "").strip()
    user_agent = (body.get("user_agent") or "").strip()
    screenshot_data = body.get("screenshot_data")  # base64 PNG
    priority = body.get("priority", "normal")

    if not description:
        raise HTTPException(status_code=400, detail="Description is required")

    # Auto-generate title from description if not provided
    if not title:
        title = description[:100] + ("..." if len(description) > 100 else "")

    ticket = Ticket(
        reporter_id=current_user.id,
        reporter_name=getattr(current_user, "name", "") or current_user.username,
        reporter_username=current_user.username,
        title=title,
        description=description,
        page_url=page_url,
        user_agent=user_agent[:500] if user_agent else "",
        screenshot_data=screenshot_data,
        status="open",
        priority=priority,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    logger.info(f"Ticket #{ticket.id} created by {current_user.username}: {title[:60]}")

    return {
        "id": ticket.id,
        "status": "created",
        "message": f"Ticket #{ticket.id} created successfully",
    }


# ── List Tickets ─────────────────────────────────────────────────────────────

@router.get("")
def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    reporter: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tickets with optional filters."""
    q = db.query(Ticket)

    if status:
        q = q.filter(Ticket.status == status)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if reporter:
        q = q.filter(Ticket.reporter_username == reporter)

    tickets = q.order_by(desc(Ticket.created_at)).limit(limit).all()

    return {
        "tickets": [_ticket_to_dict(t, include_screenshot=False) for t in tickets],
        "total": q.count(),
    }


# ── Get Ticket Detail ────────────────────────────────────────────────────────

@router.get("/{ticket_id}")
def get_ticket(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full ticket detail including screenshot."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return _ticket_to_dict(ticket, include_screenshot=True)


# ── Get Screenshot ───────────────────────────────────────────────────────────

@router.get("/{ticket_id}/screenshot")
def get_screenshot(
    ticket_id: int,
    db: Session = Depends(get_db),
):
    """Get ticket screenshot as base64 PNG."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket or not ticket.screenshot_data:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    from fastapi.responses import Response
    import base64

    # Strip data URL prefix if present
    data = ticket.screenshot_data
    if data.startswith("data:"):
        data = data.split(",", 1)[1]

    return Response(
        content=base64.b64decode(data),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=ticket-{ticket_id}.png"},
    )


# ── Update Ticket ────────────────────────────────────────────────────────────

@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update ticket status, priority, or add resolution notes."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    body = await request.json()

    if "status" in body:
        ticket.status = body["status"]
        if body["status"] == "resolved":
            ticket.resolved_at = datetime.utcnow()
            ticket.resolved_by = current_user.username
    if "priority" in body:
        ticket.priority = body["priority"]
    if "resolution_notes" in body:
        ticket.resolution_notes = body["resolution_notes"]

    db.commit()
    db.refresh(ticket)

    return _ticket_to_dict(ticket, include_screenshot=False)


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
def ticket_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Quick stats for ticket badge counts."""
    open_count = db.query(Ticket).filter(Ticket.status == "open").count()
    in_progress = db.query(Ticket).filter(Ticket.status == "in_progress").count()
    total = db.query(Ticket).count()
    return {"open": open_count, "in_progress": in_progress, "total": total}


# ── Helper ───────────────────────────────────────────────────────────────────

def _ticket_to_dict(t: Ticket, include_screenshot: bool = False) -> dict:
    d = {
        "id": t.id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "reporter_name": t.reporter_name,
        "reporter_username": t.reporter_username,
        "title": t.title,
        "description": t.description,
        "page_url": t.page_url,
        "status": t.status,
        "priority": t.priority,
        "resolution_notes": t.resolution_notes,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "resolved_by": t.resolved_by,
        "has_screenshot": bool(t.screenshot_data),
    }
    if include_screenshot and t.screenshot_data:
        d["screenshot_data"] = t.screenshot_data
    return d
