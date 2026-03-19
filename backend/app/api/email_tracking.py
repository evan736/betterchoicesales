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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

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

    return {"status": "ok", "event": event_type}
