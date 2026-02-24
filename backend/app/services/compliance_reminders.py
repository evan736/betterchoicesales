"""Compliance Reminder Engine — deadline-proximity-based follow-ups.

Sends reminders for open compliance tasks (inspections, UW requirements, non-pay)
based on how close we are to the deadline, not from when the first email was sent.

Reminder Schedule (days until deadline):
  >90 days  → reminders at: 60d, 30d, 14d, 7d, 3d, 1d
  30-90 days → reminders at: 14d, 7d, 3d, 1d
  14-30 days → reminders at: 7d, 3d, 1d
  7-14 days  → reminders at: 3d, 1d
  <7 days    → reminders at: 3d, 1d
  Overdue    → one final "overdue" notice, then stop

The first notification is always sent immediately when the task is created.
Once a task is completed or deadline passes + overdue sent, reminders stop.

Called by: daily cron / manual trigger / NatGen daily poll
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.task import Task, TaskStatus
from app.models.compliance_reminder import ComplianceReminder

logger = logging.getLogger(__name__)

# ── Reminder milestones (days before deadline) ────────────────────────

REMINDER_MILESTONES = [60, 30, 14, 7, 3, 1]

TIER_CONFIG = {
    "60d": {
        "subject_prefix": "📋 Reminder",
        "urgency": "low",
        "banner_color": "#10b981",  # green
        "banner_label": "FRIENDLY REMINDER",
        "intro": "Just a friendly reminder — there's still plenty of time, but we wanted to keep this on your radar.",
    },
    "30d": {
        "subject_prefix": "📋 Reminder",
        "urgency": "medium",
        "banner_color": "#f59e0b",  # amber
        "banner_label": "REMINDER — 30 DAYS LEFT",
        "intro": "This is a reminder that the deadline is approaching in about 30 days. Please take action soon to avoid any issues with your policy.",
    },
    "14d": {
        "subject_prefix": "⚠️ Action Needed",
        "urgency": "medium",
        "banner_color": "#f59e0b",  # amber
        "banner_label": "ACTION NEEDED — 2 WEEKS LEFT",
        "intro": "The deadline is now just 2 weeks away. Please take care of this as soon as possible to keep your coverage active.",
    },
    "7d": {
        "subject_prefix": "⚠️ Urgent",
        "urgency": "high",
        "banner_color": "#ef4444",  # red
        "banner_label": "URGENT — 1 WEEK LEFT",
        "intro": "The deadline is only 7 days away. Immediate action is needed to prevent any disruption to your insurance coverage.",
    },
    "3d": {
        "subject_prefix": "🚨 Critical",
        "urgency": "high",
        "banner_color": "#dc2626",  # dark red
        "banner_label": "CRITICAL — 3 DAYS LEFT",
        "intro": "This is critical — only 3 days remain before the deadline. Please act immediately to avoid losing your coverage.",
    },
    "1d": {
        "subject_prefix": "🚨 Final Notice",
        "urgency": "critical",
        "banner_color": "#991b1b",  # darker red
        "banner_label": "FINAL NOTICE — TOMORROW",
        "intro": "This is your final reminder — the deadline is tomorrow. If you haven't already done so, please take action immediately.",
    },
    "overdue": {
        "subject_prefix": "❌ Overdue",
        "urgency": "critical",
        "banner_color": "#7f1d1d",  # deep red
        "banner_label": "OVERDUE",
        "intro": "The deadline for this requirement has passed. Please contact us immediately at (773) 985-0711 to discuss your options and avoid further action on your policy.",
    },
}


def _get_reminder_tier(days_remaining: int) -> Optional[str]:
    """Determine which reminder tier to send based on days until deadline."""
    if days_remaining < 0:
        return "overdue"
    for milestone in REMINDER_MILESTONES:
        if days_remaining <= milestone:
            tier = f"{milestone}d"
            # Only trigger if we're within the window (at or below the milestone)
            return tier
    return None


def _should_send_reminder(db: Session, task: Task, tier: str) -> bool:
    """Check if this reminder tier has already been sent for this task."""
    existing = db.query(ComplianceReminder).filter(
        ComplianceReminder.task_id == task.id,
        ComplianceReminder.reminder_tier == tier,
    ).first()
    return existing is None


def _get_task_type_label(task_type: str) -> str:
    """Human-readable label for task type."""
    labels = {
        "inspection": "Inspection Follow-Up",
        "uw_requirement": "Underwriting Requirement",
        "non_pay": "Payment Required",
    }
    return labels.get(task_type, "Compliance Item")


def _build_reminder_email(
    task: Task,
    tier: str,
    days_remaining: int,
) -> tuple[str, str]:
    """Build a reminder email based on task type and urgency tier."""
    config = TIER_CONFIG.get(tier, TIER_CONFIG["7d"])
    task_label = _get_task_type_label(task.task_type)

    carrier = task.carrier or "Your Insurance Carrier"
    carrier_display = carrier.replace("_", " ").title()
    policy = task.policy_number or "your policy"
    customer_name = task.customer_name or "Valued Customer"
    first_name = customer_name.split()[0]

    # Deadline display
    if task.due_date:
        deadline_str = task.due_date.strftime("%m/%d/%Y")
    else:
        deadline_str = "as soon as possible"

    subject = f"{config['subject_prefix']}: {task_label} — {carrier_display} Policy {policy}"

    # Build action text from task description
    action_text = ""
    if task.description:
        for line in task.description.split("\n"):
            if line.startswith("Action Required:"):
                action_text = line.replace("Action Required:", "").strip()
                break
    if not action_text:
        action_text = task.title

    # Days remaining display
    if days_remaining < 0:
        time_display = f"<strong style='color:#dc2626;'>OVERDUE by {abs(days_remaining)} day{'s' if abs(days_remaining) != 1 else ''}</strong>"
    elif days_remaining == 0:
        time_display = "<strong style='color:#dc2626;'>DUE TODAY</strong>"
    elif days_remaining == 1:
        time_display = "<strong style='color:#dc2626;'>Due tomorrow</strong>"
    else:
        time_display = f"<strong>{days_remaining} days remaining</strong>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f1f5f9; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:600px; margin:0 auto; padding:20px;">

  <!-- Urgency Banner -->
  <div style="background:{config['banner_color']}; border-radius:16px 16px 0 0; padding:24px 32px; text-align:center;">
    <p style="margin:0 0 4px; font-size:12px; color:rgba(255,255,255,0.85); letter-spacing:1.5px; font-weight:600;">{config['banner_label']}</p>
    <h1 style="margin:0; font-size:20px; color:#ffffff; font-weight:700;">{task_label}</h1>
    <p style="margin:6px 0 0; font-size:14px; color:rgba(255,255,255,0.9);">{time_display}</p>
  </div>

  <!-- Body Card -->
  <div style="background:#ffffff; padding:32px; border-radius:0 0 16px 16px; box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    <p style="font-size:16px; color:#1e293b; margin:0 0 16px;">Hi {first_name},</p>
    <p style="font-size:15px; color:#334155; margin:0 0 20px; line-height:1.7;">{config['intro']}</p>

    <!-- Details Box -->
    <div style="margin:24px 0; padding:20px; background:#fef2f2; border-radius:12px; border:1px solid #fecaca; border-left:4px solid {config['banner_color']};">
      <table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">
        <tr><td style="padding:6px 0; color:#64748b; width:140px;">Policy Number</td><td style="padding:6px 0; font-weight:700; color:#1e293b;">{policy}</td></tr>
        <tr><td style="padding:6px 0; color:#64748b;">Carrier</td><td style="padding:6px 0; font-weight:600;">{carrier_display}</td></tr>
        <tr><td style="padding:6px 0; color:#64748b;">Deadline</td><td style="padding:6px 0; font-weight:700; color:#dc2626;">{deadline_str}</td></tr>
      </table>
    </div>

    <!-- What's Needed -->
    <div style="margin:24px 0; padding:16px; background:#f0f9ff; border-radius:12px; border:1px solid #bae6fd;">
      <p style="margin:0 0 8px; font-size:13px; font-weight:700; color:#0369a1;">WHAT'S NEEDED</p>
      <p style="margin:0; font-size:14px; color:#334155; line-height:1.6;">{action_text}</p>
    </div>

    <!-- CTA -->
    <p style="font-size:14px; color:#334155; margin:20px 0 16px; line-height:1.6;">
      If you've already taken care of this, please let us know by replying to this email or calling us so we can close this out.
    </p>

    <a href="mailto:service@betterchoiceins.com" style="display:block; padding:14px 24px; background:#1e40af; color:#ffffff; text-decoration:none; border-radius:10px; font-weight:700; font-size:15px; text-align:center; margin:0 0 12px;">
      📧 Reply to Better Choice Insurance
    </a>
    <a href="tel:+17739850711" style="display:block; padding:14px 24px; background:#475569; color:#ffffff; text-decoration:none; border-radius:10px; font-weight:700; font-size:15px; text-align:center;">
      📞 Call Us: (773) 985-0711
    </a>

    <!-- Footer -->
    <div style="margin-top:32px; padding-top:20px; border-top:1px solid #e2e8f0; text-align:center;">
      <p style="font-size:12px; color:#94a3b8; margin:0;">Better Choice Insurance</p>
      <p style="font-size:11px; color:#cbd5e1; margin:4px 0 0;">This is an automated reminder about your policy. If you have questions, please contact us.</p>
    </div>
  </div>
</div></body></html>"""

    return subject, html


def _send_reminder_email(
    to_email: str,
    subject: str,
    html: str,
) -> dict:
    """Send reminder email via Mailgun."""
    import requests as http_requests

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance <service@{settings.MAILGUN_DOMAIN}>",
                "to": [to_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
                "bcc": ["evan@betterchoiceins.com"],
            },
        )
        if resp.status_code == 200:
            return {"success": True, "message_id": resp.json().get("id")}
        else:
            return {"success": False, "error": f"Mailgun {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_compliance_reminders(db: Session, dry_run: bool = False) -> dict:
    """Check all open compliance tasks and send reminders based on deadline proximity.

    Returns summary of actions taken.
    """
    now = datetime.utcnow()

    # Eligible task types for follow-up reminders
    eligible_types = ["inspection", "uw_requirement"]

    tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        Task.task_type.in_(eligible_types),
        Task.due_date.isnot(None),
        Task.notifications_disabled != True,
    ).all()

    results = {
        "checked": len(tasks),
        "reminders_sent": 0,
        "skipped": 0,
        "details": [],
    }

    for task in tasks:
        # Calculate days remaining
        days_remaining = (task.due_date.replace(tzinfo=None) - now).days

        # Determine appropriate tier
        tier = _get_reminder_tier(days_remaining)
        if not tier:
            results["skipped"] += 1
            continue

        # Check if this tier was already sent
        if not _should_send_reminder(db, task, tier):
            results["skipped"] += 1
            continue

        # Need a customer email to send
        customer_email = task.notes  # May contain email... let me check
        # Actually, we need to look up customer email from the task
        # Tasks don't always store customer_email directly, so look it up
        from app.models.customer import Customer, CustomerPolicy
        customer = None
        if task.policy_number:
            policy = db.query(CustomerPolicy).filter(
                CustomerPolicy.policy_number == task.policy_number
            ).first()
            if policy:
                customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()

        if not customer or not customer.email:
            results["details"].append({
                "task_id": task.id,
                "policy": task.policy_number,
                "tier": tier,
                "status": "skipped_no_email",
            })
            results["skipped"] += 1
            continue

        # Build and send
        subject, html = _build_reminder_email(task, tier, days_remaining)

        detail = {
            "task_id": task.id,
            "policy": task.policy_number,
            "customer": customer.full_name,
            "email": customer.email,
            "tier": tier,
            "days_remaining": days_remaining,
            "task_type": task.task_type,
        }

        if dry_run:
            detail["status"] = "would_send"
            results["details"].append(detail)
            results["reminders_sent"] += 1
            continue

        email_result = _send_reminder_email(customer.email, subject, html)

        # Log the reminder
        reminder = ComplianceReminder(
            task_id=task.id,
            policy_number=task.policy_number or "",
            task_type=task.task_type or "",
            reminder_tier=tier,
            days_remaining=days_remaining,
            customer_emailed=email_result.get("success", False),
            customer_email=customer.email,
            customer_name=customer.full_name,
            carrier=task.carrier,
            email_subject=subject,
            email_status="sent" if email_result.get("success") else "failed",
        )
        db.add(reminder)

        # Update task tracking
        task.last_notification_tier = tier
        if tier == "overdue":
            task.notifications_disabled = True

        detail["status"] = "sent" if email_result.get("success") else "failed"
        detail["error"] = email_result.get("error")
        results["details"].append(detail)
        results["reminders_sent"] += 1

    if not dry_run:
        db.commit()

    logger.info(
        "Compliance reminders: checked=%d, sent=%d, skipped=%d",
        results["checked"], results["reminders_sent"], results["skipped"],
    )
    return results
