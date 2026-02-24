"""Missive ↔ ORBIT/NowCerts integration.

Two features:
1. Log outgoing emails to NowCerts — Missive webhook fires on outgoing_email,
   ORBIT looks up the customer and adds a note to their NowCerts profile.
2. Customer context sidebar — Missive calls ORBIT to get customer info
   (policies, premium, producer, compliance items) for display in a sidebar.
"""

import logging
import hmac
import hashlib
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.core.database import get_db
from app.core.config import settings
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/missive", tags=["missive"])

# ── Config ────────────────────────────────────────────────────────────
MISSIVE_WEBHOOK_SECRET = getattr(settings, "MISSIVE_WEBHOOK_SECRET", None)
MISSIVE_API_TOKEN = getattr(settings, "MISSIVE_API_TOKEN", None)


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify Missive webhook signature if secret is configured."""
    if not MISSIVE_WEBHOOK_SECRET:
        return True  # No secret = skip verification
    expected = "sha256=" + hmac.new(
        MISSIVE_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _extract_email_from_conversation(conv: dict) -> Optional[str]:
    """Extract customer email from Missive conversation data."""
    # Check 'from' fields in messages
    messages = conv.get("messages", [])
    for msg in messages:
        from_field = msg.get("from_field", {})
        addr = from_field.get("address", "")
        if addr and not _is_agency_email(addr):
            return addr.lower()
        # Check 'to' fields
        for to in msg.get("to_fields", []):
            addr = to.get("address", "")
            if addr and not _is_agency_email(addr):
                return addr.lower()

    # Check conversation-level contacts
    for contact in conv.get("contacts", []):
        email = contact.get("email", "")
        if email and not _is_agency_email(email):
            return email.lower()

    return None


def _is_agency_email(email: str) -> bool:
    """Check if email belongs to the agency (not a customer)."""
    agency_domains = ["betterchoiceins.com", "mg.betterchoiceins.com"]
    domain = email.lower().split("@")[-1] if "@" in email else ""
    return domain in agency_domains


def _lookup_customer(db: Session, email: str) -> Optional[dict]:
    """Look up a customer by email and return their full profile."""
    customer = db.query(Customer).filter(
        func.lower(Customer.email) == email.lower()
    ).first()

    if not customer:
        return None

    # Get policies
    policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.customer_id == customer.id
    ).order_by(CustomerPolicy.effective_date.desc()).all()

    active_policies = [p for p in policies if (p.status or "").lower() in ("active", "in force", "inforce")]
    total_premium = sum(float(p.premium or 0) for p in active_policies)

    nowcerts_url = None
    if customer.nowcerts_insured_id:
        nowcerts_url = f"https://www6.nowcerts.com/AMSINS/Insureds/Details/{customer.nowcerts_insured_id}/Information"

    return {
        "customer": {
            "id": customer.id,
            "name": customer.full_name,
            "email": customer.email,
            "phone": customer.phone or customer.mobile_phone,
            "address": f"{customer.address or ''}, {customer.city or ''}, {customer.state or ''} {customer.zip_code or ''}".strip(", "),
            "agent": customer.agent_name,
            "is_active": customer.is_active,
            "nowcerts_url": nowcerts_url,
        },
        "policies": [
            {
                "number": p.policy_number,
                "carrier": p.carrier,
                "type": p.policy_type or p.line_of_business,
                "status": p.status,
                "effective": p.effective_date.strftime("%m/%d/%Y") if p.effective_date else None,
                "expiration": p.expiration_date.strftime("%m/%d/%Y") if p.expiration_date else None,
                "premium": float(p.premium or 0),
            }
            for p in policies
        ],
        "summary": {
            "total_policies": len(policies),
            "active_policies": len(active_policies),
            "total_premium": total_premium,
        },
    }


# ── 1. Webhook: Log outgoing emails to NowCerts ─────────────────────

@router.post("/webhook")
async def missive_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive Missive webhook for outgoing emails.
    Looks up the customer and logs the email as a note in NowCerts.
    
    Missive rule setup:
    - Trigger: outgoing_email
    - Action: Webhook → https://better-choice-api.onrender.com/api/missive/webhook
    """
    raw = await request.body()

    # Verify signature if configured
    signature = request.headers.get("X-Hook-Signature", "")
    if MISSIVE_WEBHOOK_SECRET and not _verify_signature(raw, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    try:
        payload = json.loads(raw.decode())
    except Exception:
        return {"status": "ignored", "reason": "invalid_json"}

    conv = payload.get("conversation", {})
    rule = payload.get("rule", {})
    rule_type = rule.get("type", "")

    logger.info("Missive webhook: type=%s, subject=%s", rule_type, conv.get("subject", ""))

    # Extract customer email
    customer_email = _extract_email_from_conversation(conv)
    if not customer_email:
        return {"status": "skipped", "reason": "no_customer_email"}

    # Look up in NowCerts
    customer_data = _lookup_customer(db, customer_email)
    if not customer_data:
        return {"status": "skipped", "reason": "customer_not_found", "email": customer_email}

    # Add note to NowCerts
    try:
        from app.services.nowcerts import get_nowcerts_client
        nc = get_nowcerts_client()
        if nc.is_configured:
            subject_line = conv.get("subject", "Email conversation")
            sender = "Agent"
            for msg in conv.get("messages", []):
                from_field = msg.get("from_field", {})
                if _is_agency_email(from_field.get("address", "")):
                    sender = from_field.get("name", "Agent")
                    break

            note_subject = f"Email: {subject_line}"
            note_body = (
                f"Email sent to {customer_data['customer']['name']} ({customer_email}).\n"
                f"Subject: {subject_line}\n"
                f"From: {sender}\n"
                f"Logged via Missive → ORBIT integration"
            )

            name = customer_data["customer"]["name"] or ""
            parts = name.strip().split()
            first_name = parts[0] if parts else ""
            last_name = parts[-1] if len(parts) > 1 else ""

            nc.insert_note({
                "subject": f"{note_subject} | {note_body}",
                "insured_email": customer_email,
                "insured_first_name": first_name,
                "insured_last_name": last_name,
                "type": "Email",
                "creator_name": f"Missive ({sender})",
                "create_date": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
            })

            logger.info("NowCerts note added via Missive webhook for %s", customer_email)
            return {"status": "logged", "customer": customer_data["customer"]["name"]}
    except Exception as e:
        logger.error("Missive webhook NowCerts note failed: %s", e)
        return {"status": "error", "reason": str(e)}

    return {"status": "skipped", "reason": "nowcerts_not_configured"}


# ── 2. Customer Context API (for Missive sidebar / lookup) ───────────

@router.get("/customer-context")
def customer_context(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Look up customer context for Missive sidebar integration.
    Returns customer profile, policies, and summary stats.
    
    Query params: email, phone, or name
    """
    if not email and not phone and not name:
        raise HTTPException(status_code=400, detail="Provide email, phone, or name")

    customer = None

    if email:
        customer = db.query(Customer).filter(
            func.lower(Customer.email) == email.lower()
        ).first()

    if not customer and phone:
        clean_phone = re.sub(r"[^\d]", "", phone)
        if len(clean_phone) >= 7:
            customer = db.query(Customer).filter(
                or_(
                    Customer.phone.contains(clean_phone[-7:]),
                    Customer.mobile_phone.contains(clean_phone[-7:]),
                )
            ).first()

    if not customer and name:
        parts = name.strip().split()
        if len(parts) >= 2:
            customer = db.query(Customer).filter(
                Customer.full_name.ilike(f"%{parts[0]}%{parts[-1]}%")
            ).first()
        elif parts:
            customer = db.query(Customer).filter(
                Customer.full_name.ilike(f"%{parts[0]}%")
            ).first()

    if not customer:
        return {"found": False, "query": {"email": email, "phone": phone, "name": name}}

    result = _lookup_customer(db, customer.email or "")
    if not result:
        # Customer found but no email — build response from customer directly
        policies = db.query(CustomerPolicy).filter(
            CustomerPolicy.customer_id == customer.id
        ).order_by(CustomerPolicy.effective_date.desc()).all()
        active_policies = [p for p in policies if (p.status or "").lower() in ("active", "in force", "inforce")]

        result = {
            "customer": {
                "id": customer.id,
                "name": customer.full_name,
                "email": customer.email,
                "phone": customer.phone or customer.mobile_phone,
                "address": f"{customer.address or ''}, {customer.city or ''}, {customer.state or ''} {customer.zip_code or ''}".strip(", "),
                "agent": customer.agent_name,
                "is_active": customer.is_active,
                "nowcerts_url": f"https://www6.nowcerts.com/AMSINS/Insureds/Details/{customer.nowcerts_insured_id}/Information" if customer.nowcerts_insured_id else None,
            },
            "policies": [
                {
                    "number": p.policy_number,
                    "carrier": p.carrier,
                    "type": p.policy_type or p.line_of_business,
                    "status": p.status,
                    "effective": p.effective_date.strftime("%m/%d/%Y") if p.effective_date else None,
                    "expiration": p.expiration_date.strftime("%m/%d/%Y") if p.expiration_date else None,
                    "premium": float(p.premium or 0),
                }
                for p in policies
            ],
            "summary": {
                "total_policies": len(policies),
                "active_policies": len(active_policies),
                "total_premium": sum(float(p.premium or 0) for p in active_policies),
            },
        }

    result["found"] = True
    return result


# ── Validation endpoint (Missive sends a test POST on rule save) ─────

@router.post("/webhook/validate")
async def validate_webhook():
    """Missive sends a validation POST when saving a webhook rule."""
    return {"status": "ok"}
