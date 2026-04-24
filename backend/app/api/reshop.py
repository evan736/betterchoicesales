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
from sqlalchemy import or_, and_, func, desc, case
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
#
# ROTATION STRATEGY: Target-share weighted round-robin.
# Each agent has a configured target share of NEW assignments (must sum to 1.0).
# We count how many reshops were auto-assigned to each agent *since the rotation
# started* (assignments_counter below), and assign the next one to whichever
# agent is most under their target share. This gives each agent a predictable
# fraction of new leads regardless of their current open-lead count, so a new
# agent like April ramps up smoothly without getting flooded to force balance.
#
# Changing the target shares only affects NEW assignments. Existing balance
# resolves naturally as old leads close.

RESHOP_AUTO_ASSIGN_AGENTS = ["salma.marquez", "michelle.robles", "april.wilson"]  # Usernames for rotation

# Target share of NEW assignments per agent (must sum to ~1.0). Equal 1/3 split.
RESHOP_AGENT_TARGET_SHARES = {
    "salma.marquez": 1.0 / 3.0,
    "michelle.robles": 1.0 / 3.0,
    "april.wilson": 1.0 / 3.0,
}


def _get_next_round_robin_agent(db: Session, customer_id: int = None, customer_name: str = "") -> Optional[int]:
    """Get the next agent ID in the target-share weighted rotation.

    Customer-aware: if this customer already has an active reshop assigned
    to someone, return that same agent (don't split accounts).

    Uses a DB-persisted counter of *auto-assignments per agent* since start
    of rotation (stored in a simple AppSetting-style key-value table or the
    reshop activity log) to determine who's most under their target share.
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

    # New customer — weighted round-robin based on target share of NEW assignments.
    agents = db.query(User).filter(
        User.username.in_(RESHOP_AUTO_ASSIGN_AGENTS),
        User.is_active == True,
    ).all()

    if not agents:
        logger.warning("Round-robin: no active agents found for auto-assignment")
        return None

    # Count how many reshops each agent has received via AUTO-ASSIGN since
    # the rotation started. We detect auto-assigns via ReshopActivity rows
    # with action='auto_assigned' — anything older predates the activity log
    # and counts as "historical" (not in the denominator).
    auto_assign_counts = {}
    for agent in agents:
        n = db.query(ReshopActivity).join(
            Reshop, ReshopActivity.reshop_id == Reshop.id
        ).filter(
            Reshop.assigned_to == agent.id,
            ReshopActivity.action == "auto_assigned",
        ).count()
        auto_assign_counts[agent.id] = n

    total_auto_assigns = sum(auto_assign_counts.values())

    # Compute each agent's share deficit: target_share - actual_share.
    # If nobody has been auto-assigned yet (total=0), every agent has equal
    # deficit, so picking the one with the lowest ID gives stable first-run
    # behavior. Otherwise, highest deficit wins (= most under target).
    best_agent = None
    best_deficit = -999.0
    for agent in agents:
        target = RESHOP_AGENT_TARGET_SHARES.get((agent.username or "").lower(), 0.0)
        actual = (auto_assign_counts[agent.id] / total_auto_assigns) if total_auto_assigns > 0 else 0.0
        deficit = target - actual
        if deficit > best_deficit:
            best_deficit = deficit
            best_agent = agent

    if not best_agent:
        return None

    logger.info(
        "Round-robin (weighted): %s chosen. Counts so far: %s. Target shares: %s. For customer '%s'",
        best_agent.full_name,
        {a.full_name: auto_assign_counts[a.id] for a in agents},
        {(a.username or ""): RESHOP_AGENT_TARGET_SHARES.get((a.username or "").lower(), 0.0) for a in agents},
        customer_name,
    )
    return best_agent.id

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
            <a href="https://orbit.betterchoiceins.com/reshop" style="display:inline-block; background:linear-gradient(135deg, #0ea5e9, #0284c7); color:white; padding:14px 36px; border-radius:10px; text-decoration:none; font-weight:700; font-size:15px;">
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

def _notify_retention_team(reshop: "Reshop", created_by: str, db: Session = None):
    """Send email notification to the ASSIGNED agent about a new reshop request.
    CC Andrey on all notifications. Highlights same-day/next-day urgency."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping reshop notification")
        return

    # Determine recipient — assigned agent only
    to_email = None
    assignee_name = "Team"
    if reshop.assigned_to and db:
        assignee = db.query(User).filter(User.id == reshop.assigned_to).first()
        if assignee and assignee.email:
            to_email = assignee.email
            assignee_name = assignee.full_name.split()[0] if assignee.full_name else "Team"

    if not to_email:
        # Fallback: send to both
        to_email = "salma@betterchoiceins.com"

    cc_email = os.environ.get("RESHOP_CC_EMAIL", "andrey@betterchoiceins.com")

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

    premium_str = "${:,.0f}".format(float(reshop.current_premium)) if reshop.current_premium else "N/A"
    exp_str = reshop.expiration_date.strftime("%m/%d/%Y") if reshop.expiration_date else "N/A"

    # Determine urgency — same day or next day
    import pytz
    central = pytz.timezone("America/Chicago")
    now_ct = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(central)
    is_after_2pm = now_ct.hour >= 14

    urgency_html = ""
    if reshop.priority == "urgent":
        if is_after_2pm:
            urgency_html = (
                '<div style="background:#fef2f2; border:2px solid #dc2626; border-radius:10px; padding:16px; margin:0 0 16px; text-align:center;">'
                '<p style="margin:0; font-size:18px; font-weight:800; color:#dc2626;">⚡ DUE TOMORROW MORNING</p>'
                '<p style="margin:4px 0 0; font-size:13px; color:#991b1b;">Assigned after 2 PM — please prioritize first thing tomorrow</p>'
                '</div>'
            )
        else:
            urgency_html = (
                '<div style="background:#fef2f2; border:2px solid #dc2626; border-radius:10px; padding:16px; margin:0 0 16px; text-align:center;">'
                '<p style="margin:0; font-size:18px; font-weight:800; color:#dc2626;">⚡ DUE TODAY</p>'
                '<p style="margin:4px 0 0; font-size:13px; color:#991b1b;">This customer needs to be contacted immediately</p>'
                '</div>'
            )

    referred_row = ""
    if reshop.referred_by:
        referred_row = '<tr><td style="padding: 8px 0; color: #64748b;">Referred by</td><td style="padding: 8px 0; color: #1e293b;">' + (reshop.referred_by or '') + '</td></tr>'
    
    notes_row = ""
    if reshop.notes:
        notes_row = '<tr><td style="padding: 8px 0; color: #64748b;">Notes</td><td style="padding: 8px 0; color: #1e293b;">' + (reshop.notes or '') + '</td></tr>'

    html = (
        '<div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: 0 auto;">'
        '<div style="background: linear-gradient(135deg, #1e3a5f 0%, #0f2440 100%); padding: 20px 24px; border-radius: 12px 12px 0 0;">'
        '<h2 style="color: #ffffff; margin: 0; font-size: 18px;">🔄 New Reshop Request</h2>'
        '<p style="color: #94a3b8; margin: 6px 0 0; font-size: 13px;">Created by ' + created_by + ' via ' + source_label + '</p>'
        '</div>'
        '<div style="background: #ffffff; padding: 24px; border: 1px solid #e2e8f0; border-top: none;">'
        
        + urgency_html +
        
        '<table style="width: 100%; font-size: 14px; border-collapse: collapse;">'
        '<tr><td style="padding: 8px 0; color: #64748b; width: 120px;">Customer</td>'
        '<td style="padding: 8px 0; font-weight: 600; color: #1e293b;">' + (reshop.customer_name or '') + '</td></tr>'
        '<tr><td style="padding: 8px 0; color: #64748b;">Phone</td>'
        '<td style="padding: 8px 0; color: #1e293b;">' + (reshop.customer_phone or '—') + '</td></tr>'
        '<tr><td style="padding: 8px 0; color: #64748b;">Email</td>'
        '<td style="padding: 8px 0; color: #1e293b;">' + (reshop.customer_email or '—') + '</td></tr>'
        '<tr><td style="padding: 8px 0; color: #64748b;">Policy</td>'
        '<td style="padding: 8px 0; color: #1e293b;">' + (reshop.policy_number or '—') + ' (' + (reshop.carrier or 'Unknown carrier') + ')</td></tr>'
        '<tr><td style="padding: 8px 0; color: #64748b;">Premium</td>'
        '<td style="padding: 8px 0; color: #1e293b;">' + premium_str + '</td></tr>'
        '<tr><td style="padding: 8px 0; color: #64748b;">Expires</td>'
        '<td style="padding: 8px 0; color: #1e293b;">' + exp_str + '</td></tr>'
        '<tr><td style="padding: 8px 0; color: #64748b;">Priority</td>'
        '<td style="padding: 8px 0;"><span style="background: ' + priority_color + '; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">' + (reshop.priority or 'normal').upper() + '</span></td></tr>'
        + referred_row + notes_row +
        '</table>'
        '<div style="margin-top: 20px; text-align: center;">'
        '<a href="https://orbit.betterchoiceins.com/reshop" '
        'style="display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; padding: 10px 24px; border-radius: 8px; font-weight: 600; font-size: 14px;">'
        'Open Reshop Pipeline</a></div>'
        '</div>'
        '<div style="padding: 12px 24px; background: #f8fafc; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px; text-align: center;">'
        '<p style="color: #94a3b8; font-size: 11px; margin: 0;">Better Choice Insurance — ORBIT Reshop Pipeline</p>'
        '</div></div>'
    )

    subject = "🔄 New Reshop: " + (reshop.customer_name or "Unknown")
    if reshop.priority in ("urgent", "high"):
        subject = "🚨 URGENT Reshop: " + (reshop.customer_name or "Unknown")
    if reshop.referred_by:
        subject += " (via " + reshop.referred_by + ")"

    try:
        from_email = settings.MAILGUN_FROM_EMAIL or "service@" + settings.MAILGUN_DOMAIN
        resp = http_requests.post(
            "https://api.mailgun.net/v3/" + settings.MAILGUN_DOMAIN + "/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": "ORBIT Reshop <" + from_email + ">",
                "to": [to_email],
                "cc": [cc_email],
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        logger.info("Reshop notification sent to %s (cc: %s): %s", to_email, cc_email, resp.status_code)
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
        # Outreach attempts (3-attempt workflow)
        "attempt_1_at": r.attempt_1_at.isoformat() if getattr(r, "attempt_1_at", None) else None,
        "attempt_1_answered": r.attempt_1_answered if hasattr(r, "attempt_1_answered") else None,
        "attempt_2_at": r.attempt_2_at.isoformat() if getattr(r, "attempt_2_at", None) else None,
        "attempt_2_answered": r.attempt_2_answered if hasattr(r, "attempt_2_answered") else None,
        "attempt_3_at": r.attempt_3_at.isoformat() if getattr(r, "attempt_3_at", None) else None,
        "attempt_3_answered": r.attempt_3_answered if hasattr(r, "attempt_3_answered") else None,
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
    is_producer = current_user.role.lower() == "producer"
    if not _can_access(current_user) and not is_producer:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Reshop)

    # Determine visibility scope
    is_admin_or_manager = current_user.role.lower() in ("admin", "manager")
    # Andrey has elevated visibility (can see all reshops)
    is_elevated = current_user.username == "andrey.dayson"
    
    if is_producer:
        # Producers only see reshops they referred
        query = query.filter(Reshop.referred_by == current_user.full_name)
    elif not is_admin_or_manager and not is_elevated:
        # Retention specialists (Salma, Michelle) only see their assigned reshops
        query = query.filter(Reshop.assigned_to == current_user.id)

    if stage:
        query = query.filter(Reshop.stage == stage)
    elif not show_closed:
        # Active-stage cards + recently-closed (within 24h) cards so agents see
        # the card briefly after they mark it Renewed/Lost, giving a chance to
        # undo a mistake. After 24h, closed cards auto-archive out of the
        # pipeline view. All closed cards remain queryable via the outcome
        # report and with show_closed=true.
        recent_threshold = datetime.utcnow() - timedelta(hours=24)
        query = query.filter(
            or_(
                Reshop.stage.in_(ACTIVE_STAGES),
                and_(
                    Reshop.stage.in_(CLOSED_STAGES),
                    Reshop.stage_updated_at >= recent_threshold,
                ),
            )
        )

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
    is_producer = current_user.role.lower() == "producer"
    if not _can_access(current_user) and not is_producer:
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


@router.get("/outcome-report")
def reshop_outcome_report(
    start_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD (inclusive)"),
    end_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD (inclusive)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Outcome report — all reshops resolved (Rewrote or Lost) in the given window.

    Used by the Report tab on the Reshop page to pull historical outcomes for
    any date range. Defaults to the current month if no dates given.
    """
    is_producer = current_user.role.lower() == "producer"
    if not _can_access(current_user) and not is_producer:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Parse dates; default to current calendar month
    now = datetime.utcnow()
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date (use YYYY-MM-DD)")
    else:
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date (use YYYY-MM-DD)")
    else:
        end_dt = now

    # Scope query same as list endpoint
    is_admin_or_manager = current_user.role.lower() in ("admin", "manager")
    is_elevated = current_user.username == "andrey.dayson"

    base_query = db.query(Reshop).filter(
        Reshop.stage.in_(CLOSED_STAGES),
        Reshop.completed_at >= start_dt,
        Reshop.completed_at <= end_dt,
    )
    if is_producer:
        base_query = base_query.filter(Reshop.referred_by == current_user.full_name)
    elif not is_admin_or_manager and not is_elevated:
        base_query = base_query.filter(Reshop.assigned_to == current_user.id)

    rows = base_query.order_by(desc(Reshop.completed_at)).all()

    # Summary counts
    bound_rows = [r for r in rows if r.stage in ("bound", "renewed")]
    lost_rows = [r for r in rows if r.stage == "lost"]
    total_resolved = len(bound_rows) + len(lost_rows)
    win_rate = round(len(bound_rows) / max(total_resolved, 1) * 100, 1)

    # Savings sum (only on bound/renewed)
    total_savings = sum(float(r.premium_savings or 0) for r in bound_rows)

    # Per-agent breakdown
    by_agent = {}
    for r in rows:
        aid = r.assigned_to or 0
        name = r.assignee_name or "Unassigned"
        key = (aid, name)
        if key not in by_agent:
            by_agent[key] = {
                "agent_id": aid or None,
                "agent_name": name,
                "rewrote": 0,
                "lost": 0,
                "savings": 0.0,
            }
        if r.stage in ("bound", "renewed"):
            by_agent[key]["rewrote"] += 1
            by_agent[key]["savings"] += float(r.premium_savings or 0)
        elif r.stage == "lost":
            by_agent[key]["lost"] += 1
    agents_list = sorted(by_agent.values(), key=lambda x: -(x["rewrote"] + x["lost"]))
    for a in agents_list:
        total = a["rewrote"] + a["lost"]
        a["total"] = total
        a["win_rate"] = round(a["rewrote"] / max(total, 1) * 100, 1)

    # Detail list — minimal fields for display
    details = [
        {
            "id": r.id,
            "customer_name": r.customer_name,
            "carrier": r.carrier,
            "policy_number": r.policy_number,
            "line_of_business": r.line_of_business,
            "assignee_name": r.assignee_name,
            "stage": r.stage,
            "current_premium": float(r.current_premium) if r.current_premium else None,
            "renewal_premium": float(r.renewal_premium) if r.renewal_premium else None,
            "quoted_premium": float(r.quoted_premium) if r.quoted_premium else None,
            "premium_savings": float(r.premium_savings) if r.premium_savings else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "source": r.source,
        }
        for r in rows
    ]

    return {
        "window": {
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
        },
        "summary": {
            "total_resolved": total_resolved,
            "rewrote": len(bound_rows),
            "lost": len(lost_rows),
            "win_rate": win_rate,
            "total_savings": round(total_savings, 2),
        },
        "by_agent": agents_list,
        "details": details,
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
    is_producer = current_user.role.lower() == "producer"
    if not _can_access(current_user) and not is_producer:
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

    # Auto-assign: retention specialists (Salma/Michelle) assign to themselves.
    # Producers and admins go through round-robin.
    retention_usernames = [u.lower() for u in RESHOP_AUTO_ASSIGN_AGENTS]
    was_auto_assigned = False
    if current_user.username and current_user.username.lower() in retention_usernames:
        reshop.assigned_to = current_user.id
    else:
        auto_agent_id = _get_next_round_robin_agent(db, customer_id=data.customer_id, customer_name=data.customer_name or "")
        if auto_agent_id:
            reshop.assigned_to = auto_agent_id
            was_auto_assigned = True

    db.add(reshop)
    db.flush()

    _log_activity(db, reshop.id, current_user, "created",
                  f"Reshop created via {source or 'manual entry'}" + (f" — referred by {current_user.full_name}" if is_producer else ""))
    if was_auto_assigned:
        # Track auto-assignments for the weighted round-robin counter
        _log_activity(db, reshop.id, current_user, "auto_assigned",
                      f"Weighted round-robin → user_id={reshop.assigned_to}")

    db.commit()
    db.refresh(reshop)

    # Notify assigned agent / retention team on all new reshops
    if reshop.assigned_to:
        try:
            assignee = db.query(User).filter(User.id == reshop.assigned_to).first()
            _notify_reshop_assignment(reshop, assignee, current_user.full_name or current_user.username, db)
        except Exception as e:
            logger.error("Reshop notification error: %s", e)
    try:
        _notify_retention_team(reshop, current_user.full_name or current_user.username, db)
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

    # Broadcast live update
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("reshop:updated", {
            "id": reshop.id,
            "customer_name": reshop.customer_name,
            "user": current_user.full_name or current_user.username,
        })
    except Exception:
        pass

    return _reshop_to_dict(reshop)


@router.delete("/{reshop_id}")
def delete_reshop(
    reshop_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a single reshop and its activity log.

    Retention specialists, managers, and admins can delete.
    Returns {status, deleted_id, customer_name}.
    """
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete reshops")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    customer_name = reshop.customer_name
    # Clear child activities first (no FK cascade configured)
    db.query(ReshopActivity).filter(ReshopActivity.reshop_id == reshop_id).delete(synchronize_session=False)
    db.delete(reshop)
    db.commit()

    # Broadcast live update so other open tabs refresh
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("reshop:deleted", {
            "id": reshop_id,
            "customer_name": customer_name,
            "user": current_user.full_name or current_user.username,
        })
    except Exception:
        pass

    return {"status": "ok", "deleted_id": reshop_id, "customer_name": customer_name}


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


# ── Outreach attempt tracking ─────────────────────────────────────
class ReshopAttemptLog(BaseModel):
    attempt_number: int  # 1, 2, or 3
    answered: bool       # True = they answered the call → thank-you email
                         # False = didn't reach them → "we tried" email
    send_email: bool = True  # Allow skipping email if customer has no email on file


def _send_reshop_attempt_email(reshop: Reshop, answered: bool, attempt_number: int) -> tuple[bool, str]:
    """Send the branded attempt email. Returns (success, message_id_or_error)."""
    from app.services.welcome_email import BCI_NAVY, BCI_CYAN
    mg_key = os.environ.get("MAILGUN_API_KEY") or settings.MAILGUN_API_KEY
    mg_domain = os.environ.get("MAILGUN_DOMAIN") or settings.MAILGUN_DOMAIN
    if not mg_key or not mg_domain:
        return False, "Mailgun not configured"
    if not reshop.customer_email:
        return False, "No customer email on file"

    # Pick the right copy
    if answered:
        subject = "Thank you for speaking with us — Better Choice Insurance"
        headline = "Thank You"
        body = (
            f"Hi {reshop.customer_name.split()[0] if reshop.customer_name else 'there'},"
            "<br><br>"
            "Thank you for taking the time to speak with us today about your policy. "
            "We appreciate the opportunity to review your coverage and look forward to "
            "finding the right solution for you."
            "<br><br>"
            "If you have any follow-up questions, don't hesitate to reach out — we're "
            "here to help."
            "<br><br>"
            "Best regards,"
            "<br>"
            "Better Choice Insurance Group"
        )
    else:
        subject = "We tried reaching you about your policy renewal"
        headline = "We Tried to Reach You"
        body = (
            f"Hi {reshop.customer_name.split()[0] if reshop.customer_name else 'there'},"
            "<br><br>"
            "We tried reaching out to you today regarding your upcoming policy renewal, but weren't able to connect. "
            "We'd love the chance to review your current coverage and make sure you're still getting "
            "the best rate and protection."
            "<br><br>"
            "Please give us a call back at your earliest convenience — "
            "<strong>847-908-5665</strong> — or reply to this email and we'll reach out at a "
            "time that works for you."
            "<br><br>"
            "Best regards,"
            "<br>"
            "Better Choice Insurance Group"
        )

    html = f"""
    <!DOCTYPE html>
    <html><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f5f5;padding:30px 0;">
        <tr><td align="center">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,.08);">
            <tr><td style="background:linear-gradient(135deg,{BCI_NAVY} 0%,{BCI_CYAN} 100%);padding:30px;color:white;">
              <div style="font-size:12px;letter-spacing:2px;opacity:.85;">BETTER CHOICE INSURANCE GROUP</div>
              <div style="font-size:26px;font-weight:700;margin-top:8px;">{headline}</div>
            </td></tr>
            <tr><td style="padding:32px;color:#1a1a1a;line-height:1.6;font-size:15px;">
              {body}
            </td></tr>
            <tr><td style="background:#f8f8f8;padding:18px 32px;border-top:1px solid #e5e5e5;color:#666;font-size:12px;">
              Better Choice Insurance Group · 300 Cardinal Dr Suite 220, Saint Charles, IL 60175<br>
              847-908-5665 · service@betterchoiceins.com
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{mg_domain}/messages",
            auth=("api", mg_key),
            data={
                "from": f"Better Choice Insurance <service@{mg_domain}>",
                "to": reshop.customer_email,
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
                "h:X-Reshop-Id": str(reshop.id),
                "h:X-Attempt-Number": str(attempt_number),
            },
            timeout=20,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "sent")
            return True, msg_id
        return False, f"Mailgun {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


@router.post("/{reshop_id}/attempt")
def log_reshop_attempt(
    reshop_id: int,
    data: ReshopAttemptLog,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Log an outreach attempt on a reshop and send the matching customer email.

    attempt_number must be 1, 2, or 3 and must be the NEXT unfilled attempt
    (i.e., can't log attempt 3 before 1 and 2). Each attempt stores timestamp
    and whether the customer answered; the email dispatched matches that state.
    """
    if not _can_access(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    if data.attempt_number not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="attempt_number must be 1, 2, or 3")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    # Enforce sequential attempts
    if data.attempt_number == 2 and not reshop.attempt_1_at:
        raise HTTPException(status_code=400, detail="Must log attempt 1 before attempt 2")
    if data.attempt_number == 3 and not reshop.attempt_2_at:
        raise HTTPException(status_code=400, detail="Must log attempt 2 before attempt 3")

    # Already logged?
    existing_at = {1: reshop.attempt_1_at, 2: reshop.attempt_2_at, 3: reshop.attempt_3_at}[data.attempt_number]
    if existing_at is not None:
        raise HTTPException(status_code=400, detail=f"Attempt {data.attempt_number} already logged")

    now = datetime.utcnow()
    if data.attempt_number == 1:
        reshop.attempt_1_at = now
        reshop.attempt_1_answered = data.answered
    elif data.attempt_number == 2:
        reshop.attempt_2_at = now
        reshop.attempt_2_answered = data.answered
    else:
        reshop.attempt_3_at = now
        reshop.attempt_3_answered = data.answered

    email_result = {"sent": False, "reason": None}
    if data.send_email and reshop.customer_email:
        sent, info = _send_reshop_attempt_email(reshop, data.answered, data.attempt_number)
        email_result = {"sent": sent, "message_id": info if sent else None, "error": None if sent else info}

    _log_activity(
        db, reshop.id, current_user, "attempt_logged",
        f"Attempt {data.attempt_number}: " +
        ("Customer answered — thank-you email sent" if data.answered else "No answer — follow-up email sent") +
        ("" if email_result.get("sent") else f" (email NOT sent: {email_result.get('error') or 'no email on file'})"),
    )

    # Push a summary note to the customer's NowCerts profile so any agent
    # looking at the customer later sees the outreach history (not just
    # inside the reshop card).
    nc_noted = False
    try:
        if reshop.policy_number:
            from app.services.nowcerts_notes import push_nowcerts_note
            outcome = "Customer answered" if data.answered else "No answer"
            email_status = (
                "Thank-you email sent" if (data.answered and email_result.get("sent"))
                else "Follow-up email sent" if (not data.answered and email_result.get("sent"))
                else f"Email not sent ({email_result.get('error') or 'no email on file'})"
            )
            note_text = (
                f"Reshop outreach attempt #{data.attempt_number} of 3\n"
                f"Outcome: {outcome}\n"
                f"Agent: {current_user.full_name or current_user.username}\n"
                f"Timestamp: {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"Email: {email_status}\n"
                f"Policy: {reshop.policy_number or '?'}  Carrier: {reshop.carrier or '?'}\n"
                f"Source: ORBIT Reshop Pipeline"
            )
            subject = (
                f"☎️ Reshop attempt #{data.attempt_number} — "
                f"{'Answered' if data.answered else 'No answer'}"
            )
            nc_noted = push_nowcerts_note(db, reshop.policy_number, note_text, subject=subject)
    except Exception as e:
        logger.warning("NowCerts note push failed for reshop %s: %s", reshop.id, e)

    db.commit()
    db.refresh(reshop)
    return {
        "status": "ok",
        "attempt_number": data.attempt_number,
        "answered": data.answered,
        "email": email_result,
        "nowcerts_noted": nc_noted,
        "reshop": _reshop_to_dict(reshop),
    }


@router.delete("/{reshop_id}/attempt/{attempt_number}")
def clear_reshop_attempt(
    reshop_id: int,
    attempt_number: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear a logged attempt (admin/manager only — undo for mistakes).

    Clearing attempt N also clears attempts > N to keep the sequence consistent.
    Does NOT un-send the email that was already sent.
    """
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    if attempt_number not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Invalid attempt number")

    reshop = db.query(Reshop).filter(Reshop.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    # Clear this attempt and anything after it
    if attempt_number <= 1:
        reshop.attempt_1_at = None
        reshop.attempt_1_answered = None
    if attempt_number <= 2:
        reshop.attempt_2_at = None
        reshop.attempt_2_answered = None
    if attempt_number <= 3:
        reshop.attempt_3_at = None
        reshop.attempt_3_answered = None

    _log_activity(db, reshop.id, current_user, "attempt_cleared",
                  f"Cleared attempt {attempt_number} and subsequent attempts")
    db.commit()
    db.refresh(reshop)
    return {"status": "ok", "reshop": _reshop_to_dict(reshop)}


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

    # Broadcast live update
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("reshop:updated", {
            "id": reshop.id,
            "customer_name": reshop.customer_name,
            "old_stage": old_stage,
            "new_stage": stage,
            "user": current_user.full_name or current_user.username,
        })
    except Exception:
        pass

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
        # Pass A: exact policy number match (standard carriers)
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
                active_terms[t.policy_number] = t

        # Pass B: for renewing terms without an exact match, try matching by
        # customer_id + carrier + earlier effective date (handles NatGen-style
        # term suffixes like 202268745800, 202268745801, 202268745802)
        unmatched_renewals = [r for r in renewing if r.policy_number not in active_terms]
        if unmatched_renewals:
            for renewal in unmatched_renewals:
                if not renewal.customer_id or not renewal.effective_date:
                    continue
                prior = (
                    db.query(CustomerPolicy)
                    .filter(
                        CustomerPolicy.customer_id == renewal.customer_id,
                        CustomerPolicy.carrier == renewal.carrier,
                        func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]),
                        CustomerPolicy.effective_date < renewal.effective_date,
                        ~CustomerPolicy.id.in_(renewing_ids) if renewing_ids else True,
                    )
                    .order_by(CustomerPolicy.effective_date.desc())
                    .first()
                )
                if prior:
                    # Store under the RENEWAL's policy number so lookup works later
                    active_terms[renewal.policy_number] = prior

    # Check ALL reshops (active AND closed) to avoid re-creating cancelled/closed ones
    existing_policy_nums = set()
    all_reshops = db.query(Reshop).all()
    for r in all_reshops:
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
        if auto_agent_id:
            # Track auto-assignment for weighted round-robin counter
            db.add(ReshopActivity(
                reshop_id=reshop.id,
                user_name=actor_name,
                action="auto_assigned",
                detail=f"Weighted round-robin → user_id={auto_agent_id}",
            ))
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
        "created": created,
        "policies_checked": len(renewing),
        "skipped": skipped_existing,
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
    # Producers can submit referrals from the customer card but cannot view the pipeline.
    is_producer = current_user.role.lower() == "producer"
    if not _can_access(current_user) and not is_producer:
        raise HTTPException(status_code=403, detail="Not authorized")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    policy = None
    if policy_id:
        policy = db.query(CustomerPolicy).filter(CustomerPolicy.id == policy_id).first()

    # Manual reshop from customer center = URGENT, 24h deadline
    deadline = datetime.utcnow() + timedelta(hours=24)

    # If the person creating the reshop IS a retention specialist (Salma/Michelle),
    # assign to themselves — don't round-robin to the other agent.
    # Producers and admins still go through round-robin.
    retention_usernames = [u.lower() for u in RESHOP_AUTO_ASSIGN_AGENTS]
    was_auto_assigned = False
    if current_user.username and current_user.username.lower() in retention_usernames:
        auto_agent_id = current_user.id
    else:
        auto_agent_id = _get_next_round_robin_agent(db, customer_id=customer.id, customer_name=customer.full_name or "")
        if auto_agent_id:
            was_auto_assigned = True

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
    if was_auto_assigned:
        _log_activity(db, reshop.id, current_user, "auto_assigned",
                      f"Weighted round-robin → user_id={auto_agent_id}")
    db.commit()
    db.refresh(reshop)

    # Notify retention team
    try:
        _notify_retention_team(reshop, current_user.full_name or current_user.username, db)
    except Exception as e:
        logger.error("Reshop notification error: %s", e)

    return _reshop_to_dict(reshop)
