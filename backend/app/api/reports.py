"""Reports API — monthly agency reports viewable in ORBIT and emailed as PDF."""

import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/monthly")
def get_monthly_report(
    year: int = Query(None),
    month: int = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get monthly report data for in-app viewing."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    if not year or not month:
        today = date.today()
        year = today.year
        month = today.month

    from app.services.monthly_report import generate_monthly_report
    return generate_monthly_report(db, year, month)


@router.post("/monthly/send")
def send_monthly_report(
    year: int = Query(None),
    month: int = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually send the monthly report email."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if not year or not month:
        today = date.today()
        # Default to last month
        if today.month == 1:
            year = today.year - 1
            month = 12
        else:
            year = today.year
            month = today.month - 1

    from app.services.monthly_report import send_monthly_report_email
    return send_monthly_report_email(db, year, month)
