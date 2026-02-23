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
    """List tasks, optionally filtered."""
    q = db.query(Task)

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
    open_count = db.query(func.count(Task.id)).filter(
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS])
    ).scalar() or 0

    urgent_count = db.query(func.count(Task.id)).filter(
        Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
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
    """Create a task for non-renewal remarketing."""
    from dateutil import parser as dateparser

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
