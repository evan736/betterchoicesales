"""Renewal Scanner & Notification API.

Scans NowCerts for upcoming policy renewals, groups multi-policy customers,
calculates rate changes, and sends notifications with rate-based branching.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.campaign import RenewalNotice
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/renewals", tags=["Renewals"])


def _build_renewal_email_html(notice: RenewalNotice, is_high_increase: bool) -> str:
    """Build renewal notification email."""
    from app.services.welcome_email import CARRIER_INFO, BCI_NAVY, BCI_CYAN

    carrier_key = (notice.carrier or "").lower().replace(" ", "_")
    carrier = CARRIER_INFO.get(carrier_key, {})
    accent = carrier.get("accent_color", BCI_CYAN)
    carrier_name = carrier.get("display_name", (notice.carrier or "your insurance").title())
    first_name = notice.customer_name.split()[0] if notice.customer_name else "there"

    exp_str = ""
    try:
        exp_str = notice.expiration_date.strftime("%B %d, %Y")
    except:
        exp_str = str(notice.expiration_date)

    # Build policy summary for multi-policy customers
    policies_html = ""
    if notice.all_renewing_policies and len(notice.all_renewing_policies) > 1:
        rows = ""
        for p in notice.all_renewing_policies:
            rows += f"""<tr>
                <td style="padding:8px 12px;border-bottom:1px solid #E2E8F0;font-size:13px;">{p.get('policy_number','')}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #E2E8F0;font-size:13px;">{p.get('carrier','').title()}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #E2E8F0;font-size:13px;">{p.get('line_of_business','')}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #E2E8F0;font-size:13px;">{p.get('expiration_date','')}</td>
            </tr>"""
        policies_html = f"""
        <div style="margin:16px 0;">
            <p style="color:#1e293b;font-size:14px;font-weight:bold;margin:0 0 8px 0;">Your renewing policies:</p>
            <table style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;">
                <tr style="background:#F8FAFC;">
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#64748B;">Policy</th>
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#64748B;">Carrier</th>
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#64748B;">Type</th>
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#64748B;">Renews</th>
                </tr>
                {rows}
            </table>
        </div>"""

    if is_high_increase:
        # Rate review email - proactive, consultative
        body_content = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          We are reaching out because your <strong>{carrier_name}</strong> policy is
          coming up for renewal on <strong>{exp_str}</strong>, and we noticed there is
          a rate adjustment.
        </p>
        <div style="background:#FEF3C7;border-left:4px solid #F59E0B;padding:12px 16px;margin:16px 0;border-radius:0 8px 8px 0;">
          <p style="margin:0;color:#92400E;font-size:14px;">
            <strong>We want to help.</strong> We can shop your coverage across our carrier
            partners to find you the best rate. This takes about 10 minutes and could
            save you money.
          </p>
        </div>
        {policies_html}
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Would you like us to review your options? Simply reply to this email, call us,
          or click below to get started.
        </p>"""
    else:
        # Standard renewal reminder
        body_content = f"""
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          Just a friendly reminder that your <strong>{carrier_name}</strong> policy
          renews on <strong>{exp_str}</strong>. No action is needed if you would like
          to continue your current coverage.
        </p>
        {policies_html}
        <p style="color:#334155;font-size:14px;line-height:1.6;">
          If you have any questions about your renewal or would like to review your
          coverage, we are happy to help.
        </p>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
  <div style="background:{BCI_NAVY};padding:24px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:white;font-size:20px;">Better Choice Insurance Group</h1>
    <p style="margin:4px 0 0 0;color:{accent};font-size:13px;">Policy Renewal {'Review' if is_high_increase else 'Reminder'}</p>
  </div>
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;">
    <p style="color:#1e293b;font-size:16px;margin:0 0 16px 0;">Hi {first_name},</p>
    {body_content}
    <div style="text-align:center;margin:24px 0;">
      <a href="tel:8479085665" style="display:inline-block;background:{accent};color:white;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;">
        {'Schedule a Review' if is_high_increase else 'Call Us With Questions'}
      </a>
    </div>
    <p style="color:#334155;font-size:14px;margin:16px 0 0 0;">
      Thank you for choosing Better Choice Insurance Group.<br>
      <strong>(847) 908-5665</strong> | service@betterchoiceins.com
    </p>
  </div>
</div>
</body></html>"""


def _send_renewal_email(notice: RenewalNotice, is_high_increase: bool) -> bool:
    """Send renewal notification email."""
    from app.core.config import settings
    import requests

    if not notice.customer_email:
        return False
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return False

    carrier_name = (notice.carrier or "insurance").title()
    if is_high_increase:
        subject = f"Your {carrier_name} Policy Rate Review - Let Us Help"
    else:
        subject = f"Your {carrier_name} Policy Renews Soon"

    html = _build_renewal_email_html(notice, is_high_increase)

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Better Choice Insurance Group <renewals@{settings.MAILGUN_DOMAIN}>",
                "to": [notice.customer_email],
                "subject": subject,
                "html": html,
                "h:Reply-To": "service@betterchoiceins.com",
            },
        )
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Renewal email error: {e}")
        return False


# ── Scanning Logic ──

@router.post("/scan")
def scan_renewals(
    days_ahead: int = Query(default=90, ge=7, le=180),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan for policies expiring within N days and create renewal notices.

    Groups multiple policies per customer (within 30 days of each other)
    and selects the highest rate change as the trigger.
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_ahead)

    # Get active policies expiring within window
    expiring = db.query(CustomerPolicy).filter(
        CustomerPolicy.status.in_(["Active", "active"]),
        CustomerPolicy.expiration_date.isnot(None),
        CustomerPolicy.expiration_date >= now,
        CustomerPolicy.expiration_date <= cutoff,
    ).all()

    # Group by customer
    customer_policies = defaultdict(list)
    for pol in expiring:
        customer_policies[pol.customer_id].append(pol)

    created = 0
    skipped = 0

    for cust_id, policies in customer_policies.items():
        customer = db.query(Customer).filter(Customer.id == cust_id).first()
        if not customer:
            skipped += 1
            continue

        # Skip if no contact info
        if not customer.email and not customer.phone:
            skipped += 1
            continue

        # Check if renewal notice already exists for this customer in this window
        existing = db.query(RenewalNotice).filter(
            RenewalNotice.customer_id == cust_id,
            RenewalNotice.status.notin_(["completed"]),
            RenewalNotice.expiration_date >= now,
        ).first()
        if existing:
            skipped += 1
            continue

        # Group policies within 30 days of each other
        # Sort by expiration date
        policies.sort(key=lambda p: p.expiration_date or datetime.max)

        # For now, rate change is unknown unless we have renewal premium data
        # This can be enhanced when NowCerts provides renewal quotes
        highest_rate_pct = 0.0
        rate_category = "unknown"

        # Build policy summary
        policy_summaries = []
        for pol in policies:
            summary = {
                "policy_number": pol.policy_number,
                "carrier": pol.carrier or "",
                "line_of_business": pol.line_of_business or "",
                "premium": str(pol.premium) if pol.premium else "N/A",
                "expiration_date": pol.expiration_date.strftime("%m/%d/%Y") if pol.expiration_date else "",
            }
            policy_summaries.append(summary)

        # Use earliest expiration as the trigger date
        earliest_exp = policies[0].expiration_date
        primary_policy = policies[0]  # Use first policy as primary

        days_until = (earliest_exp - now).days

        notice = RenewalNotice(
            customer_id=cust_id,
            nowcerts_insured_id=customer.nowcerts_insured_id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            customer_phone=customer.phone or customer.mobile_phone,
            policy_number=primary_policy.policy_number,
            carrier=primary_policy.carrier,
            line_of_business=primary_policy.line_of_business,
            expiration_date=earliest_exp,
            rate_change_pct=highest_rate_pct,
            rate_category=rate_category,
            all_renewing_policies=policy_summaries,
            agent_name=customer.agent_name,
            status="pending",
        )
        db.add(notice)
        created += 1

    db.commit()

    return {
        "scanned_policies": len(expiring),
        "unique_customers": len(customer_policies),
        "notices_created": created,
        "skipped": skipped,
        "scan_window_days": days_ahead,
    }


@router.get("/")
def list_renewals(
    status: Optional[str] = None,
    days_out: Optional[int] = None,
    rate_category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List renewal notices with filters."""
    query = db.query(RenewalNotice)

    if status:
        query = query.filter(RenewalNotice.status == status)
    if rate_category:
        query = query.filter(RenewalNotice.rate_category == rate_category)
    if days_out:
        cutoff = datetime.utcnow() + timedelta(days=days_out)
        query = query.filter(RenewalNotice.expiration_date <= cutoff)

    notices = query.order_by(RenewalNotice.expiration_date.asc()).limit(200).all()

    return {
        "total": len(notices),
        "renewals": [
            {
                "id": n.id,
                "customer_name": n.customer_name,
                "customer_email": n.customer_email,
                "customer_phone": n.customer_phone,
                "policy_number": n.policy_number,
                "carrier": n.carrier,
                "line_of_business": n.line_of_business,
                "expiration_date": n.expiration_date.isoformat() if n.expiration_date else None,
                "days_until": (n.expiration_date - datetime.utcnow()).days if n.expiration_date else None,
                "rate_change_pct": float(n.rate_change_pct) if n.rate_change_pct else None,
                "rate_category": n.rate_category,
                "all_renewing_policies": n.all_renewing_policies,
                "status": n.status,
                "email_90_sent": n.email_90_sent,
                "email_60_sent": n.email_60_sent,
                "email_30_sent": n.email_30_sent,
                "agent_name": n.agent_name,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notices
        ],
    }


@router.post("/{notice_id}/notify")
def send_renewal_notification(
    notice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send renewal notification email for a specific notice."""
    notice = db.query(RenewalNotice).filter(RenewalNotice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")

    is_high = notice.rate_category == "high_increase"
    email_sent = _send_renewal_email(notice, is_high)

    days_until = (notice.expiration_date - datetime.utcnow()).days if notice.expiration_date else 0

    if email_sent:
        if days_until > 75:
            notice.email_90_sent = True
            notice.status = "notified_90"
        elif days_until > 45:
            notice.email_60_sent = True
            notice.status = "notified_60"
        elif days_until > 20:
            notice.email_30_sent = True
            notice.status = "notified_30"
        else:
            notice.email_14_sent = True

        # NowCerts note
        try:
            from app.services.nowcerts import get_nowcerts_client
            nc = get_nowcerts_client()
            if nc.is_configured:
                parts = notice.customer_name.strip().split(maxsplit=1)
                nc.insert_note({
                    "subject": f"Renewal Reminder Sent — {notice.policy_number} | Renews {notice.expiration_date.strftime('%m/%d/%Y') if notice.expiration_date else 'soon'}",
                    "insured_email": notice.customer_email or "",
                    "insured_first_name": parts[0] if parts else "",
                    "insured_last_name": parts[1] if len(parts) > 1 else "",
                    "type": "Email",
                    "creator_name": "BCI Renewal System",
                    "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
                })
        except Exception as e:
            logger.debug(f"NowCerts note failed: {e}")

        # Fire GHL webhook
        try:
            from app.services.ghl_webhook import get_ghl_service
            ghl = get_ghl_service()
            ghl.fire_renewal_approaching(
                customer_name=notice.customer_name,
                email=notice.customer_email or "",
                phone=notice.customer_phone or "",
                days_until=days_until,
                highest_rate_pct=float(notice.rate_change_pct or 0),
                rate_category=notice.rate_category or "unknown",
                policies=notice.all_renewing_policies or [],
            )
            notice.ghl_webhook_sent = True
        except Exception as e:
            logger.debug(f"GHL webhook failed: {e}")

        db.commit()

    return {"email_sent": email_sent, "days_until_renewal": days_until, "status": notice.status}


@router.post("/{notice_id}/update-rate")
def update_rate_info(
    notice_id: int,
    current_premium: float = Query(...),
    renewal_premium: float = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually update rate change info for a renewal notice."""
    notice = db.query(RenewalNotice).filter(RenewalNotice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")

    notice.current_premium = current_premium
    notice.renewal_premium = renewal_premium

    if current_premium > 0:
        pct = ((renewal_premium - current_premium) / current_premium) * 100
        notice.rate_change_pct = round(pct, 2)
        notice.rate_category = "high_increase" if pct >= 10 else ("low_increase" if pct > 0 else "decrease")
    else:
        notice.rate_change_pct = 0
        notice.rate_category = "unknown"

    db.commit()

    return {
        "id": notice.id,
        "rate_change_pct": float(notice.rate_change_pct),
        "rate_category": notice.rate_category,
    }
