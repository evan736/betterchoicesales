"""Retell AI webhook routes for BCI AI Receptionist (MIA).

Handles:
1. Inbound Call Webhook - NowCerts caller lookup, returns dynamic variables
2. Custom Function - Callback/message request handling + Mailgun email
3. Post-Call Webhook - Logs calls to NowCerts, sends summary emails

Retell docs:
- Inbound webhook: https://docs.retellai.com/features/inbound-call-webhook
- Custom functions: https://docs.retellai.com/retell-llm/add-function-calling
- Call webhooks: https://docs.retellai.com/features/webhook-overview
"""
import logging
import re
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

# US Central Time offset (CT = UTC-6, CDT = UTC-5)
# For simplicity we use America/Chicago via a fixed check
def _get_business_hours_info() -> dict:
    """Return current time info in Central Time and whether it's business hours."""
    try:
        import zoneinfo
        ct = datetime.now(zoneinfo.ZoneInfo("America/Chicago"))
    except Exception:
        # Fallback: assume CDT (UTC-5) March-Nov, CST (UTC-6) Nov-March
        utc_now = datetime.now(timezone.utc)
        ct = utc_now - timedelta(hours=6)  # CST as safe default

    weekday = ct.weekday()  # 0=Monday, 6=Sunday
    hour = ct.hour
    minute = ct.minute
    
    is_weekday = weekday < 5  # Mon-Fri
    is_in_hours = 9 <= hour < 18  # 9 AM - 6 PM
    is_business_hours = is_weekday and is_in_hours
    
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    time_str = ct.strftime("%I:%M %p CT")
    
    return {
        "is_business_hours": "true" if is_business_hours else "false",
        "current_time": time_str,
        "current_day": day_names[weekday],
    }

import requests
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.services.nowcerts import get_nowcerts_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/retell", tags=["retell"])


# ── Helpers ────────────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Strip a phone number to last 10 digits for NowCerts search."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def build_policy_summary(policies: list[dict]) -> str:
    """Build a natural language summary of a customer's policies.
    
    Example: "an auto policy with Progressive and a home policy with Safeco"
    """
    if not policies:
        return ""

    # Map line of business to friendly names
    lob_map = {
        "personal auto": "auto",
        "auto": "auto",
        "homeowners": "home",
        "home": "home",
        "renters": "renters",
        "condo": "condo",
        "dwelling fire": "dwelling",
        "umbrella": "umbrella",
        "motorcycle": "motorcycle",
        "watercraft": "watercraft",
        "boat": "boat",
        "flood": "flood",
        "life": "life",
        "commercial auto": "commercial auto",
        "general liability": "general liability",
        "bop": "business",
        "workers comp": "workers comp",
    }

    parts = []
    seen = set()
    for pol in policies:
        status = (pol.get("status") or pol.get("policyStatus") or "").lower().strip()
        
        # Explicitly exclude known inactive statuses
        inactive_statuses = {"cancelled", "canceled", "expired", "non-renewed", "non renewed",
                           "nonrenewed", "void", "flat cancelled", "flat canceled", "renewed"}
        if status in inactive_statuses:
            logger.debug("Skipping inactive policy: status=%s carrier=%s", status,
                        pol.get("carrierName") or pol.get("carrier_name") or "?")
            continue
        
        # Only include policies that are currently active
        active_statuses = {"active", "renewing", "in force", "pending", "bound", "issued", ""}
        if status and status not in active_statuses:
            logger.debug("Skipping unknown status policy: status=%s carrier=%s", status,
                        pol.get("carrierName") or pol.get("carrier_name") or "?")
            continue

        carrier = (
            pol.get("carrier_name") or pol.get("carrierName") or
            pol.get("carrier") or pol.get("companyName") or "unknown carrier"
        )
        lob_raw = (
            pol.get("line_of_business") or pol.get("lineOfBusiness") or
            pol.get("lob") or ""
        )
        # Handle lineOfBusinesses array from OData
        if isinstance(lob_raw, list):
            lob_raw = lob_raw[0].get("name", "") if lob_raw and isinstance(lob_raw[0], dict) else str(lob_raw[0]) if lob_raw else ""

        lob = lob_map.get(lob_raw.lower().strip(), lob_raw.lower().strip()) if lob_raw else "insurance"

        key = f"{lob}|{carrier.lower()}"
        if key not in seen:
            seen.add(key)
            article = "an" if lob[0] in "aeiou" else "a"
            parts.append(f"{article} {lob} policy with {carrier}")

    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def build_carrier_list(policies: list[dict]) -> str:
    """Build a comma-separated list of active carriers."""
    active_statuses = {"active", "renewing", "in force", "pending", "bound"}
    carriers = set()
    for pol in policies:
        status = (pol.get("status") or pol.get("policyStatus") or "").lower().strip()
        if status and status not in active_statuses:
            continue
        carrier = (
            pol.get("carrier_name") or pol.get("carrierName") or
            pol.get("carrier") or pol.get("companyName") or ""
        )
        if carrier:
            carriers.add(carrier)
    return ", ".join(sorted(carriers))


def send_mailgun_email(to: str, subject: str, html: str) -> bool:
    """Send email via Mailgun. `to` can be a comma-separated list."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured, skipping email")
        return False
    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"MIA AI Receptionist <service@{settings.MAILGUN_DOMAIN}>",
                "to": to,
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
        logger.info("Mailgun response: %s %s", resp.status_code, resp.text[:200])
        return resp.status_code == 200
    except Exception as e:
        logger.error("Mailgun send failed: %s", e)
        return False


# ── EMAIL ROUTING ─────────────────────────────────────────────────
# Determines who should receive the email based on request context.
# service@ always gets a copy. Staff get CC'd based on rules.

STAFF_EMAILS = {
    "evan": "evan@betterchoiceins.com",
    "salma": "salma@betterchoiceins.com",
    "giulian": "giulian@betterchoiceins.com",
    "joseph": "joseph@betterchoiceins.com",
    "michelle": "michelle@betterchoiceins.com",
}

SERVICE_EMAIL = "service@betterchoiceins.com"

# Quote requests go to the sales team
QUOTE_TEAM = ["joseph", "giulian", "evan"]


def _get_email_recipients(
    request_type: str = "",
    staff_requested: str = "",
    urgency: str = "normal",
    reason: str = "",
) -> str:
    """Return comma-separated email recipients based on routing rules.

    Rules (service@ is ALWAYS included):
    1. staff_requested by name → add that person's email
    2. quote_request → add Joseph, Giulian, Evan
    3. cancellation + urgent → add Evan
    4. urgency=urgent (non-cancellation) → add Evan
    5. premium_complaint / reshop → add Evan
    """
    recipients = {SERVICE_EMAIL}

    # Rule 1: Specific staff requested
    if staff_requested:
        staff_key = staff_requested.strip().lower()
        if staff_key in STAFF_EMAILS:
            recipients.add(STAFF_EMAILS[staff_key])
            logger.info("Email routing: +%s (staff requested)", staff_key)

    # Rule 2: Quote requests → sales team
    if request_type.lower() in ("quote_request", "quote"):
        for name in QUOTE_TEAM:
            recipients.add(STAFF_EMAILS[name])
        logger.info("Email routing: +quote team (joseph, giulian, evan)")

    # Rule 3: Cancellations → Evan
    is_cancellation = (
        request_type.lower() == "cancellation"
        or "CANCELLATION" in reason.upper()
    )
    if is_cancellation:
        recipients.add(STAFF_EMAILS["evan"])
        logger.info("Email routing: +evan (cancellation)")

    # Rule 4: Urgent requests → Evan
    if urgency.lower() == "urgent":
        recipients.add(STAFF_EMAILS["evan"])
        logger.info("Email routing: +evan (urgent)")

    # Rule 5: Premium complaints / reshop → Evan
    if request_type.lower() in ("premium_complaint", "reshop"):
        recipients.add(STAFF_EMAILS["evan"])
        logger.info("Email routing: +evan (premium/reshop)")

    result = ", ".join(sorted(recipients))
    logger.info("Email recipients: %s", result)
    return result


# ── 1. INBOUND CALL WEBHOOK ───────────────────────────────────────
# Retell POSTs here when a call comes in. We look up the caller in
# NowCerts and return dynamic variables so MIA can greet by name.
#
# CRITICAL: Retell has a 10-second timeout. If we don't respond in 10s,
# the call starts without dynamic variables. We must be FAST.
#
# Retell sends: {from_number, to_number, agent_id}
# We return:    {call_inbound: {dynamic_variables: {...}}}

import asyncio
import time as _time
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4)

# In-memory cache: phone_digits -> {customer, policies, cached_at}
# Survives across requests within the same Render worker process
_phone_cache: dict = {}
_CACHE_TTL = 3600  # 1 hour

# Repeat caller detection — tracks recent calls per phone number
# Format: {phone_digits: [timestamp1, timestamp2, ...]}
_recent_calls: dict = {}
_REPEAT_WINDOW_SHORT = 1800   # 30 minutes — same session repeat
_REPEAT_WINDOW_LONG = 86400   # 24 hours — same day repeat
_REPEAT_CLEANUP_INTERVAL = 3600  # Clean old entries every hour
_last_repeat_cleanup = 0.0

# Mid-call request store — holds request data until post-call email combines it
# Format: {call_id: [request_dict, ...]}  (a call can have multiple requests)
_pending_requests: dict = {}
_PENDING_REQUEST_TTL = 1800  # Clean up after 30 min (calls shouldn't last that long)


def _check_repeat_caller(phone_digits: str) -> dict:
    """Check if this phone number has called recently. Returns repeat info."""
    global _last_repeat_cleanup
    now = _time.time()

    # Periodic cleanup of old entries
    if now - _last_repeat_cleanup > _REPEAT_CLEANUP_INTERVAL:
        stale = [k for k, v in _recent_calls.items()
                 if not v or (now - max(v)) > _REPEAT_WINDOW_LONG]
        for k in stale:
            del _recent_calls[k]
        _last_repeat_cleanup = now

    history = _recent_calls.get(phone_digits, [])

    # Count calls within windows
    calls_30min = sum(1 for t in history if (now - t) < _REPEAT_WINDOW_SHORT)
    calls_24hr = sum(1 for t in history if (now - t) < _REPEAT_WINDOW_LONG)

    # Record this call
    history.append(now)
    # Keep only last 24 hours of entries
    history = [t for t in history if (now - t) < _REPEAT_WINDOW_LONG]
    _recent_calls[phone_digits] = history

    is_repeat_short = calls_30min > 0  # Called at least once in last 30 min
    is_repeat_long = calls_24hr > 1    # Called 2+ times today (not counting current)

    return {
        "is_repeat": is_repeat_short or is_repeat_long,
        "is_repeat_30min": is_repeat_short,
        "calls_30min": calls_30min + 1,  # Including current call
        "calls_24hr": calls_24hr + 1,
    }


def _local_db_phone_lookup(phone_digits: str) -> dict:
    """Look up customer in local PostgreSQL cache — should take <100ms."""
    try:
        from app.core.database import SessionLocal
        from app.models.customer import Customer, CustomerPolicy
        from sqlalchemy import or_, case
        
        db = SessionLocal()
        try:
            # Search by phone or mobile_phone
            # Order: exact phone match first, then mobile_phone match
            # Also prefer records with more data (has email, has address = more likely real)
            customers = db.query(Customer).filter(
                or_(
                    Customer.phone.like(f"%{phone_digits[-10:]}%"),
                    Customer.mobile_phone.like(f"%{phone_digits[-10:]}%"),
                )
            ).order_by(
                # Prefer phone match over mobile_phone match
                case(
                    (Customer.phone.like(f"%{phone_digits[-10:]}%"), 0),
                    else_=1
                ),
                # Prefer records with email (more likely to be real)
                case(
                    (Customer.email.isnot(None), 0),
                    else_=1
                ),
            ).limit(5).all()
            
            if not customers:
                return {}
            
            customer = customers[0]
            
            # Get active policies
            active_statuses = ["Active", "Renewing", "In Force", "Pending", "Bound",
                             "active", "renewing", "in force", "pending", "bound"]
            policies = db.query(CustomerPolicy).filter(
                CustomerPolicy.customer_id == customer.id,
                CustomerPolicy.status.in_(active_statuses)
            ).all()
            
            policy_dicts = [
                {
                    "carrierName": p.carrier or "",
                    "lineOfBusiness": p.line_of_business or "",
                    "status": p.status or "",
                }
                for p in policies
            ]
            
            return {
                "customer": {
                    "firstName": customer.first_name or "",
                    "lastName": customer.last_name or "",
                    "commercialName": customer.full_name or "",
                    "databaseId": customer.nowcerts_insured_id or "",
                },
                "policies": policy_dicts,
                "source": "local_db",
            }
        finally:
            db.close()
    except Exception as e:
        logger.warning("Local DB lookup failed: %s", e)
        return {}


def _nowcerts_phone_lookup(phone_digits: str) -> dict:
    """Synchronous NowCerts lookup — runs in thread pool.
    
    Returns dict with customer info or empty dict on failure.
    Total budget: ~9 seconds (Retell gives us 10s, need margin).
    """
    import time
    start = time.time()
    
    try:
        client = get_nowcerts_client()
        if not client.is_configured:
            return {}

        # Get auth token (cached after first call — should be instant on subsequent calls)
        token = client._authenticate()
        elapsed = time.time() - start
        logger.info("NowCerts auth took %.1fs (token cached: %s)", elapsed, bool(client._token))
        
        if elapsed > 8:
            logger.warning("Auth alone took %.1fs, aborting lookup", elapsed)
            return {}
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Customer lookup — give it up to 8 seconds
        remaining = 9.0 - elapsed
        resp = requests.get(
            f"{client.base_url}/api/Customers/GetCustomers",
            headers=headers,
            params={"Phone": phone_digits},
            timeout=min(remaining, 8),
        )
        
        elapsed = time.time() - start
        logger.info("GetCustomers took %.1fs total", elapsed)

        if resp.status_code != 200 or not resp.text.strip():
            return {}

        results = resp.json()
        if not isinstance(results, list) or not results:
            return {}

        # Pick the best match: prefer the one whose phone/cellPhone matches most closely
        best = results[0]
        for r in results:
            r_phone = re.sub(r"\D", "", r.get("phone") or "")
            r_cell = re.sub(r"\D", "", r.get("cellPhone") or "")
            if r_phone.endswith(phone_digits) or r_cell.endswith(phone_digits):
                if r_phone.endswith(phone_digits):
                    best = r
                    break
                best = r

        # Get policies only if we have time left (need at least 1s margin)
        elapsed = time.time() - start
        remaining = 9.0 - elapsed
        policies = []
        insured_id = best.get("databaseId") or ""
        if insured_id and remaining > 1.5:
            try:
                logger.info("Fetching policies with %.1fs remaining", remaining)
                policies = client.get_insured_policies(str(insured_id))
            except Exception as e:
                logger.warning("Policy lookup failed (%.1fs in): %s", time.time() - start, e)
        else:
            logger.info("Skipping policy lookup — only %.1fs remaining", remaining)

        logger.info("NowCerts lookup complete in %.1fs: customer=%s, policies=%d",
                     time.time() - start, best.get("firstName", "?"), len(policies))
        return {"customer": best, "policies": policies}

    except requests.exceptions.Timeout:
        logger.warning("NowCerts lookup timed out after %.1fs", time.time() - start)
        return {}
    except Exception as e:
        logger.error("NowCerts phone lookup failed after %.1fs: %s", time.time() - start, e)
        return {}


@router.post("/inbound-webhook")
async def inbound_call_webhook(request: Request):
    """Look up inbound caller in NowCerts and return dynamic variables to Retell."""
    try:
        body = await request.json()
        
        # Retell sends: {event: "call_inbound", call_inbound: {from_number, to_number, agent_id}}
        # The fields are nested inside call_inbound, NOT at the top level
        call_data = body.get("call_inbound", {})
        from_number = call_data.get("from_number", "") or body.get("from_number", "")
        to_number = call_data.get("to_number", "") or body.get("to_number", "")
        agent_id = call_data.get("agent_id", "") or body.get("agent_id", "")

        logger.info(
            "Retell inbound webhook: from=%s to=%s agent=%s raw_keys=%s",
            from_number, to_number, agent_id, list(body.keys())
        )

        # Default response — no customer found
        bh_info = _get_business_hours_info()
        dynamic_variables = {
            "customer_name": "",
            "policy_summary": "",
            "carrier_list": "",
            "customer_phone": from_number,
            "nowcerts_insured_id": "",
            "customer_found": "false",
            "is_repeat_caller": "false",
            "repeat_call_count": "1",
            "customer_email": "",
            "is_business_hours": bh_info["is_business_hours"],
            "current_time": bh_info["current_time"],
            "current_day": bh_info["current_day"],
        }

        # Check for repeat caller
        phone_digits = normalize_phone(from_number)
        repeat_info = {"is_repeat": False, "calls_30min": 1, "calls_24hr": 1}
        if phone_digits and len(phone_digits) >= 10:
            repeat_info = _check_repeat_caller(phone_digits)
            dynamic_variables["is_repeat_caller"] = "true" if repeat_info["is_repeat"] else "false"
            dynamic_variables["repeat_call_count"] = str(repeat_info["calls_24hr"])
        result = None
        if phone_digits and len(phone_digits) >= 10:
            # Layer 1: In-memory cache (~0ms)
            cached = _phone_cache.get(phone_digits)
            if cached and (_time.time() - cached.get("cached_at", 0)) < _CACHE_TTL:
                result = cached
                logger.info("Cache hit for %s: %s", phone_digits, 
                           result.get("customer", {}).get("firstName", "?"))
            
            # Layer 2: NowCerts API (~2-7s) — authoritative source
            # Local DB disabled: stale/test data was returning wrong customers
            if not result:
                try:
                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(_executor, _nowcerts_phone_lookup, phone_digits),
                        timeout=7.0
                    )
                    # Cache successful NowCerts lookups
                    if result and result.get("customer"):
                        result["cached_at"] = _time.time()
                        _phone_cache[phone_digits] = result
                        logger.info("Cached NowCerts result for %s", phone_digits)
                except asyncio.TimeoutError:
                    logger.warning("NowCerts lookup timed out (7s) for phone: %s", phone_digits)
                except Exception as e:
                    logger.error("NowCerts lookup failed: %s", e)

            # Extract customer data from result (regardless of which layer found it)
            if result and result.get("customer"):
                customer = result["customer"]
                policies = result.get("policies", [])

                first_name = customer.get("firstName") or customer.get("first_name") or ""
                last_name = customer.get("lastName") or customer.get("last_name") or ""
                commercial_name = customer.get("commercialName") or customer.get("commercial_name") or ""
                customer_name = (
                    f"{first_name} {last_name}".strip()
                    if first_name else commercial_name or ""
                )
                insured_id = customer.get("databaseId") or customer.get("database_id") or ""

                dynamic_variables["customer_name"] = customer_name
                dynamic_variables["nowcerts_insured_id"] = str(insured_id)
                dynamic_variables["customer_found"] = "true"

                # Extract email for document requests / confirmations
                customer_email = customer.get("email") or customer.get("eMail") or ""
                dynamic_variables["customer_email"] = customer_email

                if policies:
                    dynamic_variables["policy_summary"] = build_policy_summary(policies)
                    dynamic_variables["carrier_list"] = build_carrier_list(policies)

                logger.info(
                    "Customer match: name=%s, id=%s, carriers=%s, source=%s",
                    customer_name, insured_id,
                    dynamic_variables["carrier_list"][:80],
                    result.get("source", "nowcerts")
                )
            else:
                logger.info("No match found for phone: %s", phone_digits)

        # Build the greeting message based on whether we found the customer
        is_repeat = repeat_info["is_repeat"]
        is_repeat_30min = repeat_info.get("is_repeat_30min", False)
        call_count = repeat_info["calls_24hr"]
        is_open = bh_info["is_business_hours"] == "true"

        if dynamic_variables["customer_found"] == "true" and dynamic_variables["customer_name"]:
            name = dynamic_variables["customer_name"].split()[0]  # First name only

            if is_repeat_30min:
                # Called within last 30 min — acknowledge immediately
                begin_msg = (
                    f"Hi {name}, welcome back! I see you just called a little while ago. "
                    f"I want to make sure we get this taken care of for you. "
                    f"How can I help?"
                )
            elif is_repeat and call_count >= 3 and is_open:
                # 3+ calls today during BH — auto-transfer to office
                logger.info(
                    "REPEAT CALLER AUTO-TRANSFER: %s has called %d times — connecting to office",
                    name, call_count
                )
                spoken = (
                    f"Hi {name}, I can see you've called a few times today. "
                    f"Let me connect you directly with our team right now."
                )
                dynamic_variables["is_repeat_caller"] = "true"
                dynamic_variables["repeat_call_count"] = str(call_count)
                dynamic_variables["bypass_active"] = "true"
                dynamic_variables["bypass_reason"] = f"repeat_caller_{call_count}_calls"

                return {
                    "call_inbound": {
                        "dynamic_variables": dynamic_variables,
                        "agent_override": {
                            "retell_llm": {
                                "begin_message": spoken,
                            },
                            "reminder_trigger_ms": 2000,
                            "reminder_max_count": 1,
                        },
                        "metadata": {
                            "source": "repeat_caller_auto_transfer",
                            "call_count": call_count,
                        }
                    }
                }
            elif is_repeat and call_count >= 3:
                # 3+ calls after hours — take urgent message
                begin_msg = (
                    f"Hi {name}, I can see you've called a few times today and I want to make sure "
                    f"you get the help you need. Let me take down your information and have someone "
                    f"from our team call you back as a priority. What can I help you with?"
                )
            elif is_open:
                begin_msg = (
                    f"Thank you for calling Better Choice Insurance Group! "
                    f"Hi {name}! How can I help you today?"
                )
            else:
                # After hours — greet normally; Mia mentions office
                # closed AFTER hearing their request
                begin_msg = (
                    f"Thank you for calling Better Choice Insurance Group! "
                    f"Hi {name}! How can I help you today?"
                )
        else:
            if is_repeat_30min:
                begin_msg = (
                    "Welcome back to Better Choice Insurance Group! "
                    "I see you just called — let's make sure we get this handled. "
                    "How can I help?"
                )
            elif is_open:
                begin_msg = (
                    "Thank you for calling Better Choice Insurance Group! "
                    "My name is Mia. What are you calling about today?"
                )
            else:
                # After hours, unknown caller — greet normally
                begin_msg = (
                    "Thank you for calling Better Choice Insurance Group! "
                    "My name is Mia. How can I help you today?"
                )

        dynamic_variables["greeting_message"] = begin_msg

        # Return dynamic variables AND override begin_message for guaranteed greeting
        return {
            "call_inbound": {
                "dynamic_variables": dynamic_variables,
                "agent_override": {
                    "retell_llm": {
                        "begin_message": begin_msg,
                    }
                },
                "metadata": {
                    "source": "bci_crm",
                    "lookup_phone": phone_digits,
                }
            }
        }

    except Exception as e:
        logger.error("Inbound webhook error: %s", e)
        # Return empty response — Retell will proceed with defaults
        return {"call_inbound": {}}


# ── 1b. FRONT-END INBOUND WEBHOOK ────────────────────────────────
# Used by the MIA - FRONT END agent. Same as overflow webhook but
# checks VIP/temp auth bypass FIRST. If bypass found, tells MIA to
# transfer directly to BCI office (skipping the normal conversation).
#
# NOT connected to the live overflow agent — only the front-end agent.

@router.post("/frontend-inbound")
async def frontend_inbound_webhook(request: Request):
    """Front-end receptionist inbound webhook.

    Checks VIP/temp auth bypass before NowCerts lookup. If the caller
    has an active bypass, returns a dynamic variable telling MIA to
    transfer them to the BCI office immediately.
    """
    try:
        body = await request.json()

        call_data = body.get("call_inbound", {})
        from_number = call_data.get("from_number", "") or body.get("from_number", "")
        to_number = call_data.get("to_number", "") or body.get("to_number", "")
        agent_id = call_data.get("agent_id", "") or body.get("agent_id", "")

        logger.info(
            "MIA Front-End inbound: from=%s to=%s agent=%s",
            from_number, to_number, agent_id
        )

        phone_digits = normalize_phone(from_number)

        # ── BYPASS CHECK ──────────────────────────────────────
        # Check VIP list and temp authorizations BEFORE doing any lookup
        bypass_result = _check_bypass(phone_digits)

        if bypass_result["bypass"]:
            bypass_name = bypass_result.get("customer_name", "")
            logger.info(
                "BYPASS MATCH: %s → %s (%s)",
                phone_digits, bypass_result["reason"], bypass_name
            )

            # Strategy: begin_message plays the greeting aloud.
            # After it plays, the LLM waits for user speech. But the
            # BYPASS HANDLING prompt tells the LLM: if bypass_active is
            # true and the caller says ANYTHING (or even stays silent),
            # immediately call transfer_bci_office.
            first_name = bypass_name.split()[0] if bypass_name else ""
            spoken_greeting = (
                f"One moment please, {first_name}, I'm connecting you now."
                if first_name else
                "One moment please, I'm connecting you to the office now."
            )

            bh_info = _get_business_hours_info()
            return {
                "call_inbound": {
                    "dynamic_variables": {
                        "customer_name": bypass_name,
                        "customer_phone": from_number,
                        "customer_found": "true" if bypass_name else "false",
                        "bypass_active": "true",
                        "bypass_reason": bypass_result["reason"],
                        "policy_summary": "",
                        "carrier_list": "",
                        "nowcerts_insured_id": "",
                        "customer_email": "",
                        "is_repeat_caller": "false",
                        "repeat_call_count": "1",
                        "greeting_message": spoken_greeting,
                        "is_business_hours": bh_info["is_business_hours"],
                        "current_time": bh_info["current_time"],
                        "current_day": bh_info["current_day"],
                    },
                    "agent_override": {
                        "retell_llm": {
                            "begin_message": spoken_greeting,
                        },
                        # Short reminder so if user is silent after greeting,
                        # the LLM gets prompted again quickly and can transfer
                        "reminder_trigger_ms": 2000,
                        "reminder_max_count": 1,
                    },
                    "metadata": {
                        "source": "bypass",
                        "bypass_reason": bypass_result["reason"],
                    }
                }
            }

        # ── NO BYPASS — proceed with normal NowCerts lookup ───
        # (Same logic as the overflow webhook)
        bh_info = _get_business_hours_info()
        dynamic_variables = {
            "customer_name": "",
            "policy_summary": "",
            "carrier_list": "",
            "customer_phone": from_number,
            "nowcerts_insured_id": "",
            "customer_found": "false",
            "bypass_active": "false",
            "bypass_reason": "",
            "is_repeat_caller": "false",
            "repeat_call_count": "1",
            "customer_email": "",
            "is_business_hours": bh_info["is_business_hours"],
            "current_time": bh_info["current_time"],
            "current_day": bh_info["current_day"],
        }

        repeat_info = {"is_repeat": False, "is_repeat_30min": False, "calls_30min": 1, "calls_24hr": 1}
        if phone_digits and len(phone_digits) >= 10:
            repeat_info = _check_repeat_caller(phone_digits)
            dynamic_variables["is_repeat_caller"] = "true" if repeat_info["is_repeat"] else "false"
            dynamic_variables["repeat_call_count"] = str(repeat_info["calls_24hr"])

        result = None
        if phone_digits and len(phone_digits) >= 10:
            # Layer 1: In-memory cache
            cached = _phone_cache.get(phone_digits)
            if cached and (_time.time() - cached.get("cached_at", 0)) < _CACHE_TTL:
                result = cached

            # Layer 2: NowCerts API
            if not result:
                try:
                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(_executor, _nowcerts_phone_lookup, phone_digits),
                        timeout=7.0
                    )
                    if result and result.get("customer"):
                        result["cached_at"] = _time.time()
                        _phone_cache[phone_digits] = result
                except asyncio.TimeoutError:
                    logger.warning("NowCerts lookup timed out (7s) for phone: %s", phone_digits)
                except Exception as e:
                    logger.error("NowCerts lookup failed: %s", e)

            if result and result.get("customer"):
                customer = result["customer"]
                policies = result.get("policies", [])

                first_name = customer.get("firstName") or customer.get("first_name") or ""
                last_name = customer.get("lastName") or customer.get("last_name") or ""
                commercial_name = customer.get("commercialName") or customer.get("commercial_name") or ""
                customer_name = (
                    f"{first_name} {last_name}".strip()
                    if first_name else commercial_name or ""
                )
                insured_id = customer.get("databaseId") or customer.get("database_id") or ""

                dynamic_variables["customer_name"] = customer_name
                dynamic_variables["nowcerts_insured_id"] = str(insured_id)
                dynamic_variables["customer_found"] = "true"

                customer_email = customer.get("email") or customer.get("eMail") or ""
                dynamic_variables["customer_email"] = customer_email

                if policies:
                    dynamic_variables["policy_summary"] = build_policy_summary(policies)
                    dynamic_variables["carrier_list"] = build_carrier_list(policies)

        # Build greeting — MUST account for business hours
        is_repeat = repeat_info["is_repeat"]
        is_repeat_30min = repeat_info.get("is_repeat_30min", False)
        call_count = repeat_info["calls_24hr"]
        is_open = bh_info["is_business_hours"] == "true"

        if dynamic_variables["customer_found"] == "true" and dynamic_variables["customer_name"]:
            name = dynamic_variables["customer_name"].split()[0]

            if is_repeat_30min:
                begin_msg = (
                    f"Hi {name}, welcome back! I see you just called a little while ago. "
                    f"I want to make sure we get this taken care of for you. "
                    f"How can I help?"
                )
            elif is_repeat and call_count >= 3 and is_open:
                # 3+ calls today during BH — auto-transfer to office
                logger.info(
                    "REPEAT CALLER AUTO-TRANSFER (frontend): %s has called %d times — connecting to office",
                    name, call_count
                )
                spoken = (
                    f"Hi {name}, I can see you've called a few times today. "
                    f"Let me connect you directly with our team right now."
                )
                dynamic_variables["is_repeat_caller"] = "true"
                dynamic_variables["repeat_call_count"] = str(call_count)
                dynamic_variables["bypass_active"] = "true"
                dynamic_variables["bypass_reason"] = f"repeat_caller_{call_count}_calls"

                return {
                    "call_inbound": {
                        "dynamic_variables": dynamic_variables,
                        "agent_override": {
                            "retell_llm": {
                                "begin_message": spoken,
                            },
                            "reminder_trigger_ms": 2000,
                            "reminder_max_count": 1,
                        },
                        "metadata": {
                            "source": "repeat_caller_auto_transfer",
                            "call_count": call_count,
                        }
                    }
                }
            elif is_repeat and call_count >= 3:
                # 3+ calls after hours — take urgent message
                begin_msg = (
                    f"Hi {name}, I can see you've called a few times today and I want to make sure "
                    f"you get the help you need. Let me take down your information and have someone "
                    f"from our team call you back as a priority. What can I help you with?"
                )
            elif is_open:
                # Business hours — standard greeting
                begin_msg = (
                    f"Thank you for calling Better Choice Insurance Group! "
                    f"Hi {name}! How can I help you today?"
                )
            else:
                # After hours — greet normally; Mia mentions office
                # closed AFTER hearing their request
                begin_msg = (
                    f"Thank you for calling Better Choice Insurance Group! "
                    f"Hi {name}! How can I help you today?"
                )
        else:
            if is_repeat_30min:
                begin_msg = (
                    "Welcome back to Better Choice Insurance Group! "
                    "I see you just called — let's make sure we get this handled. "
                    "How can I help?"
                )
            elif is_open:
                begin_msg = (
                    "Thank you for calling Better Choice Insurance Group! "
                    "My name is Mia. What are you calling about today?"
                )
            else:
                # After hours, unknown caller — greet normally
                begin_msg = (
                    "Thank you for calling Better Choice Insurance Group! "
                    "My name is Mia. How can I help you today?"
                )

        dynamic_variables["greeting_message"] = begin_msg

        return {
            "call_inbound": {
                "dynamic_variables": dynamic_variables,
                "agent_override": {
                    "retell_llm": {
                        "begin_message": begin_msg,
                    }
                },
                "metadata": {
                    "source": "bci_crm",
                    "lookup_phone": phone_digits,
                }
            }
        }

    except Exception as e:
        logger.error("Frontend inbound webhook error: %s", e)
        return {"call_inbound": {}}


def _check_bypass(phone_digits: str) -> dict:
    """Check if a phone number has an active VIP or temp auth bypass.

    Queries the database directly (fast — single indexed lookup).
    Returns: {bypass: bool, reason: str, customer_name: str|None}
    """
    if not phone_digits or len(phone_digits) < 10:
        return {"bypass": False, "reason": "none", "customer_name": None}

    try:
        from app.core.database import SessionLocal
        from app.models.mia_bypass import VipBypass, TempAuthorization
        from datetime import datetime, timezone

        db = SessionLocal()
        try:
            # Check permanent VIP list
            vip = (
                db.query(VipBypass)
                .filter(VipBypass.phone == phone_digits, VipBypass.is_active == True)
                .first()
            )
            if vip:
                return {
                    "bypass": True,
                    "reason": "vip",
                    "customer_name": vip.customer_name,
                }

            # Check active temp authorizations
            now = datetime.now(timezone.utc)
            temp = (
                db.query(TempAuthorization)
                .filter(
                    TempAuthorization.phone == phone_digits,
                    TempAuthorization.is_active == True,
                    TempAuthorization.expires_at > now,
                )
                .first()
            )
            if temp:
                return {
                    "bypass": True,
                    "reason": "temp_auth",
                    "customer_name": temp.customer_name,
                }
        finally:
            db.close()
    except Exception as e:
        logger.error("Bypass check failed: %s", e)

    return {"bypass": False, "reason": "none", "customer_name": None}


# ── 2. CUSTOM FUNCTION: CALLBACK / MESSAGE REQUEST ────────────────
# MIA calls this when a caller wants a callback or leaves a message.
# Sends an email to service@betterchoiceins.com with the details.
#
# Retell sends: {name, args: {...}, call: {call_id, from_number, ...}}

@router.post("/callback-request")
async def callback_request(request: Request):
    """Handle callback/message requests from MIA mid-call.

    Instead of sending a separate email, stores the request data so the
    post-call webhook can include it in a single combined email.
    """
    try:
        body = await request.json()
        args = body.get("args", {})
        call_info = body.get("call", {})

        caller_name = args.get("caller_name", "Unknown Caller")
        caller_phone = args.get("caller_phone", call_info.get("from_number", "Unknown"))
        reason = args.get("reason", "No reason provided")
        urgency = args.get("urgency", "normal")
        preferred_time = args.get("preferred_time", "Any time")
        policy_number = args.get("policy_number", "")
        carrier = args.get("carrier", "")
        request_type = args.get("request_type", "callback")  # callback, message, policy_change
        staff_requested = args.get("staff_requested", "")

        call_id = call_info.get("call_id", "")
        timestamp = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p CT")

        logger.info(
            "MIA %s request (stored for post-call): name=%s phone=%s reason=%s call_id=%s",
            request_type, caller_name, caller_phone, reason[:80], call_id
        )

        # Store request data — will be included in the post-call summary email
        request_data = {
            "caller_name": caller_name,
            "caller_phone": caller_phone,
            "reason": reason,
            "urgency": urgency,
            "preferred_time": preferred_time,
            "policy_number": policy_number,
            "carrier": carrier,
            "request_type": request_type,
            "staff_requested": staff_requested,
            "timestamp": timestamp,
            "stored_at": _time.time(),
        }

        if call_id:
            if call_id not in _pending_requests:
                _pending_requests[call_id] = []
            _pending_requests[call_id].append(request_data)

        # Cleanup old entries (shouldn't accumulate but just in case)
        now = _time.time()
        stale_ids = [k for k, v in _pending_requests.items()
                     if v and (now - v[0].get("stored_at", 0)) > _PENDING_REQUEST_TTL]
        for k in stale_ids:
            del _pending_requests[k]

        # ── URGENT MID-CALL EMAIL for cancellations ──────────
        # Cancellation requests get an IMMEDIATE email so agents
        # can prepare or intercept. Also still stored for post-call.
        is_cancellation = (
            urgency.lower() == "urgent"
            and "CANCELLATION" in reason.upper()
        )

        if is_cancellation:
            logger.info("🔴 URGENT cancellation request — sending mid-call email NOW")
            cancel_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #dc2626; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
                    <h2 style="margin: 0;">🔴 CANCELLATION — Transferring to Office</h2>
                    <p style="margin: 4px 0 0; opacity: 0.9;">MIA AI Receptionist — URGENT Mid-Call Alert</p>
                </div>
                <div style="border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
                    <p style="margin-top: 0; font-size: 16px; font-weight: bold; color: #dc2626;">
                        A customer is requesting to cancel and is being transferred to the office NOW.
                    </p>
                    <table style="width: 100%; border-collapse: collapse; margin-top: 12px;">
                        <tr><td style="padding: 8px 0; font-weight: bold; width: 140px;">Caller:</td>
                            <td style="padding: 8px 0;">{caller_name}</td></tr>
                        <tr><td style="padding: 8px 0; font-weight: bold;">Phone:</td>
                            <td style="padding: 8px 0;">{caller_phone}</td></tr>
                        {"<tr><td style='padding: 8px 0; font-weight: bold;'>Carrier:</td><td style='padding: 8px 0;'>" + carrier + "</td></tr>" if carrier else ""}
                        {"<tr><td style='padding: 8px 0; font-weight: bold;'>Policy #:</td><td style='padding: 8px 0;'>" + policy_number + "</td></tr>" if policy_number else ""}
                    </table>
                    <div style="background: #fef2f2; padding: 16px; border-radius: 6px; margin-top: 16px; border-left: 4px solid #dc2626;">
                        <p style="margin: 0; font-weight: bold;">Reason:</p>
                        <p style="margin: 8px 0 0;">{reason}</p>
                    </div>
                    <p style="color: #888; font-size: 12px; margin-top: 16px;">
                        Sent: {timestamp} · Call ID: {call_id} · This is a mid-call alert — call summary will follow.
                    </p>
                </div>
            </div>
            """
            send_mailgun_email(
                _get_email_recipients(
                    request_type="cancellation",
                    staff_requested=staff_requested,
                    urgency="urgent",
                    reason=reason,
                ),
                f"🔴 CANCELLATION — {caller_name} ({caller_phone}) — Transferring NOW",
                cancel_html
            )

        # Return success message that MIA will read to caller
        # Use business-hours-aware language so MIA doesn't say "as soon as possible" on weekends
        bh_info = _get_business_hours_info()
        if bh_info["is_business_hours"] == "true":
            followup_timing = "as soon as possible"
        else:
            # Figure out next business day
            day = bh_info["current_day"]
            if day in ("Friday", "Saturday"):
                followup_timing = "on Monday, the next business day"
            elif day == "Sunday":
                followup_timing = "on Monday, the next business day"
            else:
                followup_timing = "on the next business day"

        return {
            "result": f"Message recorded successfully. The service team has been notified and will reach out to {caller_name} {followup_timing}."
        }

    except Exception as e:
        logger.error("Callback request error: %s", e)
        bh_info = _get_business_hours_info()
        if bh_info["is_business_hours"] == "true":
            return {
                "result": "I've noted your request. Our service team will follow up with you shortly."
            }
        else:
            return {
                "result": "I've noted your request. Our service team will follow up with you on the next business day."
            }


# ── 2b. LOOKUP CUSTOMER (mid-call tool) ───────────────────────────
# MIA calls this when the initial webhook didn't find the customer
# (e.g. NowCerts timeout). She asks the caller for their phone or
# name and then fires this tool to look them up mid-call.
#
# Retell sends: {name, args: {phone?, name?}, call: {call_id, from_number, ...}}

@router.post("/lookup-customer")
async def lookup_customer(request: Request):
    """Mid-call customer lookup. Mia uses this when initial lookup failed.

    Accepts phone number and/or name, searches NowCerts, returns customer
    info so Mia can personalize the rest of the call.
    """
    try:
        body = await request.json()
        args = body.get("args", {})
        call_info = body.get("call", {})

        search_phone = args.get("phone", "")
        search_name = args.get("name", "")
        from_number = call_info.get("from_number", "")

        logger.info("lookup_customer called: phone=%s name=%s from=%s",
                     search_phone, search_name, from_number)

        # Determine which phone to search with
        phone_digits = ""
        if search_phone:
            phone_digits = re.sub(r"\D", "", search_phone)
            if len(phone_digits) > 10:
                phone_digits = phone_digits[-10:]
        if not phone_digits and from_number:
            phone_digits = normalize_phone(from_number)

        if not phone_digits and not search_name:
            return JSONResponse({
                "result": "I wasn't able to look that up. Could you give me "
                          "your phone number or full name so I can find your account?"
            })

        # Try NowCerts lookup by phone
        result = None
        if phone_digits and len(phone_digits) >= 10:
            # Check in-memory cache first
            cached = _phone_cache.get(phone_digits)
            if cached and (_time.time() - cached.get("cached_at", 0)) < _CACHE_TTL:
                result = cached
                logger.info("lookup_customer cache hit for %s", phone_digits)
            else:
                try:
                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(_executor, _nowcerts_phone_lookup, phone_digits),
                        timeout=10.0  # More generous timeout for mid-call
                    )
                    if result and result.get("customer"):
                        result["cached_at"] = _time.time()
                        _phone_cache[phone_digits] = result
                        logger.info("lookup_customer cached result for %s", phone_digits)
                except asyncio.TimeoutError:
                    logger.warning("lookup_customer NowCerts timeout for %s", phone_digits)
                except Exception as e:
                    logger.error("lookup_customer NowCerts error: %s", e)

        # TODO: If phone lookup fails and we have a name, could search by name
        # NowCerts API supports: GET /Customers/GetCustomers?Name={name}

        if result and result.get("customer"):
            customer = result["customer"]
            policies = result.get("policies", [])

            first_name = customer.get("firstName") or customer.get("first_name") or ""
            last_name = customer.get("lastName") or customer.get("last_name") or ""
            commercial_name = customer.get("commercialName") or customer.get("commercial_name") or ""
            customer_name = (
                f"{first_name} {last_name}".strip()
                if first_name else commercial_name or ""
            )

            # Build policy summary
            carriers = []
            policy_lines = []
            for p in policies:
                carrier = p.get("carrier") or p.get("carrierName") or "Unknown"
                lob = p.get("lineOfBusiness") or p.get("line_of_business") or ""
                if carrier not in carriers:
                    carriers.append(carrier)
                if lob:
                    policy_lines.append(f"{lob} with {carrier}")
                else:
                    policy_lines.append(f"a policy with {carrier}")

            policy_summary = ", ".join(policy_lines) if policy_lines else ""
            carrier_list = ", ".join(carriers) if carriers else ""
            insured_id = customer.get("databaseId") or customer.get("database_id") or ""

            response_text = f"I found the account. Customer: {customer_name}."
            if policy_summary:
                response_text += f" They have {policy_summary}."

            return JSONResponse({
                "result": response_text,
                "customer_name": customer_name,
                "policy_summary": policy_summary,
                "carrier_list": carrier_list,
                "nowcerts_insured_id": insured_id,
                "customer_found": "true",
            })
        else:
            return JSONResponse({
                "result": "I wasn't able to find an account with that information. "
                          "No worries — I can still help! What can I do for you today?",
                "customer_found": "false",
            })

    except Exception as e:
        logger.error("lookup_customer error: %s", e, exc_info=True)
        return JSONResponse({
            "result": "I had a little trouble looking that up, but no worries — "
                      "I can still help you. What do you need today?",
            "customer_found": "false",
        })


# ── 3. POST-CALL WEBHOOK (call_ended / call_analyzed) ─────────────
# Retell fires this after every call. We log to NowCerts and
# optionally send a summary email.
#
# Retell sends: {event: "call_ended", call: {call_id, transcript, ...}}

@router.post("/post-call")
async def post_call_webhook(request: Request):
    """Handle post-call events from Retell — log to NowCerts, send summary."""
    try:
        body = await request.json()
        event = body.get("event", "")
        call = body.get("call", {})

        call_id = call.get("call_id", "")
        from_number = call.get("from_number", "")
        to_number = call.get("to_number", "")
        direction = call.get("direction", "")
        transcript = call.get("transcript", "")
        duration_ms = call.get("duration_ms", 0)
        disconnection_reason = call.get("disconnection_reason", "")
        dynamic_vars = call.get("retell_llm_dynamic_variables", {})

        duration_sec = (duration_ms or 0) / 1000
        duration_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60)}s"

        customer_name = dynamic_vars.get("customer_name", "Unknown Caller")
        insured_id = dynamic_vars.get("nowcerts_insured_id", "")

        logger.info(
            "Retell post-call: event=%s call_id=%s from=%s duration=%s reason=%s",
            event, call_id, from_number, duration_str, disconnection_reason
        )

        # Only process call_ended and call_analyzed
        if event not in ("call_ended", "call_analyzed"):
            return {"status": "ok", "message": f"Ignored event: {event}"}

        # Extract call analysis data (available on call_analyzed, may be on call_ended too)
        call_analysis = call.get("call_analysis", {})
        call_summary = call_analysis.get("call_summary", "")
        call_type = call_analysis.get("call_type", "")
        carrier = call_analysis.get("carrier", "")
        department = call_analysis.get("department", "")
        sentiment = call_analysis.get("caller_sentiment", call_analysis.get("user_sentiment", ""))
        resolution = call_analysis.get("resolution", "")
        follow_up = call_analysis.get("follow_up_needed", "")

        # Log note to NowCerts on call_analyzed (has summary + analysis data)
        if insured_id and event == "call_analyzed":
            try:
                client = get_nowcerts_client()
                if client.is_configured:
                    # Build note content — put everything in subject since 
                    # that's the field NowCerts displays in the Notes tab
                    subject_parts = [f"MIA Call — {duration_str}"]
                    if call_type:
                        subject_parts[0] += f" — {call_type.replace('_', ' ').title()}"
                    if call_summary:
                        subject_parts.append(f"Summary: {call_summary}")
                    if carrier:
                        subject_parts.append(f"Carrier: {carrier}")
                    if department:
                        subject_parts.append(f"Department: {department}")
                    if resolution:
                        subject_parts.append(f"Resolution: {resolution}")
                    if sentiment:
                        subject_parts.append(f"Sentiment: {sentiment}")
                    if follow_up == "true":
                        subject_parts.append("⚠️ Follow-up needed")
                    subject_parts.append(f"Caller: {customer_name} ({from_number})")

                    note_subject = "\n".join(subject_parts)

                    client.insert_note({
                        "insured_database_id": str(insured_id),
                        "subject": note_subject,
                        "text": note_subject,
                        "description": note_subject,
                        "insured_commercial_name": customer_name,
                        "creator_name": "MIA AI Receptionist",
                        "type": "Phone Call",
                    })
                    logger.info("NowCerts note logged for insured %s", insured_id)
            except Exception as e:
                logger.error("NowCerts note insert failed: %s", e)

        # Send summary email on call_analyzed (has full analysis)
        if event == "call_analyzed":
            # Build sentiment badge
            sentiment_badge = {
                "positive": "😊 Positive",
                "neutral": "😐 Neutral",
                "frustrated": "😤 Frustrated",
                "upset": "😠 Upset",
            }.get((sentiment or "").lower(), sentiment or "Unknown")

            # Build resolution badge
            resolution_badge = {
                "transferred": "📞 Transferred to Carrier",
                "message_taken": "💬 Message Taken",
                "callback_scheduled": "📅 Callback Scheduled",
                "info_provided": "ℹ️ Info Provided",
                "caller_hangup": "📵 Caller Hung Up",
                "unresolved": "⚠️ Unresolved",
            }.get((resolution or "").lower(), resolution or "Unknown")

            follow_up_badge = "🔴 Yes" if follow_up == "true" else "🟢 No"

            # Check for any mid-call requests stored for this call
            pending_reqs = _pending_requests.pop(call_id, [])
            request_html = ""
            if pending_reqs:
                for req in pending_reqs:
                    req_urgency_badge = {
                        "urgent": "🔴 URGENT",
                        "high": "🟠 High Priority",
                        "normal": "🟢 Normal",
                        "low": "🔵 Low Priority",
                    }.get((req.get("urgency", "normal")).lower(), "🟢 Normal")

                    req_type_label = {
                        "callback": "📞 Callback Request",
                        "message": "💬 Message",
                        "policy_change": "📝 Policy Change Request",
                        "document_request": "📄 Document Request",
                    }.get(req.get("request_type", "callback"), "📞 Request")

                    staff_line = ""
                    if req.get("staff_requested"):
                        staff_line = f"<tr><td style='padding: 4px 0; font-weight: bold;'>Staff Requested:</td><td style='padding: 4px 0;'>⭐ {req['staff_requested']}</td></tr>"

                    request_html += f"""
                    <div style="background: #fff8e1; padding: 16px; border-radius: 6px; margin-top: 16px; border-left: 4px solid #f59e0b;">
                        <p style="margin: 0; font-weight: bold;">{req_type_label} · {req_urgency_badge}</p>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px;">
                            <tr><td style="padding: 4px 0; font-weight: bold; width: 130px;">Phone:</td>
                                <td style="padding: 4px 0;">{req.get('caller_phone', '')}</td></tr>
                            {staff_line}
                            {"<tr><td style='padding: 4px 0; font-weight: bold;'>Carrier:</td><td style='padding: 4px 0;'>" + req['carrier'] + "</td></tr>" if req.get('carrier') else ""}
                            {"<tr><td style='padding: 4px 0; font-weight: bold;'>Policy #:</td><td style='padding: 4px 0;'>" + req['policy_number'] + "</td></tr>" if req.get('policy_number') else ""}
                            <tr><td style="padding: 4px 0; font-weight: bold;">Preferred Time:</td>
                                <td style="padding: 4px 0;">{req.get('preferred_time', 'Any time')}</td></tr>
                        </table>
                        <div style="background: #fffbeb; padding: 10px; border-radius: 4px; margin-top: 8px;">
                            <p style="margin: 0; font-size: 13px;"><strong>Reason:</strong> {req.get('reason', 'N/A')}</p>
                        </div>
                    </div>
                    """

            # Adjust subject line if there's a request
            has_request = len(pending_reqs) > 0
            req_type_for_subject = ""
            if has_request:
                first_req = pending_reqs[0]
                req_type_for_subject = {
                    "callback": "📞 Callback",
                    "message": "💬 Message",
                    "policy_change": "📝 Policy Change",
                    "document_request": "📄 Document",
                }.get(first_req.get("request_type", ""), "📞 Request")

            html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #2c3e50; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
                    <h2 style="margin: 0;">📊 Call Summary</h2>
                    <p style="margin: 4px 0 0; opacity: 0.9;">MIA AI Receptionist</p>
                </div>
                <div style="border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 6px 0; font-weight: bold; width: 130px;">Caller:</td>
                            <td>{customer_name} ({from_number})</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: bold;">Duration:</td>
                            <td>{duration_str}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: bold;">Call Type:</td>
                            <td>{call_type.replace('_', ' ').title() if call_type else 'N/A'}</td></tr>
                        {"<tr><td style='padding: 6px 0; font-weight: bold;'>Carrier:</td><td>" + carrier + "</td></tr>" if carrier else ""}
                        {"<tr><td style='padding: 6px 0; font-weight: bold;'>Department:</td><td>" + department.title() + "</td></tr>" if department else ""}
                        <tr><td style="padding: 6px 0; font-weight: bold;">Resolution:</td>
                            <td>{resolution_badge}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: bold;">Sentiment:</td>
                            <td>{sentiment_badge}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: bold;">Follow-up:</td>
                            <td>{follow_up_badge}</td></tr>
                    </table>
                    {"<div style='background: #f0f7ff; padding: 16px; border-radius: 6px; margin-top: 16px; border-left: 4px solid #1a5276;'><p style='margin: 0; font-weight: bold;'>Summary</p><p style='margin: 8px 0 0;'>" + call_summary + "</p></div>" if call_summary else ""}
                    {request_html}
                    <details style="margin-top: 16px;">
                        <summary style="cursor: pointer; font-weight: bold; color: #1a5276;">View Full Transcript</summary>
                        <pre style="white-space: pre-wrap; font-size: 13px; background: #f8f9fa; padding: 12px; border-radius: 6px; margin-top: 8px; max-height: 400px; overflow-y: auto;">{transcript[:5000] if transcript else "No transcript"}</pre>
                    </details>
                    <p style="color: #888; font-size: 12px; margin-top: 16px;">
                        Call ID: {call_id} · Disconnect: {disconnection_reason}
                    </p>
                </div>
            </div>
            """

            if has_request:
                subject = f"📊 MIA Call — {customer_name} — {req_type_for_subject} — {resolution_badge}"
            else:
                subject = f"📊 MIA Call — {customer_name} — {resolution_badge}"

            # Smart email routing based on request context
            if has_request:
                first_req = pending_reqs[0]
                email_to = _get_email_recipients(
                    request_type=first_req.get("request_type", ""),
                    staff_requested=first_req.get("staff_requested", ""),
                    urgency=first_req.get("urgency", "normal"),
                    reason=first_req.get("reason", ""),
                )
            else:
                email_to = SERVICE_EMAIL
            send_mailgun_email(email_to, subject, html)

            # Send SMS confirmation to caller if a request was taken
            if has_request and from_number:
                try:
                    from app.api.sms import send_post_call_sms
                    first_req = pending_reqs[0]
                    sms_result = send_post_call_sms(
                        caller_phone=from_number,
                        caller_name=customer_name,
                        request_type=first_req.get("request_type", "callback"),
                        carrier=first_req.get("carrier", ""),
                    )
                    logger.info("Post-call SMS: %s", sms_result)
                except Exception as e:
                    logger.error("Post-call SMS failed: %s", e)

        return {"status": "ok"}

    except Exception as e:
        logger.error("Post-call webhook error: %s", e)
        return {"status": "error", "message": str(e)}


# ── 4. HEALTH CHECK ───────────────────────────────────────────────

@router.api_route("/health", methods=["GET", "HEAD"])
async def retell_health():
    """Health check for Retell webhook endpoints. Also warms NowCerts token."""
    client = get_nowcerts_client()
    
    # Warm up NowCerts token on every health check
    token_cached = False
    try:
        if client.is_configured:
            token = client._authenticate()
            token_cached = bool(token)
    except Exception:
        pass
    
    # Check local DB
    db_count = 0
    try:
        from app.core.database import SessionLocal
        from app.models.customer import Customer
        db = SessionLocal()
        try:
            db_count = db.query(Customer).count()
        finally:
            db.close()
    except Exception as e:
        db_count = f"error: {e}"
    
    return {
        "status": "ok",
        "nowcerts_configured": client.is_configured,
        "nowcerts_token_cached": bool(client._token),
        "mailgun_configured": bool(settings.MAILGUN_API_KEY and settings.MAILGUN_DOMAIN),
        "local_db_customers": db_count,
        "endpoints": {
            "inbound_webhook": "/api/retell/inbound-webhook",
            "callback_request": "/api/retell/callback-request",
            "post_call": "/api/retell/post-call",
        }
    }


@router.api_route("/warmup", methods=["GET", "POST"])
async def warmup_nowcerts(request: Request = None):
    """Pre-authenticate with NowCerts and optionally cache a phone lookup.
    
    POST with {"phone": "8472048231"} to pre-cache a specific number.
    POST with no body to just warm up the auth token.
    """
    result = {"status": "ok"}
    
    try:
        client = get_nowcerts_client()
        if client.is_configured:
            token = client._authenticate()
            result["token_cached"] = bool(token)
        else:
            result["token_cached"] = False
    except Exception as e:
        result["auth_error"] = str(e)
    
    # Pre-cache a phone number if provided
    if request:
        try:
            body = await request.json()
            phone = body.get("phone", "")
            if phone:
                phone_digits = normalize_phone(phone)
                if phone_digits:
                    loop = asyncio.get_event_loop()
                    lookup_result = await asyncio.wait_for(
                        loop.run_in_executor(_executor, _nowcerts_phone_lookup, phone_digits),
                        timeout=15.0
                    )
                    if lookup_result and lookup_result.get("customer"):
                        lookup_result["cached_at"] = _time.time()
                        _phone_cache[phone_digits] = lookup_result
                        customer = lookup_result["customer"]
                        result["cached_phone"] = phone_digits
                        result["cached_name"] = f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip()
                        result["cached_policies"] = len(lookup_result.get("policies", []))
                    else:
                        result["cached_phone"] = phone_digits
                        result["cached_name"] = "not found"
        except Exception:
            pass  # No body or invalid JSON — just warm up auth
    
    result["cache_size"] = len(_phone_cache)
    return result


@router.get("/debug-lookup/{phone}")
async def debug_lookup(phone: str):
    """Debug endpoint to see raw NowCerts response for a phone number."""
    client = get_nowcerts_client()
    if not client.is_configured:
        return {"error": "NowCerts not configured"}

    phone_digits = normalize_phone(phone)
    results = {}

    try:
        token = client._authenticate()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        resp = requests.get(
            f"{client.base_url}/api/Customers/GetCustomers",
            headers=headers,
            params={"Phone": phone_digits},
            timeout=15,
        )
        if resp.status_code == 200 and resp.text.strip():
            data = resp.json()
            if isinstance(data, list) and data:
                results["customers"] = data
                # Also get policies for the first match
                db_id = data[0].get("databaseId", "")
                if db_id:
                    try:
                        policies = client.get_insured_policies(str(db_id))
                        results["raw_policies"] = policies[:5]  # First 5
                        results["policy_summary"] = build_policy_summary(policies)
                        results["carrier_list"] = build_carrier_list(policies)
                    except Exception as e:
                        results["policy_error"] = str(e)
            else:
                results["customers"] = "empty"
        else:
            results["status"] = resp.status_code

    except Exception as e:
        results["error"] = str(e)

    return {"phone": phone_digits, "results": results}


@router.get("/debug-db/{phone}")
async def debug_db_lookup(phone: str):
    """Debug endpoint to see local DB matches for a phone number."""
    phone_digits = normalize_phone(phone)
    try:
        from app.core.database import SessionLocal
        from app.models.customer import Customer
        from sqlalchemy import or_
        
        db = SessionLocal()
        try:
            customers = db.query(Customer).filter(
                or_(
                    Customer.phone.like(f"%{phone_digits[-10:]}%"),
                    Customer.mobile_phone.like(f"%{phone_digits[-10:]}%"),
                )
            ).limit(10).all()
            
            return {
                "phone": phone_digits,
                "count": len(customers),
                "matches": [
                    {
                        "id": c.id,
                        "name": c.full_name,
                        "first_name": c.first_name,
                        "last_name": c.last_name,
                        "phone": c.phone,
                        "mobile_phone": c.mobile_phone,
                        "email": c.email,
                        "nowcerts_id": c.nowcerts_insured_id,
                        "is_active": c.is_active,
                    }
                    for c in customers
                ]
            }
        finally:
            db.close()
    except Exception as e:
        return {"error": str(e)}
