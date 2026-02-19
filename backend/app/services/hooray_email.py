"""Hooray! sale notification email — sent to all producers when a new sale is added.

Includes sale details (customer, policy type, carrier, premium) and a running
daily sales count + total premium for the day.
"""
import logging
import requests
from datetime import date, datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.sale import Sale
from app.models.user import User

logger = logging.getLogger(__name__)

AGENCY_NAME = "Better Choice Insurance Group"
BCI_NAVY = "#1a2b5f"
BCI_CYAN = "#2cb5e8"


def _get_daily_stats(db: Session) -> dict:
    """Get today's running sales count and total premium."""
    today = date.today()
    results = (
        db.query(
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.written_premium), 0).label("premium"),
        )
        .filter(func.date(Sale.sale_date) == today)
        .first()
    )
    return {
        "count": results.count if results else 0,
        "premium": float(results.premium) if results else 0.0,
    }


def _get_all_producer_emails(db: Session) -> list[str]:
    """Get email addresses for all active users (producers, admins, managers)."""
    users = db.query(User.email).filter(User.is_active == True).all()
    return [u.email for u in users if u.email]


def _format_premium(amount) -> str:
    """Format premium as currency string."""
    try:
        return f"${float(amount):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def _policy_type_display(policy_type: str) -> str:
    """Convert policy_type slug to display name."""
    mapping = {
        "auto": "Auto",
        "auto_6m": "Auto (6-Month)",
        "auto_12m": "Auto (12-Month)",
        "home": "Homeowners",
        "renters": "Renters",
        "condo": "Condo",
        "motorcycle": "Motorcycle",
        "bundled": "Bundle",
        "other": "Other",
    }
    return mapping.get(policy_type, (policy_type or "").replace("_", " ").title())


def build_hooray_email_html(
    client_name: str,
    carrier: str,
    policy_type: str,
    premium: float,
    producer_name: str,
    daily_count: int,
    daily_premium: float,
) -> tuple[str, str]:
    """Build the Hooray email subject + HTML body."""

    premium_str = _format_premium(premium)
    daily_premium_str = _format_premium(daily_premium)
    policy_display = _policy_type_display(policy_type)
    today_str = date.today().strftime("%B %d, %Y")

    subject = f"🎉 New Sale! {client_name} — {carrier or 'New Policy'} {premium_str}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<div style="max-width:560px; margin:0 auto; padding:24px 16px;">

    <!-- Header Banner -->
    <div style="background: linear-gradient(135deg, {BCI_NAVY} 0%, #0c4a6e 100%); border-radius:16px 16px 0 0; padding:32px 24px; text-align:center;">
        <div style="font-size:48px; margin-bottom:8px;">🎉</div>
        <h1 style="margin:0; color:white; font-size:26px; font-weight:800; letter-spacing:-0.5px;">New Sale!</h1>
        <p style="margin:8px 0 0; color:{BCI_CYAN}; font-size:15px; font-weight:600;">{producer_name} just closed a deal</p>
    </div>

    <!-- Sale Details Card -->
    <div style="background:white; padding:28px 24px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">

        <!-- Premium Highlight -->
        <div style="text-align:center; margin-bottom:24px; padding:20px; background:linear-gradient(135deg, #ecfdf5, #d1fae5); border-radius:12px; border:1px solid #a7f3d0;">
            <p style="margin:0 0 4px; color:#065f46; font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:1px;">Written Premium</p>
            <p style="margin:0; color:#047857; font-size:36px; font-weight:800;">{premium_str}</p>
        </div>

        <!-- Details Table -->
        <table style="width:100%; font-size:15px; color:#334155; border-collapse:collapse;" cellpadding="0" cellspacing="0">
            <tr>
                <td style="padding:12px 0; color:#64748b; border-bottom:1px solid #f1f5f9; width:120px;">Customer</td>
                <td style="padding:12px 0; font-weight:700; border-bottom:1px solid #f1f5f9;">{client_name}</td>
            </tr>
            <tr>
                <td style="padding:12px 0; color:#64748b; border-bottom:1px solid #f1f5f9;">Carrier</td>
                <td style="padding:12px 0; font-weight:600; border-bottom:1px solid #f1f5f9;">{carrier or 'N/A'}</td>
            </tr>
            <tr>
                <td style="padding:12px 0; color:#64748b; border-bottom:1px solid #f1f5f9;">Coverage</td>
                <td style="padding:12px 0; font-weight:600; border-bottom:1px solid #f1f5f9;">{policy_display}</td>
            </tr>
            <tr>
                <td style="padding:12px 0; color:#64748b;">Sold By</td>
                <td style="padding:12px 0; font-weight:700; color:{BCI_NAVY};">{producer_name}</td>
            </tr>
        </table>
    </div>

    <!-- Daily Scoreboard -->
    <div style="background:linear-gradient(135deg, #1e293b, #0f172a); padding:24px; border-radius:0 0 16px 16px;">
        <h3 style="margin:0 0 16px; color:#94a3b8; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px; text-align:center;">📊 Today's Scoreboard — {today_str}</h3>
        <table style="width:100%;" cellpadding="0" cellspacing="0">
            <tr>
                <td style="text-align:center; width:50%; padding:8px;">
                    <p style="margin:0; color:{BCI_CYAN}; font-size:32px; font-weight:800;">{daily_count}</p>
                    <p style="margin:4px 0 0; color:#94a3b8; font-size:12px; font-weight:600; text-transform:uppercase;">Sales Today</p>
                </td>
                <td style="text-align:center; width:50%; padding:8px; border-left:1px solid #334155;">
                    <p style="margin:0; color:#34d399; font-size:32px; font-weight:800;">{daily_premium_str}</p>
                    <p style="margin:4px 0 0; color:#94a3b8; font-size:12px; font-weight:600; text-transform:uppercase;">Total Premium</p>
                </td>
            </tr>
        </table>
    </div>

    <!-- Footer -->
    <div style="text-align:center; padding:20px 0 0;">
        <p style="margin:0; color:#94a3b8; font-size:12px;">
            {AGENCY_NAME} • Keep up the great work! 🚀
        </p>
    </div>

</div>
</body>
</html>"""

    return subject, html


def send_hooray_email(
    sale: Sale,
    producer_name: str,
    db: Session,
):
    """Send the Hooray notification email to all producers.

    Called in a background thread after a new sale is created.
    """
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping hooray email")
        return {"success": False, "error": "Mailgun not configured"}

    # Get daily stats (includes this new sale since it's already committed)
    daily = _get_daily_stats(db)

    # Get all producer emails
    recipient_emails = _get_all_producer_emails(db)
    if not recipient_emails:
        logger.warning("No active producer emails found — skipping hooray email")
        return {"success": False, "error": "No recipients"}

    subject, html_body = build_hooray_email_html(
        client_name=sale.client_name or "New Customer",
        carrier=sale.carrier or "",
        policy_type=sale.policy_type or "other",
        premium=float(sale.written_premium or 0),
        producer_name=producer_name,
        daily_count=daily["count"],
        daily_premium=daily["premium"],
    )

    mail_data = {
        "from": f"{AGENCY_NAME} <{settings.MAILGUN_FROM_EMAIL}>",
        "to": recipient_emails,
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
            logger.info(
                "Hooray email sent to %d recipients for sale %s — msg_id: %s",
                len(recipient_emails),
                sale.id,
                msg_id,
            )
            return {"success": True, "message_id": msg_id, "recipients": len(recipient_emails)}
        else:
            logger.error("Mailgun error %s: %s", resp.status_code, resp.text)
            return {"success": False, "error": f"Mailgun returned {resp.status_code}"}
    except Exception as e:
        logger.error("Failed to send hooray email: %s", e)
        return {"success": False, "error": str(e)}
