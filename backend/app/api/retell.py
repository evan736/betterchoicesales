"""Retell AI webhook routes for BCI AI Receptionist (Flora).

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
from datetime import datetime
from typing import Optional

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
    """Send email via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured, skipping email")
        return False
    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": f"Flora AI Receptionist <service@{settings.MAILGUN_DOMAIN}>",
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


# ── 1. INBOUND CALL WEBHOOK ───────────────────────────────────────
# Retell POSTs here when a call comes in. We look up the caller in
# NowCerts and return dynamic variables so Flora can greet by name.
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


def _local_db_phone_lookup(phone_digits: str) -> dict:
    """Look up customer in local PostgreSQL cache — should take <100ms."""
    try:
        from app.core.database import SessionLocal
        from app.models.customer import Customer, CustomerPolicy
        from sqlalchemy import or_
        
        db = SessionLocal()
        try:
            # Search by phone or mobile_phone (strip non-digits for comparison)
            customer = db.query(Customer).filter(
                or_(
                    Customer.phone.like(f"%{phone_digits[-10:]}%"),
                    Customer.mobile_phone.like(f"%{phone_digits[-10:]}%"),
                )
            ).first()
            
            if not customer:
                return {}
            
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
        dynamic_variables = {
            "customer_name": "",
            "policy_summary": "",
            "carrier_list": "",
            "customer_phone": from_number,
            "nowcerts_insured_id": "",
            "customer_found": "false",
        }

        # Look up caller — try local DB first (fast), then NowCerts API (slow)
        phone_digits = normalize_phone(from_number)
        result = None
        if phone_digits and len(phone_digits) >= 10:
            # Layer 1: In-memory cache (~0ms)
            cached = _phone_cache.get(phone_digits)
            if cached and (_time.time() - cached.get("cached_at", 0)) < _CACHE_TTL:
                result = cached
                logger.info("Cache hit for %s: %s", phone_digits, 
                           result.get("customer", {}).get("firstName", "?"))
            
            # Layer 2: Local PostgreSQL database (~50ms)
            if not result:
                try:
                    start_t = _time.time()
                    result = _local_db_phone_lookup(phone_digits)
                    elapsed = _time.time() - start_t
                    if result:
                        logger.info("Local DB match in %.0fms: %s", elapsed*1000, 
                                   result.get("customer", {}).get("firstName", "?"))
                    else:
                        logger.info("No local DB match (%.0fms)", elapsed*1000)
                except Exception as e:
                    logger.warning("Local DB lookup error: %s", e)
            
            # Layer 3: NowCerts API (~2-10s) — only if nothing found yet
            # Use 7s timeout to leave margin for Retell's 10s deadline
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

                    if policies:
                        dynamic_variables["policy_summary"] = build_policy_summary(policies)
                        dynamic_variables["carrier_list"] = build_carrier_list(policies)

                    logger.info(
                        "NowCerts match: name=%s, id=%s, carriers=%s",
                        customer_name, insured_id,
                        dynamic_variables["carrier_list"][:80]
                    )
                else:
                    logger.info("No NowCerts match for phone: %s", phone_digits)

            except asyncio.TimeoutError:
                logger.warning("NowCerts lookup timed out (8s) for phone: %s", phone_digits)
            except Exception as e:
                logger.error("NowCerts lookup failed: %s", e)

        # Build the greeting message based on whether we found the customer
        if dynamic_variables["customer_found"] == "true" and dynamic_variables["customer_name"]:
            name = dynamic_variables["customer_name"].split()[0]  # First name only
            if dynamic_variables["policy_summary"]:
                begin_msg = (
                    f"Thank you for calling Better Choice Insurance Group! "
                    f"Hi {name}, I see you have {dynamic_variables['policy_summary']}. "
                    f"How can I help you today?"
                )
            else:
                begin_msg = (
                    f"Thank you for calling Better Choice Insurance Group! "
                    f"Hi {name}! How can I help you today?"
                )
        else:
            begin_msg = (
                "Thank you for calling Better Choice Insurance Group! "
                "My name is Flora. How can I help you today?"
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


# ── 2. CUSTOM FUNCTION: CALLBACK / MESSAGE REQUEST ────────────────
# Flora calls this when a caller wants a callback or leaves a message.
# Sends an email to service@betterchoiceins.com with the details.
#
# Retell sends: {name, args: {...}, call: {call_id, from_number, ...}}

@router.post("/callback-request")
async def callback_request(request: Request):
    """Handle callback/message requests from Flora — sends email to service team."""
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

        call_id = call_info.get("call_id", "")
        timestamp = datetime.utcnow().strftime("%B %d, %Y at %I:%M %p CT")

        logger.info(
            "Flora %s request: name=%s phone=%s reason=%s",
            request_type, caller_name, caller_phone, reason[:80]
        )

        # Build email
        urgency_badge = {
            "urgent": "🔴 URGENT",
            "high": "🟠 High Priority",
            "normal": "🟢 Normal",
            "low": "🔵 Low Priority",
        }.get(urgency.lower(), "🟢 Normal")

        type_label = {
            "callback": "📞 Callback Request",
            "message": "💬 Message",
            "policy_change": "📝 Policy Change Request",
        }.get(request_type, "📞 Request")

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #1a5276; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">{type_label}</h2>
                <p style="margin: 4px 0 0; opacity: 0.9;">From Flora AI Receptionist</p>
            </div>
            <div style="border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
                <p style="margin-top: 0;"><strong>Priority:</strong> {urgency_badge}</p>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 8px 0; font-weight: bold; width: 140px;">Caller Name:</td>
                        <td style="padding: 8px 0;">{caller_name}</td></tr>
                    <tr><td style="padding: 8px 0; font-weight: bold;">Phone:</td>
                        <td style="padding: 8px 0;">{caller_phone}</td></tr>
                    {"<tr><td style='padding: 8px 0; font-weight: bold;'>Carrier:</td><td style='padding: 8px 0;'>" + carrier + "</td></tr>" if carrier else ""}
                    {"<tr><td style='padding: 8px 0; font-weight: bold;'>Policy #:</td><td style='padding: 8px 0;'>" + policy_number + "</td></tr>" if policy_number else ""}
                    <tr><td style="padding: 8px 0; font-weight: bold;">Preferred Time:</td>
                        <td style="padding: 8px 0;">{preferred_time}</td></tr>
                </table>
                <div style="background: #f8f9fa; padding: 16px; border-radius: 6px; margin-top: 16px;">
                    <p style="margin: 0; font-weight: bold;">Reason / Message:</p>
                    <p style="margin: 8px 0 0;">{reason}</p>
                </div>
                <p style="color: #888; font-size: 12px; margin-top: 16px;">
                    Received: {timestamp} · Call ID: {call_id}
                </p>
            </div>
        </div>
        """

        subject = f"{type_label} — {caller_name} ({caller_phone})"
        send_mailgun_email("service@betterchoiceins.com", subject, html)

        # Return success message that Flora will read to caller
        return {
            "result": f"Message recorded successfully. The service team has been notified and will reach out to {caller_name} as soon as possible."
        }

    except Exception as e:
        logger.error("Callback request error: %s", e)
        return {
            "result": "I've noted your request. Our service team will follow up with you shortly."
        }


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

        # Log note to NowCerts if we have an insured ID
        if insured_id and event == "call_ended":
            try:
                client = get_nowcerts_client()
                if client.is_configured:
                    # Truncate transcript for note
                    note_transcript = transcript[:2000] if transcript else "No transcript available"
                    note_subject = (
                        f"AI Receptionist Call — {duration_str} — "
                        f"{disconnection_reason or 'completed'}"
                    )

                    client.insert_note({
                        "insured_database_id": str(insured_id),
                        "subject": note_subject,
                        "insured_commercial_name": customer_name,
                        "creator_name": "Flora AI Receptionist",
                        "type": "Phone Call",
                    })
                    logger.info("NowCerts note logged for insured %s", insured_id)
            except Exception as e:
                logger.error("NowCerts note insert failed: %s", e)

        # Send summary email for call_analyzed (has richer data)
        if event == "call_analyzed":
            call_analysis = call.get("call_analysis", {})
            summary = call_analysis.get("call_summary", "")
            sentiment = call_analysis.get("user_sentiment", "")
            successful = call_analysis.get("call_successful", None)

            if summary or transcript:
                html = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background: #2c3e50; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
                        <h2 style="margin: 0;">📊 Call Summary</h2>
                        <p style="margin: 4px 0 0; opacity: 0.9;">Flora AI Receptionist</p>
                    </div>
                    <div style="border: 1px solid #ddd; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr><td style="padding: 6px 0; font-weight: bold; width: 120px;">Caller:</td>
                                <td>{customer_name} ({from_number})</td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Duration:</td>
                                <td>{duration_str}</td></tr>
                            <tr><td style="padding: 6px 0; font-weight: bold;">Outcome:</td>
                                <td>{disconnection_reason}</td></tr>
                            {"<tr><td style='padding: 6px 0; font-weight: bold;'>Sentiment:</td><td>" + sentiment + "</td></tr>" if sentiment else ""}
                            {"<tr><td style='padding: 6px 0; font-weight: bold;'>Successful:</td><td>" + ("✅ Yes" if successful else "❌ No") + "</td></tr>" if successful is not None else ""}
                        </table>
                        {"<div style='background: #f8f9fa; padding: 16px; border-radius: 6px; margin-top: 16px;'><p style='margin: 0; font-weight: bold;'>Summary:</p><p style='margin: 8px 0 0;'>" + summary + "</p></div>" if summary else ""}
                        <details style="margin-top: 16px;">
                            <summary style="cursor: pointer; font-weight: bold; color: #1a5276;">View Full Transcript</summary>
                            <pre style="white-space: pre-wrap; font-size: 13px; background: #f8f9fa; padding: 12px; border-radius: 6px; margin-top: 8px; max-height: 400px; overflow-y: auto;">{transcript[:5000] if transcript else "No transcript"}</pre>
                        </details>
                        <p style="color: #888; font-size: 12px; margin-top: 16px;">
                            Call ID: {call_id}
                        </p>
                    </div>
                </div>
                """

                send_mailgun_email(
                    "service@betterchoiceins.com",
                    f"📊 Call Summary — {customer_name} ({duration_str})",
                    html,
                )

        return {"status": "ok"}

    except Exception as e:
        logger.error("Post-call webhook error: %s", e)
        return {"status": "error", "message": str(e)}


# ── 4. HEALTH CHECK ───────────────────────────────────────────────

@router.get("/health")
async def retell_health():
    """Health check for Retell webhook endpoints."""
    client = get_nowcerts_client()
    
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


@router.post("/warmup")
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
