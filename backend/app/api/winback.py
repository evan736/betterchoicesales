"""Win-Back Campaign API.

Targets cancelled customers for re-marketing.
Requirements:
- Customer had active policy for >= 6 months
- Agent can manually exclude customers
- Integrates with GHL for outreach sequences
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.campaign import WinBackCampaign
from app.models.customer import Customer, CustomerPolicy
from app.models.sale import Sale

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/winback", tags=["Win-Back Campaigns"])


class WinBackExclude(BaseModel):
    reason: Optional[str] = None


class WinBackCreate(BaseModel):
    """Manually add a customer to win-back campaign."""
    customer_id: Optional[int] = None
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    line_of_business: Optional[str] = None
    cancellation_date: Optional[str] = None
    cancellation_reason: Optional[str] = None


# ── Email template (v2 — plain-text feel, round-robin producer voice) ──

# The three round-robin producers. Round-robin assignment is set when
# the WinBackCampaign record is created (in agent_name) so the same
# producer handles all touchpoints for one customer (a customer who
# replies to Joseph's email gets continuity if Joseph also handles
# the follow-up). Update this list if team composition changes.
WINBACK_ROUND_ROBIN = [
    {
        "username": "joseph.rivera",
        "full_name": "Joseph Rivera",
        "first_name": "Joseph",
        "email": "joseph@betterchoiceins.com",
    },
    {
        "username": "evan.larson",
        "full_name": "Evan Larson",
        "first_name": "Evan",
        "email": "evan@betterchoiceins.com",
    },
    {
        "username": "giulian.baez",
        "full_name": "Giulian Baez",
        "first_name": "Giulian",
        "email": "giulian@betterchoiceins.com",
    },
]


def _get_assigned_producer(campaign: WinBackCampaign) -> dict:
    """Return the round-robin producer assigned to this campaign.

    Resolution order:
      1. If campaign.agent_name matches one of joseph/evan/giulian
         (by username or full_name), use that — preserves continuity
         on follow-ups.
      2. Otherwise, fall back to round-robin based on campaign.id %
         3 (deterministic given the id, so same email-builder result
         every time it's called).
    """
    name = (campaign.agent_name or "").lower().strip()
    for p in WINBACK_ROUND_ROBIN:
        if name in (p["username"], p["full_name"].lower(), p["first_name"].lower()):
            return p
    # Deterministic fallback by id
    idx = (campaign.id or 0) % len(WINBACK_ROUND_ROBIN)
    return WINBACK_ROUND_ROBIN[idx]


def _has_lob(campaign: WinBackCampaign, *targets: str) -> bool:
    """Did the customer have any of the listed lines of business with us?"""
    lob = (campaign.line_of_business or "").lower()
    if not lob:
        return False
    return any(t in lob for t in targets)


def _build_winback_email_v2(campaign: WinBackCampaign, touchpoint: int) -> tuple[str, str]:
    """Build (subject, plain-text-style HTML body) for a winback email.

    Subject lines lean on the rate-decrease hook (the actual reason
    to open). Variety across producer × touchpoint combinations so
    a customer never sees identical subjects on consecutive contacts.

    Body avoids:
      - Stacked "Mind if... Mind sharing..." asks
      - Defensive hedging
      - Generic closes ("whatever's easier")

    Tone: casual, like a real producer typed it. No header banner,
    no CTA buttons, no marketing-speak.

    Per-producer voice variation. LOB-aware copy.
    """
    first_name = (campaign.customer_name or "there").split()[0]
    producer = _get_assigned_producer(campaign)

    # Determine scope based on what they had with us
    has_home = _has_lob(campaign, "home", "ho-3", "ho-6", "renters", "condo", "dwelling")
    has_auto = _has_lob(campaign, "auto", "motorcycle", "rv", "boat")

    if has_home and has_auto:
        scope_phrase = "home and auto"
        verify = "Send the year/make/model on the cars and a rough year on the roof — I'll handle the rest."
    elif has_home:
        scope_phrase = "home"
        verify = "If you can ballpark when the roof was last replaced, I can run a few options."
    elif has_auto:
        scope_phrase = "auto"
        verify = "Send over the year/make/model on the cars and I'll dig in."
    else:
        scope_phrase = "insurance"
        verify = "Send a quick snapshot of what you have right now and I'll match it up."

    # Their prior carrier with us — gives the email specificity if available
    prior_carrier = (campaign.carrier or "").strip()
    if prior_carrier.isupper():
        prior_carrier = prior_carrier.title()

    # ─────── PER-PRODUCER, PER-TOUCHPOINT CONTENT ───────

    if producer["first_name"] == "Joseph":
        if touchpoint == 1:
            subject = "rates dropped — worth a fresh look?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Joseph Rivera over at Better Choice Insurance. You were previously with "
                f"our agency and I wanted to reach out — we just took some pretty big rate "
                f"decreases across most of our carriers.<br><br>"
                f"Want me to put fresh quotes together for {scope_phrase}? {verify}<br><br>"
                f"Or 5 minutes on the phone: (847) 908-5665."
            )
        elif touchpoint == 2:
            subject = f"{first_name} — circling back on rate decreases"
            body = (
                f"Hey {first_name},<br><br>"
                f"Joseph at Better Choice. Sent you a note a few months back about rates "
                f"coming down — figured I'd try once more in case it got lost.<br><br>"
                f"Worth me running new numbers on {scope_phrase}? Even if you're happy "
                f"where you are, no harm in seeing what's out there.<br><br>"
                f"Reply or text/call (847) 908-5665."
            )
        else:
            subject = f"rates moved again — quick check, {first_name}?"
            body = (
                f"Hey {first_name}, hope you're doing well. Carriers have continued cutting "
                f"rates and I wanted to take one more shot at flagging it for you.<br><br>"
                f"If you want a fresh quote on {scope_phrase}, just hit reply with what "
                f"you're paying now and I'll dig in.<br><br>"
                f"No pressure either way."
            )

    elif producer["first_name"] == "Evan":
        if touchpoint == 1:
            subject = "rates came back down — wanted to flag it"
            body = (
                f"Hey {first_name},<br><br>"
                f"Evan Larson at Better Choice. You were previously with us and I'd hate "
                f"for you to miss this — most of our carriers filed rate decreases over "
                f"the last few months.<br><br>"
                f"Want me to put fresh quotes together for {scope_phrase}? {verify}<br><br>"
                f"Or grab 5 minutes on the phone: (847) 908-5665."
            )
        elif touchpoint == 2:
            subject = f"{first_name}, carriers cut rates again"
            body = (
                f"Hey {first_name},<br><br>"
                f"Evan at Better Choice. Following up on the note from a few months back. "
                f"Carriers have continued filing decreases — first real reversal in a couple "
                f"of years.<br><br>"
                f"Worth a quick comparison on {scope_phrase}?<br><br>"
                f"If now's not a good time, just let me know when is."
            )
        else:
            subject = f"rates still moving — quick look, {first_name}?"
            body = (
                f"Hey {first_name}, hope all is well. Touching base — if you're getting "
                f"close to a renewal or just want a second set of eyes on {scope_phrase}, "
                f"I'd be glad to take a look.<br><br>"
                f"Reply with your dec page or current premium and I'll dig in.<br><br>"
                f"Talk soon."
            )

    else:  # Giulian
        if touchpoint == 1:
            subject = "rates are dropping — worth a fresh quote?"
            body = (
                f"Hey {first_name},<br><br>"
                f"Giulian Baez at Better Choice Insurance. You previously had insurance "
                f"with our agency and I wanted to reach back out — we just took some "
                f"pretty big rate decreases with a bunch of our carriers.<br><br>"
                f"Want me to put fresh quotes together for {scope_phrase}? {verify}<br><br>"
                f"Or hop on a quick call: (847) 908-5665."
            )
        elif touchpoint == 2:
            subject = f"{first_name} — second try, rates are down"
            body = (
                f"Hey {first_name},<br><br>"
                f"Giulian at Better Choice — wanted to circle back. Tried reaching out a "
                f"few months ago about {scope_phrase} since rates dropped, didn't hear back, "
                f"figured I'd give it one more shot.<br><br>"
                f"Want me to run a few options?<br><br>"
                f"Easy to text/call too if email isn't your thing."
            )
        else:
            subject = f"carriers came down again, {first_name}"
            body = (
                f"Hey {first_name}, just checking back in. If you're getting close to renewal "
                f"or want a fresh quote for the heck of it, I've got you.<br><br>"
                f"Reply or text me — (847) 908-5665."
            )

    # Headshot only for Evan's emails
    from app.services.producer_signatures import producer_headshot_html
    headshot_html = producer_headshot_html(producer["first_name"], size_px=96)

    body_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1a1a1a;">
<div style="max-width:560px;margin:0 auto;padding:24px 20px;">
<p style="margin:0 0 16px 0;">{body}</p>
<div style="margin:0 0 4px 0;">{headshot_html}— {producer['first_name']}</div>
<p style="margin:0 0 2px 0;color:#666;font-size:13px;">{producer['full_name']}</p>
<p style="margin:0 0 2px 0;color:#666;font-size:13px;">Better Choice Insurance Group</p>
<p style="margin:0 0 2px 0;color:#666;font-size:13px;">(847) 908-5665 &middot; {producer['email']}</p>
<p style="margin:24px 0 0 0;color:#a3a3a3;font-size:11px;border-top:1px solid #eee;padding-top:12px;">
<img src="https://www.betterchoiceins.com/images/logo.png" alt="Better Choice Insurance Group" width="140" style="display:block;margin:0 0 8px 0;max-width:140px;height:auto;" /><br>
Better Choice Insurance Group &middot; 300 Cardinal Dr Suite 220, Saint Charles, IL 60175<br>
Don't want these? Just reply STOP and I'll take you off the list.
</p>
</div>
</body></html>"""

    return subject, body_html


def _build_winback_text_v2(campaign: WinBackCampaign, touchpoint: int) -> str:
    """Build SMS body for a winback text. Single message, plain text,
    short. Includes brand identification and STOP/HELP per A2P 10DLC
    requirements.

    NOT auto-sent — this is built but only fires when:
      1. TWILIO_A2P_APPROVED env var is 'true' (manual gate)
      2. The campaign has been activated and is on the right touchpoint
    """
    first_name = (campaign.customer_name or "there").split()[0]
    producer = _get_assigned_producer(campaign)

    has_home = _has_lob(campaign, "home", "ho-3", "ho-6", "renters", "condo", "dwelling")
    has_auto = _has_lob(campaign, "auto", "motorcycle", "rv", "boat")

    if has_home and has_auto:
        scope = "home and auto"
    elif has_home:
        scope = "home"
    elif has_auto:
        scope = "auto"
    else:
        scope = "insurance"

    if touchpoint == 1:
        return (
            f"Hi {first_name}, this is {producer['first_name']} at Better Choice Insurance. "
            f"You were previously with our agency — we took some big rate decreases recently and "
            f"I wanted to see if you'd let me run new {scope} quotes for you. Reply YES or call "
            f"(847) 908-5665. Reply STOP to opt out."
        )
    elif touchpoint == 2:
        return (
            f"Hey {first_name}, {producer['first_name']} from Better Choice again. Following up "
            f"on the note I sent — worth a quick look at your {scope}? "
            f"(847) 908-5665. Reply STOP to opt out."
        )
    else:
        return (
            f"Hi {first_name}, {producer['first_name']} at Better Choice. "
            f"Just checking back in — let me know if you'd like new quotes. "
            f"(847) 908-5665. STOP to opt out."
        )


# Keep legacy function for backward compat with the old /activate endpoint
def _build_winback_email_html(campaign: WinBackCampaign, touchpoint: int) -> str:
    """LEGACY: original branded template. Kept so old code paths still work.
    New code should use _build_winback_email_v2 which returns (subject, body)."""
    _, body = _build_winback_email_v2(campaign, touchpoint)
    return body


def _send_winback_email(campaign: WinBackCampaign, touchpoint: int) -> bool:
    """Send a winback email via Mailgun using the v2 plain-text-style
    templates. From-line is the round-robin-assigned producer's name +
    sales@ domain, Reply-To is the producer's actual mailbox so any
    customer reply lands in their inbox.
    """
    from app.core.config import settings
    import requests

    if not campaign.customer_email:
        return False
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Winback send blocked — Mailgun not configured")
        return False

    producer = _get_assigned_producer(campaign)
    subject, html = _build_winback_email_v2(campaign, touchpoint)

    # From line uses the producer's name + sales@ apex domain so it
    # looks personal but the reply-to keeps the conversation in their
    # actual mailbox.
    from_header = f"{producer['full_name']} <sales@betterchoiceins.com>"

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": from_header,
                "to": [campaign.customer_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": producer["email"],
                # Tag for analytics + email_type so the centralized
                # mailer hook adds List-Unsubscribe (marketing email).
                "v:email_type": "winback",
                "v:winback_campaign_id": str(campaign.id),
                "v:touchpoint": str(touchpoint),
                "v:assigned_producer": producer["username"],
            },
        )
        if resp.status_code == 200:
            logger.info(
                "Winback email sent: campaign=%s touchpoint=%s to=%s producer=%s",
                campaign.id, touchpoint, campaign.customer_email, producer["username"],
            )
            return True
        else:
            logger.error(
                "Winback email failed: campaign=%s status=%s body=%s",
                campaign.id, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as e:
        logger.error(f"Win-back email error: campaign={campaign.id} {e}")
        return False


def _send_winback_text(campaign: WinBackCampaign, touchpoint: int, db: Session) -> bool:
    """Send a winback SMS via Twilio. GATED: only fires when env var
    TWILIO_A2P_APPROVED='true'. Until A2P 10DLC is approved by TCR,
    every call to this function returns False with a log message — the
    infrastructure is wired up but no actual texts go out.

    Once A2P is approved, flipping the env var on Render will
    immediately enable text sending without a code deploy.
    """
    import os
    if os.getenv("TWILIO_A2P_APPROVED", "false").lower() != "true":
        logger.info(
            "Winback SMS skipped — TWILIO_A2P_APPROVED not enabled. "
            "campaign=%s touchpoint=%s", campaign.id, touchpoint,
        )
        return False

    if not campaign.customer_phone:
        return False

    # Reuse the existing twilio_sms.send helper so all numbers go
    # through the same audited send pipeline (status callbacks,
    # message logging, opt-out handling).
    try:
        from app.services.twilio_sms import send_message
        body = _build_winback_text_v2(campaign, touchpoint)

        # send_message is async — call it via sync wrapper for the
        # scheduler context. If it returns failure, log and continue.
        import asyncio
        result = asyncio.run(send_message(
            to_number=campaign.customer_phone,
            content=body,
            db=db,
            customer_id=campaign.customer_id,
            context=f"winback_t{touchpoint}",
            sent_by=f"winback_scheduler_{_get_assigned_producer(campaign)['username']}",
        ))
        if result and result.get("success"):
            logger.info(
                "Winback SMS sent: campaign=%s touchpoint=%s to=%s sid=%s",
                campaign.id, touchpoint, campaign.customer_phone, result.get("sid"),
            )
            return True
        else:
            logger.error(
                "Winback SMS failed: campaign=%s result=%s", campaign.id, result,
            )
            return False
    except Exception as e:
        logger.error(f"Winback SMS error: campaign={campaign.id} {e}")
        return False


# ── API Endpoints ──

@router.post("/scan")
def scan_for_winback_candidates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan for cancelled customers eligible for win-back (>= 6 months active).

    Looks at CustomerPolicy records with status='Cancelled' or 'Expired'.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    # Find cancelled policies with sufficient tenure
    cancelled_policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.status.in_(["Cancelled", "cancelled", "Expired", "expired"]),
        CustomerPolicy.effective_date.isnot(None),
    ).all()

    candidates = []
    skipped = 0
    already_exists = 0

    for pol in cancelled_policies:
        # Calculate tenure
        cancel_date = pol.expiration_date or pol.updated_at or datetime.utcnow()
        if pol.effective_date:
            months = (cancel_date.year - pol.effective_date.year) * 12 + (cancel_date.month - pol.effective_date.month)
        else:
            months = 0

        # Must have been active >= 6 months
        if months < 6:
            skipped += 1
            continue

        # Get customer info
        customer = db.query(Customer).filter(Customer.id == pol.customer_id).first()
        if not customer:
            skipped += 1
            continue

        # Skip if no contact info
        if not customer.email and not customer.phone:
            skipped += 1
            continue

        # Check if already in win-back
        existing = db.query(WinBackCampaign).filter(
            WinBackCampaign.customer_id == customer.id,
            WinBackCampaign.status.in_(["pending", "active"]),
        ).first()
        if existing:
            already_exists += 1
            continue

        # Create win-back record
        wb = WinBackCampaign(
            customer_id=customer.id,
            nowcerts_insured_id=customer.nowcerts_insured_id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            customer_phone=customer.phone or customer.mobile_phone,
            policy_number=pol.policy_number,
            carrier=pol.carrier,
            line_of_business=pol.line_of_business,
            premium_at_cancel=pol.premium,
            original_effective_date=pol.effective_date,
            cancellation_date=cancel_date,
            months_active=months,
            agent_name=customer.agent_name,
            status="pending",
        )
        db.add(wb)
        candidates.append(customer.full_name)

    db.commit()

    return {
        "candidates_found": len(candidates),
        "skipped_short_tenure": skipped,
        "already_in_campaign": already_exists,
        "new_candidates": candidates[:50],
    }


@router.get("/")
def list_winback_campaigns(
    status: Optional[str] = None,
    include_excluded: bool = False,
    limit: int = 500,
    skip: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List win-back campaigns. Default limit bumped to 500 to handle
    bulk-enrolled cohorts. Pass ?limit=N&skip=N for pagination."""
    query = db.query(WinBackCampaign)

    if not include_excluded:
        query = query.filter(WinBackCampaign.excluded == False)
    if status:
        query = query.filter(WinBackCampaign.status == status)

    total = query.count()
    campaigns = query.order_by(WinBackCampaign.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "returned": len(campaigns),
        "skip": skip,
        "limit": limit,
        "campaigns": [
            {
                "id": c.id,
                "customer_name": c.customer_name,
                "customer_email": c.customer_email,
                "customer_phone": c.customer_phone,
                "policy_number": c.policy_number,
                "carrier": c.carrier,
                "line_of_business": c.line_of_business,
                "premium_at_cancel": float(c.premium_at_cancel) if c.premium_at_cancel else None,
                "months_active": c.months_active,
                "cancellation_date": c.cancellation_date.isoformat() if c.cancellation_date else None,
                "cancellation_reason": c.cancellation_reason,
                "status": c.status,
                "excluded": c.excluded,
                "excluded_reason": c.excluded_reason,
                "touchpoint_count": c.touchpoint_count,
                "last_touchpoint_at": c.last_touchpoint_at.isoformat() if c.last_touchpoint_at else None,
                "agent_name": c.agent_name,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in campaigns
        ],
    }


@router.post("/{campaign_id}/exclude")
def exclude_from_winback(
    campaign_id: int,
    data: WinBackExclude,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exclude a customer from win-back campaign (agent discretion)."""
    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.excluded = True
    campaign.excluded_by = current_user.id
    campaign.excluded_reason = data.reason or "Excluded by agent"
    campaign.status = "excluded"
    db.commit()

    return {"id": campaign.id, "status": "excluded", "reason": campaign.excluded_reason}


@router.post("/{campaign_id}/include")
def include_in_winback(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-include a previously excluded customer."""
    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.excluded = False
    campaign.excluded_by = None
    campaign.excluded_reason = None
    campaign.status = "pending"
    db.commit()

    return {"id": campaign.id, "status": "pending"}


@router.post("/{campaign_id}/activate")
def activate_winback(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate a win-back campaign (send first touchpoint)."""
    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.excluded:
        raise HTTPException(status_code=400, detail="This customer has been excluded from win-back")

    # Send first email
    email_sent = _send_winback_email(campaign, touchpoint=1)

    campaign.status = "active"
    campaign.touchpoint_count = 1
    campaign.last_touchpoint_at = datetime.utcnow()
    campaign.next_touchpoint_at = datetime.utcnow() + timedelta(days=14)

    # Fire GHL webhook
    try:
        from app.services.ghl_webhook import get_ghl_service
        ghl = get_ghl_service()
        ghl.fire_winback(
            customer_name=campaign.customer_name,
            email=campaign.customer_email or "",
            phone=campaign.customer_phone or "",
            carrier=campaign.carrier or "",
            policy_type=campaign.line_of_business or "",
            months_active=campaign.months_active or 0,
            cancel_reason=campaign.cancellation_reason or "",
        )
        campaign.ghl_webhook_sent = True
    except Exception as e:
        logger.debug(f"GHL webhook failed: {e}")

    # NowCerts note
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if nc.is_configured:
            parts = campaign.customer_name.strip().split(maxsplit=1)
            nc.insert_note({
                "subject": f"Win-Back Campaign Started — {campaign.policy_number or 'N/A'} | Former customer outreach initiated",
                "insured_email": campaign.customer_email or "",
                "insured_first_name": parts[0] if parts else "",
                "insured_last_name": parts[1] if len(parts) > 1 else "",
                "type": "Email",
                "creator_name": "BCI Win-Back System",
                "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
            })
    except Exception as e:
        logger.debug(f"NowCerts note failed: {e}")

    db.commit()

    return {
        "id": campaign.id,
        "status": "active",
        "email_sent": email_sent,
        "ghl_webhook_sent": campaign.ghl_webhook_sent,
        "next_touchpoint": campaign.next_touchpoint_at.isoformat() if campaign.next_touchpoint_at else None,
    }


@router.post("/activate-all")
def activate_all_pending(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate all pending (non-excluded) win-back campaigns."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    pending = db.query(WinBackCampaign).filter(
        WinBackCampaign.status == "pending",
        WinBackCampaign.excluded == False,
    ).all()

    activated = 0
    for campaign in pending:
        email_sent = _send_winback_email(campaign, touchpoint=1)
        campaign.status = "active"
        campaign.touchpoint_count = 1
        campaign.last_touchpoint_at = datetime.utcnow()
        campaign.next_touchpoint_at = datetime.utcnow() + timedelta(days=14)

        try:
            from app.services.ghl_webhook import get_ghl_service
            ghl = get_ghl_service()
            ghl.fire_winback(
                customer_name=campaign.customer_name,
                email=campaign.customer_email or "",
                phone=campaign.customer_phone or "",
                carrier=campaign.carrier or "",
                policy_type=campaign.line_of_business or "",
                months_active=campaign.months_active or 0,
                cancel_reason=campaign.cancellation_reason or "",
            )
            campaign.ghl_webhook_sent = True
        except:
            pass

        activated += 1

    db.commit()
    return {"activated": activated, "total_pending": len(pending)}


@router.post("/create")
def create_winback_manually(
    data: WinBackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually add a customer to win-back campaign."""
    cancel_dt = None
    if data.cancellation_date:
        try:
            cancel_dt = datetime.strptime(data.cancellation_date, "%Y-%m-%d")
        except ValueError:
            pass

    wb = WinBackCampaign(
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        policy_number=data.policy_number,
        carrier=data.carrier,
        line_of_business=data.line_of_business,
        cancellation_date=cancel_dt,
        cancellation_reason=data.cancellation_reason,
        months_active=6,  # manually added = assumed qualified
        agent_name=current_user.username,
        status="pending",
    )
    db.add(wb)
    db.commit()
    db.refresh(wb)

    return {"id": wb.id, "status": "pending", "customer_name": wb.customer_name}


# ─────────────────────────────────────────────────────────────────────
# Bulk Create from Analysis
# ─────────────────────────────────────────────────────────────────────


class BulkAddFromAnalysis(BaseModel):
    """Take a list of customer IDs from the lost-account-analysis output
    and create WinBackCampaign records for each. Default status='pending'
    so they're queued for review, NOT auto-sent. Skips any customer who
    already has an open winback record.
    """
    customer_ids: list[int]


@router.post("/bulk-add-from-analysis")
def bulk_add_from_analysis(
    data: BulkAddFromAnalysis,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create winback records for the given customer IDs (status=pending).

    Designed to be called from the frontend after the user reviews the
    /lost-account-analysis output and selects which customers to enroll.
    Records are created with status='pending' — they are NOT activated
    or sent until you explicitly call POST /api/winback/{id}/activate
    or POST /api/winback/activate-all.
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")

    if not data.customer_ids:
        raise HTTPException(status_code=400, detail="customer_ids is required and must be non-empty")
    if len(data.customer_ids) > 5000:
        raise HTTPException(status_code=400, detail="Too many customer_ids (max 5000 per call)")

    created = 0
    skipped_already_exists = 0
    skipped_not_found = 0
    skipped_no_contact = 0
    new_records: list[dict] = []

    for cid in data.customer_ids:
        customer = db.query(Customer).filter(Customer.id == cid).first()
        if not customer:
            skipped_not_found += 1
            continue

        if not customer.email and not customer.phone and not customer.mobile_phone:
            skipped_no_contact += 1
            continue

        # Skip if already enrolled
        existing = db.query(WinBackCampaign).filter(
            WinBackCampaign.customer_id == customer.id,
            WinBackCampaign.status.in_(["pending", "active"]),
        ).first()
        if existing:
            skipped_already_exists += 1
            continue

        # Find the most recent cancelled policy and the most recent
        # policy with non-zero premium across all of this customer's
        # policies (renewal-fallback for premium_at_cancel)
        all_pols = db.query(CustomerPolicy).filter(
            CustomerPolicy.customer_id == customer.id
        ).all()

        if not all_pols:
            continue

        all_pols_sorted = sorted(
            all_pols,
            key=lambda p: p.expiration_date or p.effective_date or datetime.min,
            reverse=True,
        )
        latest_pol = all_pols_sorted[0]
        premium_amt = None
        for p in all_pols_sorted:
            if p.premium and float(p.premium) > 0:
                premium_amt = float(p.premium)
                break

        # Tenure based on earliest known effective_date
        earliest_eff = min(
            (p.effective_date for p in all_pols if p.effective_date),
            default=None,
        )
        months = 0
        if earliest_eff and latest_pol.expiration_date:
            months = (latest_pol.expiration_date.year - earliest_eff.year) * 12 + \
                     (latest_pol.expiration_date.month - earliest_eff.month)

        wb = WinBackCampaign(
            customer_id=customer.id,
            nowcerts_insured_id=customer.nowcerts_insured_id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            customer_phone=customer.phone or customer.mobile_phone,
            policy_number=latest_pol.policy_number,
            carrier=latest_pol.carrier,
            line_of_business=latest_pol.line_of_business,
            premium_at_cancel=premium_amt,
            original_effective_date=earliest_eff,
            cancellation_date=latest_pol.expiration_date or latest_pol.updated_at,
            months_active=max(months, 0),
            agent_name=customer.agent_name or current_user.username,
            status="pending",
        )
        db.add(wb)
        created += 1
        new_records.append({
            "customer_id": customer.id,
            "customer_name": customer.full_name,
        })

    db.commit()

    return {
        "created": created,
        "skipped_already_exists": skipped_already_exists,
        "skipped_not_found": skipped_not_found,
        "skipped_no_contact": skipped_no_contact,
        "new_records_sample": new_records[:20],
    }
# ─────────────────────────────────────────────────────────────────────
# This is the analytical view (read-only, no records created) that
# answers: "How much premium have we lost in fully-cancelled accounts,
# and who are they?"
#
# DEFINITION OF 'LOST ACCOUNT':
#   A customer whose entire book with us is gone — every policy in
#   customer_policies has a non-active status. If the same person has
#   ANY active policy under ANY duplicate profile, they are not lost.
#
# DUPLICATE CROSS-CHECK:
#   Before declaring an account lost, we look for other customer rows
#   that share the same email, phone (last 10 digits), or normalized
#   full name. If any of those duplicate profiles has an active policy,
#   we treat the original as a duplicate-of-active and exclude it.
#   This matches the existing /api/customers/duplicates logic exactly.

ACTIVE_STATUSES_LOWER = {"active", "in force", "inforce"}


def _is_active_status(status: Optional[str]) -> bool:
    return (status or "").strip().lower() in ACTIVE_STATUSES_LOWER


def _phone_key(phone: Optional[str]) -> Optional[str]:
    """Last 10 digits of a phone, or None if unusable."""
    if not phone:
        return None
    digits = "".join(d for d in phone if d.isdigit())
    if len(digits) < 7:
        return None
    return digits[-10:]


@router.get("/lost-account-analysis")
def lost_account_analysis(
    months_back: Optional[int] = Query(None, description="If set, only include customers with cancellations within this many months"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Analyze fully-lost customer accounts and total cancelled premium.

    Returns a per-customer breakdown plus aggregates by carrier, producer,
    and cancellation date. Does NOT create any winback records or send
    anything — read-only analysis.

    Definition of 'lost': customer has ZERO active policies in our local
    cache (which mirrors NowCerts). Duplicates are cross-checked by
    name/phone/email before declaring a customer lost — if any duplicate
    profile has an active policy we exclude the customer from the
    'fully lost' set.
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")

    # ── Step 1: Build duplicate index across ALL customers ──
    # We need this BEFORE filtering to lost candidates, because a 'lost'
    # candidate might have a duplicate that's still active and we
    # wouldn't see that connection if we only loaded lost customers.
    all_customers = db.query(Customer).all()

    # Map customer_id → set of duplicate customer_ids (excluding self)
    name_groups: dict[str, list[int]] = {}
    phone_groups: dict[str, list[int]] = {}
    email_groups: dict[str, list[int]] = {}

    for c in all_customers:
        nk = (c.full_name or "").strip().lower()
        if nk and len(nk) > 2:
            name_groups.setdefault(nk, []).append(c.id)
        for ph in (c.phone, c.mobile_phone):
            pk = _phone_key(ph)
            if pk:
                phone_groups.setdefault(pk, []).append(c.id)
        ek = (c.email or "").strip().lower()
        if ek and "@" in ek:
            email_groups.setdefault(ek, []).append(c.id)

    duplicates_of: dict[int, set[int]] = {}
    for groups in (name_groups, phone_groups, email_groups):
        for ids in groups.values():
            if len(ids) < 2:
                continue
            id_set = set(ids)
            for cid in id_set:
                duplicates_of.setdefault(cid, set()).update(id_set - {cid})

    # ── Step 2: Determine which customers have ANY active policy ──
    # Single SQL pass to map customer_id → True/False
    customer_has_active: dict[int, bool] = {}
    all_policies = db.query(CustomerPolicy).all()
    customer_policies_map: dict[int, list[CustomerPolicy]] = {}
    for pol in all_policies:
        customer_policies_map.setdefault(pol.customer_id, []).append(pol)
        if _is_active_status(pol.status):
            customer_has_active[pol.customer_id] = True
    # Default everyone else to False
    for c in all_customers:
        customer_has_active.setdefault(c.id, False)

    # ── Step 3: Identify lost customers (no active policies + no
    # duplicate has active policies + at least one cancelled policy
    # with usable premium info) ──
    cutoff_date = None
    if months_back and months_back > 0:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)

    lost_records = []
    excluded_due_to_duplicate = 0
    excluded_due_to_no_premium = 0
    excluded_due_to_old_cancellation = 0
    excluded_no_contact_info = 0

    for c in all_customers:
        if customer_has_active.get(c.id, False):
            continue  # has active policy → not lost

        # Cross-check duplicates
        dup_ids = duplicates_of.get(c.id, set())
        if any(customer_has_active.get(dup_id, False) for dup_id in dup_ids):
            excluded_due_to_duplicate += 1
            continue

        # Their policies (all non-active by definition of being here)
        pols = customer_policies_map.get(c.id, [])
        if not pols:
            continue  # no policies at all — probably a stale prospect

        # ── Premium calculation with renewal-fallback ──
        # For each line of business the customer has had with us, find:
        #   1. the MOST RECENT policy (this gives us the cancellation date)
        #   2. the most recent policy WITH non-zero premium (this gives
        #      us the dollar amount — we walk back through renewals
        #      until we find one)
        # This recovers ~283 customers who would otherwise be excluded
        # because their final/current policy in NowCerts has $0 premium
        # synced (the data is on an earlier renewal of the same line).

        policies_by_lob: dict[str, list[CustomerPolicy]] = {}
        for p in pols:
            lob = (p.line_of_business or "Unknown").strip()
            policies_by_lob.setdefault(lob, []).append(p)

        # Sort each LOB's policies by date descending — newest first
        def _policy_sort_key(p: CustomerPolicy) -> datetime:
            return p.expiration_date or p.effective_date or datetime.min

        latest_policy_per_lob: dict[str, CustomerPolicy] = {}
        premium_per_lob: dict[str, tuple[float, bool]] = {}  # (amount, was_estimated)

        for lob, lob_pols in policies_by_lob.items():
            lob_pols_sorted = sorted(lob_pols, key=_policy_sort_key, reverse=True)

            # Most recent policy = source of truth for cancellation date
            latest_policy_per_lob[lob] = lob_pols_sorted[0]

            # Premium = most recent policy with > 0 premium
            premium_amount = 0.0
            was_estimated = False
            for idx, p in enumerate(lob_pols_sorted):
                if p.premium:
                    try:
                        amt = float(p.premium)
                        if amt > 0:
                            premium_amount = amt
                            was_estimated = (idx > 0)  # not from the most recent record
                            break
                    except (TypeError, ValueError):
                        pass
            premium_per_lob[lob] = (premium_amount, was_estimated)

        total_lost_premium = sum(amt for amt, _ in premium_per_lob.values())
        any_estimated = any(est for _, est in premium_per_lob.values())

        latest_cancel_date = None
        carriers = set()
        for lob, p in latest_policy_per_lob.items():
            if p.carrier:
                carriers.add(p.carrier)
            cd = p.expiration_date or p.updated_at
            if cd and (latest_cancel_date is None or cd > latest_cancel_date):
                latest_cancel_date = cd

        if total_lost_premium <= 0:
            excluded_due_to_no_premium += 1
            continue

        if cutoff_date and latest_cancel_date and latest_cancel_date < cutoff_date:
            excluded_due_to_old_cancellation += 1
            continue

        if not c.email and not c.phone and not c.mobile_phone:
            excluded_no_contact_info += 1
            # Still count them in totals but flag separately

        lost_records.append({
            "customer_id": c.id,
            "nowcerts_insured_id": c.nowcerts_insured_id,
            "full_name": c.full_name,
            "email": c.email,
            "phone": c.phone or c.mobile_phone,
            "city": c.city,
            "state": c.state,
            "agent_name": c.agent_name,
            "policy_count": len(pols),
            "lines_of_business": sorted(latest_policy_per_lob.keys()),
            "carriers": sorted(carriers),
            "total_lost_premium": round(total_lost_premium, 2),
            "premium_was_estimated": any_estimated,
            "latest_cancel_date": latest_cancel_date.isoformat() if latest_cancel_date else None,
            "has_email": bool(c.email),
            "has_phone": bool(c.phone or c.mobile_phone),
            "duplicate_profile_count": len(dup_ids),
        })

    # Sort by lost premium desc — biggest lost accounts first
    lost_records.sort(key=lambda r: r["total_lost_premium"], reverse=True)

    # ── Step 4: Aggregates ──
    grand_total_premium = sum(r["total_lost_premium"] for r in lost_records)

    by_carrier: dict[str, dict] = {}
    for r in lost_records:
        for carrier in r["carriers"] or ["Unknown"]:
            slot = by_carrier.setdefault(carrier, {"customer_count": 0, "premium": 0.0})
            slot["customer_count"] += 1
            slot["premium"] += r["total_lost_premium"] / max(len(r["carriers"]), 1)

    by_producer: dict[str, dict] = {}
    for r in lost_records:
        prod = r["agent_name"] or "Unassigned"
        slot = by_producer.setdefault(prod, {"customer_count": 0, "premium": 0.0})
        slot["customer_count"] += 1
        slot["premium"] += r["total_lost_premium"]

    by_year: dict[str, dict] = {}
    for r in lost_records:
        year = (r["latest_cancel_date"] or "")[:4] or "Unknown"
        slot = by_year.setdefault(year, {"customer_count": 0, "premium": 0.0})
        slot["customer_count"] += 1
        slot["premium"] += r["total_lost_premium"]

    return {
        "filters": {
            "months_back": months_back,
            "cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
        },
        "totals": {
            "lost_customer_count": len(lost_records),
            "lost_premium_total": round(grand_total_premium, 2),
            "lost_customers_with_email": sum(1 for r in lost_records if r["has_email"]),
            "lost_customers_with_phone": sum(1 for r in lost_records if r["has_phone"]),
            "lost_customers_no_contact": sum(1 for r in lost_records if not r["has_email"] and not r["has_phone"]),
            "premium_estimated_from_prior_renewal_count": sum(1 for r in lost_records if r["premium_was_estimated"]),
        },
        "exclusions": {
            "excluded_due_to_active_duplicate": excluded_due_to_duplicate,
            "excluded_due_to_no_premium_data": excluded_due_to_no_premium,
            "excluded_due_to_old_cancellation": excluded_due_to_old_cancellation,
        },
        "by_carrier": [
            {"carrier": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}}
            for k, v in sorted(by_carrier.items(), key=lambda kv: kv[1]["premium"], reverse=True)
        ],
        "by_producer": [
            {"producer": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}}
            for k, v in sorted(by_producer.items(), key=lambda kv: kv[1]["premium"], reverse=True)
        ],
        "by_year": [
            {"year": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}}
            for k, v in sorted(by_year.items(), reverse=True)
        ],
        "top_50_customers": lost_records[:50],
        "all_customer_count": len(lost_records),
    }


# ─────────────────────────────────────────────────────────────────────
# Missing-from-Active Analysis (sales-table backed)
# ─────────────────────────────────────────────────────────────────────
# Different from /lost-account-analysis: that one starts from
# customer_policies (NowCerts cache, only goes back to ~2024). This
# one starts from the sales table (now has 2022+ history via the
# Performology import) and matches against NowCerts to find sales
# whose customer no longer has any active policy.
#
# Catches the customers who:
#   - Were sold a policy 2022-2025
#   - Aren't currently active in NowCerts (cancelled, churned, or
#     never properly synced)
#   - Have contact info we can reach them at
#
# These didn't show up in /lost-account-analysis because their
# customer_policies record either doesn't exist or only shows the
# cancelled side (which the fully-cancelled check still catches),
# but THIS analysis finds them via the sale itself which we know
# happened.

@router.get("/missing-from-active")
def missing_from_active_analysis(
    sale_year_from: int = Query(2022, description="Earliest sale year (default 2022 — BCI era)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find sales whose customer has no active policy in NowCerts today."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    from sqlalchemy import or_

    ACTIVE_LOWER = {"active", "in force", "inforce"}

    sales = db.query(Sale).filter(
        Sale.sale_date >= datetime(sale_year_from, 1, 1),
        Sale.sale_date < datetime(2100, 1, 1),
        or_(Sale.lead_source != "legacy_allstate", Sale.lead_source.is_(None)),
    ).all()

    customers = db.query(Customer).all()
    by_email: dict[str, int] = {}
    by_phone: dict[str, int] = {}
    by_name: dict[str, int] = {}

    def _phone_key(p):
        if not p:
            return None
        digits = "".join(c for c in p if c.isdigit())
        return digits[-10:] if len(digits) >= 7 else None

    for c in customers:
        if c.email:
            by_email[c.email.strip().lower()] = c.id
        for ph in (c.phone, c.mobile_phone):
            pk = _phone_key(ph or "")
            if pk:
                by_phone[pk] = c.id
        if c.full_name:
            by_name[c.full_name.strip().lower()] = c.id

    customer_has_active: dict[int, bool] = {}
    for pol in db.query(CustomerPolicy).all():
        if (pol.status or "").strip().lower() in ACTIVE_LOWER:
            customer_has_active[pol.customer_id] = True

    lost_by_customer: dict[int, dict] = {}
    unmatched_lost: list[dict] = []
    skipped_active = 0
    skipped_legacy = 0

    for sale in sales:
        if sale.lead_source == "legacy_allstate":
            skipped_legacy += 1
            continue

        nc_customer_id = None
        if sale.client_email:
            nc_customer_id = by_email.get(sale.client_email.strip().lower())
        if not nc_customer_id and sale.client_phone:
            pk = _phone_key(sale.client_phone)
            if pk:
                nc_customer_id = by_phone.get(pk)
        if not nc_customer_id and sale.client_name:
            nc_customer_id = by_name.get(sale.client_name.strip().lower())

        if nc_customer_id and customer_has_active.get(nc_customer_id, False):
            skipped_active += 1
            continue

        premium_val = float(sale.written_premium or 0)
        carrier = sale.carrier or "Unknown"

        if nc_customer_id:
            slot = lost_by_customer.setdefault(nc_customer_id, {
                "customer_id": nc_customer_id,
                "client_name": sale.client_name,
                "client_email": sale.client_email,
                "client_phone": sale.client_phone,
                "policy_count": 0,
                "carriers": set(),
                "lines_of_business": set(),
                "total_premium": 0.0,
                "latest_sale_date": None,
                "earliest_sale_date": None,
                "match_source": "nowcerts",
                "sale_ids": [],
            })
            slot["policy_count"] += 1
            slot["carriers"].add(carrier)
            if sale.policy_type:
                slot["lines_of_business"].add(sale.policy_type)
            slot["total_premium"] += premium_val
            sd = sale.sale_date
            if sd:
                if not slot["latest_sale_date"] or sd > slot["latest_sale_date"]:
                    slot["latest_sale_date"] = sd
                if not slot["earliest_sale_date"] or sd < slot["earliest_sale_date"]:
                    slot["earliest_sale_date"] = sd
            slot["sale_ids"].append(sale.id)
        else:
            unmatched_lost.append({
                "customer_id": None,
                "client_name": sale.client_name,
                "client_email": sale.client_email,
                "client_phone": sale.client_phone,
                "policy_count": 1,
                "carriers": [carrier],
                "lines_of_business": [sale.policy_type] if sale.policy_type else [],
                "total_premium": premium_val,
                "latest_sale_date": sale.sale_date.isoformat() if sale.sale_date else None,
                "earliest_sale_date": sale.sale_date.isoformat() if sale.sale_date else None,
                "match_source": "sale_only",
                "sale_ids": [sale.id],
            })

    lost_records = []
    for slot in lost_by_customer.values():
        lost_records.append({
            **slot,
            "carriers": sorted(slot["carriers"]),
            "lines_of_business": sorted(slot["lines_of_business"]),
            "total_premium": round(slot["total_premium"], 2),
            "latest_sale_date": slot["latest_sale_date"].isoformat() if slot["latest_sale_date"] else None,
            "earliest_sale_date": slot["earliest_sale_date"].isoformat() if slot["earliest_sale_date"] else None,
        })
    lost_records.extend(unmatched_lost)
    lost_records.sort(key=lambda r: r["total_premium"], reverse=True)

    total_premium = sum(r["total_premium"] for r in lost_records)
    by_year_agg: dict[int, dict] = {}
    for r in lost_records:
        sd = r.get("latest_sale_date")
        year = int(sd[:4]) if sd else 0
        slot = by_year_agg.setdefault(year, {"customers": 0, "premium": 0.0})
        slot["customers"] += 1
        slot["premium"] += r["total_premium"]

    by_carrier_agg: dict[str, dict] = {}
    for r in lost_records:
        for c in r["carriers"] or ["Unknown"]:
            slot = by_carrier_agg.setdefault(c, {"customers": 0, "premium": 0.0})
            slot["customers"] += 1
            slot["premium"] += r["total_premium"] / max(len(r["carriers"]), 1)

    return {
        "filters": {"sale_year_from": sale_year_from},
        "totals": {
            "lost_records": len(lost_records),
            "matched_to_nowcerts": len(lost_by_customer),
            "unmatched_sale_only": len(unmatched_lost),
            "total_lost_premium": round(total_premium, 2),
            "with_email": sum(1 for r in lost_records if r.get("client_email")),
            "with_phone": sum(1 for r in lost_records if r.get("client_phone")),
            "with_either": sum(1 for r in lost_records if r.get("client_email") or r.get("client_phone")),
        },
        "exclusions": {
            "active_in_nowcerts": skipped_active,
            "legacy_allstate": skipped_legacy,
        },
        "by_year": [
            {"year": y, **{k: round(v, 2) if isinstance(v, float) else v for k, v in by_year_agg[y].items()}}
            for y in sorted(by_year_agg.keys(), reverse=True)
        ],
        "by_carrier": [
            {"carrier": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}}
            for k, v in sorted(by_carrier_agg.items(), key=lambda kv: kv[1]["premium"], reverse=True)
        ],
        "top_50": lost_records[:50],
        "all_count": len(lost_records),
    }


class BulkAddFromMissing(BaseModel):
    customer_ids: list[int] = []
    sale_ids: list[int] = []


@router.post("/bulk-add-from-missing")
def bulk_add_from_missing(
    data: BulkAddFromMissing,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enroll lost-from-sales records into the winback queue (status=pending)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    if not data.customer_ids and not data.sale_ids:
        raise HTTPException(status_code=400, detail="Must provide customer_ids or sale_ids")
    if len(data.customer_ids) + len(data.sale_ids) > 5000:
        raise HTTPException(status_code=400, detail="Too many IDs (max 5000)")

    created = 0
    skipped_already_exists = 0
    skipped_no_contact = 0
    new_records: list[dict] = []

    for cid in data.customer_ids:
        customer = db.query(Customer).filter(Customer.id == cid).first()
        if not customer:
            continue
        if not customer.email and not customer.phone and not customer.mobile_phone:
            skipped_no_contact += 1
            continue
        existing = db.query(WinBackCampaign).filter(
            WinBackCampaign.customer_id == customer.id,
            WinBackCampaign.status.in_(["pending", "active"]),
        ).first()
        if existing:
            skipped_already_exists += 1
            continue

        recent_sale = db.query(Sale).filter(
            Sale.client_name == customer.full_name,
        ).order_by(Sale.sale_date.desc()).first()

        wb = WinBackCampaign(
            customer_id=customer.id,
            nowcerts_insured_id=customer.nowcerts_insured_id,
            customer_name=customer.full_name,
            customer_email=customer.email or (recent_sale.client_email if recent_sale else None),
            customer_phone=customer.phone or customer.mobile_phone or (recent_sale.client_phone if recent_sale else None),
            policy_number=recent_sale.policy_number if recent_sale else None,
            carrier=recent_sale.carrier if recent_sale else None,
            line_of_business=recent_sale.policy_type if recent_sale else None,
            premium_at_cancel=recent_sale.written_premium if recent_sale else None,
            cancellation_date=recent_sale.sale_date if recent_sale else None,
            months_active=12,
            agent_name=customer.agent_name or current_user.username,
            status="pending",
        )
        db.add(wb)
        created += 1
        new_records.append({"customer_id": customer.id, "name": customer.full_name})

    for sid in data.sale_ids:
        sale = db.query(Sale).filter(Sale.id == sid).first()
        if not sale:
            continue
        if not sale.client_email and not sale.client_phone:
            skipped_no_contact += 1
            continue
        existing = db.query(WinBackCampaign).filter(
            WinBackCampaign.customer_name == sale.client_name,
            WinBackCampaign.customer_phone == sale.client_phone,
            WinBackCampaign.status.in_(["pending", "active"]),
        ).first()
        if existing:
            skipped_already_exists += 1
            continue

        wb = WinBackCampaign(
            customer_id=None,
            customer_name=sale.client_name,
            customer_email=sale.client_email,
            customer_phone=sale.client_phone,
            policy_number=sale.policy_number,
            carrier=sale.carrier,
            line_of_business=sale.policy_type,
            premium_at_cancel=sale.written_premium,
            cancellation_date=sale.sale_date,
            months_active=12,
            agent_name=current_user.username,
            status="pending",
        )
        db.add(wb)
        created += 1
        new_records.append({"sale_id": sale.id, "name": sale.client_name})

    db.commit()

    return {
        "created": created,
        "skipped_already_in_campaign": skipped_already_exists,
        "skipped_no_contact": skipped_no_contact,
        "new_records_sample": new_records[:20],
    }


@router.post("/enroll-all-missing")
def enroll_all_missing(
    sale_year_from: int = Query(2022),
    require_contact: bool = Query(True, description="Skip records with no email AND no phone"),
    require_email: bool = Query(False, description="Require email specifically"),
    max_to_enroll: int = Query(2000, description="Safety cap on number enrolled"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One-shot: run missing-from-active analysis AND enroll all reachable
    records as pending winback campaigns.

    This is the bulk-action equivalent of running /missing-from-active and
    then calling /bulk-add-from-missing with every result. Avoids the need
    to round-trip thousands of IDs through the frontend.

    Records are created with status='pending' — NOT auto-sent. Activation
    is a separate explicit step on the winback list.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    from sqlalchemy import or_

    ACTIVE_LOWER = {"active", "in force", "inforce"}

    sales = db.query(Sale).filter(
        Sale.sale_date >= datetime(sale_year_from, 1, 1),
        Sale.sale_date < datetime(2100, 1, 1),
        or_(Sale.lead_source != "legacy_allstate", Sale.lead_source.is_(None)),
    ).all()

    customers = db.query(Customer).all()
    by_email_idx: dict[str, int] = {}
    by_phone_idx: dict[str, int] = {}
    by_name_idx: dict[str, int] = {}

    def _phone_key(p):
        if not p:
            return None
        digits = "".join(c for c in p if c.isdigit())
        return digits[-10:] if len(digits) >= 7 else None

    customer_map: dict[int, Customer] = {c.id: c for c in customers}
    for c in customers:
        if c.email:
            by_email_idx[c.email.strip().lower()] = c.id
        for ph in (c.phone, c.mobile_phone):
            pk = _phone_key(ph or "")
            if pk:
                by_phone_idx[pk] = c.id
        if c.full_name:
            by_name_idx[c.full_name.strip().lower()] = c.id

    customer_has_active: dict[int, bool] = {}
    for pol in db.query(CustomerPolicy).all():
        if (pol.status or "").strip().lower() in ACTIVE_LOWER:
            customer_has_active[pol.customer_id] = True

    # Pre-load existing winback records to avoid duplicates
    existing_pending_customer_ids = set(
        cid
        for (cid,) in db.query(WinBackCampaign.customer_id)
        .filter(WinBackCampaign.status.in_(["pending", "active"]), WinBackCampaign.customer_id.isnot(None))
        .all()
    )
    existing_pending_phone_name = set()
    for wb in db.query(WinBackCampaign).filter(
        WinBackCampaign.status.in_(["pending", "active"]),
    ).all():
        if wb.customer_phone and wb.customer_name:
            existing_pending_phone_name.add((wb.customer_name, wb.customer_phone))

    # Aggregate sales per customer (so a customer with 3 cancelled
    # policies gets one winback record with combined info)
    lost_by_customer: dict[int, dict] = {}
    sale_only_records: list[dict] = []

    for sale in sales:
        if sale.lead_source == "legacy_allstate":
            continue

        nc_customer_id = None
        if sale.client_email:
            nc_customer_id = by_email_idx.get(sale.client_email.strip().lower())
        if not nc_customer_id and sale.client_phone:
            pk = _phone_key(sale.client_phone)
            if pk:
                nc_customer_id = by_phone_idx.get(pk)
        if not nc_customer_id and sale.client_name:
            nc_customer_id = by_name_idx.get(sale.client_name.strip().lower())

        if nc_customer_id and customer_has_active.get(nc_customer_id, False):
            continue  # has active policy → not lost

        if nc_customer_id:
            slot = lost_by_customer.setdefault(nc_customer_id, {
                "most_recent_sale": None,
                "total_premium": 0.0,
            })
            slot["total_premium"] += float(sale.written_premium or 0)
            sd = sale.sale_date
            if sd and (not slot["most_recent_sale"] or sd > slot["most_recent_sale"].sale_date):
                slot["most_recent_sale"] = sale
        else:
            sale_only_records.append(sale)

    # Now enroll
    created = 0
    skipped_already = 0
    skipped_no_contact = 0
    skipped_at_limit = 0

    # NowCerts-matched first
    for cid, slot in lost_by_customer.items():
        if created >= max_to_enroll:
            skipped_at_limit += 1
            continue

        customer = customer_map.get(cid)
        if not customer:
            continue
        if cid in existing_pending_customer_ids:
            skipped_already += 1
            continue

        recent_sale = slot["most_recent_sale"]
        email = customer.email or (recent_sale.client_email if recent_sale else None)
        phone = customer.phone or customer.mobile_phone or (recent_sale.client_phone if recent_sale else None)

        if require_email and not email:
            skipped_no_contact += 1
            continue
        if require_contact and not email and not phone:
            skipped_no_contact += 1
            continue

        wb = WinBackCampaign(
            customer_id=customer.id,
            nowcerts_insured_id=customer.nowcerts_insured_id,
            customer_name=customer.full_name,
            customer_email=email,
            customer_phone=phone,
            policy_number=recent_sale.policy_number if recent_sale else None,
            carrier=recent_sale.carrier if recent_sale else None,
            line_of_business=recent_sale.policy_type if recent_sale else None,
            premium_at_cancel=round(slot["total_premium"], 2) if slot["total_premium"] > 0 else None,
            cancellation_date=recent_sale.sale_date if recent_sale else None,
            months_active=12,
            agent_name=customer.agent_name or "performology_import",
            status="pending",
        )
        db.add(wb)
        created += 1

    # Sale-only (deduped to one per phone+name combo)
    seen_sale_only = set()
    for sale in sale_only_records:
        if created >= max_to_enroll:
            skipped_at_limit += 1
            continue

        key = (sale.client_name, sale.client_phone)
        if key in seen_sale_only or key in existing_pending_phone_name:
            skipped_already += 1
            continue
        seen_sale_only.add(key)

        if require_email and not sale.client_email:
            skipped_no_contact += 1
            continue
        if require_contact and not sale.client_email and not sale.client_phone:
            skipped_no_contact += 1
            continue

        wb = WinBackCampaign(
            customer_id=None,
            customer_name=sale.client_name,
            customer_email=sale.client_email,
            customer_phone=sale.client_phone,
            policy_number=sale.policy_number,
            carrier=sale.carrier,
            line_of_business=sale.policy_type,
            premium_at_cancel=sale.written_premium,
            cancellation_date=sale.sale_date,
            months_active=12,
            agent_name="performology_import",
            status="pending",
        )
        db.add(wb)
        created += 1

    db.commit()

    return {
        "enrolled": created,
        "skipped_already_in_campaign": skipped_already,
        "skipped_no_contact": skipped_no_contact,
        "skipped_at_safety_limit": skipped_at_limit,
        "filters": {
            "sale_year_from": sale_year_from,
            "require_contact": require_contact,
            "require_email": require_email,
            "max_to_enroll": max_to_enroll,
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Round-Robin Reassignment + Smart Scheduler
# ─────────────────────────────────────────────────────────────────────

@router.post("/assign-round-robin")
def assign_round_robin(
    only_unassigned: bool = Query(True, description="Only reassign records whose current agent_name isn't joseph/evan/giulian"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bulk-assign pending winback records to round-robin producer.

    For records whose agent_name doesn't match one of the three
    round-robin producers (joseph.rivera / evan.larson / giulian.baez),
    overwrites with a deterministic round-robin assignment based on
    record id. This means:
      - Record 1 → Joseph, 2 → Evan, 3 → Giulian, 4 → Joseph, etc.
      - Same customer always gets the same producer (consistent voice
        on follow-ups)
      - Distribution is even across the three producers

    Default only_unassigned=true preserves any record that already has
    one of the three producers assigned. Pass false to force-reassign
    everyone (use sparingly — destroys continuity for records that
    were correctly assigned manually).
    """
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/manager only")

    valid_names = {p["username"] for p in WINBACK_ROUND_ROBIN}
    valid_names.update(p["full_name"].lower() for p in WINBACK_ROUND_ROBIN)
    valid_names.update(p["first_name"].lower() for p in WINBACK_ROUND_ROBIN)

    query = db.query(WinBackCampaign).filter(
        WinBackCampaign.status.in_(["pending", "active"]),
        WinBackCampaign.excluded == False,
    )
    candidates = query.all()

    reassigned = 0
    skipped_already_correct = 0
    counts = {p["username"]: 0 for p in WINBACK_ROUND_ROBIN}

    for c in candidates:
        current = (c.agent_name or "").lower().strip()
        if only_unassigned and current in valid_names:
            skipped_already_correct += 1
            counts[
                next((p["username"] for p in WINBACK_ROUND_ROBIN
                      if current in (p["username"], p["full_name"].lower(), p["first_name"].lower())),
                     "unknown")
            ] = counts.get(
                next((p["username"] for p in WINBACK_ROUND_ROBIN
                      if current in (p["username"], p["full_name"].lower(), p["first_name"].lower())),
                     "unknown"),
                0,
            ) + 1
            continue

        idx = (c.id or 0) % len(WINBACK_ROUND_ROBIN)
        producer = WINBACK_ROUND_ROBIN[idx]
        c.agent_name = producer["username"]
        counts[producer["username"]] += 1
        reassigned += 1

    db.commit()

    return {
        "reassigned": reassigned,
        "skipped_already_correct": skipped_already_correct,
        "by_producer": counts,
    }


@router.post("/scheduler-tick")
def winback_scheduler_tick(
    max_emails_per_tick: int = Query(10, description="Max winback emails per tick"),
    max_texts_per_tick: int = Query(10, description="Max winback texts (only fires if A2P approved)"),
    require_business_hours: bool = Query(True, description="Skip if not 9am-6pm CT Mon-Fri"),
    phase_1_enabled: bool = Query(True, description="Send cold wake-up (Phase 1) emails"),
    phase_2_enabled: bool = Query(True, description="Send X-date prep (Phase 2) emails"),
    dry_run: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The winback campaign heartbeat. Two phases run in priority order:

    PHASE 2 — X-DATE PREP (HIGHER PRIORITY)
    ─────────────────────────────────────────
    For records whose next_x_date is approaching, send the next email
    in the -30/-21/-14/-7 day pre-renewal sequence. cycle_touchpoint_count
    tracks which of the 4 emails goes next. After cycle_touchpoint_count
    reaches 4 (or X-date passes), advance next_x_date by +12 months and
    reset cycle_touchpoint_count to 0.

    These run first because they're time-sensitive — if we miss a
    customer's X-date window, the opportunity is gone for another year.

    PHASE 1 — COLD WAKE-UP (LOWER PRIORITY)
    ─────────────────────────────────────────
    For records with phase='cold_wakeup' that haven't received any
    email yet, send the initial wake-up email. Ordered by
    premium_at_cancel DESC so highest-value get the early send slots.
    Paced to spread ~1,456 records across 90 business days
    (~16/day at default 4 ticks/day × 4 emails/tick).

    Once an email goes out, the record transitions:
      cold_wakeup → x_date_prep (or → dormant if X-date is far)

    BUSINESS HOURS GUARD
    ────────────────────
    Skips entirely outside 9am-6pm CT M-F unless require_business_hours=false.

    SUPPRESSIONS
    ────────────
    The query filters skip records with:
      - excluded=true (manual block, e.g. Houstons)
      - last_reply_at is set (customer replied; producer takes over)
      - status='won_back' (became a client again)

    REPLIES
    ───────
    Reply detection happens in the Smart Inbox webhook (separate
    endpoint). When an inbound email matches a winback customer_email,
    last_reply_at gets set and the campaign is paused. Producer sees
    the reply in their normal inbox and handles it manually.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    import os
    from zoneinfo import ZoneInfo

    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    now_ct = now_utc.astimezone(ZoneInfo("America/Chicago"))

    if require_business_hours and not dry_run:
        weekday = now_ct.weekday()
        hour = now_ct.hour
        if weekday >= 5 or hour < 9 or hour >= 15:
            return {
                "skipped": "outside_business_hours",
                "now_ct": now_ct.isoformat(),
                "current_weekday": weekday,
                "current_hour": hour,
            }

    twilio_approved = os.getenv("TWILIO_A2P_APPROVED", "false").lower() == "true"

    sent_email = 0
    sent_text = 0
    failed = 0
    phase_1_actions: list[dict] = []
    phase_2_actions: list[dict] = []
    text_actions: list[dict] = []

    remaining = max_emails_per_tick

    # ─── PHASE 2: X-DATE PREP ───
    # Records whose next_x_date is within 30 days, AND they haven't
    # finished the 4-email cycle yet (cycle_touchpoint_count < 4)
    if phase_2_enabled and remaining > 0:
        # Find the touchpoint due for each record:
        #   cycle_touchpoint_count = 0 → next email at -30 days from X
        #   cycle_touchpoint_count = 1 → next email at -21 days from X
        #   cycle_touchpoint_count = 2 → next email at -14 days from X
        #   cycle_touchpoint_count = 3 → next email at -7 days from X
        # The "due" rule: now >= (next_x_date − offset_days)
        offset_map = {0: 30, 1: 21, 2: 14, 3: 7}

        # We need records where the appropriate offset has been hit.
        # Easiest: pull all records where next_x_date is within 35 days
        # and cycle_touchpoint_count < 4, then filter in Python.
        candidates = db.query(WinBackCampaign).filter(
            WinBackCampaign.excluded == False,
            WinBackCampaign.last_reply_at.is_(None),
            (WinBackCampaign.bounce_count == None) | (WinBackCampaign.bounce_count < 3),
            WinBackCampaign.status != "won_back",
            WinBackCampaign.customer_email.isnot(None),
            WinBackCampaign.next_x_date.isnot(None),
            WinBackCampaign.next_x_date <= datetime.utcnow() + timedelta(days=35),
            WinBackCampaign.next_x_date >= datetime.utcnow() - timedelta(days=2),
            WinBackCampaign.cycle_touchpoint_count < 4,
        ).order_by(
            WinBackCampaign.next_x_date.asc(),
            WinBackCampaign.premium_at_cancel.desc().nullslast(),
        ).limit(remaining * 3).all()  # over-fetch since not all will be due

        for c in candidates:
            if remaining <= 0:
                break
            cycle_tc = c.cycle_touchpoint_count or 0
            offset_days = offset_map.get(cycle_tc, 7)
            due_at = c.next_x_date - timedelta(days=offset_days)

            # Strip TZ for comparison consistency
            due_naive = due_at.replace(tzinfo=None) if due_at.tzinfo else due_at
            now_naive = datetime.utcnow()

            if now_naive < due_naive:
                continue  # not due yet

            # If we sent an email within the last 5 days for this record,
            # skip — don't double up touchpoints in the same week
            if c.last_touchpoint_at:
                last_tp_naive = (
                    c.last_touchpoint_at.replace(tzinfo=None)
                    if c.last_touchpoint_at.tzinfo
                    else c.last_touchpoint_at
                )
                if (now_naive - last_tp_naive).days < 5:
                    continue

            tp = (c.touchpoint_count or 0) + 1
            if dry_run:
                phase_2_actions.append({
                    "campaign_id": c.id,
                    "customer_name": c.customer_name,
                    "phase": "x_date_prep",
                    "cycle_touchpoint": cycle_tc + 1,
                    "x_date_offset_days": offset_days,
                    "next_x_date": c.next_x_date.isoformat() if c.next_x_date else None,
                    "agent": _get_assigned_producer(c)["username"],
                    "premium": float(c.premium_at_cancel) if c.premium_at_cancel else 0,
                })
                remaining -= 1
                continue

            # Always use touchpoint=1 for the v2 email (avoids changing
            # email content based on cycle position; cycle is tracked
            # separately). Could differentiate later.
            ok = _send_winback_email(c, touchpoint=1 if cycle_tc == 0 else 2)
            if ok:
                c.touchpoint_count = tp
                c.cycle_touchpoint_count = cycle_tc + 1
                c.last_touchpoint_at = datetime.utcnow()
                c.phase = "x_date_prep"
                c.status = "active"
                # If this was the 4th cycle email, advance next_x_date
                # to next year and reset cycle counter
                if c.cycle_touchpoint_count >= 4:
                    c.next_x_date = c.next_x_date + timedelta(days=365)
                    c.cycle_touchpoint_count = 0
                    c.x_date_cycle_count = (c.x_date_cycle_count or 0) + 1
                    c.phase = "dormant"
                sent_email += 1
                remaining -= 1
            else:
                failed += 1

    # ─── PHASE 1: COLD WAKE-UP ───
    # Records that have never been emailed yet (touchpoint_count = 0,
    # phase = 'cold_wakeup' or NULL for backward compat)
    if phase_1_enabled and remaining > 0:
        candidates = db.query(WinBackCampaign).filter(
            WinBackCampaign.excluded == False,
            WinBackCampaign.last_reply_at.is_(None),
            (WinBackCampaign.bounce_count == None) | (WinBackCampaign.bounce_count < 3),
            WinBackCampaign.status != "won_back",
            WinBackCampaign.customer_email.isnot(None),
            WinBackCampaign.touchpoint_count == 0,
        ).filter(
            (WinBackCampaign.phase == "cold_wakeup")
            | (WinBackCampaign.phase.is_(None))
        ).order_by(
            WinBackCampaign.premium_at_cancel.desc().nullslast(),
            WinBackCampaign.created_at.asc(),
        ).limit(remaining).all()

        for c in candidates:
            # Skip if we'd double-tap with Phase 2 — i.e. their X-date
            # is within 60 days, let Phase 2 handle them so we don't
            # send a cold wake-up email and then a Phase 2 email a
            # week later.
            if c.next_x_date:
                next_x_naive = (
                    c.next_x_date.replace(tzinfo=None)
                    if c.next_x_date.tzinfo
                    else c.next_x_date
                )
                days_until_x = (next_x_naive - datetime.utcnow()).days
                if 0 < days_until_x < 60:
                    # Skip — Phase 2 will handle. Set phase explicitly
                    # so we don't keep re-evaluating this record.
                    if not dry_run:
                        c.phase = "x_date_prep"
                    continue

            if dry_run:
                phase_1_actions.append({
                    "campaign_id": c.id,
                    "customer_name": c.customer_name,
                    "phase": "cold_wakeup",
                    "agent": _get_assigned_producer(c)["username"],
                    "premium": float(c.premium_at_cancel) if c.premium_at_cancel else 0,
                })
                remaining -= 1
                continue

            ok = _send_winback_email(c, touchpoint=1)
            if ok:
                c.touchpoint_count = 1
                c.last_touchpoint_at = datetime.utcnow()
                c.status = "active"
                # Transition: set X-date if not already set, then move
                # to dormant phase between cycles
                if not c.next_x_date and c.cancellation_date:
                    cancel_naive = (
                        c.cancellation_date.replace(tzinfo=None)
                        if c.cancellation_date.tzinfo
                        else c.cancellation_date
                    )
                    # Compute next X-date: 12-month anniversary of
                    # cancellation that is in the future
                    target = cancel_naive + timedelta(days=365)
                    while target < datetime.utcnow():
                        target = target + timedelta(days=365)
                    c.next_x_date = target
                c.phase = "dormant"
                sent_email += 1
                remaining -= 1
            else:
                failed += 1

    if not dry_run:
        db.commit()

    # ─── TEXTS (gated on A2P) ───
    if twilio_approved and max_texts_per_tick > 0:
        text_candidates = db.query(WinBackCampaign).filter(
            WinBackCampaign.excluded == False,
            WinBackCampaign.last_reply_at.is_(None),
            (WinBackCampaign.bounce_count == None) | (WinBackCampaign.bounce_count < 3),
            WinBackCampaign.status != "won_back",
            WinBackCampaign.customer_phone.isnot(None),
            WinBackCampaign.touchpoint_count >= 1,
            WinBackCampaign.last_touchpoint_at < datetime.utcnow() - timedelta(hours=24),
            WinBackCampaign.last_touchpoint_at > datetime.utcnow() - timedelta(hours=72),
        ).order_by(
            WinBackCampaign.premium_at_cancel.desc().nullslast(),
        ).limit(max_texts_per_tick).all()

        for c in text_candidates:
            if dry_run:
                text_actions.append({
                    "campaign_id": c.id,
                    "would_send": "sms",
                    "touchpoint": c.touchpoint_count,
                })
                continue
            ok = _send_winback_text(c, touchpoint=c.touchpoint_count, db=db)
            if ok:
                c.last_touchpoint_at = datetime.utcnow()
                sent_text += 1
            else:
                failed += 1
        if not dry_run:
            db.commit()

    return {
        "dry_run": dry_run,
        "now_ct": now_ct.isoformat(),
        "twilio_a2p_approved": twilio_approved,
        "emails_sent": sent_email,
        "texts_sent": sent_text,
        "failed": failed,
        "phase_1_cold_wakeup": phase_1_actions if dry_run else len(phase_1_actions),
        "phase_2_x_date_prep": phase_2_actions if dry_run else len(phase_2_actions),
        "would_send_texts": text_actions if dry_run else None,
    }


@router.post("/initialize-x-dates")
def initialize_x_dates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set next_x_date on every winback record that doesn't have one yet.

    Logic: next_x_date = cancellation_date + N years, where N is the
    smallest integer that puts the result in the future.

    Records without a cancellation_date get NULL (Phase 2 won't fire
    until a date is manually set).

    Also sets phase='cold_wakeup' on records that have phase=NULL so
    they enter the Phase 1 queue.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    records = db.query(WinBackCampaign).filter(
        WinBackCampaign.excluded == False,
    ).all()

    set_x_date = 0
    set_phase = 0
    skipped_no_cancel_date = 0

    for c in records:
        # Set X-date if missing
        if not c.next_x_date:
            if c.cancellation_date:
                cancel_naive = (
                    c.cancellation_date.replace(tzinfo=None)
                    if c.cancellation_date.tzinfo
                    else c.cancellation_date
                )
                target = cancel_naive + timedelta(days=365)
                while target < datetime.utcnow():
                    target = target + timedelta(days=365)
                c.next_x_date = target
                set_x_date += 1
            else:
                skipped_no_cancel_date += 1

        # Set phase if NULL
        if not c.phase:
            c.phase = "cold_wakeup"
            set_phase += 1

    db.commit()

    return {
        "total_records": len(records),
        "x_dates_set": set_x_date,
        "phase_set_to_cold_wakeup": set_phase,
        "skipped_no_cancellation_date": skipped_no_cancel_date,
    }


@router.post("/detect-reply/{campaign_id}")
def mark_reply_received(
    campaign_id: int,
    subject: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually mark that a customer replied to a winback email.
    Pauses all future campaign emails for this record.

    Normally called automatically by Smart Inbox when an inbound email
    matches a winback customer_email. Exposed manually so producers
    can flag a phone-call response as "reply received" too.
    """
    if current_user.role.lower() not in ("admin", "manager", "producer"):
        raise HTTPException(status_code=403, detail="Auth required")

    c = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    c.last_reply_at = datetime.utcnow()
    if subject:
        c.last_reply_subject = subject
    db.commit()

    return {
        "campaign_id": c.id,
        "customer_name": c.customer_name,
        "last_reply_at": c.last_reply_at.isoformat(),
        "last_reply_subject": c.last_reply_subject,
        "status": "campaign paused — producer takes over from inbox",
    }


@router.post("/test-send-to/{recipient_email}")
def test_send_winback_email(
    recipient_email: str,
    campaign_id: int = Query(..., description="ID of an existing winback record to use as template data"),
    touchpoint: int = Query(1, description="Which touchpoint variant to send (1, 2, or 3)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a test winback email to a specified address (admin only).

    Renders the v2 email using a real winback record's customer info
    and the assigned producer's voice, then sends to recipient_email.
    The actual customer is NOT contacted — the email is redirected.

    Used for previewing what customers will receive before bulk send.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if "@" not in recipient_email:
        raise HTTPException(status_code=400, detail="Invalid email")

    campaign = db.query(WinBackCampaign).filter(WinBackCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")

    # Build the email exactly as it would go to the customer, then
    # send to recipient_email instead. We DON'T mutate the campaign record.
    from app.core.config import settings
    import requests

    producer = _get_assigned_producer(campaign)
    subject, html = _build_winback_email_v2(campaign, touchpoint)
    from_header = f"{producer['full_name']} <sales@betterchoiceins.com>"

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=500, detail="Mailgun not configured")

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": from_header,
                "to": [recipient_email],
                "subject": f"[TEST] {subject}",
                "html": html,
                "h:Reply-To": producer["email"],
                "v:email_type": "winback_test",
                "v:winback_campaign_id": str(campaign.id),
            },
        )
        return {
            "success": resp.status_code == 200,
            "status": resp.status_code,
            "campaign_used": {
                "id": campaign.id,
                "customer_name": campaign.customer_name,
                "carrier": campaign.carrier,
                "line_of_business": campaign.line_of_business,
                "agent": producer["username"],
            },
            "rendered_subject": subject,
            "sent_to": recipient_email,
            "from_header": from_header,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
