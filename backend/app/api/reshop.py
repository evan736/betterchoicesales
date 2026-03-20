"""Reshop Pipeline API — manage customer reshop/rewrite requests.

Role-based access:
- Admin: full access, can see all, assign anyone
- Retention (Salma, Michelle): full access to pipeline, present quotes
- Manager: full access
- Producer (Joseph, Giulian): can create/refer reshops, view own referrals
"""
import logging
import os
import requests as http_requests
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, func, desc, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.customer import Customer, CustomerPolicy
from app.models.reshop import Reshop, ReshopActivity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reshops", tags=["reshops"])

# ── Constants ─────────────────────────────────────────────────────

STAGES = ["proactive", "new_request", "quoting", "quote_ready", "presenting", "bound", "renewed", "lost"]
ACTIVE_STAGES = ["proactive", "new_request", "quoting", "quote_ready", "presenting"]
CLOSED_STAGES = ["bound", "renewed", "lost"]
SOURCES = ["inbound_call", "inbound_email", "producer_referral", "proactive_renewal", "walk_in", "nonpay_escalation", "other"]
REASONS = ["price_increase", "service_issue", "coverage_change", "shopping", "nonpay", "renewal_increase", "other"]
PRIORITIES = ["low", "normal", "high", "urgent"]

# Retention team members to notify on new reshop requests
RETENTION_NOTIFY_EMAILS = [
    "salma@betterchoiceins.com",
    "michelle@betterchoiceins.com",
    "evan@betterchoiceins.com",
]





# ── Round-Robin Auto-Assignment ──────────────────────────────────────
# Disabled by default. Set RESHOP_AUTO_ASSIGN=true env var to enable.
# Rotates reshop assignments between configured agents.
# IMPORTANT: Assigns per-customer, not per-policy. If a customer already
# has a reshop assigned to Salma, all future reshops for that customer
# also go to Salma (no split accounts).

RESHOP_AUTO_ASSIGN_AGENTS = ["salma.marquez", "michelle.robles"]  # Usernames for rotation

def _get_next_round_robin_agent(db: Session, customer_id: int = None, customer_name: str = "") -> Optional[int]:
    """Get the next agent ID in the round-robin rotation.
    
    Customer-aware: if this customer already has an active reshop assigned
    to someone, return that same agent (don't split accounts).
    
    Uses DB-based counting instead of in-memory counter so it survives restarts.
    Assigns to whichever agent currently has fewer active reshops (by customer count).
    """

    # Check if this customer already has a reshop assigned to someone
    if customer_id:
        existing = db.query(Reshop).filter(
            Reshop.customer_id == customer_id,
            Reshop.assigned_to.isnot(None),
            Reshop.stage.in_(ACTIVE_STAGES),
        ).first()
        if existing and existing.assigned_to:
            logger.info(f"Round-robin: customer {customer_name or customer_id} already assigned to agent {existing.assigned_to} — keeping same agent")
            return existing.assigned_to

    # Also check by customer name (in case customer_id differs across policies)
    if customer_name:
        existing_by_name = db.query(Reshop).filter(
            func.lower(Reshop.customer_name) == customer_name.lower(),
            Reshop.assigned_to.isnot(None),
            Reshop.stage.in_(ACTIVE_STAGES),
        ).first()
        if existing_by_name and existing_by_name.assigned_to:
            logger.info(f"Round-robin: customer '{customer_name}' already assigned to agent {existing_by_name.assigned_to} by name — keeping same agent")
            return existing_by_name.assigned_to

    # New customer — assign to agent with fewer active reshops (load-balanced)
    agents = db.query(User).filter(
        User.username.in_(RESHOP_AUTO_ASSIGN_AGENTS),
        User.is_active == True,
    ).all()

    if not agents:
        logger.warning("Round-robin: no active agents found for auto-assignment")
        return None

    # Count active reshops per agent
    agent_loads = []
    for agent in agents:
        count = db.query(Reshop).filter(
            Reshop.assigned_to == agent.id,
            Reshop.stage.in_(ACTIVE_STAGES),
        ).count()
        agent_loads.append((agent, count))

    # Sort by count ascending (fewest reshops first)
    agent_loads.sort(key=lambda x: x[1])
    chosen = agent_loads[0][0]

    logger.info("Round-robin reshop assignment: %s (%d active) for customer '%s'", chosen.full_name, agent_loads[0][1], customer_name)
    return chosen.id

def _detect_cross_sell(db: Session, customer_id: int, customer_name: str = "") -> list[dict]:
    """Check if a customer is missing common lines of business — cross-sell opportunities."""
    from app.models.sale import Sale

    # Check NowCerts policies
    policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.customer_id == customer_id,
        func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce", "renewing"]),
    ).all()

    # Also check Sales table (has better policy_type data: home, auto, bundled)
    sales = []
    if customer_name:
        sales = db.query(Sale).filter(
            func.lower(Sale.client_name) == customer_name.strip().lower()
        ).all()
    if not sales and customer_id:
        # Try matching by customer's policies → sales via policy number
        policy_nums = [p.policy_number for p in policies if p.policy_number]
        if policy_nums:
            sales = db.query(Sale).filter(Sale.policy_number.in_(policy_nums)).all()

    if not policies and not sales:
        return []

    # Categorize what they have from BOTH sources
    lobs = set()

    # From NowCerts policies — infer LOB from carrier name + policy number patterns
    # since line_of_business is often empty from NowCerts
    AUTO_CARRIERS = ["progressive", "geico", "bristol west", "gainsco", "clearcover"]
    HOME_CARRIERS = ["openly", "universal property", "american modern", "covertree", "hippo", "branch", "steadily", "obsidian"]
    BOTH_CARRIERS = ["safeco", "travelers", "grange", "national general", "natgen", "integon", "encompass", "first connect"]
    
    for p in policies:
        lob = (p.line_of_business or "").lower()
        carrier = (p.carrier or "").lower()
        pnum = (p.policy_number or "").upper()
        ptype = (p.policy_type or "").lower()
        status = (p.status or "").lower()
        
        # Skip non-active policies
        if status not in ("active", "in force", "inforce", "renewing"):
            continue
        
        # Direct LOB match if available
        if any(x in lob for x in ["personal auto", "auto", "vehicle"]):
            lobs.add("auto")
            continue
        if any(x in lob for x in ["homeowner", "home", "property", "dwelling"]):
            lobs.add("home")
            continue
        if "umbrella" in lob:
            lobs.add("umbrella")
            continue
        if any(x in lob for x in ["renter", "tenant"]):
            lobs.add("renters")
            continue
        
        # Infer from carrier name
        if any(c in carrier for c in AUTO_CARRIERS):
            lobs.add("auto")
        elif any(c in carrier for c in HOME_CARRIERS):
            lobs.add("home")
        elif any(c in carrier for c in BOTH_CARRIERS):
            # For carriers that do both, use policy number patterns
            # Safeco: OZ/Y = home, Z = auto; Grange: HM = home, PA = auto
            # Travelers: long numbers = auto; NatGen: varies
            if pnum.startswith("HM") or pnum.startswith("OZ") or pnum.startswith("BQ"):
                lobs.add("home")
            elif pnum.startswith("PA") or pnum.startswith("Z"):
                lobs.add("auto")
            elif len(pnum.replace("-","")) >= 10 and pnum[0].isdigit():
                # Long numeric = likely auto (Travelers, Progressive, Geico)
                lobs.add("auto")
            else:
                # Can't determine — check premium range as hint
                # Home policies tend to be $1000+ annually, auto can vary
                pass

    # From Sales table (more reliable for policy_type)
    for sale in sales:
        stype = (sale.policy_type or "").lower()
        if any(x in stype for x in ["auto", "car"]):
            lobs.add("auto")
        if any(x in stype for x in ["home", "dwelling"]):
            lobs.add("home")
        if "umbrella" in stype:
            lobs.add("umbrella")
        if any(x in stype for x in ["renter", "tenant"]):
            lobs.add("renters")
        if "condo" in stype:
            lobs.add("condo")
        if "bundled" in stype:
            lobs.add("auto")
            lobs.add("home")
        if "life" in stype:
            lobs.add("life")

    opportunities = []

    # Auto customer without home — high-value cross-sell
    if "auto" in lobs and "home" not in lobs and "renters" not in lobs and "condo" not in lobs:
        opportunities.append({
            "type": "home",
            "label": "Home Insurance",
            "reason": "Has auto but no home/renters policy on file",
        })

    # Home customer without auto — high-value cross-sell
    if ("home" in lobs or "condo" in lobs) and "auto" not in lobs:
        opportunities.append({
            "type": "auto",
            "label": "Auto Insurance",
            "reason": "Has home but no auto policy on file",
        })

    return opportunities

def _notify_reshop_assignment(reshop, assignee, assigned_by, db=None):
    """Send email notification when a reshop is assigned, with cross-sell opportunities."""
    import requests as _requests
    import logging
    _logger = logging.getLogger(__name__)

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    try:
        # Detect cross-sell opportunities
        cross_sell = []
        if db and reshop.customer_id:
            cross_sell = _detect_cross_sell(db, reshop.customer_id, reshop.customer_name or "")
        customer = reshop.customer_name or "Unknown Customer"
        carrier = reshop.carrier or "Unknown Carrier"
        policy = reshop.policy_number or ""
        current = f"${float(reshop.current_premium or 0):,.0f}"
        renewal = f"${float(reshop.renewal_premium or 0):,.0f}"
        increase = ""
        if reshop.current_premium and reshop.renewal_premium:
            pct = ((float(reshop.renewal_premium) - float(reshop.current_premium)) / float(reshop.current_premium)) * 100
            increase = f" (+{pct:.0f}%)"
        days = ""
        if reshop.renewal_date:
            from datetime import datetime
            d = (reshop.renewal_date - datetime.utcnow()).days
            if d > 0:
                days = f" — renews in {d} days"

        priority_colors = {"urgent": "#dc2626", "high": "#f59e0b", "normal": "#3b82f6", "low": "#6b7280"}
        p_color = priority_colors.get(reshop.priority or "normal", "#3b82f6")
        p_label = (reshop.priority or "normal").upper()

        assignee_first = assignee.full_name.split()[0] if assignee.full_name else "Team Member"
        assigner_name = assigned_by.full_name if assigned_by else "Admin"

        subject = f"Reshop Assigned: {customer} — {carrier} {current} → {renewal}{increase}"

        # Build cross-sell HTML outside the f-string (Python 3.11 can't nest f-strings)
        cross_sell_html = ""
        if cross_sell:
            for opp in cross_sell:
                cross_sell_html += (
                    '<div style="background:#fefce8; border:1px solid #fde68a; border-radius:8px; padding:16px; margin:16px 0;">'
                    '<p style="margin:0 0 8px; color:#92400e; font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:1px;">&#128161; Cross-Sell Opportunity</p>'
                    f'<p style="margin:0 0 4px; color:#78350f; font-size:15px; font-weight:600;">{opp["label"]}</p>'
                    f'<p style="margin:0; color:#92400e; font-size:13px;">{opp["reason"]}</p>'
                    '</div>'
                )

        # Build days HTML outside f-string (Python 3.11 compat)
        days_html = ""
        if days:
            days_clean = days.strip(" —")
            days_html = f'<p style="margin:12px 0 0; color:#f59e0b; font-size:13px; font-weight:600;">{days_clean}</p>'

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:560px; margin:0 auto; padding:24px 16px;">
    <div style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding:24px; border-radius:12px 12px 0 0; text-align:center;">
        <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="Better Choice Insurance" style="height:40px;" />
        <p style="margin:8px 0 0; color:#22d3ee; font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:1.5px;">Reshop Assignment</p>
    </div>
    <div style="background:white; padding:28px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">
        <p style="margin:0 0 16px; color:#334155; font-size:15px;">
            Hi {assignee_first}, <strong>{assigner_name}</strong> has assigned you a reshop:
        </p>

        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:20px; margin:16px 0;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <h3 style="margin:0; color:#0f172a; font-size:17px;">{customer}</h3>
                <span style="background:{p_color}; color:white; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:700;">{p_label}</span>
            </div>
            <table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">
                <tr><td style="padding:5px 0; color:#64748b;">Carrier</td><td style="padding:5px 0; text-align:right; font-weight:600;">{carrier}</td></tr>
                <tr><td style="padding:5px 0; color:#64748b;">Policy</td><td style="padding:5px 0; text-align:right; font-weight:600;">{policy}</td></tr>
                <tr><td style="padding:5px 0; color:#64748b;">Current Premium</td><td style="padding:5px 0; text-align:right;">{current}</td></tr>
                <tr><td style="padding:5px 0; color:#64748b;">Renewal Premium</td><td style="padding:5px 0; text-align:right; font-weight:700; color:#dc2626;">{renewal}{increase}</td></tr>
            </table>
            {days_html}
        </div>

        {cross_sell_html}

        <div style="text-align:center; margin:24px 0;">
            <a href="https://better-choice-web.onrender.com/reshop" style="display:inline-block; background:linear-gradient(135deg, #0ea5e9, #0284c7); color:white; padding:14px 36px; border-radius:10px; text-decoration:none; font-weight:700; font-size:15px;">
                Open Reshop Pipeline →
            </a>
        </div>
    </div>
    <div style="background:#f8fafc; padding:16px; text-align:center; border-radius:0 0 12px 12px; border-top:1px solid #e2e8f0;">
        <p style="margin:0; color:#94a3b8; font-size:11px;">Better Choice Insurance Group · (847) 908-5665</p>
    </div>
</div></body></html>"""

        # Use the same from address as hooray emails (those work)
        from_email = settings.MAILGUN_FROM_EMAIL or os.environ.get("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")
        # CC Andrey on all reshop assignment notifications
        cc_email = os.environ.get("RESHOP_CC_EMAIL", "andrey@betterchoiceins.com")
        resp = _requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance <{from_email}>",
                "to": [assignee.email],
                "cc": [cc_email],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        _logger.info(f"Reshop notification: {resp.status_code} {resp.text[:200]} → {assignee.email} (cc: {cc_email})")
    except Exception as e:
        _logger.warning(f"Reshop assignment notification failed: {e}")

def _notify_retention_team(reshop: "Reshop", created_by: str):
    """Send email notification to retention team about a new reshop request."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping reshop notification")
        return

    source_label = {
        "inbound_call": "Inbound Call",
        "inbound_email": "Inbound Email",
        "producer_referral": "Producer Referral",
        "proactive_renewal": "Proactive (Renewal)",
        "nonpay_escalation": "Non-Pay Escalation",
        "walk_in": "Walk-in",
    }.get(reshop.source or "", reshop.source or "Manual Entry")

    priority_color = {
        "urgent": "#dc2626", "high": "#ea580c",
        "normal": "#2563eb", "low": "#64748b",
    }.get(reshop.priority or "normal", "#2563eb")

    premium_str = f"${float(reshop.current_premium):,.0f}" if reshop.current_premium else "N/A"
    exp_str = reshop.expiration_date.strftime("%m/%d/%Y") if reshop.expiration_date else "N/A"

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: 0 auto;">
      <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0f2440 100%); padding: 20px 24px; border-radius: 12px 12px 0 0;">
        <h2 style="color: #ffffff; margin: 0; font-size: 18px;">🔄 New Reshop Request</h2>
        <p style="color: #94a3b8; margin: 6px 0 0; font-size: 13px;">Created by {created_by} via {source_label}</p>
      </div>
      <div style="background: #ffffff; padding: 24px; border: 1px solid #e2e8f0; border-top: none;">
        <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
          <tr>
            <td style="padding: 8px 0; color: #64748b; width: 120px;">Customer</td>
            <td style="padding: 8px 0; font-weight: 600; color: #1e293b;">{reshop.customer_name}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748b;">Phone</td>
            <td style="padding: 8px 0; color: #1e293b;">{reshop.customer_phone or '—'}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748b;">Email</td>
            <td style="padding: 8px 0; color: #1e293b;">{reshop.customer_email or '—'}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748b;">Policy</td>
            <td style="padding: 8px 0; color: #1e293b;">{reshop.policy_number or '—'} ({reshop.carrier or 'Unknown carrier'})</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748b;">Premium</td>
            <td style="padding: 8px 0; color: #1e293b;">{premium_str}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748b;">Expires</td>
            <td style="padding: 8px 0; color: #1e293b;">{exp_str}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748b;">Priority</td>
            <td style="padding: 8px 0;">
              <span style="background: {priority_color}; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">{(reshop.priority or 'normal').upper()}</span>
            </td>
          </tr>
          {"<tr><td style='padding: 8px 0; color: #64748b;'>Referred by</td><td style='padding: 8px 0; color: #1e293b;'>" + (reshop.referred_by or '') + "</td></tr>" if reshop.referred_by else ""}
          {"<tr><td style='padding: 8px 0; color: #64748b;'>Notes</td><td style='padding: 8px 0; color: #1e293b;'>" + (reshop.notes or '') + "</td></tr>" if reshop.notes else ""}
        </table>
        <div style="margin-top: 20px; text-align: center;">
          <a href="https://better-choice-web.onrender.com/reshop" 
             style="display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; padding: 10px 24px; border-radius: 8px; font-weight: 600; font-size: 14px;">
            Open Reshop Pipeline
          </a>
        </div>
      </div>
      <div style="padding: 12px 24px; background: #f8fafc; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px; text-align: center;">
        <p style="color: #94a3b8; font-size: 11px; margin: 0;">Better Choice Insurance — ORBIT Reshop Pipeline</p>
      </div>
    </div>
    """

    subject = f"🔄 New Reshop: {reshop.customer_name}"
    if reshop.priority in ("urgent", "high"):
        subject = f"🚨 {reshop.priority.upper()} Reshop: {reshop.customer_name}"
    if reshop.referred_by:
        subject += f" (via {reshop.referred_by})"

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"ORBIT Reshop <service@{settings.MAILGUN_DOMAIN}>",
                "to": RETENTION_NOTIFY_EMAILS,
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        logger.info("Reshop notification sent to %s: %s", RETENTION_NOTIFY_EMAILS, resp.status_code)
    except Exception as e:
        logger.error("Failed to send reshop notification: %s", e)


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
    """Check if user can access the reshop pipeline view."""
    # Producers cannot see the pipeline — they submit reshop requests which
    # go directly to retention specialists via round-robin
    return user.role.lower() in ("admin", "retention_specialist", "manager")


def _can_manage(user: User) -> bool:
    """Check if user can manage reshops (full CRUD, assign, stage changes)."""
    return user.role.lower() in ("admin", "retention_specialist", "manager")


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
        "cross_sell_opportunities": [],  # Populated on detail view
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
    """List reshops with filters. Agents see only their assigned reshops. Admin/Manager/Andrey see all."""
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Reshop)

    # Determine visibility scope
    is_admin_or_manager = current_user.role.lower() in ("admin", "manager")
    # Andrey has elevated visibility (can see all reshops)
    is_elevated = current_user.username == "andrey.dayson"
    
    if not is_admin_or_manager and not is_elevated:
        # Retention specialists (Salma, Michelle) only see their assigned reshops
        query = query.filter(Reshop.assigned_to == current_user.id)

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

    # Scope query same as list endpoint
    is_admin_or_manager = current_user.role.lower() in ("admin", "manager")
    is_elevated = current_user.username == "andrey.dayson"
    
    base_query = db.query(Reshop)
    if not is_admin_or_manager and not is_elevated:
        base_query = base_query.filter(Reshop.assigned_to == current_user.id)

    active = base_query.filter(Reshop.stage.in_(ACTIVE_STAGES)).all()

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


@router.get("/badge-count")
def reshop_badge_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lightweight count of active reshops for nav badge."""
    if not _can_access(current_user):
        return {"count": 0}
    
    # Scope same as list endpoint
    is_admin_or_manager = current_user.role.lower() in ("admin", "manager")
    is_elevated = current_user.username == "andrey.dayson"
    
    base = db.query(func.count(Reshop.id)).filter(Reshop.stage.in_(ACTIVE_STAGES))
    if not is_admin_or_manager and not is_elevated:
        base = base.filter(Reshop.assigned_to == current_user.id)
    
    count = base.scalar() or 0
    
    # New = created in last 24h (same scope)
    new_base = db.query(func.count(Reshop.id)).filter(
        Reshop.stage.in_(ACTIVE_STAGES),
        Reshop.created_at >= datetime.utcnow() - timedelta(hours=24),
    )
    if not is_admin_or_manager and not is_elevated:
        new_base = new_base.filter(Reshop.assigned_to == current_user.id)
    
    new_count = new_base.scalar() or 0
    
    return {"count": count, "new": new_count}


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
    """Create a new reshop request. Producers can submit — goes URGENT to retention team via round-robin."""
    # Producers can CREATE reshops (submit referrals) but not view the pipeline
    is_producer = current_user.role.lower() == "producer"
    if not _can_access(current_user) and not is_producer:
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

    # If submitted by a producer, override to URGENT + new_request
    if is_producer:
        priority = "urgent"
        stage = "new_request"
        source = data.source or "producer_referral"
        source_detail = f"Referred by {current_user.full_name or current_user.username}. {data.source_detail or data.reason or ''}"
    else:
        priority = data.priority or "normal"
        stage = data.stage or "new_request"
        source = data.source
        source_detail = data.source_detail

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
        stage=stage,
        priority=priority,
        source=source,
        source_detail=source_detail,
        reason=data.reason,
        reason_detail=data.reason_detail,
        notes=data.notes,
        is_proactive=False,
        referred_by=current_user.full_name or current_user.username if is_producer else None,
    )

    # Auto-assign via round-robin (customer-aware)
    auto_agent_id = _get_next_round_robin_agent(db, customer_id=data.customer_id, customer_name=data.customer_name or "")
    if auto_agent_id:
        reshop.assigned_to = auto_agent_id

    db.add(reshop)
    db.flush()

    _log_activity(db, reshop.id, current_user, "created",
                  f"Reshop created via {source or 'manual entry'}" + (f" — referred by {current_user.full_name}" if is_producer else ""))

    db.commit()
    db.refresh(reshop)

    # Notify assigned agent — DISABLED: replaced by daily digest email at 8:30 AM CT
    # Individual assignment emails no longer sent; agents get a full pipeline summary instead
    if reshop.assigned_to:
        assignee = db.query(User).filter(User.id == reshop.assigned_to).first()
        # Notification moved to daily digest (reshop_digest.py)
    else:
        # Fallback: notify retention team
        try:
            _notify_retention_team(reshop, current_user.full_name or current_user.username)
        except Exception as e:
            logger.error("Reshop notification error: %s", e)

    return _reshop_to_dict(reshop)

# ── Proactive Detection ──────────────────────────────────────────

@router.delete("/purge-proactive")
def purge_proactive_reshops(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete all proactive reshop entries (for re-scanning with new criteria)."""
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Delete activities for proactive reshops first
    proactive_ids = [r.id for r in db.query(Reshop.id).filter(Reshop.is_proactive == True).all()]
    if proactive_ids:
        db.query(ReshopActivity).filter(ReshopActivity.reshop_id.in_(proactive_ids)).delete(synchronize_session=False)
    
    count = db.query(Reshop).filter(Reshop.is_proactive == True).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok", "deleted": count}




@router.post("/test-notification/{reshop_id}")
def test_reshop_notification(
    reshop_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test reshop notification email (admin only). Returns error details if it fails."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")
    
    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")
    
    assignee = db.query(User).filter(User.id == reshop.assigned_to).first() if reshop.assigned_to else None
    if not assignee:
        raise HTTPException(status_code=400, detail="Reshop not assigned to anyone")
    
    try:
        _notify_reshop_assignment(reshop, assignee, current_user, db)
        return {"status": "sent", "to": assignee.email, "customer": reshop.customer_name, "from_email": settings.MAILGUN_FROM_EMAIL, "domain": settings.MAILGUN_DOMAIN}
    except Exception as e:
        import traceback
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@router.post("/send-digest")
def send_reshop_digest_now(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger the daily reshop digest email (admin only)."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    from app.services.reshop_digest import send_reshop_digests
    from datetime import date
    result = send_reshop_digests(db, date.today())
    return result



@router.get("/commercial-accounts")
def list_commercial_accounts(
    days_out: int = Query(60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List commercial accounts that would be skipped by the proactive scan."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_out)

    # Get all upcoming policies
    all_upcoming = (
        db.query(CustomerPolicy)
        .filter(
            func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce", "renewing"]),
            CustomerPolicy.effective_date >= now - timedelta(days=7),
            CustomerPolicy.effective_date <= cutoff,
        )
        .all()
    )

    COMMERCIAL_KEYWORDS = [
        "commercial", "general liability", "business owner",
        "workers comp", "professional liability", "e&o", "d&o",
        "commercial auto", "commercial property", "commercial package",
        "inland marine", "artisan", "contractor",
        "business auto", "business property", "business liability",
    ]

    commercial = []
    for p in all_upcoming:
        lob = (p.line_of_business or "").lower()
        if any(kw in lob for kw in COMMERCIAL_KEYWORDS):
            customer = db.query(Customer).filter(Customer.id == p.customer_id).first()
            commercial.append({
                "customer_name": customer.full_name if customer else "Unknown",
                "customer_id": p.customer_id,
                "policy_number": p.policy_number,
                "carrier": p.carrier,
                "line_of_business": p.line_of_business,
                "policy_type": p.policy_type,
                "premium": float(p.premium or 0),
                "effective_date": str(p.effective_date)[:10] if p.effective_date else None,
                "expiration_date": str(p.expiration_date)[:10] if p.expiration_date else None,
            })

    commercial.sort(key=lambda x: x["premium"], reverse=True)
    return {"count": len(commercial), "accounts": commercial}

@router.post("/detect-proactive")
def detect_proactive_reshops(
    days_out: int = Query(60, description="Look for renewals with effective dates within N days"),
    increase_threshold: float = Query(10.0, description="Minimum premium increase % to flag"),
    min_annual_premium: float = Query(2000.0, description="Minimum annualized premium to consider"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan for upcoming renewal terms and flag policies with premium increases."""
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return _run_proactive_scan(db, days_out, increase_threshold, min_annual_premium, current_user.full_name or current_user.username)


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

    result = _reshop_to_dict(reshop)
    
    # Detect cross-sell opportunities for this customer
    if reshop.customer_id:
        result["cross_sell_opportunities"] = _detect_cross_sell(db, reshop.customer_id, reshop.customer_name or "")

    return {
        "reshop": result,
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

        # Notification moved to daily digest (reshop_digest.py)
        # _notify_reshop_assignment(reshop, assignee, current_user, db)

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
    if current_user.role.lower() == "producer" and stage != "new_request":
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



def _run_proactive_scan(
    db: Session,
    days_out: int = 60,
    increase_threshold: float = 10.0,
    min_annual_premium: float = 2000.0,
    actor_name: str = "system",
):
    """Core reshop detection logic — callable from scheduler or endpoint.
    
    Scans for upcoming renewal terms and flags policies with premium increases.
    NowCerts syncs future renewal terms (status='Renewing') 30-60 days before
    effective date. Compares each Renewing term's premium to the current Active term.
    """
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_out)

    # Pass 1: Find policies with status "Renewing" (standard NowCerts sync)
    renewing = (
        db.query(CustomerPolicy)
        .filter(
            func.lower(CustomerPolicy.status).in_(["renewing"]),
            CustomerPolicy.effective_date >= now - timedelta(days=7),
            CustomerPolicy.effective_date <= cutoff,
        )
        .all()
    )

    # Pass 2: Find renewal terms stored as "Active" (NowCerts sometimes syncs
    # renewing terms with Active status). Look for duplicate policy numbers
    # where one effective date is in the future (upcoming term) and one is current.
    from sqlalchemy import and_ as sa_and
    from collections import defaultdict

    # Get policies with effective dates in the near future (potential renewal terms)
    upcoming_active = (
        db.query(CustomerPolicy)
        .filter(
            func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]),
            CustomerPolicy.effective_date >= now - timedelta(days=7),
            CustomerPolicy.effective_date <= cutoff,
        )
        .all()
    )

    # For each upcoming policy, check if there's a PRIOR term with a different premium
    already_renewing_pnums = set(p.policy_number for p in renewing if p.policy_number)
    for upcoming in upcoming_active:
        pnum = upcoming.policy_number
        if not pnum or pnum in already_renewing_pnums:
            continue

        # Find prior terms for this policy number (older effective date)
        prior_terms = (
            db.query(CustomerPolicy)
            .filter(
                CustomerPolicy.policy_number == pnum,
                CustomerPolicy.id != upcoming.id,
                CustomerPolicy.effective_date < upcoming.effective_date,
            )
            .order_by(CustomerPolicy.effective_date.desc())
            .limit(1)
            .all()
        )

        if prior_terms:
            prior = prior_terms[0]
            if (upcoming.premium or 0) != (prior.premium or 0) and (prior.premium or 0) > 0:
                renewing.append(upcoming)
                already_renewing_pnums.add(pnum)

    renewing_policy_nums = [p.policy_number for p in renewing if p.policy_number]
    # Build a set of renewing term IDs to exclude from active lookup
    renewing_ids = set(p.id for p in renewing)
    active_terms = {}
    if renewing_policy_nums:
        active_results = (
            db.query(CustomerPolicy)
            .filter(
                CustomerPolicy.policy_number.in_(renewing_policy_nums),
                func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce", "renewing"]),
                ~CustomerPolicy.id.in_(renewing_ids) if renewing_ids else True,
            )
            .order_by(CustomerPolicy.effective_date.desc())
            .all()
        )
        for t in active_results:
            if t.policy_number and t.policy_number not in active_terms:
                # Pick the most recent term that ISN'T the renewal
                active_terms[t.policy_number] = t

    existing_policy_nums = set()
    active_reshops = db.query(Reshop).filter(Reshop.stage.in_(ACTIVE_STAGES)).all()
    for r in active_reshops:
        if r.policy_number:
            existing_policy_nums.add(r.policy_number.lower())

    created = 0
    skipped_existing = 0
    skipped_below_threshold = 0
    skipped_no_increase = 0
    skipped_no_active = 0
    skipped_commercial = 0
    skipped_current_month = 0
    candidates = []

    for renewal in renewing:
        pnum = (renewal.policy_number or "").lower()
        if pnum and pnum in existing_policy_nums:
            skipped_existing += 1
            continue

        active = active_terms.get(renewal.policy_number)
        if not active:
            skipped_no_active += 1
            continue

        # Skip commercial accounts — personal lines only
        COMMERCIAL_KEYWORDS = [
            "commercial", "general liability", "business owner",
            "workers comp", "professional liability", "e&o", "d&o",
            "commercial auto", "commercial property", "commercial package",
            "inland marine", "artisan", "contractor",
            "business auto", "business property", "business liability",
        ]
        lob_check = (active.line_of_business or "").lower()
        ptype_check = (active.policy_type or "").lower()
        # Only check LOB — policy_type has "New Business" which is a transaction type, not commercial
        if any(kw in lob_check for kw in COMMERCIAL_KEYWORDS):
            skipped_commercial += 1
            continue

        current_prem = float(active.premium or 0)
        renewal_prem = float(renewal.premium or 0)
        if current_prem <= 0 or renewal_prem <= 0:
            continue

        def calc_term_months(p):
            if p.effective_date and p.expiration_date:
                delta = (p.expiration_date - p.effective_date).days
                if delta < 200:
                    return 6
            return 12

        current_term = calc_term_months(active)
        renewal_term = calc_term_months(renewal)
        ann_current = current_prem * (12 / current_term)
        ann_renewal = renewal_prem * (12 / renewal_term)

        if ann_renewal < min_annual_premium:
            skipped_below_threshold += 1
            continue

        change_pct = ((ann_renewal - ann_current) / ann_current) * 100
        if change_pct < increase_threshold:
            skipped_no_increase += 1
            continue

        candidates.append({
            "renewal": renewal,
            "active": active,
            "ann_current": ann_current,
            "ann_renewal": ann_renewal,
            "change_pct": change_pct,
            "current_term": current_term,
            "renewal_term": renewal_term,
        })

    candidates.sort(key=lambda c: c["ann_renewal"], reverse=True)

    for c in candidates:
        renewal = c["renewal"]
        active_pol = c["active"]
        customer = db.query(Customer).filter(Customer.id == renewal.customer_id).first()
        if not customer:
            continue

        # Skip if expiration is in current month or past — only create reshops for future months
        exp_date = active_pol.expiration_date
        if exp_date:
            first_of_next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
            if exp_date < first_of_next_month:
                skipped_current_month += 1
                continue

        ann = c["ann_renewal"]
        if ann >= 10000:
            priority = "urgent"
        elif ann >= 5000:
            priority = "high"
        elif ann >= 3000:
            priority = "normal"
        else:
            priority = "low"

        days_to_renewal = (renewal.effective_date - now).days if renewal.effective_date else 0
        term_note = " [6mo annualized]" if c["current_term"] < 12 or c["renewal_term"] < 12 else ""
        source_detail = (
            f"+{c['change_pct']:.1f}% increase: "
            f"${float(active_pol.premium or 0):,.0f} → ${float(renewal.premium or 0):,.0f}{term_note}, "
            f"renews in {days_to_renewal} days"
        )

        # Auto-assign via round-robin (if enabled)
        auto_agent_id = _get_next_round_robin_agent(db, customer_id=customer.id, customer_name=customer.full_name or "")

        reshop = Reshop(
            customer_id=customer.id,
            customer_name=customer.full_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip(),
            customer_phone=customer.phone,
            customer_email=customer.email,
            policy_number=renewal.policy_number,
            carrier=active_pol.carrier or renewal.carrier,
            line_of_business=active_pol.line_of_business or renewal.line_of_business,
            current_premium=active_pol.premium,
            assigned_to=auto_agent_id,
            renewal_premium=renewal.premium,
            premium_change_pct=round(c["change_pct"], 1),
            expiration_date=active_pol.expiration_date,
            stage="proactive",
            priority=priority,
            source="proactive_renewal",
            source_detail=source_detail,
            reason="renewal_increase",
            is_proactive=True,
        )
        db.add(reshop)
        db.flush()
        # Log activity with system actor
        activity = ReshopActivity(
            reshop_id=reshop.id,
            user_name=actor_name,
            action="created",
            detail=source_detail,
        )
        db.add(activity)
        created += 1
        existing_policy_nums.add(pnum)

    db.commit()

    # Broadcast live update if new reshops were created
    if created > 0:
        try:
            from app.api.events import event_bus
            event_bus.publish_sync("reshop:new", {"created": created})
            event_bus.publish_sync("dashboard:refresh", {})
        except Exception:
            pass

    return {
        "renewing_terms_found": len(renewing),
        "skipped_existing_reshop": skipped_existing,
        "skipped_no_active_term": skipped_no_active,
        "skipped_commercial": skipped_commercial,
        "skipped_current_month": skipped_current_month,
        "skipped_below_premium_threshold": skipped_below_threshold,
        "skipped_below_increase_threshold": skipped_no_increase,
        "criteria": {
            "days_out": days_out,
            "min_annual_premium": min_annual_premium,
            "increase_threshold_pct": increase_threshold,
        },
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

    # Manual reshop from customer center = URGENT, 24h deadline
    deadline = datetime.utcnow() + timedelta(hours=24)
    auto_agent_id = _get_next_round_robin_agent(db, customer_id=customer.id, customer_name=customer.full_name or "")

    reshop = Reshop(
        customer_id=customer.id,
        customer_name=customer.full_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip(),
        customer_phone=customer.phone,
        customer_email=customer.email,
        policy_number=policy.policy_number if policy else None,
        carrier=policy.carrier if policy else None,
        line_of_business=policy.line_of_business if policy else None,
        current_premium=policy.premium if policy else None,
        expiration_date=policy.expiration_date if policy and policy.expiration_date else deadline,
        stage="new_request",
        priority="urgent",
        source=source,
        reason=reason,
        notes=notes,
        assigned_to=auto_agent_id,
        referred_by=current_user.full_name if current_user.role.lower() == "producer" else None,
    )
    db.add(reshop)
    db.flush()

    _log_activity(db, reshop.id, current_user, "created",
                  f"Created from customer card by {current_user.full_name or current_user.username}")
    db.commit()
    db.refresh(reshop)

    # Notify retention team
    try:
        _notify_retention_team(reshop, current_user.full_name or current_user.username)
    except Exception as e:
        logger.error("Reshop notification error: %s", e)

    return _reshop_to_dict(reshop)
