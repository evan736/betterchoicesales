"""
Smart Inbox — NowCerts integration for customer matching and note logging.

Lookup cascade: policy_number → email → phone → name (ILIKE)
Logging: Creates activity notes on matched customer profiles.
"""
import os
import re
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

NOWCERTS_API_KEY = os.getenv("NOWCERTS_API_KEY", "")
NOWCERTS_BASE = "https://api.nowcerts.com/api"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOWCERTS_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _clean_phone(phone: str) -> str:
    """Strip non-digit chars for phone matching."""
    return re.sub(r"\D", "", phone or "")


async def lookup_customer(
    policy_number: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """
    Cascade lookup: policy → email → phone → name.
    Returns (customer_dict_or_None, match_method, confidence).
    """
    if not NOWCERTS_API_KEY:
        logger.warning("NOWCERTS_API_KEY not set")
        return None, "none", 0.0

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Policy number lookup
        if policy_number:
            try:
                resp = await client.get(
                    f"{NOWCERTS_BASE}/Insured",
                    headers=_headers(),
                    params={"filter": f"policyNumber eq '{policy_number}'"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    insureds = data if isinstance(data, list) else data.get("value", [])
                    if insureds:
                        logger.info(f"Customer matched by policy_number: {policy_number}")
                        return insureds[0], "policy_number", 0.95
            except Exception as e:
                logger.error(f"Policy lookup failed: {e}")

        # 2. Email lookup
        if email:
            try:
                resp = await client.get(
                    f"{NOWCERTS_BASE}/Insured",
                    headers=_headers(),
                    params={"filter": f"email eq '{email}'"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    insureds = data if isinstance(data, list) else data.get("value", [])
                    if insureds:
                        logger.info(f"Customer matched by email: {email}")
                        return insureds[0], "email", 0.90
            except Exception as e:
                logger.error(f"Email lookup failed: {e}")

        # 3. Phone lookup
        if phone:
            cleaned = _clean_phone(phone)
            if len(cleaned) >= 10:
                try:
                    resp = await client.get(
                        f"{NOWCERTS_BASE}/Insured",
                        headers=_headers(),
                        params={"filter": f"phone eq '{cleaned}'"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        insureds = data if isinstance(data, list) else data.get("value", [])
                        if insureds:
                            logger.info(f"Customer matched by phone: {cleaned}")
                            return insureds[0], "phone", 0.85
                except Exception as e:
                    logger.error(f"Phone lookup failed: {e}")

        # 4. Name lookup (ILIKE / contains)
        if name and len(name.strip()) > 2:
            try:
                resp = await client.get(
                    f"{NOWCERTS_BASE}/Insured",
                    headers=_headers(),
                    params={"filter": f"contains(commercialName, '{name.strip()}')"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    insureds = data if isinstance(data, list) else data.get("value", [])
                    if insureds:
                        # Take best match if multiple
                        logger.info(f"Customer matched by name: {name}")
                        return insureds[0], "name", 0.70
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
    if not NOWCERTS_API_KEY:
        return None

    note_payload = {
        "insuredDatabaseId": insured_id,
        "subject": subject,
        "noteBody": note_body,
        "category": category,
        "isImportant": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{NOWCERTS_BASE}/insured/note",
                headers=_headers(),
                json=note_payload,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                note_id = data.get("databaseId") or data.get("id") or "created"
                logger.info(f"Note logged to NowCerts insured {insured_id}: {note_id}")
                return str(note_id)
            else:
                logger.error(f"NowCerts note creation failed: {resp.status_code} — {resp.text[:200]}")
                return None
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
        f"📧 SMART INBOX — Inbound Email Logged\n"
        f"{'─' * 40}\n"
        f"From: {from_address}\n"
        f"Subject: {subject}\n"
        f"Category: {category.replace('_', ' ').title()}\n"
        f"AI Summary: {summary}\n"
        f"{'─' * 40}\n"
        f"Preview:\n{preview}\n"
        f"{'─' * 40}\n"
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
        f"📤 SMART INBOX — Outbound Email {'Sent' if status == 'sent' else 'Queued'}\n"
        f"{'─' * 40}\n"
        f"To: {to_email}\n"
        f"Subject: {subject}\n"
        f"Status: {status.replace('_', ' ').title()}\n"
        f"{'─' * 40}\n"
        f"Preview:\n{preview}\n"
        f"{'─' * 40}\n"
        f"Logged automatically by ORBIT Smart Inbox"
    )
