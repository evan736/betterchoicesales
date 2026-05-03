"""Email preview endpoints — render existing email templates and send
to a specified address WITHOUT touching production data.

Useful for:
  - Verifying template changes (e.g. headshot rendering)
  - Showing customers what an email will look like before triggering
  - QA after carrier-specific template edits

These endpoints DO send a real email via Mailgun (otherwise we couldn't
verify how it actually renders in different mail clients). The
recipient is whoever is specified in the URL — typically
evan@betterchoiceins.com for testing. Real customer records are
NEVER created or modified by these endpoints.

Admin only.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email-preview", tags=["email-preview"])


@router.post("/welcome/{recipient_email}")
def preview_welcome_email(
    recipient_email: str,
    client_name: str = Query("Test Customer", description="Sample customer name"),
    carrier: str = Query("Progressive", description="Carrier — drives template selection"),
    policy_type: str = Query("auto", description="auto, home, motorcycle, etc."),
    producer_name: str = Query("Evan Larson", description="Producer name (Evan = headshot rendered)"),
    producer_email: str = Query("evan@betterchoiceins.com", description="Producer email for Reply-To"),
    current_user: User = Depends(get_current_user),
):
    """Send a welcome email preview to recipient_email using sample data.

    Renders the SAME template that fires when a real sale is created.
    No real Sale record is created. The email goes to whoever you
    specify in the URL.

    Use producer_name='Evan Larson' to verify the headshot renders.
    Use producer_name='Joseph Rivera' to verify other producers
    correctly skip the headshot.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if "@" not in recipient_email:
        raise HTTPException(status_code=400, detail="Invalid email")

    try:
        from app.services.welcome_email import send_welcome_email
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"welcome_email import: {e}")

    # Use a fake sale_id high enough that no real sale collides — survey
    # link still renders, just won't go anywhere meaningful when clicked
    fake_sale_id = 999999
    fake_policy_number = "PREVIEW-TEST-12345"

    result = send_welcome_email(
        to_email=recipient_email,
        client_name=client_name,
        policy_number=fake_policy_number,
        carrier=carrier,
        producer_name=producer_name,
        sale_id=fake_sale_id,
        policy_type=policy_type,
        producer_email=producer_email,
    )

    return {
        "success": result.get("success", False) if isinstance(result, dict) else False,
        "sent_to": recipient_email,
        "with": {
            "client_name": client_name,
            "carrier": carrier,
            "policy_type": policy_type,
            "producer_name": producer_name,
            "producer_email": producer_email,
        },
        "headshot_should_render": producer_name.lower().split()[0] == "evan",
        "raw_result": str(result)[:500],
    }


@router.post("/quote/{recipient_email}")
def preview_quote_email(
    recipient_email: str,
    prospect_name: str = Query("Test Prospect", description="Sample prospect name"),
    carrier: str = Query("Progressive", description="Carrier name"),
    policy_type: str = Query("auto", description="auto, home, motorcycle, etc."),
    premium: str = Query("$1,250.00", description="Total premium with $ prefix"),
    premium_term: str = Query("6 months", description="6 months / 12 months"),
    effective_date: str = Query("2026-06-01", description="YYYY-MM-DD"),
    agent_name: str = Query("Evan Larson", description="Producer name (Evan = headshot rendered)"),
    agent_email: str = Query("evan@betterchoiceins.com"),
    agent_phone: str = Query("(847) 908-5665"),
    additional_notes: str = Query("", description="Optional inline note"),
    current_user: User = Depends(get_current_user),
):
    """Send a quote email preview using sample data. No real Quote
    record is created.

    Renders the same template that fires when a producer sends a real
    quote. Use agent_name='Evan Larson' to verify headshot rendering.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if "@" not in recipient_email:
        raise HTTPException(status_code=400, detail="Invalid email")

    try:
        from app.services.quote_email import send_quote_email
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"quote_email import: {e}")

    result = send_quote_email(
        to_email=recipient_email,
        prospect_name=prospect_name,
        carrier=carrier,
        policy_type=policy_type,
        premium=premium,
        premium_term=premium_term,
        effective_date=effective_date,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_phone=agent_phone,
        additional_notes=additional_notes,
        # Skip PDF attachment for previews
        pdf_path=None,
        pdf_filename=None,
        quote_id=None,  # Suppresses the bind URL since fake
        unsubscribe_token=None,
    )

    return {
        "success": result.get("success", False) if isinstance(result, dict) else False,
        "sent_to": recipient_email,
        "with": {
            "prospect_name": prospect_name,
            "carrier": carrier,
            "policy_type": policy_type,
            "premium": premium,
            "premium_term": premium_term,
            "agent_name": agent_name,
        },
        "headshot_should_render": agent_name.lower().split()[0] == "evan",
        "raw_result": str(result)[:500],
    }


@router.post("/quote-followup/{recipient_email}")
def preview_quote_followup_email(
    recipient_email: str,
    prospect_name: str = Query("Test Prospect"),
    carrier: str = Query("Progressive"),
    policy_type: str = Query("auto"),
    premium: float = Query(1250.00),
    premium_term: str = Query("6 months"),
    agent_name: str = Query("Evan Larson"),
    agent_email: str = Query("evan@betterchoiceins.com"),
    day: int = Query(3, description="3, 7, 14, or 90 — which step in the follow-up sequence"),
    current_user: User = Depends(get_current_user),
):
    """Send a quote follow-up email preview. Tests any of the day-3,
    day-7, day-14, or day-90 follow-up touchpoints."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if "@" not in recipient_email:
        raise HTTPException(status_code=400, detail="Invalid email")

    try:
        from app.services.quote_followup_email import build_followup_email
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"quote_followup import: {e}")

    subject, html = build_followup_email(
        prospect_name=prospect_name,
        carrier=carrier,
        policy_type=policy_type,
        premium=premium,
        premium_term=premium_term,
        agent_name=agent_name,
        agent_email=agent_email,
        quote_id=999999,
        day=day,
        unsubscribe_token="preview-token",
    )
    if not subject:
        raise HTTPException(status_code=400, detail=f"Invalid day: {day}")

    from app.core.config import settings
    import requests
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")

    resp = requests.post(
        f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data={
            "from": "Better Choice Insurance <sales@betterchoiceins.com>",
            "to": [recipient_email],
            "subject": f"[PREVIEW day{day}] {subject}",
            "html": html,
            "h:Reply-To": agent_email or "sales@betterchoiceins.com",
            "v:email_type": "quote_followup_preview",
        },
        timeout=15,
    )
    return {
        "success": resp.status_code == 200,
        "status_code": resp.status_code,
        "sent_to": recipient_email,
        "rendered_subject": subject,
        "headshot_should_render": agent_name.lower().split()[0] == "evan",
    }
