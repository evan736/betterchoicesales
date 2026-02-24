"""Task management API."""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.task import Task, TaskStatus, TaskPriority

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    status: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    task_type: Optional[str] = Query(None),
    limit: int = Query(50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tasks, optionally filtered. Admins see all, producers see only their tasks."""
    q = db.query(Task)

    # Visibility: non-admin users only see tasks assigned to them
    if current_user.role not in ("admin", "ADMIN"):
        q = q.filter(Task.assigned_to_id == current_user.id)

    if status:
        q = q.filter(Task.status == status)
    else:
        # Default: show open + in_progress
        q = q.filter(Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]))

    if assigned_to:
        q = q.filter(Task.assigned_to_id == assigned_to)

    if task_type:
        q = q.filter(Task.task_type == task_type)

    tasks = q.order_by(
        Task.priority.desc(),
        Task.due_date.asc().nullslast(),
        Task.created_at.desc(),
    ).limit(limit).all()

    return [_task_to_dict(t, db) for t in tasks]


@router.get("/counts")
def task_counts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get task counts by status for badge display."""
    base_filter = [Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS])]
    # Non-admin users only count their own tasks
    if current_user.role not in ("admin", "ADMIN"):
        base_filter.append(Task.assigned_to_id == current_user.id)

    open_count = db.query(func.count(Task.id)).filter(
        *base_filter
    ).scalar() or 0

    urgent_count = db.query(func.count(Task.id)).filter(
        *base_filter,
        Task.priority == TaskPriority.URGENT,
    ).scalar() or 0

    my_count = db.query(func.count(Task.id)).filter(
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        Task.assigned_to_id == current_user.id,
    ).scalar() or 0

    return {"open": open_count, "urgent": urgent_count, "my_tasks": my_count}


@router.patch("/{task_id}")
def update_task(
    task_id: int,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update task status, assignment, notes, etc."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return {"error": "Task not found"}

    if "status" in payload:
        task.status = payload["status"]
        if payload["status"] == "completed":
            task.completed_at = datetime.utcnow()
            task.notifications_disabled = True  # Stop all future escalation emails
        elif payload["status"] == "cancelled":
            task.notifications_disabled = True

    if "assigned_to_id" in payload:
        task.assigned_to_id = payload["assigned_to_id"]

    if "notes" in payload:
        task.notes = payload["notes"]

    if "priority" in payload:
        task.priority = payload["priority"]

    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return _task_to_dict(task, db)


def _task_to_dict(task: Task, db: Session) -> dict:
    assignee_name = None
    if task.assigned_to_id:
        user = db.query(User).filter(User.id == task.assigned_to_id).first()
        if user:
            assignee_name = user.full_name or user.username

    # Look up NowCerts insured ID for direct link
    nowcerts_url = None
    if task.policy_number:
        from app.models.customer import Customer, CustomerPolicy
        clean = task.policy_number.replace(" ", "").strip()
        nc_pol = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number.ilike(f"%{clean}%")
        ).first()
        if nc_pol:
            cust = db.query(Customer).filter(Customer.id == nc_pol.customer_id).first()
            if cust and cust.nowcerts_insured_id:
                nowcerts_url = f"https://www6.nowcerts.com/AMSINS/Insureds/Details/{cust.nowcerts_insured_id}/Information"

    # Look up customer email if not stored on task
    customer_email = task.customer_email
    if not customer_email and task.policy_number:
        from app.models.customer import Customer as Cust2, CustomerPolicy as CP2
        cp = db.query(CP2).filter(CP2.policy_number == task.policy_number).first()
        if cp:
            c = db.query(Cust2).filter(Cust2.id == cp.customer_id).first()
            if c:
                customer_email = c.email

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "priority": task.priority.value if task.priority else "medium",
        "status": task.status.value if task.status else "open",
        "assigned_to_id": task.assigned_to_id,
        "assigned_to_name": assignee_name,
        "created_by": task.created_by,
        "customer_name": task.customer_name,
        "policy_number": task.policy_number,
        "carrier": task.carrier,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "source": task.source,
        "notes": task.notes,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "customer_email": customer_email,
        "last_sent_at": task.last_sent_at.isoformat() if task.last_sent_at else None,
        "send_count": task.send_count or 0,
        "last_send_method": task.last_send_method,
        "nowcerts_url": nowcerts_url,
    }


def create_non_renewal_task(
    db: Session,
    customer_name: str,
    policy_number: str,
    carrier: str,
    effective_date: str,
    premium: Optional[float] = None,
    producer_name: str = "",
    assigned_to_id: Optional[int] = None,
) -> Task:
    """Create a task for non-renewal remarketing. Deduplicates by policy number."""
    from dateutil import parser as dateparser

    # Check for existing open task for this policy
    existing = db.query(Task).filter(
        Task.policy_number == policy_number,
        Task.task_type == "non_renewal",
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
    ).first()

    if existing:
        logger.info("Non-renewal task already exists for %s (task #%d)", policy_number, existing.id)
        return existing  # Return existing — escalation engine handles notifications

    due = None
    try:
        due = dateparser.parse(effective_date)
    except Exception:
        pass

    premium_str = f"${premium:,.2f}" if premium else "N/A"

    task = Task(
        title=f"Non-Renewal: Remarket {customer_name}",
        description=(
            f"Policy {policy_number} with {carrier} is not being renewed.\n"
            f"Coverage ends: {effective_date}\n"
            f"Current premium: {premium_str}\n"
            f"Producer: {producer_name}\n\n"
            f"Action: Shop replacement coverage before {effective_date}."
        ),
        task_type="non_renewal",
        priority=TaskPriority.URGENT if _is_within_days(effective_date, 30) else TaskPriority.HIGH,
        status=TaskStatus.OPEN,
        assigned_to_id=assigned_to_id,
        created_by="system",
        customer_name=customer_name,
        policy_number=policy_number,
        carrier=carrier,
        due_date=due,
        source="natgen_activity",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info("Created non-renewal task #%d for %s/%s", task.id, customer_name, policy_number)
    return task


def _is_within_days(date_str: str, days: int) -> bool:
    """Check if a date string is within N days from now."""
    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(date_str)
        return (dt - datetime.now()).days <= days
    except Exception:
        return False


@router.post("/check-escalations")
def check_escalations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run the non-renewal escalation check manually or via cron."""
    from app.services.nonrenewal_escalation import run_escalation_check
    result = run_escalation_check(db)
    return result


@router.get("/{task_id}/notifications")
def get_task_notifications(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get notification history for a task."""
    from app.models.task import NonRenewalNotification
    notis = db.query(NonRenewalNotification).filter(
        NonRenewalNotification.task_id == task_id,
    ).order_by(NonRenewalNotification.sent_at.desc()).all()

    return [
        {
            "id": n.id,
            "tier": n.tier,
            "days_remaining": n.days_remaining,
            "producer_emailed": n.producer_emailed,
            "service_emailed": n.service_emailed,
            "customer_emailed": n.customer_emailed,
            "evan_emailed": n.evan_emailed,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        }
        for n in notis
    ]


def create_uw_requirement_task(
    db: Session,
    customer_name: str,
    policy_number: str,
    carrier: str,
    requirement_type: str,
    due_date: str = None,
    producer_name: str = None,
    assigned_to_id: int = None,
) -> Task:
    """Create or return existing UW requirement task for a policy."""
    from dateutil import parser as dateparser

    # Dedup by policy_number + task_type
    existing = db.query(Task).filter(
        Task.policy_number == policy_number,
        Task.task_type == "uw_requirement",
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
    ).first()

    if existing:
        logger.info("UW requirement task already exists for %s (task #%d)", policy_number, existing.id)
        return existing

    due = None
    try:
        due = dateparser.parse(due_date)
    except Exception:
        pass

    req_labels = {
        "proof_of_continuous_insurance": "Proof of Continuous Insurance",
        "nopop": "No Proof of Prior Insurance",
        "change_prior_bi": "Change Prior BI Limits",
        "proof_of_prior_bi": "Proof of Prior BI",
        "vehicle_photos": "Vehicle Photos",
        "proof_of_mileage": "Proof of Annual Mileage",
        "proof_of_residence": "Proof of Residence Insurance",
        "proof_of_residence_insurance": "Proof of Residence Insurance",
        "discount": "Discount Verification",
        "discount_verification": "Discount Verification",
        "general_uw": "Underwriting Documentation",
    }
    req_label = req_labels.get(requirement_type, requirement_type)

    task = Task(
        title=f"UW Requirement: {req_label} — {customer_name}",
        description=(
            f"Policy {policy_number} with {carrier} requires: {req_label}\n"
            f"Customer: {customer_name}\n"
            f"Due date: {due_date or 'Not specified'}\n"
            f"Producer: {producer_name or 'Unassigned'}\n\n"
            f"Action: Contact customer to obtain the required documentation."
        ),
        task_type="uw_requirement",
        priority=TaskPriority.HIGH,
        status=TaskStatus.OPEN,
        assigned_to_id=assigned_to_id,
        created_by="system",
        customer_name=customer_name,
        policy_number=policy_number,
        carrier=carrier,
        due_date=due,
        source="natgen_activity",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info("Created UW requirement task #%d for %s/%s", task.id, customer_name, policy_number)
    return task


@router.post("/{task_id}/send")
def send_task_notification(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually send/resend the compliance notification for a task.
    
    - If customer has email → sends appropriate email (UW requirement, inspection, etc.)
    - If no email but has address → sends Thanks.io letter
    - Tracks last_sent_at and send_count
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Look up customer info
    from app.models.customer import Customer, CustomerPolicy
    customer = None
    if task.policy_number:
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number == task.policy_number
        ).first()
        if policy:
            customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()

    # Use task.customer_email or fall back to customer record
    email = task.customer_email or (customer.email if customer else None)
    customer_name = task.customer_name or (customer.full_name if customer else "Valued Customer")

    result = {
        "task_id": task_id,
        "method": None,
        "success": False,
        "error": None,
    }

    if email:
        # ── Send email based on task type ──
        result["method"] = "email"
        try:
            if task.task_type == "uw_requirement":
                from app.services.uw_requirement_email import send_uw_requirement_email
                # Determine UW type from task description/title
                uw_type = "general_uw"
                title_lower = (task.title or "").lower()
                if "vehicle photo" in title_lower:
                    uw_type = "vehicle_photos"
                elif "mileage" in title_lower:
                    uw_type = "proof_of_mileage"
                elif "residence" in title_lower:
                    uw_type = "proof_of_residence"
                elif "continuous" in title_lower or "proof of insurance" in title_lower:
                    uw_type = "proof_of_continuous_insurance"
                elif "discount" in title_lower:
                    uw_type = "discount_verification"

                email_result = send_uw_requirement_email(
                    to_email=email,
                    customer_name=customer_name,
                    policy_number=task.policy_number or "",
                    carrier=task.carrier or "",
                    requirement_type=uw_type,
                    deadline=task.due_date.strftime("%m/%d/%Y") if task.due_date else None,
                )
                result["success"] = email_result.get("success", False)
                result["error"] = email_result.get("error")

            elif task.task_type == "inspection":
                # For inspection tasks, use the compliance reminder email
                from app.services.compliance_reminders import _build_reminder_email, _send_reminder_email
                from datetime import datetime
                days_remaining = (task.due_date.replace(tzinfo=None) - datetime.utcnow()).days if task.due_date else 30
                tier = "7d" if days_remaining <= 7 else "14d" if days_remaining <= 14 else "30d" if days_remaining <= 30 else "60d"
                subject, html = _build_reminder_email(task, tier, days_remaining)
                email_result = _send_reminder_email(email, subject, html)
                result["success"] = email_result.get("success", False)
                result["error"] = email_result.get("error")

            else:
                # Generic: use compliance reminder
                from app.services.compliance_reminders import _build_reminder_email, _send_reminder_email
                from datetime import datetime
                days_remaining = (task.due_date.replace(tzinfo=None) - datetime.utcnow()).days if task.due_date else 30
                tier = "7d" if days_remaining <= 7 else "14d" if days_remaining <= 14 else "30d"
                subject, html = _build_reminder_email(task, tier, days_remaining)
                email_result = _send_reminder_email(email, subject, html)
                result["success"] = email_result.get("success", False)
                result["error"] = email_result.get("error")

        except Exception as e:
            result["error"] = str(e)

    elif customer and customer.address and customer.city and customer.state and customer.zip:
        # ── No email — send Thanks.io letter ──
        result["method"] = "letter"
        try:
            from app.services.thanksio_letter import send_thanksio_letter
            letter_result = send_thanksio_letter(
                client_name=customer_name,
                address=customer.address,
                city=customer.city,
                state=customer.state,
                zip_code=customer.zip,
                policy_number=task.policy_number or "",
                carrier=task.carrier or "",
                due_date=task.due_date.strftime("%m/%d/%Y") if task.due_date else None,
            )
            result["success"] = letter_result.get("success", False)
            result["order_id"] = letter_result.get("order_id")
            result["error"] = letter_result.get("error")
        except Exception as e:
            result["error"] = str(e)
    else:
        result["error"] = "No email address and no mailing address on file"

    # Update task tracking
    if result["success"]:
        from datetime import datetime
        task.last_sent_at = datetime.utcnow()
        task.send_count = (task.send_count or 0) + 1
        task.last_send_method = result["method"]
        task.customer_email = email
        db.commit()

        # Push NowCerts note
        try:
            from app.services.nowcerts_notes import push_nowcerts_note
            method_label = "email" if result["method"] == "email" else "physical letter via Thanks.io"
            task_label = {
                "uw_requirement": "UW Requirement",
                "inspection": "Inspection Follow-Up",
            }.get(task.task_type, "Compliance")
            note_text = (
                f"{task_label} {method_label} sent to {email or 'mailing address'}\n"
                f"Policy: {task.policy_number} | Carrier: {task.carrier}\n"
                f"Task: {task.title}\n"
                f"Send #{task.send_count} | Sent via ORBIT Compliance Center"
            )
            push_nowcerts_note(
                db, task.policy_number, note_text,
                subject=f"📧 ORBIT: {task_label} sent — {task.policy_number}",
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("NowCerts note failed for task %s: %s", task_id, e)

    result["last_sent_at"] = task.last_sent_at.isoformat() if task.last_sent_at else None
    result["send_count"] = task.send_count or 0
    return result
