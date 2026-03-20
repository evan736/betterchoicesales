"""Non-renewal escalation engine.

Runs on a schedule (or triggered by daily NatGen email) to check all open
non-renewal tasks and send escalating notifications as deadlines approach.

Cadence:
  60 days → Gentle producer-only heads-up
  45 days → Producer + service@ reminder
  30 days → Producer + service@ + insured gets non-renewal email
  14 days → Producer + service@ + insured reminder
   7 days → Final warning — all parties
   3 days → Last chance — Evan CC'd directly

When task is completed → notifications_disabled = True, all future sends stop.
When NatGen sends duplicate non-renewal → deduplicates by policy_number + task.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.task import Task, TaskStatus, TaskPriority, NonRenewalNotification

logger = logging.getLogger(__name__)

# ── Escalation tiers ──────────────────────────────────────────────────

TIERS = [
    {
        "name": "60d",
        "days_max": 60,
        "days_min": 46,
        "priority": TaskPriority.MEDIUM,
        "subject_prefix": "📋",
        "tone": "heads_up",
        "notify_producer": False,
        "notify_service": True,
        "notify_customer": False,
        "notify_evan": False,
        "banner_color": "#10b981",  # green
        "banner_label": "HEADS UP",
        "body_intro": "A non-renewal notice has been received. There's plenty of time to find a replacement — just wanted to put this on your radar.",
    },
    {
        "name": "45d",
        "days_max": 45,
        "days_min": 31,
        "priority": TaskPriority.MEDIUM,
        "subject_prefix": "📋",
        "tone": "reminder",
        "notify_producer": False,
        "notify_service": True,
        "notify_customer": True,
        "notify_evan": False,
        "banner_color": "#eab308",  # yellow
        "banner_label": "REMINDER",
        "body_intro": "This non-renewal is approaching the 30-day mark. Please start shopping replacement options if you haven't already.",
    },
    {
        "name": "30d",
        "days_max": 30,
        "days_min": 15,
        "priority": TaskPriority.HIGH,
        "subject_prefix": "⚠️",
        "tone": "urgent",
        "notify_producer": False,
        "notify_service": True,
        "notify_customer": True,
        "notify_evan": False,
        "banner_color": "#f97316",  # orange
        "banner_label": "ACTION NEEDED",
        "body_intro": "Coverage ends in about 30 days. Replacement options should be quoted and presented to the customer soon.",
    },
    {
        "name": "14d",
        "days_max": 14,
        "days_min": 8,
        "priority": TaskPriority.HIGH,
        "subject_prefix": "🔴",
        "tone": "critical",
        "notify_producer": False,
        "notify_service": True,
        "notify_customer": True,
        "notify_evan": False,
        "banner_color": "#ef4444",  # red
        "banner_label": "CRITICAL",
        "body_intro": "Only 2 weeks remain. If replacement coverage hasn't been bound yet, this needs immediate attention.",
    },
    {
        "name": "7d",
        "days_max": 7,
        "days_min": 4,
        "priority": TaskPriority.URGENT,
        "subject_prefix": "🔴🔴",
        "tone": "final_warning",
        "notify_producer": False,
        "notify_service": True,
        "notify_customer": True,
        "notify_evan": False,
        "banner_color": "#dc2626",  # dark red
        "banner_label": "FINAL WARNING",
        "body_intro": "Coverage expires in days. This customer will have a gap in coverage if replacement is not bound immediately.",
    },
    {
        "name": "3d",
        "days_max": 3,
        "days_min": -7,  # Keep alerting up to 7 days PAST expiry
        "priority": TaskPriority.URGENT,
        "subject_prefix": "🚨",
        "tone": "last_chance",
        "notify_producer": False,
        "notify_service": True,
        "notify_customer": True,
        "notify_evan": True,
        "banner_color": "#991b1b",  # deep red
        "banner_label": "LAST CHANCE",
        "body_intro": "Coverage is about to expire or has already expired. Bind replacement coverage TODAY to avoid a lapse.",
    },
]

TIER_ORDER = [t["name"] for t in TIERS]  # ["60d", "45d", "30d", "14d", "7d", "3d"]


def get_current_tier(days_remaining: int) -> Optional[dict]:
    """Determine which notification tier applies for the given days remaining."""
    for tier in TIERS:
        if tier["days_min"] <= days_remaining <= tier["days_max"]:
            return tier
    return None


def should_escalate(task: Task, days_remaining: int) -> Optional[dict]:
    """Check if a task needs escalation to a new tier.
    
    Returns the tier dict if escalation is needed, None otherwise.
    """
    if task.notifications_disabled:
        return None
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        return None

    current_tier = get_current_tier(days_remaining)
    if not current_tier:
        return None  # Outside all tiers (>60 days or <-7 days)

    last = task.last_notification_tier
    if not last:
        return current_tier  # First notification ever

    # Only escalate if we haven't sent this tier yet
    if last == current_tier["name"]:
        return None  # Already sent this tier

    # Check that the new tier is further along (closer to deadline)
    last_idx = TIER_ORDER.index(last) if last in TIER_ORDER else -1
    curr_idx = TIER_ORDER.index(current_tier["name"])
    if curr_idx > last_idx:
        return current_tier  # New tier, escalate

    return None


def run_escalation_check(db: Session) -> dict:
    """Check all open non-renewal tasks and send escalating notifications.
    
    Should be called daily (from NatGen email handler or a cron endpoint).
    Returns summary of actions taken.
    """
    open_tasks = db.query(Task).filter(
        Task.task_type == "non_renewal",
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        Task.notifications_disabled == False,
        Task.due_date.isnot(None),
    ).all()

    results = {"checked": len(open_tasks), "escalated": 0, "skipped": 0, "reshops_created": 0, "details": []}

    for task in open_tasks:
        days = (task.due_date.replace(tzinfo=None) - datetime.utcnow()).days

        # Auto-create reshop if one doesn't exist for this policy
        try:
            from app.models.reshop import Reshop
            from app.models.customer import Customer, CustomerPolicy
            from app.api.reshop import _get_next_round_robin_agent, ACTIVE_STAGES

            existing_reshop = db.query(Reshop).filter(
                Reshop.policy_number == task.policy_number,
                Reshop.stage.in_(ACTIVE_STAGES),
            ).first()

            if not existing_reshop and task.policy_number:
                # Skip commercial
                lob = (task.line_of_business or "").lower()
                COMMERCIAL_KW = ["commercial", "business", "general liability", "bop", "workers comp"]
                if not any(kw in lob for kw in COMMERCIAL_KW):
                    # Find customer
                    customer = None
                    current_premium = None
                    policy = db.query(CustomerPolicy).filter(
                        CustomerPolicy.policy_number == task.policy_number
                    ).first()
                    if policy:
                        customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()
                        current_premium = policy.premium

                    carrier_name = (task.carrier or "").replace("_", " ").title()
                    cust_name = task.customer_name or (customer.full_name if customer else "Unknown")
                    auto_agent = _get_next_round_robin_agent(
                        db, customer_id=customer.id if customer else None,
                        customer_name=cust_name
                    )

                    reshop = Reshop(
                        customer_id=customer.id if customer else None,
                        customer_name=cust_name,
                        customer_phone=customer.phone if customer else None,
                        customer_email=customer.email if customer else None,
                        policy_number=task.policy_number,
                        carrier=carrier_name,
                        current_premium=current_premium,
                        expiration_date=task.due_date,
                        priority="urgent",
                        source="non_renewal",
                        source_detail="Non-renewal escalation: " + carrier_name + " — " + str(days) + " days remaining",
                        stage="new_request",
                        assigned_to=auto_agent,
                    )
                    db.add(reshop)
                    db.flush()
                    results["reshops_created"] += 1
                    logger.info("Auto-created reshop from non-renewal escalation: %s / %s", cust_name, task.policy_number)
        except Exception as e:
            logger.warning("Failed to create reshop from escalation: %s", e)

        tier = should_escalate(task, days)
        if not tier:
            results["skipped"] += 1
            continue

        # Send notifications for this tier
        detail = _send_tier_notifications(db, task, tier, days)
        results["escalated"] += 1
        results["details"].append(detail)

        # Update task
        task.last_notification_tier = tier["name"]
        task.priority = tier["priority"]
        if tier["notify_customer"]:
            task.customer_notified = True
        task.updated_at = datetime.utcnow()
        db.commit()

    logger.info(
        "Escalation check: %d tasks, %d escalated, %d skipped",
        results["checked"], results["escalated"], results["skipped"],
    )
    return results


def _send_tier_notifications(db: Session, task: Task, tier: dict, days_remaining: int) -> dict:
    """Send all notifications for a given escalation tier."""
    import requests as req_lib
    from app.services.uw_requirement_email import send_non_renewal_email
    from app.models.user import User

    detail = {
        "task_id": task.id,
        "policy": task.policy_number,
        "customer": task.customer_name,
        "tier": tier["name"],
        "days_remaining": days_remaining,
        "actions": [],
    }

    # Look up producer
    producer_email = None
    producer_name = None
    if task.assigned_to_id:
        producer = db.query(User).filter(User.id == task.assigned_to_id).first()
        if producer:
            producer_email = producer.email
            producer_name = producer.full_name or producer.username

    # Also try to find producer from the task description
    if not producer_email and task.description:
        import re
        m = re.search(r"Producer:\s*(.+)", task.description)
        if m:
            producer_name = m.group(1).strip()

    # Look up customer email from Sales
    customer_email = _get_customer_email(db, task.policy_number, task.customer_name)

    # Build the internal escalation email
    _send_escalation_email(
        task=task,
        tier=tier,
        days_remaining=days_remaining,
        producer_email=producer_email,
        producer_name=producer_name,
        customer_email=customer_email,
    )

    noti_record = NonRenewalNotification(
        task_id=task.id,
        policy_number=task.policy_number or "",
        tier=tier["name"],
        days_remaining=days_remaining,
        producer_emailed=tier["notify_producer"] and bool(producer_email),
        service_emailed=tier["notify_service"],
        customer_emailed=False,
        evan_emailed=tier["notify_evan"],
    )

    if tier["notify_producer"] and producer_email:
        detail["actions"].append(f"producer_email:{producer_email}")
    if tier["notify_service"]:
        detail["actions"].append("service@betterchoiceins.com")
    if tier["notify_evan"]:
        detail["actions"].append("evan@betterchoiceins.com (direct)")

    # Send customer-facing non-renewal email if this tier includes it
    if tier["notify_customer"] and customer_email:
        try:
            result = send_non_renewal_email(
                to_email=customer_email,
                client_name=task.customer_name or "Valued Customer",
                policy_number=task.policy_number or "",
                carrier=task.carrier or "national_general",
                effective_date=task.due_date.strftime("%m/%d/%Y") if task.due_date else "",
                producer_name=producer_name,
                producer_email=producer_email,
            )
            if result.get("success"):
                noti_record.customer_emailed = True
                detail["actions"].append(f"customer_email:{customer_email}")
            else:
                detail["actions"].append(f"customer_email_failed:{result.get('error')}")
        except Exception as e:
            logger.error("Customer non-renewal email failed: %s", e)
            detail["actions"].append(f"customer_email_error:{e}")

    db.add(noti_record)
    db.commit()

    return detail


def _send_escalation_email(
    task: Task,
    tier: dict,
    days_remaining: int,
    producer_email: Optional[str] = None,
    producer_name: Optional[str] = None,
    customer_email: Optional[str] = None,
):
    """Send the internal escalation email to producer/service/evan."""
    import requests as req_lib

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    days_word = f"{days_remaining} days" if days_remaining > 0 else f"{abs(days_remaining)} days past expiry"
    premium_line = ""
    if task.description:
        import re
        m = re.search(r"Current premium:\s*(\S+)", task.description)
        if m:
            premium_line = f'<tr><td style="padding:6px 0;color:#64748b;">Premium</td><td style="font-weight:600;">{m.group(1)}</td></tr>'

    banner = tier["banner_color"]
    label = tier["banner_label"]
    intro = tier["body_intro"]
    prefix = tier["subject_prefix"]

    subject = f'{prefix} Non-Renewal {label}: {task.customer_name} — {days_word}'

    # Progress bar showing urgency
    progress_pct = max(0, min(100, int((60 - days_remaining) / 60 * 100)))
    progress_color = banner

    html = f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
<div style="background:{banner};border-radius:16px 16px 0 0;padding:24px 32px;text-align:center;">
<p style="margin:0 0 4px;font-size:12px;color:rgba(255,255,255,0.8);letter-spacing:1.5px;font-weight:700;">{label}</p>
<h1 style="margin:0;font-size:20px;color:#fff;">Non-Renewal: {task.customer_name}</h1>
<p style="margin:8px 0 0;font-size:14px;color:rgba(255,255,255,0.9);">{days_word} until coverage ends</p>
</div>
<div style="background:#fff;padding:28px 32px;border-radius:0 0 16px 16px;">

<!-- Urgency progress bar -->
<div style="margin:0 0 20px;">
<div style="display:flex;justify-content:space-between;font-size:11px;color:#64748b;margin-bottom:4px;">
<span>60 days</span><span>Today</span><span>Expiry</span>
</div>
<div style="height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;">
<div style="height:100%;width:{progress_pct}%;background:{progress_color};border-radius:4px;transition:width 0.3s;"></div>
</div>
</div>

<p style="font-size:14px;color:#475569;line-height:1.7;margin:0 0 20px;">{intro}</p>

<div style="padding:16px;background:#f8fafc;border-radius:10px;border:1px solid #e2e8f0;margin:0 0 20px;">
<table style="width:100%;font-size:14px;color:#334155;" cellpadding="0" cellspacing="0">
<tr><td style="padding:6px 0;color:#64748b;width:140px;">Customer</td><td style="font-weight:700;">{task.customer_name}</td></tr>
<tr><td style="padding:6px 0;color:#64748b;">Policy</td><td style="font-weight:600;">{task.policy_number}</td></tr>
<tr><td style="padding:6px 0;color:#64748b;">Carrier</td><td>{task.carrier or "National General"}</td></tr>
<tr><td style="padding:6px 0;color:#64748b;">Coverage Ends</td><td style="font-weight:700;color:{banner};">{task.due_date.strftime("%m/%d/%Y") if task.due_date else "Unknown"}</td></tr>
{premium_line}
<tr><td style="padding:6px 0;color:#64748b;">Producer</td><td>{producer_name or "Unassigned"}</td></tr>
<tr><td style="padding:6px 0;color:#64748b;">Customer Email</td><td>{customer_email or "Not on file"}</td></tr>
</table>
</div>

{"<div style='padding:12px 16px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;margin:0 0 16px;'><p style='margin:0;font-size:13px;color:#166534;'>✅ Customer has been notified via email.</p></div>" if tier["notify_customer"] and customer_email else ""}

<div style="padding:12px 16px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;">
<p style="margin:0;font-size:13px;color:#1e40af;">
<strong>To stop these notifications:</strong> Mark this task as complete in the dashboard when replacement coverage is bound.</p>
</div>

</div></div></body></html>'''

    # Build recipient list
    to_list = []
    if tier["notify_producer"] and producer_email:
        to_list.append(producer_email)
    if tier["notify_service"]:
        if "service@betterchoiceins.com" not in to_list:
            to_list.append("service@betterchoiceins.com")
    if tier["notify_evan"]:
        if "evan@betterchoiceins.com" not in to_list:
            to_list.append("evan@betterchoiceins.com")

    if not to_list:
        to_list = ["service@betterchoiceins.com"]

    try:
        resp = req_lib.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance <service@{settings.MAILGUN_DOMAIN}>",
                "to": to_list,
                "subject": subject,
                "html": html,
        "o:tracking-clicks": "yes",
        "o:tracking-opens": "yes",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info("Escalation email [%s] sent for %s/%s to %s",
                        tier["name"], task.customer_name, task.policy_number, to_list)
        else:
            logger.error("Escalation email failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("Escalation email error: %s", e)


def _get_customer_email(db: Session, policy_number: str, customer_name: str) -> Optional[str]:
    """Look up customer email from the sales table."""
    from app.models.sale import Sale

    if not policy_number:
        return None

    clean = policy_number.replace(" ", "").strip()
    sale = db.query(Sale).filter(Sale.policy_number.ilike(f"%{clean}%")).first()

    if not sale and len(clean) > 2:
        base = clean[:-2] if clean[-2:] in ("00", "01") else clean
        sale = db.query(Sale).filter(Sale.policy_number.ilike(f"%{base}%")).first()

    if not sale and customer_name:
        parts = customer_name.strip().split()
        if len(parts) >= 2:
            sale = db.query(Sale).filter(
                Sale.client_name.ilike(f"%{parts[0]}%"),
                Sale.client_name.ilike(f"%{parts[-1]}%"),
            ).first()

    return sale.client_email if sale else None
