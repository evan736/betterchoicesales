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


@router.post("/debug")
def debug_poll(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Debug endpoint — full scan of NowCerts pending cancellations.
    
    Scans ALL policies in batches, returns only ACTIVE pending cancellations.
    Does NOT send any emails.
    """
    from app.services.nowcerts import get_nowcerts_client
    from app.models.customer import Customer, CustomerPolicy

    client = get_nowcerts_client()
    debug = {
        "nowcerts_configured": client.is_configured,
        "auth": None,
        "total_policies_with_nc_id": 0,
        "total_customers_with_nc_id": 0,
        "batches_processed": 0,
        "total_raw_results": 0,
        "active_pending_cancellations": [],
        "inactive_count": 0,
        "errors": [],
    }

    if not client.is_configured:
        debug["error"] = "NowCerts credentials not configured"
        return debug

    # Auth
    try:
        client._authenticate()
        debug["auth"] = "success"
    except Exception as e:
        debug["auth"] = f"failed: {e}"
        return debug

    # Get all policies with NowCerts IDs
    policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.nowcerts_policy_id.isnot(None),
        CustomerPolicy.nowcerts_policy_id != "",
    ).all()
    debug["total_policies_with_nc_id"] = len(policies)

    # Build policy map for carrier lookup
    nc_policy_map = {}
    for p in policies:
        if p.nowcerts_policy_id:
            nc_policy_map[p.nowcerts_policy_id] = p

    customers = db.query(Customer).filter(
        Customer.nowcerts_insured_id.isnot(None),
        Customer.nowcerts_insured_id != "",
    ).all()
    debug["total_customers_with_nc_id"] = len(customers)

    # Scan ALL policies in batches of 100
    policy_db_ids = list(nc_policy_map.keys())
    seen = set()

    for i in range(0, len(policy_db_ids), 100):
        batch = policy_db_ids[i:i + 100]
        debug["batches_processed"] += 1
        try:
            data = client._post("/api/Policy/PendingCancellations", {
                "policyDataBaseId": batch
            })

            items = data if isinstance(data, list) else []
            debug["total_raw_results"] += len(items)

            for item in items:
                if not isinstance(item, dict):
                    continue

                is_active = str(item.get("active", "")).lower() in ("yes", "true")
                policy_num = item.get("policyNumber", "")

                if not is_active:
                    debug["inactive_count"] += 1
                    continue

                if policy_num in seen:
                    continue
                seen.add(policy_num)

                # Look up carrier from our DB
                nc_pid = item.get("policyDatabaseId") or ""
                our_policy = nc_policy_map.get(nc_pid)
                carrier = our_policy.carrier if our_policy else ""

                # Check customer email
                insured_email = item.get("insuredEmail") or ""
                commercial_name = item.get("insuredCommercialName") or ""
                first = item.get("insuredFirstName") or ""
                last = item.get("insuredLastName") or ""

                debug["active_pending_cancellations"].append({
                    "policy_number": policy_num,
                    "carrier": carrier,
                    "customer_name": commercial_name or f"{first} {last}".strip(),
                    "customer_email": insured_email,
                    "cancel_date": str(item.get("to", ""))[:10],
                    "description": item.get("description") or "",
                    "created": str(item.get("createDate", ""))[:10],
                    "our_policy_status": our_policy.status if our_policy else "not_found",
                })

        except Exception as e:
            debug["errors"].append(f"Batch {i}: {str(e)}")

    debug["active_count"] = len(debug["active_pending_cancellations"])
    debug["message"] = (
        f"Scanned {debug['batches_processed']} batches ({len(policy_db_ids)} policies). "
        f"Found {debug['total_raw_results']} total records: "
        f"{debug['active_count']} ACTIVE, {debug['inactive_count']} inactive."
    )

    return debug
