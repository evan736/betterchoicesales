"""
Smart Inbox — NowCerts integration for customer matching and note logging.

Uses the existing NowCertsClient which handles OAuth auth and has proven
search methods including policy number lookup via PolicyDetailList.

Lookup cascade: policy_number → email → phone → name
Logging: Creates activity notes on matched customer profiles.
"""
import logging
from typing import Optional, Dict, Any, Tuple

from app.services.nowcerts import NowCertsClient

logger = logging.getLogger(__name__)


def _get_client() -> Optional[NowCertsClient]:
    """Get an authenticated NowCerts client, or None if not configured."""
    try:
        client = NowCertsClient()
        return client
    except Exception as e:
        logger.error(f"Failed to create NowCerts client: {e}")
        return None


async def lookup_customer(
    policy_number: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """
    Cascade lookup: policy -> email -> phone -> name.
    Returns (customer_dict_or_None, match_method, confidence).
    """
    client = _get_client()
    if not client:
        return None, "none", 0.0

    # 1. Policy number lookup (most reliable)
    if policy_number:
        try:
            results = client.search_by_policy_number(policy_number.strip())
            if results:
                customer = results[0]
                logger.info(f"Customer matched by policy_number: {policy_number} -> {customer.get('commercial_name')}")
                return customer, "policy_number", 0.95
        except Exception as e:
            logger.error(f"Policy number lookup failed: {e}")

    # 2. Email lookup
    if email and email.strip():
        try:
            results = client.search_insureds(email.strip(), limit=5)
            if results:
                for r in results:
                    if (r.get("email") or "").lower() == email.strip().lower():
                        logger.info(f"Customer matched by email: {email}")
                        return r, "email", 0.90
                logger.info(f"Customer fuzzy-matched by email search: {email}")
                return results[0], "email", 0.75
        except Exception as e:
            logger.error(f"Email lookup failed: {e}")

    # 3. Phone lookup
    if phone and len(phone.strip()) >= 7:
        try:
            import re
            cleaned = re.sub(r"\D", "", phone)
            if len(cleaned) >= 10:
                results = client.search_insureds(cleaned, limit=5)
                if results:
                    logger.info(f"Customer matched by phone: {cleaned}")
                    return results[0], "phone", 0.85
        except Exception as e:
            logger.error(f"Phone lookup failed: {e}")

    # 4. Name lookup
    if name and len(name.strip()) > 2:
        try:
            results = client.search_insureds(name.strip(), limit=5)
            if results:
                logger.info(f"Customer matched by name: {name}")
                return results[0], "name", 0.70
        except Exception as e:
            logger.error(f"Name lookup failed: {e}")

    return None, "none", 0.0


async def log_note_to_customer(
    insured_id: str,
    subject: str,
    note_body: str,
    category: str = "Email",
) -> Optional[str]:
    """
    Create an activity note on the customer's NowCerts profile.
    Returns the note ID on success, None on failure.
    """
    client = _get_client()
    if not client:
        return None

    try:
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
    """Format an inbound email as a NowCerts note body."""
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
    """Format an outbound email as a NowCerts note body."""
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
