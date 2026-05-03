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


# ── Email template ──

def _build_winback_email_html(campaign: WinBackCampaign, touchpoint: int) -> str:
    """Build win-back email based on touchpoint number."""
    from app.services.welcome_email import BCI_NAVY, BCI_CYAN

    first_name = campaign.customer_name.split()[0] if campaign.customer_name else "there"

    if touchpoint == 1:
        # Initial win-back: warm, personal
        subject_text = "We miss you!"
        body = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Hi {first_name},
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We noticed your insurance policy is no longer active with us, and we wanted
          to reach out personally. At Better Choice Insurance Group, every customer matters
          to us, and we would love the opportunity to help you again.
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Insurance rates change frequently, and we may be able to find you a better rate
          than what you are currently paying. Would you be open to a quick, no-obligation quote?
        </p>"""
    elif touchpoint == 2:
        # Follow-up: value-focused
        subject_text = "New rates available for you"
        body = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Hi {first_name},
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We wanted to follow up and let you know that we have access to new carrier
          options and competitive rates that may save you money on your insurance.
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We work with over 15 carriers and can shop your coverage in minutes. Many of
          our returning customers are pleasantly surprised at the savings.
        </p>"""
    else:
        # Later touchpoints: seasonal/timely
        subject_text = "Time for an insurance check-up?"
        body = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Hi {first_name},
        </p>
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          It has been a while since we last worked together, and we just wanted to
          remind you that we are always here if you need us. Insurance needs change
          over time, and a quick review could save you money or improve your coverage.
        </p>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
  <div style="background:{BCI_NAVY};padding:24px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="Better Choice Insurance Group" width="220" style="display:block;margin:0 auto;max-width:220px;height:auto;" />
    <p style="margin:4px 0 0 0;color:{BCI_CYAN};font-size:13px;">{subject_text}</p>
  </div>
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;">
    {body}
    <div style="text-align:center;margin:24px 0;">
      <a href="tel:8479085665" style="display:inline-block;background:{BCI_CYAN};color:white;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;">
        Call Us: (847) 908-5665
      </a>
    </div>
    <p style="color:#334155;font-size:14px;margin:16px 0 0 0;">
      Best regards,<br><strong>Better Choice Insurance Group</strong>
    </p>
    <p style="color:#94a3b8;font-size:11px;margin:16px 0 0 0;">
      If you no longer wish to receive these messages, simply reply STOP.
    </p>
  </div>
</div>
</body></html>"""


def _send_winback_email(campaign: WinBackCampaign, touchpoint: int) -> bool:
    """Send win-back email via Mailgun."""
    from app.core.config import settings
    import requests

    if not campaign.customer_email:
        return False
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return False

    first_name = campaign.customer_name.split()[0] if campaign.customer_name else "Valued Customer"
    subjects = {
        1: f"{first_name}, we miss having you as a customer!",
        2: f"New insurance rates available for you, {first_name}",
        3: f"Time for an insurance check-up, {first_name}?",
    }
    subject = subjects.get(touchpoint, f"A message from Better Choice Insurance")
    html = _build_winback_email_html(campaign, touchpoint)

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                # Hardcoded apex From — see commit 91c2859.
                "from": f"Better Choice Insurance Group <service@betterchoiceins.com>",
                "to": [campaign.customer_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
            },
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Win-back email error: {e}")
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List win-back campaigns."""
    query = db.query(WinBackCampaign)

    if not include_excluded:
        query = query.filter(WinBackCampaign.excluded == False)
    if status:
        query = query.filter(WinBackCampaign.status == status)

    campaigns = query.order_by(WinBackCampaign.created_at.desc()).limit(200).all()

    return {
        "total": len(campaigns),
        "campaigns": [
            {
                "id": c.id,
                "customer_name": c.customer_name,
                "customer_email": c.customer_email,
                "customer_phone": c.customer_phone,
                "policy_number": c.policy_number,
                "carrier": c.carrier,
                "line_of_business": c.line_of_business,
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
