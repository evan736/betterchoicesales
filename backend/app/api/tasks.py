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
    if current_user.role != "admin":
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
    if current_user.role != "admin":
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
