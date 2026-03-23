"""NowCerts Pending Cancellations Poller.

Pulls pending cancellation data from NowCerts (populated by IVANS carrier downloads)
and feeds it into ORBIT's non-pay email workflow. This replaces the need for
carrier-specific email parsers by using one universal pipe:

    IVANS → NowCerts → ORBIT (this poller) → customer emails

Runs on a background schedule (every 4 hours).
Respects existing 1x/7-day rate limit per policy.

Feature flag: NOWCERTS_PENDING_CANCEL_POLL=true (default: false)

NowCerts API endpoints used:
- POST api/Insured/PendingCancellations  (pending cancellations by insured)
- POST api/Policy/PendingCancellations   (pending cancellations by policy)
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.services.nowcerts import get_nowcerts_client
from app.models.nonpay import NonPayNotice, NonPayEmail
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)

# Feature flag
POLL_ENABLED = os.environ.get("NOWCERTS_PENDING_CANCEL_POLL", "false").lower() == "true"

# Track last poll time to avoid re-processing
_last_poll_time: Optional[datetime] = None


def poll_pending_cancellations(db: Session) -> dict:
    """Main entry point: pull pending cancellations from NowCerts and process them.
    
    Returns summary dict with counts.
    """
    result = {
        "enabled": POLL_ENABLED,
        "timestamp": datetime.utcnow().isoformat(),
        "policies_found": 0,
        "already_tracked": 0,
        "new_notices": 0,
        "emails_sent": 0,
        "emails_skipped_rate_limit": 0,
        "errors": 0,
        "error_details": [],
    }

    if not POLL_ENABLED:
        result["message"] = "Polling disabled. Set NOWCERTS_PENDING_CANCEL_POLL=true to enable."
        return result

    client = get_nowcerts_client()
    if not client.is_configured:
        result["message"] = "NowCerts credentials not configured"
        return result

    # Step 1: Get all policies from our DB to use their NowCerts database IDs
    policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.nowcerts_policy_id.isnot(None),
        CustomerPolicy.nowcerts_policy_id != "",
        CustomerPolicy.status.notin_(["cancelled", "expired", "non-renewed"]),
    ).all()

    if not policies:
        result["message"] = "No active policies with NowCerts IDs found"
        return result

    logger.info("Polling NowCerts pending cancellations for %d policies...", len(policies))

    # Step 2: Fetch pending cancellations from NowCerts
    pending_cancellations = _fetch_pending_cancellations(client, policies)
    result["policies_found"] = len(pending_cancellations)

    if not pending_cancellations:
        result["message"] = "No pending cancellations found in NowCerts"
        return result

    logger.info("Found %d pending cancellations in NowCerts", len(pending_cancellations))

    # Step 3: Create a batch notice record
    notice = NonPayNotice(
        filename="nowcerts_pending_cancellations_poll",
        upload_type="api_poll",
        uploaded_by="system_poller",
        policies_found=len(pending_cancellations),
        status="processing",
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)

    # Step 4: Process each pending cancellation
    emails_sent = 0
    skipped = 0
    matched = 0

    for pc in pending_cancellations:
        try:
            process_result = _process_pending_cancellation(db, notice.id, pc)

            if process_result.get("matched"):
                matched += 1
            if process_result.get("email_sent"):
                emails_sent += 1
            if process_result.get("skipped_rate_limit"):
                skipped += 1
            if process_result.get("error"):
                result["errors"] += 1
                result["error_details"].append(process_result["error"])

        except Exception as e:
            logger.error("Error processing pending cancellation %s: %s",
                        pc.get("policy_number", "?"), e)
            result["errors"] += 1
            result["error_details"].append(str(e))

    # Update notice record
    notice.policies_matched = matched
    notice.emails_sent = emails_sent
    notice.emails_skipped = skipped
    notice.status = "completed"
    db.commit()

    result["new_notices"] = matched
    result["emails_sent"] = emails_sent
    result["emails_skipped_rate_limit"] = skipped
    result["notice_id"] = notice.id
    result["message"] = (
        f"Processed {len(pending_cancellations)} pending cancellations: "
        f"{emails_sent} emails sent, {skipped} skipped (rate limit), "
        f"{result['errors']} errors"
    )

    logger.info("NowCerts poll complete: %s", result["message"])
    return result


def _fetch_pending_cancellations(client, policies: list) -> list[dict]:
    """Fetch pending cancellations from NowCerts API.
    
    NowCerts PendingCancellations response format (confirmed via debug):
    {
        "databaseId": "guid",
        "to": "2024-10-04T00:00:00",          # cancellation effective date
        "changeDate": "2024-09-23T10:14:00",
        "createDate": "2024-09-23T10:14:00",
        "sendReminders": "No",
        "description": "",
        "active": "Yes" or "No",               # CRITICAL: only process "Yes"
        "insuredDatabaseId": "guid",
        "insuredEmail": "email@example.com",
        "insuredFirstName": "John",
        "insuredLastName": "Wright",
        "insuredCommercialName": "Wright, John",
        "policyDatabaseId": "guid",
        "policyNumber": "975063537"
    }
    
    NOTE: Carrier name is NOT in the response — we look it up from our DB.
    """
    results = []
    seen_policies = set()

    # Build a map of NowCerts policy IDs to our policy records
    nc_policy_map = {}
    for p in policies:
        if p.nowcerts_policy_id:
            nc_policy_map[p.nowcerts_policy_id] = p

    # Approach 1: Fetch via policy database IDs (batches of 100)
    policy_db_ids = list(nc_policy_map.keys())
    logger.info("Fetching pending cancellations for %d policies...", len(policy_db_ids))

    for i in range(0, len(policy_db_ids), 100):
        batch = policy_db_ids[i:i + 100]
        try:
            data = client._post("/api/Policy/PendingCancellations", {
                "policyDataBaseId": batch
            })

            items = data if isinstance(data, list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue

                # CRITICAL: Only process ACTIVE pending cancellations
                if str(item.get("active", "")).lower() not in ("yes", "true"):
                    continue

                pc = _normalize_pending_cancellation(item, nc_policy_map)
                if pc and pc.get("policy_number") not in seen_policies:
                    results.append(pc)
                    seen_policies.add(pc["policy_number"])

        except Exception as e:
            logger.warning("Policy PendingCancellations batch %d failed: %s", i, e)

    # Approach 2: If no results from policy-level, try insured-level
    if not results:
        try:
            from app.models.customer import Customer
            from app.core.database import SessionLocal
            db = SessionLocal()
            try:
                customers = db.query(Customer).filter(
                    Customer.nowcerts_insured_id.isnot(None),
                    Customer.nowcerts_insured_id != "",
                    Customer.is_active == True,
                ).all()
                insured_db_ids = [c.nowcerts_insured_id for c in customers if c.nowcerts_insured_id]

                logger.info("Trying insured-level fetch for %d customers...", len(insured_db_ids))

                for i in range(0, len(insured_db_ids), 100):
                    batch = insured_db_ids[i:i + 100]
                    try:
                        data = client._post("/api/Insured/PendingCancellations", {
                            "insuredDataBaseId": batch
                        })

                        items = data if isinstance(data, list) else []
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            if str(item.get("active", "")).lower() not in ("yes", "true"):
                                continue

                            pc = _normalize_pending_cancellation(item, nc_policy_map)
                            if pc and pc.get("policy_number") not in seen_policies:
                                results.append(pc)
                                seen_policies.add(pc["policy_number"])

                    except Exception as e:
                        logger.warning("Insured PendingCancellations batch %d failed: %s", i, e)
            finally:
                db.close()
        except Exception as e:
            logger.error("Insured-level pending cancellation fetch failed: %s", e)

    logger.info("Total active pending cancellations found: %d", len(results))
    return results


def _normalize_pending_cancellation(raw: dict, policy_map: dict) -> Optional[dict]:
    """Normalize a NowCerts pending cancellation API response.
    
    Confirmed NowCerts fields:
    - policyNumber          → policy_number
    - policyDatabaseId      → nowcerts_policy_id (used to look up carrier from our DB)
    - insuredCommercialName → insured_name
    - insuredEmail          → customer email
    - insuredFirstName/LastName
    - to                    → cancellation effective date
    - active                → "Yes" or "No"
    - description           → reason/notes
    - createDate / changeDate
    
    NOTE: Carrier is NOT in the response — we look it up from our policy map.
    """
    policy_number = (raw.get("policyNumber") or "").strip()
    if not policy_number:
        return None

    # Look up carrier from our DB via the policy map
    nc_policy_id = raw.get("policyDatabaseId") or raw.get("policyDataBaseId") or ""
    carrier = ""
    our_policy = policy_map.get(nc_policy_id)
    if our_policy:
        carrier = our_policy.carrier or ""

    # Build insured name
    commercial_name = raw.get("insuredCommercialName") or ""
    first = raw.get("insuredFirstName") or ""
    last = raw.get("insuredLastName") or ""
    insured_name = commercial_name or f"{first} {last}".strip() or ""

    # Parse cancellation date from "to" field
    cancel_date = raw.get("to") or ""
    if cancel_date and "T" in str(cancel_date):
        cancel_date = str(cancel_date)[:10]

    # Description as reason
    reason = raw.get("description") or "non_pay"

    return {
        "policy_number": policy_number,
        "carrier": carrier,
        "insured_name": insured_name,
        "insured_email": raw.get("insuredEmail") or "",
        "cancel_date": cancel_date,
        "reason": reason,
        "amount_due": None,  # Not provided by NowCerts PendingCancellations endpoint
        "nowcerts_policy_id": nc_policy_id,
        "nowcerts_insured_id": raw.get("insuredDatabaseId") or "",
        "source": "nowcerts_pending_cancellation",
        "active": raw.get("active", ""),
        "create_date": raw.get("createDate") or "",
        "_raw": raw,
    }


def _process_pending_cancellation(db: Session, notice_id: int, pc: dict) -> dict:
    """Process a single pending cancellation — match to customer, send email if needed.
    
    Reuses the same logic as the nonpay email workflow:
    - Find policy in our DB
    - Match to customer
    - Check 1x/7-day rate limit
    - Send non-pay email
    - Record in NonPayEmail table
    """
    from app.api.nonpay import _process_single_policy

    policy_number = pc.get("policy_number", "")
    carrier = pc.get("carrier", "")
    insured_name = pc.get("insured_name", "")
    amount_due = pc.get("amount_due")
    cancel_date = pc.get("cancel_date", "")

    # Delegate to the existing nonpay single-policy processor
    # This handles: DB lookup, customer matching, rate limiting, email sending
    result = _process_single_policy(
        db=db,
        notice_id=notice_id,
        policy_number=policy_number,
        carrier=carrier,
        insured_name=insured_name,
        amount_due=amount_due,
        due_date=cancel_date,
        dry_run=not POLL_ENABLED,  # Extra safety
    )

    # Also push a note to NowCerts if we sent an email
    if result.get("email_sent"):
        try:
            client = get_nowcerts_client()
            if client.is_configured:
                client.insert_note({
                    "subject": f"⚠️ ORBIT: Non-Pay Notice Sent ({carrier})",
                    "text": (
                        f"ORBIT auto-detected pending cancellation via NowCerts/IVANS.\n"
                        f"Policy: {policy_number}\n"
                        f"Carrier: {carrier}\n"
                        f"Cancel Date: {cancel_date}\n"
                        f"Amount Due: ${amount_due:.2f if amount_due else 'N/A'}\n"
                        f"Customer email notification sent automatically."
                    ),
                    "insured_commercial_name": insured_name,
                    "insured_email": result.get("customer_email", ""),
                    "creator_name": "ORBIT System",
                    "type": "Email",
                })
        except Exception as e:
            logger.warning("Failed to push NowCerts note for %s: %s", policy_number, e)

    return result


# ── Background Scheduler Entry Point ──

def run_scheduled_poll():
    """Called by the background scheduler thread in main.py.
    
    Runs every 4 hours. Creates its own DB session.
    """
    global _last_poll_time

    if not POLL_ENABLED:
        return

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        result = poll_pending_cancellations(db)
        _last_poll_time = datetime.utcnow()

        if result.get("emails_sent", 0) > 0 or result.get("errors", 0) > 0:
            logger.info("NowCerts pending cancellation poll: %s", result.get("message", ""))

        # Notify Evan via email if there are new pending cancellations
        if result.get("emails_sent", 0) > 0:
            _send_poll_summary_email(result)

    except Exception as e:
        logger.error("NowCerts pending cancellation poll failed: %s", e)
    finally:
        db.close()


def _send_poll_summary_email(result: dict):
    """Send Evan a summary email when new pending cancellations are detected."""
    from app.core.config import settings
    import requests as http_requests

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
    <div style="background:linear-gradient(135deg,#1a2b5f,#0c4a6e);padding:20px;border-radius:12px 12px 0 0;text-align:center;">
        <h2 style="color:white;margin:0;">ORBIT — NowCerts Pending Cancellations</h2>
        <p style="color:#00e5c7;margin:4px 0 0;font-size:13px;">{result.get('timestamp', '')}</p>
    </div>
    <div style="background:white;padding:24px;border-radius:0 0 12px 12px;border:1px solid #e2e8f0;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr><td style="padding:8px 0;color:#64748b;">Policies Found</td><td style="padding:8px 0;font-weight:700;">{result.get('policies_found', 0)}</td></tr>
            <tr><td style="padding:8px 0;color:#64748b;">Emails Sent</td><td style="padding:8px 0;font-weight:700;color:#059669;">{result.get('emails_sent', 0)}</td></tr>
            <tr><td style="padding:8px 0;color:#64748b;">Skipped (Rate Limit)</td><td style="padding:8px 0;">{result.get('emails_skipped_rate_limit', 0)}</td></tr>
            <tr><td style="padding:8px 0;color:#64748b;">Errors</td><td style="padding:8px 0;color:#dc2626;">{result.get('errors', 0)}</td></tr>
        </table>
        <div style="margin-top:16px;text-align:center;">
            <a href="https://orbit.betterchoiceins.com/retention" 
               style="display:inline-block;background:#1a2b5f;color:white;padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:600;">
                View Retention Dashboard
            </a>
        </div>
    </div></div>"""

    try:
        http_requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"ORBIT System <system@{settings.MAILGUN_DOMAIN}>",
                "to": ["evan@betterchoiceins.com"],
                "subject": f"ORBIT: {result.get('emails_sent', 0)} Non-Pay Alerts Sent (NowCerts Poll)",
                "html": html,
            },
        )
    except Exception as e:
        logger.warning("Poll summary email failed: %s", e)
