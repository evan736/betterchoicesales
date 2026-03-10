"""Daily Sales Recap Email — sent at 8 PM CST to all employees.

Shows:
- Total agency sales for the day (count + premium)
- Individual producer breakdown (sales count, premium, items)
- Premium leaderboard
- List of each sale made today with details
"""
import logging
import requests
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import func, extract
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.sale import Sale
from app.models.user import User

logger = logging.getLogger(__name__)

AGENCY_NAME = "Better Choice Insurance Group"
BCI_NAVY = "#1a2b5f"
BCI_CYAN = "#2cb5e8"


def _format_premium(amount) -> str:
    try:
        return f"${float(amount):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def _get_daily_sales(db: Session, target_date: date = None) -> dict:
    """Get all sales for a specific day with producer breakdown."""
    if target_date is None:
        target_date = date.today()

    # Get all sales for the day
    sales = db.query(Sale).filter(
        func.date(Sale.sale_date) == target_date
    ).order_by(Sale.written_premium.desc()).all()

    if not sales:
        return {"date": target_date, "sales": [], "producers": [], "total_premium": 0, "total_count": 0, "total_items": 0}

    # Resolve producer names
    producer_ids = list(set(s.producer_id for s in sales if s.producer_id))
    producers = {u.id: u for u in db.query(User).filter(User.id.in_(producer_ids)).all()} if producer_ids else {}

    # Build sale details
    sale_list = []
    for s in sales:
        p = producers.get(s.producer_id)
        sale_list.append({
            "client_name": s.client_name or "Unknown",
            "carrier": s.carrier or "N/A",
            "policy_type": (s.policy_type or "other").replace("_", " ").title(),
            "premium": float(s.written_premium or 0),
            "items": s.item_count or 1,
            "producer_name": p.full_name if p else "Unknown",
            "producer_first": p.full_name.split()[0] if p else "Unknown",
            "lead_source": (s.lead_source or "").replace("_", " ").title(),
        })

    # Producer breakdown
    producer_stats = {}
    for s in sale_list:
        name = s["producer_name"]
        if name not in producer_stats:
            producer_stats[name] = {"name": name, "first_name": s["producer_first"], "count": 0, "premium": 0, "items": 0}
        producer_stats[name]["count"] += 1
        producer_stats[name]["premium"] += s["premium"]
        producer_stats[name]["items"] += s["items"]

    # Sort by premium descending (leaderboard)
    leaderboard = sorted(producer_stats.values(), key=lambda x: x["premium"], reverse=True)

    total_premium = sum(s["premium"] for s in sale_list)
    total_items = sum(s["items"] for s in sale_list)

    return {
        "date": target_date,
        "sales": sale_list,
        "producers": leaderboard,
        "total_premium": total_premium,
        "total_count": len(sale_list),
        "total_items": total_items,
    }


def _medal(rank: int) -> str:
    """Return medal emoji for leaderboard position."""
    if rank == 0:
        return "🥇"
    elif rank == 1:
        return "🥈"
    elif rank == 2:
        return "🥉"
    return ""


def build_daily_recap_html(data: dict) -> tuple[str, str]:
    """Build the daily recap email subject + HTML body."""
    target_date = data["date"]
    date_str = target_date.strftime("%A, %B %d, %Y")
    short_date = target_date.strftime("%m/%d/%Y")
    total_premium = _format_premium(data["total_premium"])
    total_count = data["total_count"]
    total_items = data["total_items"]
    producers = data["producers"]
    sales = data["sales"]

    if total_count == 0:
        subject = f"📊 Daily Sales Recap — {short_date} — No Sales Today"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:24px 16px;">
    <div style="background:linear-gradient(135deg, {BCI_NAVY} 0%, #0c4a6e 100%); border-radius:16px; padding:32px 24px; text-align:center;">
        <h1 style="margin:0; color:white; font-size:24px; font-weight:800;">📊 Daily Sales Recap</h1>
        <p style="margin:8px 0 0; color:{BCI_CYAN}; font-size:14px;">{date_str}</p>
        <p style="margin:16px 0 0; color:#94a3b8; font-size:16px;">No sales recorded today. Let's get after it tomorrow! 💪</p>
    </div>
    <div style="text-align:center; padding:20px 0;"><p style="margin:0; color:#94a3b8; font-size:12px;">{AGENCY_NAME}</p></div>
</div></body></html>"""
        return subject, html

    subject = f"📊 Daily Sales Recap — {short_date} — {total_count} Sales, {total_premium}"

    # Build leaderboard rows
    leaderboard_rows = ""
    for i, p in enumerate(producers):
        medal = _medal(i)
        bg = "background:#ecfdf5;" if i == 0 else ""
        leaderboard_rows += f"""
        <tr style="{bg}">
            <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; font-size:15px;">
                {medal} <strong>{p['name']}</strong>
            </td>
            <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; text-align:center; color:{BCI_NAVY}; font-weight:700; font-size:15px;">
                {p['count']}
            </td>
            <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; text-align:center; font-size:15px;">
                {p['items']}
            </td>
            <td style="padding:10px 12px; border-bottom:1px solid #f1f5f9; text-align:right; color:#047857; font-weight:800; font-size:15px;">
                {_format_premium(p['premium'])}
            </td>
        </tr>"""

    # Build individual sale rows
    sale_rows = ""
    for s in sales:
        sale_rows += f"""
        <tr>
            <td style="padding:8px 10px; border-bottom:1px solid #f1f5f9; font-size:13px;">
                <strong>{s['client_name']}</strong><br>
                <span style="color:#64748b; font-size:12px;">{s['carrier']} • {s['policy_type']}</span>
                {"<br><span style='color:#94a3b8; font-size:11px;'>" + s['lead_source'] + "</span>" if s['lead_source'] else ""}
            </td>
            <td style="padding:8px 10px; border-bottom:1px solid #f1f5f9; text-align:center; font-size:13px; color:#64748b;">
                {s['producer_first']}
            </td>
            <td style="padding:8px 10px; border-bottom:1px solid #f1f5f9; text-align:right; font-weight:700; font-size:13px; color:#047857;">
                {_format_premium(s['premium'])}
            </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:24px 16px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg, {BCI_NAVY} 0%, #0c4a6e 100%); border-radius:16px 16px 0 0; padding:32px 24px; text-align:center;">
        <h1 style="margin:0; color:white; font-size:26px; font-weight:800;">📊 Daily Sales Recap</h1>
        <p style="margin:8px 0 0; color:{BCI_CYAN}; font-size:14px; font-weight:600;">{date_str}</p>
    </div>

    <!-- Summary Stats -->
    <div style="background:white; padding:20px 24px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">
        <table style="width:100%;" cellpadding="0" cellspacing="0">
            <tr>
                <td style="text-align:center; padding:12px; width:33%;">
                    <p style="margin:0; color:{BCI_NAVY}; font-size:36px; font-weight:800;">{total_count}</p>
                    <p style="margin:4px 0 0; color:#64748b; font-size:12px; font-weight:600; text-transform:uppercase;">Sales</p>
                </td>
                <td style="text-align:center; padding:12px; width:33%; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">
                    <p style="margin:0; color:#047857; font-size:36px; font-weight:800;">{total_premium}</p>
                    <p style="margin:4px 0 0; color:#64748b; font-size:12px; font-weight:600; text-transform:uppercase;">Premium</p>
                </td>
                <td style="text-align:center; padding:12px; width:33%;">
                    <p style="margin:0; color:{BCI_CYAN}; font-size:36px; font-weight:800;">{total_items}</p>
                    <p style="margin:4px 0 0; color:#64748b; font-size:12px; font-weight:600; text-transform:uppercase;">Items</p>
                </td>
            </tr>
        </table>
    </div>

    <!-- Producer Leaderboard -->
    <div style="background:white; padding:20px 24px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0; border-top:2px solid #e2e8f0;">
        <h2 style="margin:0 0 12px; color:{BCI_NAVY}; font-size:18px; font-weight:800;">🏆 Producer Leaderboard</h2>
        <table style="width:100%; border-collapse:collapse;" cellpadding="0" cellspacing="0">
            <tr style="background:#f8fafc;">
                <th style="padding:8px 12px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700;">Producer</th>
                <th style="padding:8px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700;">Sales</th>
                <th style="padding:8px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700;">Items</th>
                <th style="padding:8px 12px; text-align:right; color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700;">Premium</th>
            </tr>
            {leaderboard_rows}
        </table>
    </div>

    <!-- Sale Details -->
    <div style="background:white; padding:20px 24px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0; border-top:2px solid #e2e8f0; border-radius:0 0 16px 16px;">
        <h2 style="margin:0 0 12px; color:{BCI_NAVY}; font-size:18px; font-weight:800;">📋 Today's Sales</h2>
        <table style="width:100%; border-collapse:collapse;" cellpadding="0" cellspacing="0">
            <tr style="background:#f8fafc;">
                <th style="padding:8px 10px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">Customer / Policy</th>
                <th style="padding:8px 10px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Agent</th>
                <th style="padding:8px 10px; text-align:right; color:#64748b; font-size:11px; text-transform:uppercase;">Premium</th>
            </tr>
            {sale_rows}
        </table>
    </div>

    <!-- Footer -->
    <div style="text-align:center; padding:20px 0;">
        <p style="margin:0; color:#94a3b8; font-size:12px;">
            {AGENCY_NAME} • Great work today, team! 🚀
        </p>
    </div>

</div></body></html>"""

    return subject, html


def _get_all_employee_emails(db: Session) -> list[str]:
    """Get emails for all active employees (excludes system accounts)."""
    EXCLUDED_USERNAMES = {"beacon.ai", "admin"}
    users = db.query(User).filter(
        User.is_active == True,
        User.email.isnot(None),
        User.email != "",
    ).all()
    return [
        u.email for u in users
        if u.email and "@" in u.email
        and (u.username or "").lower() not in EXCLUDED_USERNAMES
    ]


def send_daily_recap(db: Session, target_date: date = None) -> dict:
    """Build and send the daily sales recap email."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping daily recap")
        return {"success": False, "error": "Mailgun not configured"}

    data = _get_daily_sales(db, target_date)
    subject, html_body = build_daily_recap_html(data)

    recipients = _get_all_employee_emails(db)
    if not recipients:
        logger.warning("No employee emails found — skipping daily recap")
        return {"success": False, "error": "No recipients"}

    mail_data = {
        "from": f"{AGENCY_NAME} <{settings.MAILGUN_FROM_EMAIL}>",
        "to": recipients,
        "subject": subject,
        "html": html_body,
    }

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info(f"Daily recap sent to {len(recipients)} recipients — {data['total_count']} sales, {_format_premium(data['total_premium'])}")
            return {"success": True, "message_id": msg_id, "recipients": len(recipients), "sales": data["total_count"]}
        else:
            logger.error(f"Mailgun error {resp.status_code}: {resp.text}")
            return {"success": False, "error": f"Mailgun {resp.status_code}"}
    except Exception as e:
        logger.error(f"Failed to send daily recap: {e}")
        return {"success": False, "error": str(e)}
