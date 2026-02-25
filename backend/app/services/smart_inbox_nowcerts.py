"""
Smart Inbox — Customer matching and NowCerts note logging.

Primary lookup uses LOCAL database (customers + customer_policies tables)
which are synced from NowCerts. Falls back to NowCerts API if needed.

Lookup cascade: policy_number -> email -> phone -> name
"""
import re
import logging
from typing import Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)


def _clean_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def lookup_customer_sync(
    db: Session,
    policy_number: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """
    Synchronous lookup using local DB.
    Returns (customer_dict_or_None, match_method, confidence).
    """

    # 1. Policy number lookup (most reliable)
    if policy_number and policy_number.strip():
        clean_pn = policy_number.strip()
        pattern = f"%{clean_pn}%"
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number.ilike(pattern)
        ).first()
        if policy:
            customer = db.query(Customer).filter(
                Customer.id == policy.customer_id
            ).first()
            if customer:
                logger.info(f"Customer matched by policy_number: {policy_number} -> {customer.full_name}")
                return _customer_to_dict(customer), "policy_number", 0.95

    # 2. Email lookup
    if email and email.strip():
        customer = db.query(Customer).filter(
            func.lower(Customer.email) == email.strip().lower()
        ).first()
        if customer:
            logger.info(f"Customer matched by email: {email}")
            return _customer_to_dict(customer), "email", 0.90

    # 3. Phone lookup
    if phone:
        cleaned = _clean_phone(phone)
        if len(cleaned) >= 10:
            customer = db.query(Customer).filter(
                or_(
                    Customer.phone.contains(cleaned[-10:]),
                    Customer.mobile_phone.contains(cleaned[-10:]),
                )
            ).first()
            if customer:
                logger.info(f"Customer matched by phone: {cleaned}")
                return _customer_to_dict(customer), "phone", 0.85

    # 4. Name lookup
    if name and len(name.strip()) > 2:
        pattern = f"%{name.strip()}%"
        customer = db.query(Customer).filter(
            Customer.full_name.ilike(pattern)
        ).first()
        if customer:
            logger.info(f"Customer matched by name: {name}")
            return _customer_to_dict(customer), "name", 0.70

    return None, "none", 0.0


async def lookup_customer(
    policy_number: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """
    Async wrapper that creates its own DB session for background task use.
    """
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        return lookup_customer_sync(db, policy_number, email, phone, name)
    finally:
        db.close()


def _customer_to_dict(c: Customer) -> Dict[str, Any]:
    return {
        "database_id": c.nowcerts_insured_id or str(c.id),
        "commercial_name": c.full_name,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "email": c.email,
        "phone": c.phone or c.mobile_phone,
        "city": c.city,
        "state": c.state,
        "zip_code": c.zip_code,
        "nowcerts_insured_id": c.nowcerts_insured_id,
        "local_id": c.id,
    }


async def log_note_to_customer(
    insured_id: str,
    subject: str,
    note_body: str,
    category: str = "Email",
) -> Optional[str]:
    """
    Create an activity note on the customer's NowCerts profile.
    Uses NowCertsClient for the API call.
    """
    try:
        from app.services.nowcerts import NowCertsClient
        client = NowCertsClient()
        result = client._post("/api/insured/note", data={
            "insuredDatabaseId": insured_id,
            "subject": subject,
            "noteBody": note_body,
            "category": category,
            "isImportant": False,
        })
        note_id = result.get("databaseId") or result.get("id") or "created"
        logger.info(f"Note logged to NowCerts insured {insured_id}: {note_id}")
        return str(note_id)
    except Exception as e:
        logger.error(f"NowCerts note logging error: {e}")
        return None


def format_inbound_note(
    subject: str,
    from_address: str,
    category: str,
    summary: str,
    body_preview: str,
) -> str:
    preview = (body_preview or "")[:500]
    return (
        f"SMART INBOX - Inbound Email Logged\n"
        f"{'=' * 40}\n"
        f"From: {from_address}\n"
        f"Subject: {subject}\n"
        f"Category: {category.replace('_', ' ').title()}\n"
        f"AI Summary: {summary}\n"
        f"{'=' * 40}\n"
        f"Preview:\n{preview}\n"
        f"{'=' * 40}\n"
        f"Logged automatically by ORBIT Smart Inbox"
    )


def format_outbound_note(
    to_email: str,
    subject: str,
    status: str,
    body_preview: str,
) -> str:
    preview = (body_preview or "")[:500]
    return (
        f"SMART INBOX - Outbound Email {'Sent' if status == 'sent' else 'Queued'}\n"
        f"{'=' * 40}\n"
        f"To: {to_email}\n"
        f"Subject: {subject}\n"
        f"Status: {status.replace('_', ' ').title()}\n"
        f"{'=' * 40}\n"
        f"Preview:\n{preview}\n"
        f"{'=' * 40}\n"
        f"Logged automatically by ORBIT Smart Inbox"
    )
