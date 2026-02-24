"""NowCerts Pending Cancellation Poll API.

Endpoints for manually triggering and monitoring the NowCerts → ORBIT
pending cancellation pipeline.

The background scheduler runs this every 4 hours automatically when
NOWCERTS_PENDING_CANCEL_POLL=true.
"""
import os
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.nowcerts_cancellation_poller import (
    poll_pending_cancellations,
    POLL_ENABLED,
    _last_poll_time,
)
from app.models.nonpay import NonPayNotice

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nowcerts-poll", tags=["NowCerts Poll"])


@router.get("/status")
def poll_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check the status of the NowCerts pending cancellation poller."""
    # Get last few poll results
    recent_polls = (
        db.query(NonPayNotice)
        .filter(NonPayNotice.upload_type == "api_poll")
        .order_by(NonPayNotice.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "enabled": POLL_ENABLED,
        "env_var": "NOWCERTS_PENDING_CANCEL_POLL",
        "last_poll_time": _last_poll_time.isoformat() if _last_poll_time else None,
        "schedule": "Every 4 hours (when enabled)",
        "recent_polls": [
            {
                "id": p.id,
                "policies_found": p.policies_found,
                "policies_matched": p.policies_matched,
                "emails_sent": p.emails_sent,
                "emails_skipped": p.emails_skipped,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in recent_polls
        ],
    }


@router.post("/trigger")
def trigger_poll(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a NowCerts pending cancellation poll.
    
    This runs the full pipeline:
    1. Fetch pending cancellations from NowCerts API
    2. Match to customers in ORBIT
    3. Send non-pay emails (respecting rate limits)
    4. Push notes back to NowCerts
    
    Works even if NOWCERTS_PENDING_CANCEL_POLL env var is false
    (manual trigger always works for testing).
    """
    # For manual triggers, temporarily override the feature flag
    import app.services.nowcerts_cancellation_poller as poller
    original_flag = poller.POLL_ENABLED
    poller.POLL_ENABLED = True

    try:
        result = poll_pending_cancellations(db)
    finally:
        poller.POLL_ENABLED = original_flag

    return result


@router.post("/dry-run")
def dry_run_poll(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dry-run: fetch and match pending cancellations but DON'T send emails.
    
    Use this to test what the poller would do before enabling it.
    """
    import app.services.nowcerts_cancellation_poller as poller

    # Force disabled so _process_single_policy runs in dry_run mode
    original_flag = poller.POLL_ENABLED
    poller.POLL_ENABLED = False

    try:
        result = poll_pending_cancellations(db)
        # Override the message since we forced dry-run
        result["enabled"] = False
        result["message"] = (
            f"DRY RUN: Found {result.get('policies_found', 0)} pending cancellations. "
            f"No emails sent. Set NOWCERTS_PENDING_CANCEL_POLL=true to enable."
        )
    finally:
        poller.POLL_ENABLED = original_flag

    return result
