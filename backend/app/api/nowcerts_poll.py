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
    """Debug endpoint — shows exactly what each NowCerts API call returns.
    
    Does NOT send any emails. Just shows raw API responses.
    """
    from app.services.nowcerts import get_nowcerts_client
    from app.models.customer import Customer, CustomerPolicy

    client = get_nowcerts_client()
    debug = {
        "nowcerts_configured": client.is_configured,
        "steps": [],
    }

    if not client.is_configured:
        debug["error"] = "NowCerts credentials not configured"
        return debug

    # Step 1: Auth check
    try:
        token = client._authenticate()
        debug["auth"] = "success"
        debug["token_preview"] = token[:20] + "..." if token else None
    except Exception as e:
        debug["auth"] = f"failed: {e}"
        return debug

    # Step 2: Count policies with NowCerts IDs
    policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.nowcerts_policy_id.isnot(None),
        CustomerPolicy.nowcerts_policy_id != "",
    ).all()
    debug["total_policies_with_nc_id"] = len(policies)

    # Step 3: Count customers with NowCerts IDs
    customers = db.query(Customer).filter(
        Customer.nowcerts_insured_id.isnot(None),
        Customer.nowcerts_insured_id != "",
        Customer.is_active == True,
    ).all()
    debug["total_customers_with_nc_id"] = len(customers)

    # Step 4: Try Policy PendingCancellations with first 5 policy IDs
    sample_policy_ids = [p.nowcerts_policy_id for p in policies[:5]]
    debug["sample_policy_ids"] = sample_policy_ids

    try:
        resp = client._post("/api/Policy/PendingCancellations", {
            "policyDataBaseId": sample_policy_ids
        })
        debug["steps"].append({
            "endpoint": "POST /api/Policy/PendingCancellations",
            "payload": {"policyDataBaseId": sample_policy_ids},
            "response_type": type(resp).__name__,
            "response_preview": str(resp)[:1000] if resp else "empty",
        })
    except Exception as e:
        debug["steps"].append({
            "endpoint": "POST /api/Policy/PendingCancellations",
            "error": str(e),
        })

    # Step 5: Try Insured PendingCancellations with first 5 insured IDs
    sample_insured_ids = [c.nowcerts_insured_id for c in customers[:5]]
    debug["sample_insured_ids"] = sample_insured_ids

    try:
        resp = client._post("/api/Insured/PendingCancellations", {
            "insuredDataBaseId": sample_insured_ids
        })
        debug["steps"].append({
            "endpoint": "POST /api/Insured/PendingCancellations",
            "payload": {"insuredDataBaseId": sample_insured_ids[:3]},
            "response_type": type(resp).__name__,
            "response_preview": str(resp)[:1000] if resp else "empty",
        })
    except Exception as e:
        debug["steps"].append({
            "endpoint": "POST /api/Insured/PendingCancellations",
            "error": str(e),
        })

    # Step 6: Try OData fallback for pending cancel status
    try:
        for status_filter in [
            "status eq 'Pending Cancellation'",
            "status eq 'Pending Cancel'",
            "contains(tolower(status), 'cancel')",
            "contains(tolower(status), 'pending')",
        ]:
            try:
                resp = client._odata_get("PolicyDetailList", skip=0, top=10,
                                          filter_expr=status_filter)
                items = resp.get("value", [])
                count = resp.get("@odata.count", len(items))
                debug["steps"].append({
                    "endpoint": f"GET PolicyDetailList?$filter={status_filter}",
                    "count": count,
                    "sample": [
                        {
                            "number": i.get("number", ""),
                            "status": i.get("status", ""),
                            "carrier": i.get("carrierName", ""),
                            "insured": i.get("insuredName", i.get("commercialName", "")),
                        }
                        for i in items[:5]
                    ] if items else [],
                })
                if count > 0:
                    break  # Found results, no need to try other filters
            except Exception as e:
                debug["steps"].append({
                    "endpoint": f"GET PolicyDetailList?$filter={status_filter}",
                    "error": str(e),
                })
    except Exception as e:
        debug["steps"].append({
            "endpoint": "OData fallback",
            "error": str(e),
        })

    # Step 7: Get distinct policy statuses to understand what NowCerts uses
    try:
        resp = client._get("/api/Policy/StatusTypes")
        debug["steps"].append({
            "endpoint": "GET /api/Policy/StatusTypes",
            "response_preview": str(resp)[:500] if resp else "empty",
        })
    except Exception as e:
        debug["steps"].append({
            "endpoint": "GET /api/Policy/StatusTypes",
            "error": str(e),
        })

    return debug
