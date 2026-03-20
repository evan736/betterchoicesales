"""
Daily Reshop Digest Email
Sends a daily summary to each retention specialist with their assigned reshops,
sorted by urgency (days until renewal). Replaces individual assignment emails.

Schedule: 8:30 AM CT daily (Monday-Friday)
CC: Andrey Dayson on all digests
"""

import os
import logging
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def send_reshop_digests(db: Session, today: date = None) -> dict:
    """Send daily reshop digest to each agent with assigned open reshops."""
    from app.models.reshop import Reshop
    from app.models.user import User
    from app.core.config import settings
    import requests

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping reshop digest")
        return {"status": "skipped", "reason": "mailgun_not_configured"}

    today = today or date.today()
    now = datetime.utcnow()

    # Get all open reshops (not bound, lost, or cancelled)
    closed_stages = ("bound", "lost", "cancelled")
    open_reshops = db.query(Reshop).filter(
        Reshop.assigned_to.isnot(None),
        ~Reshop.stage.in_(closed_stages),
    ).all()

    if not open_reshops:
        logger.info("No open assigned reshops — skipping digest")
        return {"status": "skipped", "reason": "no_open_reshops"}

    # Group by assignee
    from collections import defaultdict
    by_agent = defaultdict(list)
    for r in open_reshops:
        by_agent[r.assigned_to].append(r)

    # Get agent info
    agent_ids = list(by_agent.keys())
    agents = {u.id: u for u in db.query(User).filter(User.id.in_(agent_ids)).all()}

    from_email = settings.MAILGUN_FROM_EMAIL or os.environ.get("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")
    cc_email = os.environ.get("RESHOP_CC_EMAIL", "andrey@betterchoiceins.com")

    results = []

    for agent_id, reshops in by_agent.items():
        agent = agents.get(agent_id)
        if not agent or not agent.email:
            continue

        first_name = agent.full_name.split()[0] if agent.full_name else "Team"

        # Calculate days until renewal for each reshop and sort
        reshop_data = []
        for r in reshops:
            days_left = None
            if r.renewal_date:
                days_left = (r.renewal_date - now).days
            elif r.expiration_date:
                days_left = (r.expiration_date - now).days

            # Premium increase
            increase_pct = None
            if r.current_premium and r.renewal_premium:
                try:
                    increase_pct = ((float(r.renewal_premium) - float(r.current_premium)) / float(r.current_premium)) * 100
                except (ValueError, ZeroDivisionError):
                    pass

            reshop_data.append({
                "id": r.id,
                "customer_name": r.customer_name or "Unknown",
                "carrier": r.carrier or "Unknown",
                "policy_number": r.policy_number or "",
                "current_premium": float(r.current_premium or 0),
                "renewal_premium": float(r.renewal_premium or 0),
                "increase_pct": increase_pct,
                "days_left": days_left,
                "stage": r.stage or "proactive",
                "priority": r.priority or "normal",
                "renewal_date": r.renewal_date,
            })

        # Sort by days_left ascending (most urgent first)
        reshop_data.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 999)

        # Count by urgency
        overdue = sum(1 for r in reshop_data if r["days_left"] is not None and r["days_left"] < 0)
        critical = sum(1 for r in reshop_data if r["days_left"] is not None and 0 <= r["days_left"] <= 7)
        urgent = sum(1 for r in reshop_data if r["days_left"] is not None and 7 < r["days_left"] <= 14)
        upcoming = sum(1 for r in reshop_data if r["days_left"] is not None and r["days_left"] > 14)

        # Build table rows
        rows_html = ""
        for r in reshop_data:
            # Color code by urgency
            if r["days_left"] is not None and r["days_left"] < 0:
                days_color = "#dc2626"
                days_bg = "#fef2f2"
                days_text = f"OVERDUE ({abs(r['days_left'])}d)"
                row_border = "border-left: 4px solid #dc2626;"
            elif r["days_left"] is not None and r["days_left"] <= 7:
                days_color = "#dc2626"
                days_bg = "#fef2f2"
                days_text = f"{r['days_left']} days"
                row_border = "border-left: 4px solid #dc2626;"
            elif r["days_left"] is not None and r["days_left"] <= 14:
                days_color = "#f59e0b"
                days_bg = "#fffbeb"
                days_text = f"{r['days_left']} days"
                row_border = "border-left: 4px solid #f59e0b;"
            elif r["days_left"] is not None and r["days_left"] <= 21:
                days_color = "#3b82f6"
                days_bg = "#eff6ff"
                days_text = f"{r['days_left']} days"
                row_border = "border-left: 4px solid #3b82f6;"
            else:
                days_color = "#6b7280"
                days_bg = "#f9fafb"
                days_text = f"{r['days_left']}d" if r["days_left"] is not None else "—"
                row_border = "border-left: 4px solid #e5e7eb;"

            increase_html = ""
            if r["increase_pct"] is not None and r["increase_pct"] > 0:
                increase_html = f' <span style="color:#dc2626; font-size:12px;">(+{r["increase_pct"]:.0f}%)</span>'

            stage_labels = {
                "proactive": "Not Started",
                "new_request": "New",
                "quoting": "Quoting",
                "quote_ready": "Quote Ready",
                "presenting": "Presenting",
            }
            stage_text = stage_labels.get(r["stage"], r["stage"].title())

            renewal_str = ""
            if r["renewal_date"]:
                renewal_str = r["renewal_date"].strftime("%b %d")

            rows_html += f'''
            <tr style="background:{days_bg}; {row_border}">
                <td style="padding:12px 10px; font-weight:600; color:#0f172a; font-size:14px;">{r["customer_name"]}</td>
                <td style="padding:12px 8px; color:#475569; font-size:13px;">{r["carrier"]}</td>
                <td style="padding:12px 8px; color:#475569; font-size:13px; text-align:right;">${r["current_premium"]:,.0f}</td>
                <td style="padding:12px 8px; font-weight:700; color:#0f172a; font-size:13px; text-align:right;">${r["renewal_premium"]:,.0f}{increase_html}</td>
                <td style="padding:12px 8px; text-align:center;"><span style="color:{days_color}; font-weight:700; font-size:13px;">{days_text}</span></td>
                <td style="padding:12px 8px; color:#64748b; font-size:12px; text-align:center;">{renewal_str}</td>
                <td style="padding:12px 8px; color:#64748b; font-size:12px; text-align:center;">{stage_text}</td>
            </tr>'''

        # Summary badges
        badge_html = ""
        if overdue > 0:
            badge_html += f'<span style="background:#dc2626; color:white; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700; margin-right:8px;">{overdue} OVERDUE</span>'
        if critical > 0:
            badge_html += f'<span style="background:#ef4444; color:white; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700; margin-right:8px;">{critical} within 7 days</span>'
        if urgent > 0:
            badge_html += f'<span style="background:#f59e0b; color:white; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700; margin-right:8px;">{urgent} within 14 days</span>'
        if upcoming > 0:
            badge_html += f'<span style="background:#3b82f6; color:white; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700;">{upcoming} upcoming</span>'

        total_premium = sum(r["renewal_premium"] for r in reshop_data)

        subject = f"Reshop Pipeline — {len(reshop_data)} Open | {critical + overdue} Need Immediate Attention"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:700px; margin:0 auto; padding:24px 16px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding:24px; border-radius:12px 12px 0 0; text-align:center;">
        <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="Better Choice Insurance" style="height:36px;" />
        <h1 style="margin:12px 0 4px; color:#fff; font-size:20px;">Daily Reshop Pipeline</h1>
        <p style="margin:0; color:#94a3b8; font-size:13px;">{today.strftime("%A, %B %d, %Y")}</p>
    </div>

    <!-- Body -->
    <div style="background:white; padding:28px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">

        <p style="margin:0 0 16px; color:#334155; font-size:15px;">
            Good morning {first_name}! Here's your reshop pipeline. <strong style="color:#dc2626;">Please prioritize items with 7 or fewer days remaining</strong> — customers are more likely to stay if we reach them before their renewal date.
        </p>

        <!-- Summary -->
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:16px; margin:0 0 20px; text-align:center;">
            <div style="display:inline-block; margin:0 16px; text-align:center;">
                <div style="font-size:28px; font-weight:800; color:#0f172a;">{len(reshop_data)}</div>
                <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:1px;">Open Reshops</div>
            </div>
            <div style="display:inline-block; margin:0 16px; text-align:center;">
                <div style="font-size:28px; font-weight:800; color:#dc2626;">{critical + overdue}</div>
                <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:1px;">Need Attention</div>
            </div>
            <div style="display:inline-block; margin:0 16px; text-align:center;">
                <div style="font-size:28px; font-weight:800; color:#0f172a;">${total_premium:,.0f}</div>
                <div style="font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:1px;">Renewal Premium</div>
            </div>
        </div>

        <!-- Urgency badges -->
        <div style="margin:0 0 16px; text-align:center;">{badge_html}</div>

        <!-- Table -->
        <table style="width:100%; border-collapse:collapse; font-size:13px;" cellpadding="0" cellspacing="0">
            <thead>
                <tr style="background:#f1f5f9; border-bottom:2px solid #e2e8f0;">
                    <th style="padding:10px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase; letter-spacing:0.5px;">Customer</th>
                    <th style="padding:10px 8px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">Carrier</th>
                    <th style="padding:10px 8px; text-align:right; color:#64748b; font-size:11px; text-transform:uppercase;">Current</th>
                    <th style="padding:10px 8px; text-align:right; color:#64748b; font-size:11px; text-transform:uppercase;">Renewal</th>
                    <th style="padding:10px 8px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Days Left</th>
                    <th style="padding:10px 8px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Renews</th>
                    <th style="padding:10px 8px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Stage</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <!-- Goal reminder -->
        <div style="background:#ecfdf5; border:1px solid #a7f3d0; border-radius:8px; padding:14px; margin:20px 0 0; text-align:center;">
            <p style="margin:0; color:#065f46; font-size:13px; font-weight:600;">
                🎯 Goal: Complete reshops at least 7 days before renewal to maximize retention
            </p>
        </div>

        <!-- CTA -->
        <div style="text-align:center; margin:24px 0 0;">
            <a href="https://orbit.betterchoiceins.com/reshop" style="display:inline-block; background:linear-gradient(135deg, #0ea5e9, #0284c7); color:white; padding:14px 36px; border-radius:10px; text-decoration:none; font-weight:700; font-size:15px;">
                Open Reshop Pipeline →
            </a>
        </div>
    </div>

    <!-- Footer -->
    <div style="background:#f8fafc; padding:16px; text-align:center; border-radius:0 0 12px 12px; border-top:1px solid #e2e8f0;">
        <p style="margin:0; color:#94a3b8; font-size:11px;">Better Choice Insurance Group · (847) 908-5665</p>
    </div>
</div></body></html>"""

        try:
            resp = requests.post(
                f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
                auth=("api", settings.MAILGUN_API_KEY),
                data={
                    "from": f"Better Choice Insurance <{from_email}>",
                    "to": [agent.email],
                    "cc": [cc_email],
                    "subject": subject,
                    "html": html,
                },
                timeout=15,
            )
            logger.info(f"Reshop digest sent to {agent.email}: {resp.status_code} ({len(reshop_data)} reshops)")
            results.append({
                "agent": agent.full_name,
                "email": agent.email,
                "reshops": len(reshop_data),
                "critical": critical + overdue,
                "status": resp.status_code,
            })
        except Exception as e:
            logger.error(f"Failed to send reshop digest to {agent.email}: {e}")
            results.append({"agent": agent.full_name, "email": agent.email, "error": str(e)})

    return {"status": "sent", "date": str(today), "digests": results}
