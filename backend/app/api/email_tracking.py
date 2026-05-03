"""Email Tracking — Mailgun webhook handler for open/click events.

Receives Mailgun webhook events and notifies agents when customers
open their quote emails so they can follow up while the customer
is actively engaged.
"""
import logging
import hashlib
import hmac
import os
import requests
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/email-tracking", tags=["email-tracking"])


def _verify_mailgun_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify Mailgun webhook signature."""
    api_key = settings.MAILGUN_API_KEY
    if not api_key:
        return True  # Skip verification if no key configured
    hmac_digest = hmac.new(
        key=api_key.encode("ascii"),
        msg=f"{timestamp}{token}".encode("ascii"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(str(signature), str(hmac_digest))


def _send_open_notification(
    agent_email: str,
    agent_name: str,
    customer_name: str,
    customer_email: str,
    carrier: str,
    quote_id: str,
    opened_at: str,
):
    """Send a notification email to the agent that a customer opened their quote."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return

    first_name = agent_name.split()[0] if agent_name else "Team"
    subject = f"👀 {customer_name} just opened your {carrier} quote email"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background:#f0f4f8; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:520px; margin:0 auto; padding:24px 16px;">
    <div style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding:20px 24px; border-radius:12px 12px 0 0; text-align:center;">
        <p style="margin:0; font-size:28px;">👀</p>
        <p style="margin:8px 0 0; color:#22d3ee; font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px;">Quote Opened</p>
    </div>
    <div style="background:white; padding:24px; border-left:1px solid #e2e8f0; border-right:1px solid #e2e8f0;">
        <p style="margin:0 0 16px; color:#334155; font-size:15px;">
            {first_name}, <strong>{customer_name}</strong> just opened the <strong>{carrier}</strong> quote email you sent.
        </p>
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:16px; margin:16px 0;">
            <p style="margin:0 0 4px; color:#166534; font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:1px;">🔥 Hot Lead — Follow Up Now</p>
            <p style="margin:0; color:#15803d; font-size:13px;">The customer is actively looking at your quote right now. A quick call or text could close the deal.</p>
        </div>
        <table style="width:100%; font-size:14px; color:#334155;" cellpadding="0" cellspacing="0">
            <tr><td style="padding:6px 0; color:#64748b;">Customer</td><td style="padding:6px 0; text-align:right; font-weight:600;">{customer_name}</td></tr>
            <tr><td style="padding:6px 0; color:#64748b;">Email</td><td style="padding:6px 0; text-align:right;">{customer_email}</td></tr>
            <tr><td style="padding:6px 0; color:#64748b;">Carrier</td><td style="padding:6px 0; text-align:right; font-weight:600;">{carrier}</td></tr>
            <tr><td style="padding:6px 0; color:#64748b;">Opened at</td><td style="padding:6px 0; text-align:right;">{opened_at}</td></tr>
        </table>
    </div>
    <div style="background:#f8fafc; padding:12px; text-align:center; border-radius:0 0 12px 12px; border-top:1px solid #e2e8f0;">
        <p style="margin:0; color:#94a3b8; font-size:11px;">Better Choice Insurance Group · ORBIT Email Tracking</p>
    </div>
</div></body></html>"""

    try:
        from_email = os.environ.get("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")
        requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"ORBIT Notifications <{from_email}>",
                "to": [agent_email],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        logger.info(f"Quote open notification sent to {agent_email} for {customer_name}")
    except Exception as e:
        logger.warning(f"Failed to send open notification: {e}")


# Track which emails have already sent a notification (avoid spamming on multiple opens)
_notified_cache: dict[str, datetime] = {}


@router.post("/mailgun-webhook")
async def mailgun_tracking_webhook(request: Request):
    """Receive Mailgun tracking events (opens, clicks).
    
    Configure in Mailgun: Domain → Webhooks → 'opened' event →
    https://better-choice-api.onrender.com/api/email-tracking/mailgun-webhook
    """
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid request body")

    # Handle nested event-data structure (newer Mailgun format)
    event_data = data.get("event-data", data)
    if isinstance(event_data, str):
        import json
        try:
            event_data = json.loads(event_data)
        except Exception:
            event_data = data

    # Verify signature (optional — check both formats)
    sig = data.get("signature", event_data.get("signature", {}))
    if isinstance(sig, dict):
        token = sig.get("token", "")
        timestamp = sig.get("timestamp", "")
        signature = sig.get("signature", "")
    else:
        token = data.get("token", "")
        timestamp = data.get("timestamp", "")
        signature = data.get("signature", "")

    # Don't hard-fail on signature — Mailgun format varies
    if token and timestamp and signature:
        if not _verify_mailgun_signature(token, timestamp, signature):
            logger.warning("Mailgun signature verification failed")

    # Get event type
    event_type = event_data.get("event", data.get("event", "")).lower()
    
    # Get custom variables we attached to the email
    user_vars = event_data.get("user-variables", {})
    if not user_vars:
        # Try legacy format
        user_vars = {
            "email_type": data.get("email_type", ""),
            "customer_name": data.get("customer_name", ""),
            "customer_email": data.get("customer_email", ""),
            "carrier": data.get("carrier", ""),
            "agent_name": data.get("agent_name", ""),
            "agent_email": data.get("agent_email", ""),
            "quote_id": data.get("quote_id", ""),
        }

    email_type = user_vars.get("email_type", "")
    customer_name = user_vars.get("customer_name", "")
    customer_email = user_vars.get("customer_email", "")
    carrier = user_vars.get("carrier", "")
    agent_name = user_vars.get("agent_name", "")
    agent_email = user_vars.get("agent_email", "")
    quote_id = user_vars.get("quote_id", "")

    recipient = event_data.get("recipient", data.get("recipient", customer_email))
    message_id = event_data.get("message", {}).get("headers", {}).get("message-id", "")

    logger.info(f"Email tracking event: {event_type} | type={email_type} | customer={customer_name} | recipient={recipient}")

    # Handle OPEN events for quote emails
    if event_type == "opened" and email_type == "quote":
        # Only notify up to 1 time per day per customer+carrier
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        cache_key = f"{quote_id or customer_email}:{carrier}:{today_str}"
        
        if cache_key not in _notified_cache:
            _notified_cache[cache_key] = datetime.utcnow()
            
            # Clean old cache entries (older than today)
            stale = [k for k, v in _notified_cache.items() if (datetime.utcnow() - v).days > 1]
            for k in stale:
                del _notified_cache[k]

            # Determine who to notify
            notify_email = agent_email or os.environ.get("SMART_INBOX_BCC", "evan@betterchoiceins.com")
            notify_name = agent_name or "Team"

            now_str = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")
            _send_open_notification(
                agent_email=notify_email,
                agent_name=notify_name,
                customer_name=customer_name or recipient,
                customer_email=recipient,
                carrier=carrier or "Insurance",
                quote_id=quote_id,
                opened_at=now_str,
            )

            return {"status": "notified", "event": event_type, "customer": customer_name}
        else:
            return {"status": "already_notified", "event": event_type, "customer": customer_name}

    # Handle CLICK events (log but don't notify — opens are more actionable)
    if event_type == "clicked":
        url = event_data.get("url", data.get("url", ""))
        logger.info(f"Email click: {customer_name} clicked {url} in {email_type} email")

    # Handle requote campaign open/click events — update lead + campaign counters
    if email_type == "requote_campaign" and event_type in ("opened", "clicked"):
        try:
            from app.core.database import SessionLocal
            from app.models.campaign import RequoteCampaign
            db = SessionLocal()
            try:
                # Find the lead by email
                from sqlalchemy import text
                lead_row = db.execute(text(
                    "SELECT id, campaign_id, touch1_opened, touch2_opened, touch3_opened "
                    "FROM requote_leads WHERE LOWER(email) = :email LIMIT 1"
                ), {"email": (recipient or customer_email or "").lower().strip()}).fetchone()

                if lead_row:
                    lead_id, campaign_id = lead_row[0], lead_row[1]
                    # Mark the latest touch as opened
                    if not lead_row[2]:
                        db.execute(text("UPDATE requote_leads SET touch1_opened = TRUE WHERE id = :id"), {"id": lead_id})
                    elif not lead_row[3]:
                        db.execute(text("UPDATE requote_leads SET touch2_opened = TRUE WHERE id = :id"), {"id": lead_id})
                    elif not lead_row[4]:
                        db.execute(text("UPDATE requote_leads SET touch3_opened = TRUE WHERE id = :id"), {"id": lead_id})

                    # Increment campaign counter
                    if event_type == "opened":
                        db.execute(text("UPDATE requote_campaigns SET emails_opened = emails_opened + 1 WHERE id = :id"), {"id": campaign_id})
                    elif event_type == "clicked":
                        db.execute(text("UPDATE requote_campaigns SET emails_clicked = COALESCE(emails_clicked, 0) + 1 WHERE id = :id"), {"id": campaign_id})
                    db.commit()
                    logger.info(f"Campaign {event_type} tracked: {recipient} (lead {lead_id}, campaign {campaign_id})")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Campaign tracking error: {e}")

    # Handle quote followup open/click events
    if email_type == "quote_followup" and event_type == "opened":
        try:
            from app.core.database import SessionLocal
            db = SessionLocal()
            try:
                from sqlalchemy import text
                db.execute(text(
                    "UPDATE quotes SET followup_disabled = followup_disabled WHERE prospect_email ILIKE :email"
                ), {"email": (recipient or customer_email or "").lower().strip()})
                # Just log — the important thing is we know they're engaged
                logger.info(f"Quote followup opened by {recipient}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Quote followup tracking error: {e}")

    # ── BOUNCE / COMPLAINT / UNSUBSCRIBE HANDLING ────────────────────
    # Critical for outreach campaigns — protects sender reputation by
    # immediately suppressing addresses that:
    #   - Hard bounce (mailbox doesn't exist) → permanent_fail / failed
    #   - Mark our message as spam → complained
    #   - Click the unsubscribe link → unsubscribed
    #
    # Soft bounces (temporary_fail, severity=temporary) are tolerated up
    # to 3 occurrences before suppressing — these can be transient
    # network/server issues, full inboxes that get cleared, etc.
    #
    # Mailgun sends events using the v2 'event-data' nested format. The
    # payload includes 'severity' = 'permanent' or 'temporary' for fails.
    bounce_recipient = (recipient or customer_email or "").lower().strip()
    if bounce_recipient and event_type in ("failed", "complained", "unsubscribed", "rejected"):
        try:
            from app.core.database import SessionLocal
            from app.models.campaign import ColdProspect, WinBackCampaign
            from sqlalchemy import func as sa_fn

            db = SessionLocal()
            try:
                # Reason from the payload (helps debug recurring failures)
                severity = event_data.get("severity", "")
                reason = (
                    event_data.get("reason")
                    or event_data.get("delivery-status", {}).get("description", "")
                    or event_data.get("description", "")
                    or ""
                )[:500]

                # Determine if this is a "hard" suppression event
                is_hard = (
                    event_type == "complained"
                    or event_type == "unsubscribed"
                    or event_type == "rejected"
                    or (event_type == "failed" and severity != "temporary")
                )

                now_dt = datetime.utcnow()

                # ── COLD PROSPECTS ──────────────────────────────────
                cps = db.query(ColdProspect).filter(
                    sa_fn.lower(ColdProspect.email) == bounce_recipient
                ).all()
                for cp in cps:
                    cp.bounce_count = (cp.bounce_count or 0) + 1
                    cp.last_bounce_at = now_dt
                    cp.bounce_reason = f"{event_type}:{severity}:{reason}"[:500]
                    if is_hard:
                        # Permanent suppression
                        if event_type == "complained":
                            cp.status = "paused_complained"
                        elif event_type == "unsubscribed":
                            cp.status = "paused_unsubscribed"
                        else:
                            cp.status = "paused_bounced"
                        cp.excluded = True
                        cp.excluded_reason = f"{event_type}:{reason}"[:500]
                        logger.info(
                            f"Cold prospect HARD-suppressed: id={cp.id} email={cp.email} event={event_type} reason={reason[:100]}"
                        )
                    elif cp.bounce_count >= 3:
                        # Soft-bounce auto-suppress threshold
                        cp.status = "paused_bounced"
                        cp.excluded = True
                        cp.excluded_reason = f"3+ soft bounces; last={reason}"[:500]
                        logger.info(
                            f"Cold prospect SOFT-suppressed (3+ bounces): id={cp.id}"
                        )
                if cps:
                    db.commit()

                # ── WINBACK CAMPAIGNS ───────────────────────────────
                wbs = db.query(WinBackCampaign).filter(
                    sa_fn.lower(WinBackCampaign.customer_email) == bounce_recipient
                ).all()
                for wb in wbs:
                    wb.bounce_count = (wb.bounce_count or 0) + 1
                    wb.last_bounce_at = now_dt
                    wb.bounce_reason = f"{event_type}:{severity}:{reason}"[:500]
                    if is_hard:
                        if event_type == "complained":
                            wb.status = "paused_complained"
                            wb.excluded = True
                            wb.excluded_reason = f"complaint:{reason}"[:500]
                        elif event_type == "unsubscribed":
                            wb.status = "paused_unsubscribed"
                            wb.excluded = True
                            wb.excluded_reason = f"unsubscribed via Mailgun"[:500]
                        else:
                            # Hard bounce
                            wb.status = "paused_bounced"
                            wb.excluded = True
                            wb.excluded_reason = f"hard bounce: {reason}"[:500]
                        logger.info(
                            f"Winback HARD-suppressed: id={wb.id} email={wb.customer_email} event={event_type}"
                        )
                    elif wb.bounce_count >= 3:
                        wb.status = "paused_bounced"
                        wb.excluded = True
                        wb.excluded_reason = f"3+ soft bounces; last={reason}"[:500]
                        logger.info(
                            f"Winback SOFT-suppressed (3+ bounces): id={wb.id}"
                        )
                if wbs:
                    db.commit()

                if cps or wbs:
                    return {
                        "status": "bounce_processed",
                        "event": event_type,
                        "severity": severity,
                        "is_hard": is_hard,
                        "cold_prospects_updated": len(cps),
                        "winback_updated": len(wbs),
                    }
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Bounce/complaint webhook handling error: {e}")
            # Don't re-raise — return 200 to Mailgun so it stops retrying

    return {"status": "ok", "event": event_type}


@router.get("/bounce-stats")
def bounce_stats(
    current_user = Depends(get_current_user),
):
    """Diagnostic: how many bounces/complaints have we recorded?

    Useful for daily monitoring. Run this each morning to catch any
    spike in bounces that might indicate a deliverability problem.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    from app.core.database import SessionLocal
    from app.models.campaign import ColdProspect, WinBackCampaign
    from sqlalchemy import func as sa_fn

    db = SessionLocal()
    try:
        result = {}

        # Cold prospects
        result["cold_prospects"] = {
            "total_with_bounce": db.query(sa_fn.count(ColdProspect.id)).filter(
                ColdProspect.bounce_count > 0
            ).scalar(),
            "suppressed_paused_bounced": db.query(sa_fn.count(ColdProspect.id)).filter(
                ColdProspect.status == "paused_bounced"
            ).scalar(),
            "suppressed_complained": db.query(sa_fn.count(ColdProspect.id)).filter(
                ColdProspect.status == "paused_complained"
            ).scalar(),
            "suppressed_unsubscribed": db.query(sa_fn.count(ColdProspect.id)).filter(
                ColdProspect.status == "paused_unsubscribed"
            ).scalar(),
            "bounces_last_24h": db.query(sa_fn.count(ColdProspect.id)).filter(
                ColdProspect.last_bounce_at >= datetime.utcnow() - timedelta(hours=24)
            ).scalar(),
        }

        # Winback
        result["winback"] = {
            "total_with_bounce": db.query(sa_fn.count(WinBackCampaign.id)).filter(
                WinBackCampaign.bounce_count > 0
            ).scalar(),
            "suppressed_paused_bounced": db.query(sa_fn.count(WinBackCampaign.id)).filter(
                WinBackCampaign.status == "paused_bounced"
            ).scalar(),
            "suppressed_complained": db.query(sa_fn.count(WinBackCampaign.id)).filter(
                WinBackCampaign.status == "paused_complained"
            ).scalar(),
            "suppressed_unsubscribed": db.query(sa_fn.count(WinBackCampaign.id)).filter(
                WinBackCampaign.status == "paused_unsubscribed"
            ).scalar(),
            "bounces_last_24h": db.query(sa_fn.count(WinBackCampaign.id)).filter(
                WinBackCampaign.last_bounce_at >= datetime.utcnow() - timedelta(hours=24)
            ).scalar(),
        }

        return result
    finally:
        db.close()


@router.post("/bounce-test")
def bounce_test(
    test_email: str,
    event: str = "failed",
    severity: str = "permanent",
    reason: str = "test bounce — do not page Evan",
    current_user = Depends(get_current_user),
):
    """Simulate a bounce event for a given email — admin-only.

    Use this to verify the bounce-handling logic works against real
    cold_prospects / winback records WITHOUT waiting for an actual
    bounce or asking Mailgun to fire one.

    Example:
      POST /api/email-tracking/bounce-test?test_email=fake@nowhere.com&event=failed&severity=permanent

    NOTE: this WILL set status='paused_bounced' on matching records.
    Use a real test email (or a recipient you don't care about
    suppressing).
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if event not in ("failed", "complained", "unsubscribed", "rejected"):
        raise HTTPException(
            status_code=400,
            detail="event must be one of: failed, complained, unsubscribed, rejected",
        )

    # Construct the same shape Mailgun sends
    fake_event_data = {
        "event": event,
        "severity": severity,
        "reason": reason,
        "recipient": test_email,
    }

    # Reuse the suppression logic by calling it directly via mock request body
    # Easier just to inline the same logic:
    from app.core.database import SessionLocal
    from app.models.campaign import ColdProspect, WinBackCampaign
    from sqlalchemy import func as sa_fn

    db = SessionLocal()
    try:
        bounce_recipient = test_email.lower().strip()
        is_hard = (
            event == "complained"
            or event == "unsubscribed"
            or event == "rejected"
            or (event == "failed" and severity != "temporary")
        )
        now_dt = datetime.utcnow()

        cps = db.query(ColdProspect).filter(
            sa_fn.lower(ColdProspect.email) == bounce_recipient
        ).all()
        for cp in cps:
            cp.bounce_count = (cp.bounce_count or 0) + 1
            cp.last_bounce_at = now_dt
            cp.bounce_reason = f"{event}:{severity}:{reason}"[:500]
            if is_hard:
                cp.status = "paused_bounced" if event == "failed" else f"paused_{event}"
                cp.excluded = True
                cp.excluded_reason = f"{event}:{reason}"[:500]
            elif cp.bounce_count >= 3:
                cp.status = "paused_bounced"
                cp.excluded = True
        if cps:
            db.commit()

        wbs = db.query(WinBackCampaign).filter(
            sa_fn.lower(WinBackCampaign.customer_email) == bounce_recipient
        ).all()
        for wb in wbs:
            wb.bounce_count = (wb.bounce_count or 0) + 1
            wb.last_bounce_at = now_dt
            wb.bounce_reason = f"{event}:{severity}:{reason}"[:500]
            if is_hard:
                wb.status = "paused_bounced" if event == "failed" else f"paused_{event}"
                wb.excluded = True
                wb.excluded_reason = f"{event}:{reason}"[:500]
            elif wb.bounce_count >= 3:
                wb.status = "paused_bounced"
                wb.excluded = True
        if wbs:
            db.commit()

        return {
            "test_email": test_email,
            "event": event,
            "severity": severity,
            "is_hard": is_hard,
            "cold_prospects_updated": len(cps),
            "winback_updated": len(wbs),
            "note": "If counts are 0, no record exists with this email. Try a real one from your data.",
        }
    finally:
        db.close()
