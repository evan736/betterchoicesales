"""UW digest + reminder service.

Runs daily at 7:30 AM CT to:
  1. Send each assignee a daily summary email of their open UW items
  2. Send Evan a master daily summary of the entire agency's open items
  3. Fire 3-day-out, 1-day-out, and overdue reminders to assignees
     (each reminder fires once per item — tracked via flags on UWItem)

All notifications fail open: if Mailgun is misconfigured or an individual
email send errors, the loop continues to the next item.
"""
import os
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import requests as http_requests
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models.uw_item import UWItem, UWActivity
from app.models.user import User

logger = logging.getLogger(__name__)


def _account_total_premium(item: UWItem, db: Session) -> Optional[float]:
    """Sum of premium across the customer's active policies, or None.

    Mirrors the helper in api/uw_tracker.py — duplicated here to keep
    services free of api imports. Uses the caller's existing DB session
    rather than opening a new one (the digest loop already has one).
    """
    if not item.customer_id:
        return None
    try:
        from app.models.customer import CustomerPolicy
        policies = (
            db.query(CustomerPolicy)
            .filter(CustomerPolicy.customer_id == item.customer_id)
            .filter(or_(
                CustomerPolicy.status.is_(None),
                ~func.lower(CustomerPolicy.status).in_(
                    ["cancelled", "canceled", "expired", "lapsed", "non-renewed", "non renewed"]
                ),
            ))
            .all()
        )
        if not policies:
            return None
        total = sum(float(p.premium or 0) for p in policies)
        return total if total > 0 else None
    except Exception as e:
        logger.debug(f"Could not compute account premium for UW item {item.id}: {e}")
        return None


def _fmt_money(amount: Optional[float]) -> str:
    if amount is None or amount == 0:
        return "—"
    return f"${amount:,.0f}"


def _mailgun_send(to: str, subject: str, html: str) -> bool:
    mg_key = os.environ.get("MAILGUN_API_KEY")
    mg_domain = os.environ.get("MAILGUN_DOMAIN")
    if not mg_key or not mg_domain:
        logger.warning("Mailgun not configured — skipping UW notification")
        return False
    if not to:
        return False
    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{mg_domain}/messages",
            auth=("api", mg_key),
            data={
                "from": f"ORBIT UW Tracker <noreply@{mg_domain}>",
                "to": to,
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Mailgun send failed: {e}")
        return False


def _format_item_row(item: UWItem, app_url: str, db: Optional[Session] = None) -> str:
    """Return an HTML table row for a UW item in a digest email.

    db is optional — when provided, we look up the customer's account
    premium and render it under the customer name. Without db, the row
    renders without premium (used by callers that don't have access).
    """
    today = date.today()
    if item.due_date:
        days_to = (item.due_date - today).days
        if days_to < 0:
            badge_color = "#dc2626"
            badge_text = f"OVERDUE ({-days_to}d)"
        elif days_to == 0:
            badge_color = "#dc2626"
            badge_text = "DUE TODAY"
        elif days_to <= 3:
            badge_color = "#f59e0b"
            badge_text = f"{days_to}d left"
        else:
            badge_color = "#0ea5e9"
            badge_text = f"{days_to}d left"
        due_str = item.due_date.strftime("%b %d")
    else:
        badge_color = "#64748b"
        badge_text = "no deadline"
        due_str = "—"

    customer = item.customer_name or "(unknown)"
    carrier = item.carrier or "?"
    policy = item.policy_number or "?"

    # Account premium — small line below carrier · policy. Only renders
    # when we have a customer match AND policies in the local DB.
    premium_html = ""
    if db is not None:
        total = _account_total_premium(item, db)
        if total is not None:
            premium_html = (
                f'<div style="color:#0f172a;font-size:11px;margin-top:2px;'
                f'font-weight:600;">Premium: {_fmt_money(total)}</div>'
            )

    return f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:10px 8px;vertical-align:top;">
            <div style="font-weight:600;color:#0f172a;font-size:13px;">{customer}</div>
            <div style="color:#64748b;font-size:11px;margin-top:2px;">{carrier} · #{policy}</div>
            {premium_html}
          </td>
          <td style="padding:10px 8px;vertical-align:top;color:#475569;font-size:12px;line-height:1.4;">
            {(item.title or item.required_action or '')[:80]}
          </td>
          <td style="padding:10px 8px;vertical-align:top;text-align:right;white-space:nowrap;">
            <span style="display:inline-block;background:{badge_color};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;">{badge_text}</span>
            <div style="color:#64748b;font-size:11px;margin-top:4px;">{due_str}</div>
          </td>
          <td style="padding:10px 8px;vertical-align:top;text-align:right;">
            <a href="{app_url}/uw-tracker?item={item.id}" style="color:#0ea5e9;font-size:12px;text-decoration:none;font-weight:600;">View →</a>
          </td>
        </tr>
    """


def _build_digest_html(
    user_name: str,
    items: list[UWItem],
    app_url: str,
    is_admin_master: bool = False,
    db: Optional[Session] = None,
) -> str:
    """Build the daily digest email HTML."""
    if not items:
        title = "All clear today" if not is_admin_master else "All UW items handled"
        body_msg = (
            "You have no open underwriting items today. Enjoy a quiet inbox!"
            if not is_admin_master else
            "Nothing in the UW tracker requires attention today."
        )
        return f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
          <div style="background:#10b981;color:#fff;padding:20px;border-radius:10px 10px 0 0;">
            <div style="font-size:12px;letter-spacing:2px;font-weight:700;">ORBIT · UW TRACKER</div>
            <div style="font-size:18px;font-weight:600;margin-top:6px;">✅ {title}</div>
          </div>
          <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;">
            <p style="color:#475569;font-size:14px;">Hi {user_name.split()[0] if user_name else 'there'},</p>
            <p style="color:#475569;font-size:14px;">{body_msg}</p>
          </div>
        </div>
        """

    today = date.today()
    overdue = [i for i in items if i.due_date and i.due_date < today]
    due_today = [i for i in items if i.due_date == today]
    due_3d = [i for i in items if i.due_date and 0 < (i.due_date - today).days <= 3]
    due_later = [i for i in items if not i.due_date or (i.due_date - today).days > 3]

    sections = []
    for label, group, color in [
        ("🔴 Overdue", overdue, "#dc2626"),
        ("⚠️ Due today", due_today, "#dc2626"),
        ("🟡 Due in next 3 days", due_3d, "#f59e0b"),
        ("🟢 Later", due_later, "#0ea5e9"),
    ]:
        if not group:
            continue
        rows = "".join(_format_item_row(i, app_url, db) for i in group)
        sections.append(f"""
        <div style="margin-top:24px;">
          <div style="font-size:13px;font-weight:700;color:{color};letter-spacing:0.5px;margin-bottom:8px;">
            {label} ({len(group)})
          </div>
          <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
            {rows}
          </table>
        </div>
        """)

    headline = "🔔 Your UW Items Today" if not is_admin_master else "📋 Agency UW Tracker — Daily Summary"
    intro = (
        f"You have <strong>{len(items)}</strong> open UW item{'s' if len(items) > 1 else ''} today."
        if not is_admin_master else
        f"The agency has <strong>{len(items)}</strong> open UW item{'s' if len(items) > 1 else ''} across all assignees."
    )

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;">
      <div style="background:#1e293b;color:#fff;padding:20px;border-radius:10px 10px 0 0;">
        <div style="font-size:12px;letter-spacing:2px;font-weight:700;">ORBIT · UW TRACKER</div>
        <div style="font-size:18px;font-weight:600;margin-top:6px;">{headline}</div>
      </div>
      <div style="background:#f8fafc;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;">
        <p style="color:#475569;font-size:14px;margin-top:0;">Hi {user_name.split()[0] if user_name else 'there'},</p>
        <p style="color:#475569;font-size:14px;">{intro}</p>
        {''.join(sections)}
        <p style="margin:24px 0 0 0;text-align:center;">
          <a href="{app_url}/uw-tracker" style="background:#0ea5e9;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;font-size:14px;">
            Open UW Tracker →
          </a>
        </p>
      </div>
    </div>
    """


def send_daily_digests(db: Session) -> dict:
    """Send daily digest to each assignee and a master summary to admin."""
    app_url = os.environ.get("APP_URL", "https://better-choice-web.onrender.com")
    today = date.today()

    open_items = (
        db.query(UWItem)
        .filter(UWItem.status.notin_(["completed", "dismissed"]))
        .order_by(UWItem.due_date.asc().nullslast())
        .all()
    )

    # Group by assignee
    by_assignee: dict[int, list[UWItem]] = {}
    for item in open_items:
        if item.assigned_to:
            by_assignee.setdefault(item.assigned_to, []).append(item)

    sent_to_assignees = 0
    skipped_no_email = 0
    for user_id, items in by_assignee.items():
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.email:
            skipped_no_email += 1
            continue
        html = _build_digest_html(user.full_name or user.username, items, app_url, db=db)
        ok = _mailgun_send(
            to=user.email,
            subject=f"📋 Your UW items today ({len(items)} open)",
            html=html,
        )
        if ok:
            sent_to_assignees += 1

    # Master admin summary
    admin_email = "evan@betterchoiceins.com"
    admin_html = _build_digest_html(
        user_name="Evan",
        items=open_items,
        app_url=app_url,
        is_admin_master=True,
        db=db,
    )
    pending_count = sum(1 for i in open_items if i.status == "pending_assignment")
    overdue_count = sum(1 for i in open_items if i.due_date and i.due_date < today)
    subj_parts = [f"{len(open_items)} open"]
    if pending_count:
        subj_parts.append(f"{pending_count} unassigned")
    if overdue_count:
        subj_parts.append(f"{overdue_count} overdue")
    admin_ok = _mailgun_send(
        to=admin_email,
        subject=f"📋 UW Daily Summary: {' · '.join(subj_parts)}",
        html=admin_html,
    )

    logger.info(
        f"UW digests sent — assignees: {sent_to_assignees}, "
        f"skipped (no email): {skipped_no_email}, admin: {admin_ok}"
    )
    return {
        "assignees_sent": sent_to_assignees,
        "skipped_no_email": skipped_no_email,
        "admin_sent": admin_ok,
        "total_open_items": len(open_items),
    }


def send_proximity_reminders(db: Session) -> dict:
    """Send 3-day-out, 1-day-out, and overdue reminders.

    Each item has flags (notif_3day_sent, notif_1day_sent, notif_overdue_sent)
    so each reminder fires only once. Edits to due_date reset the flags.

    These run alongside (in addition to) the daily digest. The intent is the
    digest gives a calm overview; the proximity reminders escalate visibility
    on items getting close to deadline.
    """
    app_url = os.environ.get("APP_URL", "https://better-choice-web.onrender.com")
    today = date.today()
    sent_3d = 0
    sent_1d = 0
    sent_overdue = 0

    items = (
        db.query(UWItem)
        .filter(
            UWItem.status.notin_(["completed", "dismissed"]),
            UWItem.assigned_to.isnot(None),
            UWItem.due_date.isnot(None),
        )
        .all()
    )

    for item in items:
        if not item.assignee or not item.assignee.email:
            continue
        days_to = (item.due_date - today).days

        # Pick the right reminder, if any
        if days_to == 3 and not item.notif_3day_sent:
            kind = "3day"
            badge_color = "#f59e0b"
            heading = f"🟡 Reminder — Due in 3 days: {item.customer_name or 'item'}"
        elif days_to == 1 and not item.notif_1day_sent:
            kind = "1day"
            badge_color = "#f97316"
            heading = f"⚠️ Reminder — Due tomorrow: {item.customer_name or 'item'}"
        elif days_to < 0 and not item.notif_overdue_sent:
            kind = "overdue"
            badge_color = "#dc2626"
            heading = f"🔴 OVERDUE — {item.customer_name or 'item'}"
        else:
            continue

        first_name = (item.assignee.full_name or '').split()[0] or 'there'
        due_str = item.due_date.strftime("%b %d, %Y")
        account_total = _account_total_premium(item, db)
        premium_line = ""
        if account_total is not None:
            premium_line = (
                f'<div style="color:#475569;font-size:13px;margin-top:6px;">'
                f'Account premium: <strong style="color:#0f172a;">{_fmt_money(account_total)}</strong>'
                f'</div>'
            )
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
          <div style="background:{badge_color};color:#fff;padding:20px;border-radius:10px 10px 0 0;">
            <div style="font-size:12px;letter-spacing:2px;font-weight:700;">ORBIT · UW TRACKER</div>
            <div style="font-size:18px;font-weight:600;margin-top:6px;">{heading}</div>
          </div>
          <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;">
            <p style="color:#475569;font-size:14px;margin-top:0;">Hi {first_name},</p>
            <p style="color:#475569;font-size:14px;">A UW item assigned to you is approaching its deadline:</p>
            <div style="background:#f1f5f9;border-left:4px solid {badge_color};padding:14px 16px;margin:14px 0;border-radius:4px;">
              <div style="font-weight:700;color:#0f172a;font-size:14px;">{item.title or '(no title)'}</div>
              <div style="color:#475569;font-size:13px;margin-top:4px;">
                {item.customer_name or '(unknown customer)'} &middot; {item.carrier or '?'} &middot; #{item.policy_number or '?'}
              </div>
              <div style="color:{badge_color};font-size:13px;font-weight:600;margin-top:6px;">
                Due: {due_str}
              </div>
              {premium_line}
            </div>
            <p style="color:#475569;font-size:13px;line-height:1.5;">{(item.required_action or '')[:400]}</p>
            <p style="margin:20px 0 0 0;">
              <a href="{app_url}/uw-tracker?item={item.id}" style="background:{badge_color};color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;">
                Open in ORBIT →
              </a>
            </p>
          </div>
        </div>
        """

        if kind == "3day":
            subject = f"🟡 UW reminder — Due in 3 days: {item.customer_name or 'item'}"
        elif kind == "1day":
            subject = f"⚠️ UW reminder — Due TOMORROW: {item.customer_name or 'item'}"
        else:
            subject = f"🔴 UW OVERDUE — {item.customer_name or 'item'}"

        ok = _mailgun_send(item.assignee.email, subject, html)
        if not ok:
            continue

        if kind == "3day":
            item.notif_3day_sent = True
            sent_3d += 1
        elif kind == "1day":
            item.notif_1day_sent = True
            sent_1d += 1
        else:
            item.notif_overdue_sent = True
            sent_overdue += 1

        # Mark item status as overdue for visibility on the kanban
        if days_to < 0 and item.status != "overdue":
            old_status = item.status
            item.status = "overdue"
            db.add(UWActivity(
                uw_item_id=item.id,
                user_name="system",
                action="overdue",
                detail=f"Status auto-changed from {old_status}",
            ))

    db.commit()
    logger.info(
        f"UW proximity reminders sent — 3day: {sent_3d}, 1day: {sent_1d}, overdue: {sent_overdue}"
    )
    return {"3day_sent": sent_3d, "1day_sent": sent_1d, "overdue_sent": sent_overdue}
