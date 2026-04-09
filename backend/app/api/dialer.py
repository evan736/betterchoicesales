"""Dialer API — manage outbound calling campaigns."""
import csv
import io
import json
import logging
import random
import requests as http_requests
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, Query
from app.core.database import SessionLocal
from app.models.dialer import DialerCampaign, DialerLead, DialerDNC

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dialer", tags=["dialer"])

RETELL_API_KEY = "key_316cf491d8daeb1214e3490380a7"
RETELL_HEADERS = {
    "Authorization": f"Bearer {RETELL_API_KEY}",
    "Content-Type": "application/json",
}


def _get_active_call_count() -> int:
    """Check how many calls are currently active/in-progress via Retell API."""
    try:
        resp = http_requests.post(
            "https://api.retellai.com/v2/list-calls",
            headers=RETELL_HEADERS,
            json={
                "filter_criteria": [
                    {"member": "status", "operator": "eq", "value": ["in_progress"]},
                    {"member": "direction", "operator": "eq", "value": ["outbound"]},
                ],
                "sort_order": "descending",
                "limit": 50,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            calls = resp.json()
            if isinstance(calls, list):
                return len(calls)
            return len(calls.get("calls", calls.get("data", [])))
        else:
            logger.warning(f"[Concurrency] Retell list-calls error: {resp.status_code} {resp.text[:200]}")
            return 0  # Fail open — don't block dialing if API errors
    except Exception as e:
        logger.warning(f"[Concurrency] Failed to check active calls: {e}")
        return 0  # Fail open

# 30-day cadence: (day_offset, preferred_time_slot)
CADENCE = [
    (0, "morning"), (0, "afternoon"),
    (1, "evening"), (2, "morning"),
    (4, "afternoon"), (6, "evening"),
    (10, "morning"), (14, "afternoon"),
    (21, "evening"), (29, "morning"),
]

MAX_LEAD_AGE = 75


def get_ct_now():
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("America/Chicago"))
    except:
        return datetime.utcnow() - timedelta(hours=6)


def get_time_slot():
    h = get_ct_now().hour
    if h < 12: return "morning"
    elif h < 15: return "afternoon"
    return "evening"


def clean_phone(phone):
    if not phone: return None
    p = str(phone).strip().replace("-","").replace("(","").replace(")","").replace(" ","").replace(".","")
    if p.startswith("+1"): return p
    if p.startswith("1") and len(p) == 11: return f"+{p}"
    if len(p) == 10: return f"+1{p}"
    return None


def is_calling_hours():
    ct = get_ct_now()
    if ct.weekday() >= 5: return False, "Weekend"
    if ct.hour < 10 or (ct.hour == 10 and ct.minute < 30): return False, "Before 10:30 AM"
    if ct.hour >= 18: return False, "After 6 PM"
    return True, "OK"


def get_lead_age(lead):
    if lead.request_date:
        return (datetime.now() - lead.request_date).days
    return (datetime.now() - lead.created_at).days


def pitch_style(age):
    if age <= 7: return "hot"
    elif age <= 21: return "warm"
    elif age <= 45: return "cool"
    return "cold"


# ── Campaign CRUD ──────────────────────────────────────────────

@router.get("/campaigns")
def list_campaigns():
    db = SessionLocal()
    try:
        campaigns = db.query(DialerCampaign).filter(
            DialerCampaign.status != "deleted"
        ).order_by(DialerCampaign.created_at.desc()).all()
        return [
            {
                "id": c.id, "name": c.name, "agent_id": c.agent_id,
                "agent_name": c.agent_name, "from_number": c.from_number,
                "status": c.status, "total_leads": c.total_leads,
                "total_dialed": c.total_dialed, "total_transferred": c.total_transferred,
                "total_callbacks": c.total_callbacks,
                "max_calls_per_day": c.max_calls_per_day,
                "concurrency_cap": c.concurrency_cap or 1,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in campaigns
        ]
    finally:
        db.close()


@router.post("/campaigns")
async def create_campaign(request: Request):
    body = await request.json()
    db = SessionLocal()
    try:
        c = DialerCampaign(
            name=body.get("name", "New Campaign"),
            agent_id=body.get("agent_id", "agent_9053034bcaf1d5142849878c2d"),
            agent_name=body.get("agent_name", "Grace"),
            from_number=body.get("from_number", "+12108649246"),
            max_calls_per_day=body.get("max_calls_per_day", 300),
            concurrency_cap=body.get("concurrency_cap", 1),
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return {"id": c.id, "name": c.name, "status": c.status}
    finally:
        db.close()


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: int, request: Request):
    body = await request.json()
    db = SessionLocal()
    try:
        c = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
        if not c:
            return {"error": "Campaign not found"}
        for key in ["name", "status", "agent_id", "from_number", "max_calls_per_day", "concurrency_cap"]:
            if key in body:
                setattr(c, key, body[key])
        db.commit()
        return {"id": c.id, "status": c.status}
    finally:
        db.close()


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    """Delete a campaign and all its leads. Cannot delete an active campaign."""
    db = SessionLocal()
    try:
        c = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
        if not c:
            return {"error": "Campaign not found"}
        if c.status == "active":
            return {"error": "Cannot delete an active campaign — pause it first"}
        # Delete leads first
        deleted_leads = db.query(DialerLead).filter(DialerLead.campaign_id == campaign_id).delete()
        db.delete(c)
        db.commit()
        return {"status": "deleted", "campaign_id": campaign_id, "leads_deleted": deleted_leads}
    finally:
        db.close()


# ── Lead Upload ────────────────────────────────────────────────

@router.post("/campaigns/{campaign_id}/upload")
async def upload_leads(campaign_id: int, file: UploadFile = File(...)):
    db = SessionLocal()
    try:
        campaign = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}

        # Get existing phones + DNC
        existing = {l.phone for l in db.query(DialerLead.phone).filter(DialerLead.campaign_id == campaign_id).all()}
        dnc = {d.phone for d in db.query(DialerDNC.phone).all()}

        content = await file.read()
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        added = 0
        skipped_dup = 0
        skipped_dnc = 0
        skipped_bad = 0
        skipped_expired = 0

        for row in reader:
            first = row.get("FirstName") or row.get("firstname") or row.get("first_name") or ""
            last = row.get("LastName") or row.get("lastname") or row.get("last_name") or ""
            name = (row.get("name") or row.get("Name") or f"{first} {last}").strip()

            phone_raw = row.get("PHONE") or row.get("phone") or row.get("Phone") or row.get("phone_number") or ""
            phone = clean_phone(phone_raw)

            if not phone:
                skipped_bad += 1
                continue
            if phone in dnc:
                skipped_dnc += 1
                continue
            if phone in existing:
                skipped_dup += 1
                continue

            # Parse request date
            rd_raw = row.get("requestdate") or row.get("RequestDate") or row.get("request_date") or ""
            request_date = None
            if rd_raw:
                try:
                    request_date = datetime.strptime(rd_raw.split(" ")[0], "%m/%d/%Y")
                except:
                    try:
                        request_date = datetime.strptime(rd_raw.split(" ")[0], "%Y-%m-%d")
                    except:
                        pass

            if request_date and (datetime.now() - request_date).days > MAX_LEAD_AGE:
                skipped_expired += 1
                continue

            # Build address
            parts = []
            for f in ["address", "Address", "ADDRESS"]:
                if row.get(f): parts.append(row[f])
            for f in ["city", "City", "CITY"]:
                if row.get(f): parts.append(row[f])
            for f in ["state", "State", "STATE"]:
                if row.get(f): parts.append(row[f])
            for f in ["zip", "Zip", "Zipcode", "ZIP"]:
                if row.get(f): parts.append(row[f])

            # Parse insurance expiration
            insexp_raw = row.get("insexp") or row.get("InsExp") or row.get("insurance_exp") or ""
            insurance_exp = None
            if insexp_raw:
                try:
                    insurance_exp = datetime.strptime(insexp_raw.split(" ")[0], "%m/%d/%Y")
                except:
                    try:
                        insurance_exp = datetime.strptime(insexp_raw.split(" ")[0], "%Y-%m-%d")
                    except:
                        pass

            lead_state = row.get("state") or row.get("State") or row.get("STATE") or ""
            lead_city = row.get("city") or row.get("City") or row.get("CITY") or ""
            lead_dob = row.get("dob") or row.get("DOB") or row.get("DateOfBirth") or ""

            lead = DialerLead(
                campaign_id=campaign_id,
                name=name or "Unknown",
                phone=phone,
                email=row.get("email") or row.get("Email") or row.get("EMAIL") or "",
                address=", ".join(parts),
                carrier=row.get("Carrier") or row.get("carrier") or "",
                home_value=row.get("HOMEVALUE") or "",
                roof_installed=row.get("RoofInstalled") or "",
                prop_type=row.get("Proptype") or "",
                insurance_exp=insurance_exp,
                state=lead_state,
                city=lead_city,
                dob=lead_dob,
                request_date=request_date,
            )
            db.add(lead)
            existing.add(phone)
            added += 1

        db.commit()

        # Update campaign totals
        campaign.total_leads = db.query(DialerLead).filter(DialerLead.campaign_id == campaign_id).count()
        db.commit()

        return {
            "added": added,
            "skipped_dup": skipped_dup,
            "skipped_dnc": skipped_dnc,
            "skipped_bad": skipped_bad,
            "skipped_expired": skipped_expired,
            "total_leads": campaign.total_leads,
        }
    finally:
        db.close()


# ── Lead Stats ─────────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/stats")
def campaign_stats(campaign_id: int):
    db = SessionLocal()
    try:
        leads = db.query(DialerLead).filter(DialerLead.campaign_id == campaign_id).all()

        statuses = {}
        age_buckets = {"0-7d": 0, "8-14d": 0, "15-21d": 0, "22-30d": 0, "31-60d": 0, "61-75d": 0}
        by_attempts = {}
        due_now = 0

        # Conversion tracking by age bucket
        age_performance = {}
        for bucket in ["0-7d", "8-14d", "15-21d", "22-30d", "31-60d", "61-75d"]:
            age_performance[bucket] = {
                "total": 0, "dialed": 0, "contacted": 0, "transferred": 0,
                "callbacks": 0, "soft_no": 0, "hard_no": 0, "dnc": 0,
                "contact_rate": 0, "transfer_rate": 0,
            }

        total_dialed = 0
        total_contacted = 0  # answered (not no_answer, not voicemail)
        total_transferred = 0
        total_callbacks = 0
        total_dnc = 0
        total_attempts = 0
        next_scheduled = None
        last_dialed = None

        contacted_statuses = {"transferred", "callback_scheduled", "soft_no", "hard_no", "do_not_call", "interested", "already_insured"}

        for l in leads:
            statuses[l.status] = statuses.get(l.status, 0) + 1
            age = get_lead_age(l)

            # Age bucket
            if age <= 7: bucket = "0-7d"
            elif age <= 14: bucket = "8-14d"
            elif age <= 21: bucket = "15-21d"
            elif age <= 30: bucket = "22-30d"
            elif age <= 60: bucket = "31-60d"
            else: bucket = "61-75d"

            age_buckets[bucket] += 1
            age_performance[bucket]["total"] += 1

            by_attempts[l.attempts] = by_attempts.get(l.attempts, 0) + 1

            if l.attempts > 0:
                total_dialed += 1
                total_attempts += l.attempts
                age_performance[bucket]["dialed"] += 1

            if l.status in contacted_statuses:
                total_contacted += 1
                age_performance[bucket]["contacted"] += 1

            if l.status == "transferred":
                total_transferred += 1
                age_performance[bucket]["transferred"] += 1
            elif l.status == "callback_scheduled":
                total_callbacks += 1
                age_performance[bucket]["callbacks"] += 1
            elif l.status == "soft_no":
                age_performance[bucket]["soft_no"] += 1
            elif l.status == "hard_no":
                age_performance[bucket]["hard_no"] += 1
            elif l.status == "do_not_call":
                total_dnc += 1
                age_performance[bucket]["dnc"] += 1

            # Track next scheduled dial
            if l.next_attempt_after and l.status in ("pending", "dialed"):
                if not next_scheduled or l.next_attempt_after < next_scheduled:
                    next_scheduled = l.next_attempt_after

            # Track last dialed
            if l.last_attempt_at:
                if not last_dialed or l.last_attempt_at > last_dialed:
                    last_dialed = l.last_attempt_at

            # Check if due
            if l.status in ("pending", "dialed") and l.attempts < 10 and age <= MAX_LEAD_AGE:
                if not l.next_attempt_after or datetime.now() >= l.next_attempt_after:
                    due_now += 1

        # Calculate rates per age bucket
        for bucket in age_performance:
            p = age_performance[bucket]
            if p["dialed"] > 0:
                p["contact_rate"] = round(p["contacted"] / p["dialed"] * 100, 1)
                p["transfer_rate"] = round(p["transferred"] / p["dialed"] * 100, 1)

        # Overall rates
        contact_rate = round(total_contacted / total_dialed * 100, 1) if total_dialed > 0 else 0
        transfer_rate = round(total_transferred / total_dialed * 100, 1) if total_dialed > 0 else 0
        answer_rate = round(total_contacted / total_dialed * 100, 1) if total_dialed > 0 else 0

        return {
            "total": len(leads),
            "due_now": due_now,
            "statuses": statuses,
            "age_buckets": age_buckets,
            "by_attempts": by_attempts,
            "age_performance": age_performance,
            # Overall metrics
            "total_dialed": total_dialed,
            "total_contacted": total_contacted,
            "total_transferred": total_transferred,
            "total_callbacks": total_callbacks,
            "total_dnc": total_dnc,
            "total_attempts": total_attempts,
            "contact_rate": contact_rate,
            "transfer_rate": transfer_rate,
            "answer_rate": answer_rate,
            "avg_attempts": round(total_attempts / total_dialed, 1) if total_dialed > 0 else 0,
            "next_scheduled": next_scheduled.isoformat() if next_scheduled else None,
            "last_dialed": last_dialed.isoformat() if last_dialed else None,
        }
    finally:
        db.close()


@router.get("/campaigns/{campaign_id}/leads")
def list_leads(campaign_id: int, status: Optional[str] = None, limit: int = 50, offset: int = 0):
    db = SessionLocal()
    try:
        q = db.query(DialerLead).filter(DialerLead.campaign_id == campaign_id)
        if status:
            q = q.filter(DialerLead.status == status)
        q = q.order_by(DialerLead.request_date.desc().nullslast())
        total = q.count()
        leads = q.offset(offset).limit(limit).all()
        return {
            "total": total,
            "leads": [
                {
                    "id": l.id, "name": l.name, "phone": l.phone, "email": l.email,
                    "address": l.address, "carrier": l.carrier, "status": l.status,
                    "attempts": l.attempts, "interest_level": l.interest_level,
                    "request_date": l.request_date.isoformat() if l.request_date else None,
                    "last_attempt_at": l.last_attempt_at.isoformat() if l.last_attempt_at else None,
                    "next_attempt_after": l.next_attempt_after.isoformat() if l.next_attempt_after else None,
                    "notes": l.notes,
                    "call_ids": l.call_ids or [],
                }
                for l in leads
            ]
        }
    finally:
        db.close()


# ── DNC Management ─────────────────────────────────────────────

@router.post("/leads/{lead_id}/dnc")
def mark_lead_dnc(lead_id: int):
    """Mark a specific lead as DNC from the UI."""
    db = SessionLocal()
    try:
        lead = db.query(DialerLead).filter(DialerLead.id == lead_id).first()
        if not lead:
            return {"error": "Lead not found"}
        lead.status = "do_not_call"
        # Also add to global DNC
        existing = db.query(DialerDNC).filter(DialerDNC.phone == lead.phone).first()
        if not existing:
            db.add(DialerDNC(phone=lead.phone, reason="lead_request"))
        db.commit()
        return {"id": lead.id, "status": "do_not_call"}
    finally:
        db.close()


# ── Lead Pipeline Integration ──────────────────────────────────

@router.post("/campaigns/{campaign_id}/export-to-pipeline")
async def export_to_pipeline(campaign_id: int, request: Request):
    """Export ALL leads into a Requote Campaign for X-date email drip targeting."""
    db = SessionLocal()
    try:
        from app.api.requote_campaigns import RequoteCampaign, RequoteLead, GlobalOptOut
        import hashlib

        dialer_leads = db.query(DialerLead).filter(
            DialerLead.campaign_id == campaign_id,
            DialerLead.status != "do_not_call",
        ).all()

        if not dialer_leads:
            return {"error": "No leads to export"}

        # Get opt-outs to skip
        opt_outs = {o.email.lower() for o in db.query(GlobalOptOut).all() if o.email}

        # Get existing requote emails to dedup
        # Create a new RequoteCampaign
        campaign_name = f"AI Dialer Export {datetime.now().strftime('%m/%d/%Y')}"
        rc = RequoteCampaign(
            name=campaign_name,
            description="Auto-exported from AI Dialer — aged home leads with insurance expiration targeting",
            status="active",
            original_filename="ai_dialer_export",
            touch1_days_before=45,
            touch2_days_before=28,
            touch3_days_before=15,
        )
        db.add(rc)
        db.flush()  # get rc.id

        added = 0
        skipped_no_email = 0
        skipped_opted_out = 0
        skipped_no_xdate = 0
        by_exp_month = {}

        for l in dialer_leads:
            if not l.email or not l.email.strip():
                skipped_no_email += 1
                continue

            if l.email.lower().strip() in opt_outs:
                skipped_opted_out += 1
                continue

            # Parse name
            parts = (l.name or "").split()
            first_name = parts[0] if parts else ""
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

            # Parse address parts
            addr_parts = (l.address or "").split(", ")

            # X-date is the insurance expiration date
            x_date = l.insurance_exp

            # Schedule touches based on x_date
            t1_date = None
            t2_date = None
            t3_date = None
            if x_date:
                t1_date = x_date - timedelta(days=45)
                t2_date = x_date - timedelta(days=28)
                t3_date = x_date - timedelta(days=15)
                # If touch date is in the past, schedule for tomorrow
                now = datetime.now()
                if t1_date < now: t1_date = now + timedelta(days=1)
                if t2_date < now: t2_date = now + timedelta(days=2)
                if t3_date < now: t3_date = now + timedelta(days=3)

                month_key = x_date.strftime("%Y-%m")
                by_exp_month[month_key] = by_exp_month.get(month_key, 0) + 1

            # Generate unsubscribe token
            token = hashlib.sha256(f"{l.email}-{rc.id}-{l.id}".encode()).hexdigest()[:24]

            rl = RequoteLead(
                campaign_id=rc.id,
                first_name=first_name,
                last_name=last_name,
                email=l.email.strip(),
                phone=l.phone,
                address=addr_parts[0] if addr_parts else "",
                city=l.city or (addr_parts[1] if len(addr_parts) > 1 else ""),
                state=l.state or (addr_parts[2] if len(addr_parts) > 2 else ""),
                zip_code=addr_parts[3] if len(addr_parts) > 3 else "",
                policy_type="home",
                carrier=l.carrier or "",
                x_date=x_date,
                touch1_scheduled_date=t1_date,
                touch2_scheduled_date=t2_date,
                touch3_scheduled_date=t3_date,
                status="touch1_scheduled" if t1_date else "pending",
                unsubscribe_token=token,
            )
            db.add(rl)
            added += 1

        # Update campaign stats
        rc.total_uploaded = len(dialer_leads)
        rc.total_valid = added
        rc.total_skipped = skipped_no_email + skipped_opted_out

        db.commit()

        return {
            "campaign_id": rc.id,
            "campaign_name": campaign_name,
            "exported": added,
            "skipped_no_email": skipped_no_email,
            "skipped_opted_out": skipped_opted_out,
            "by_exp_month": dict(sorted(by_exp_month.items())),
        }
    finally:
        db.close()


@router.get("/campaigns/{campaign_id}/export-csv")
def export_leads_csv(campaign_id: int, status: Optional[str] = None):
    """Download leads as CSV for email campaign import."""
    db = SessionLocal()
    try:
        q = db.query(DialerLead).filter(
            DialerLead.campaign_id == campaign_id,
            DialerLead.status != "do_not_call",
        )
        if status:
            q = q.filter(DialerLead.status == status)
        leads = q.all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "name", "email", "phone", "address", "city", "state",
            "carrier", "home_value", "prop_type", "insurance_exp",
            "request_date", "dialer_status", "attempts", "interest_level",
        ])
        for l in leads:
            writer.writerow([
                l.name, l.email, l.phone, l.address, l.city or "", l.state or "",
                l.carrier, l.home_value, l.prop_type,
                l.insurance_exp.strftime("%m/%d/%Y") if l.insurance_exp else "",
                l.request_date.strftime("%m/%d/%Y") if l.request_date else "",
                l.status, l.attempts, l.interest_level or "",
            ])

        from fastapi.responses import StreamingResponse
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=dialer_leads_{campaign_id}.csv"},
        )
    finally:
        db.close()


# ── Auto-Dialer Engine ─────────────────────────────────────────

import asyncio
import threading

_dialer_threads = {}  # campaign_id -> thread reference

# Number rotation config
CALLS_PER_NUMBER_PER_DAY = 60
ACTIVE_DAYS_BEFORE_REST = 5   # Use a number for 5 days then rest it
REST_DAYS = 30                 # Rest a number for 30 days before reuse
ACTIVE_POOL_SIZE = 5           # Always keep 5 numbers active
AREA_CODE = 210                # San Antonio TX

# In-memory daily counts (reset on restart, which is fine)
_number_daily_counts = {}
_current_number_idx = 0


def _get_number_pool(db):
    """Get active numbers, handle rotation/cooldown/purchasing."""
    from app.models.dialer import DialerPhoneNumber

    today = datetime.now().date()

    # Check all numbers
    all_numbers = db.query(DialerPhoneNumber).order_by(DialerPhoneNumber.created_at).all()

    active = []
    resting = []

    for n in all_numbers:
        if n.status == "resting":
            # Check if rest period is over
            if n.rest_until and today >= n.rest_until.date():
                n.status = "available"
                n.days_used = 0
                n.first_used_date = None
                n.rest_until = None
                db.commit()

        if n.status == "active":
            # Check if this number has been active for 5 days
            if n.first_used_date and (today - n.first_used_date.date()).days >= ACTIVE_DAYS_BEFORE_REST:
                n.status = "resting"
                n.rest_until = datetime.now() + timedelta(days=REST_DAYS)
                db.commit()
                logger.info(f"[NumberPool] {n.phone} resting until {n.rest_until.strftime('%m/%d/%Y')}")
                resting.append(n)
                continue
            active.append(n)

        elif n.status == "available":
            active.append(n)

    # If we don't have enough active numbers, promote available or buy new
    while len(active) < ACTIVE_POOL_SIZE:
        # Try to find an available number
        avail = db.query(DialerPhoneNumber).filter(DialerPhoneNumber.status == "available").first()
        if avail:
            avail.status = "active"
            if not avail.first_used_date:
                avail.first_used_date = datetime.now()
            db.commit()
            active.append(avail)
            logger.info(f"[NumberPool] Activated {avail.phone}")
        else:
            # Buy a new number
            try:
                resp = http_requests.post(
                    "https://api.retellai.com/create-phone-number",
                    headers=RETELL_HEADERS,
                    json={"area_code": AREA_CODE, "outbound_agent_id": "agent_9053034bcaf1d5142849878c2d"},
                    timeout=30,
                )
                if resp.status_code == 201:
                    new_phone = resp.json().get("phone_number")
                    new_num = DialerPhoneNumber(
                        phone=new_phone, status="active",
                        first_used_date=datetime.now(),
                    )
                    db.add(new_num)
                    db.commit()
                    active.append(new_num)
                    logger.info(f"[NumberPool] Purchased & activated {new_phone}")
                else:
                    logger.error(f"[NumberPool] Failed to buy number: {resp.text}")
                    break
            except Exception as e:
                logger.error(f"[NumberPool] Error buying number: {e}")
                break

    return [n.phone for n in active]


def _get_next_from_number(db):
    """Get the next outbound number with daily count rotation."""
    global _current_number_idx
    today = datetime.now().strftime("%Y-%m-%d")

    pool = _get_number_pool(db)
    if not pool:
        return "+12108649246"  # Fallback

    for _ in range(len(pool)):
        idx = _current_number_idx % len(pool)
        num = pool[idx]
        key = f"{today}:{num}"
        count = _number_daily_counts.get(key, 0)

        if count < CALLS_PER_NUMBER_PER_DAY:
            _number_daily_counts[key] = count + 1

            # Update first_used_date if needed
            from app.models.dialer import DialerPhoneNumber
            pn = db.query(DialerPhoneNumber).filter(DialerPhoneNumber.phone == num).first()
            if pn and not pn.first_used_date:
                pn.first_used_date = datetime.now()
                db.commit()

            return num

        _current_number_idx = (_current_number_idx + 1) % len(pool)

    # All maxed — use first
    return pool[0]


def _reset_daily_counts_if_new_day():
    """Clear counts at midnight."""
    global _number_daily_counts
    today = datetime.now().strftime("%Y-%m-%d")
    _number_daily_counts = {k: v for k, v in _number_daily_counts.items() if k.startswith(today)}


def _auto_dial_loop(campaign_id: int):
    """Background loop that dials continuously M-F 10:30AM-6PM CT while campaign is active."""
    logger.info(f"[AutoDialer] Campaign {campaign_id} — background dialer started")

    while True:
        db = SessionLocal()
        try:
            campaign = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
            if not campaign or campaign.status != "active":
                logger.info(f"[AutoDialer] Campaign {campaign_id} — stopped (status: {campaign.status if campaign else 'deleted'})")
                break

            ok, msg = is_calling_hours()
            if not ok:
                db.close()
                import time
                time.sleep(300)
                continue

            _reset_daily_counts_if_new_day()

            # Get due leads sorted by age (newest first)
            leads = db.query(DialerLead).filter(
                DialerLead.campaign_id == campaign_id,
                DialerLead.status.in_(["pending", "dialed"]),
                DialerLead.attempts < 10,
            ).all()

            due = []
            for l in leads:
                age = get_lead_age(l)
                if age > MAX_LEAD_AGE:
                    l.status = "expired"
                    continue
                if l.next_attempt_after and datetime.now() < l.next_attempt_after:
                    continue
                if l.last_attempt_at and (datetime.now() - l.last_attempt_at).total_seconds() < 14400:
                    continue
                due.append((l, age))

            db.commit()

            if not due:
                db.close()
                import time
                time.sleep(300)  # Check again in 5 min
                continue

            due.sort(key=lambda x: x[1])
            session_max = campaign.max_calls_per_session or 75
            to_dial = due[:session_max]

            current_slot = get_time_slot()
            dialed = 0
            cap = campaign.concurrency_cap or 1
            idx = 0  # pointer into to_dial list

            while idx < len(to_dial):
                # Re-check campaign status
                db.refresh(campaign)
                if campaign.status != "active":
                    logger.info(f"[AutoDialer] Campaign {campaign_id} — paused mid-session")
                    break

                ok, _ = is_calling_hours()
                if not ok:
                    break

                # How many slots are free?
                active = _get_active_call_count()
                slots = max(0, cap - active)

                if slots == 0:
                    import time
                    time.sleep(5)
                    continue

                # Grab the next batch of leads to dial concurrently
                batch = to_dial[idx:idx + slots]
                idx += len(batch)

                # Fire all calls in the batch
                for lead, age in batch:
                    first_name = lead.name.split()[0] if lead.name else "there"
                    try:
                        from_number = _get_next_from_number(db)
                        resp = http_requests.post(
                            "https://api.retellai.com/v2/create-phone-call",
                            headers=RETELL_HEADERS,
                            json={
                                "agent_id": campaign.agent_id,
                                "from_number": from_number,
                                "to_number": lead.phone,
                                "retell_llm_dynamic_variables": {
                                    "lead_name": first_name,
                                    "lead_full_name": lead.name,
                                    "lead_address": lead.address or "",
                                    "callback_number": "2108649246",
                                    "lead_age_days": str(age),
                                    "pitch_style": pitch_style(age),
                                },
                            },
                            timeout=30,
                        )

                        if resp.status_code == 201:
                            call_id = resp.json().get("call_id", "")
                            lead.attempts += 1
                            lead.last_attempt_at = datetime.now()
                            lead.last_time_slot = current_slot
                            lead.status = "dialed"
                            cids = lead.call_ids or []
                            cids.append(call_id)
                            lead.call_ids = cids

                            if lead.attempts < len(CADENCE):
                                next_day, _ = CADENCE[lead.attempts]
                                base = lead.request_date or lead.created_at
                                lead.next_attempt_after = base + timedelta(days=next_day)
                            else:
                                lead.status = "exhausted"

                            campaign.total_dialed = (campaign.total_dialed or 0) + 1
                            dialed += 1
                            logger.info(f"[AutoDialer] Called {lead.name} ({lead.phone}) from {from_number} — attempt {lead.attempts}, age {age}d")
                        else:
                            err = resp.json().get("message", "")
                            if "invalid" in err.lower():
                                lead.status = "wrong_number"
                            logger.warning(f"[AutoDialer] Failed {lead.phone}: {err}")

                    except Exception as e:
                        logger.error(f"[AutoDialer] Error calling {lead.phone}: {e}")

                db.commit()

                # Brief pause between batches (let calls connect before checking slots again)
                import time
                time.sleep(random.uniform(8, 15))

            logger.info(f"[AutoDialer] Campaign {campaign_id} — session complete: {dialed} calls")

        except Exception as e:
            logger.error(f"[AutoDialer] Campaign {campaign_id} — error: {e}")
        finally:
            db.close()

        # Wait between sessions — 2 minutes
        import time
        time.sleep(120)

    # Cleanup
    _dialer_threads.pop(campaign_id, None)
    logger.info(f"[AutoDialer] Campaign {campaign_id} — thread exited")


@router.post("/campaigns/{campaign_id}/start")
async def start_auto_dialer(campaign_id: int):
    """Start the auto-dialer. Runs continuously M-F 10:30AM-6PM CT until paused."""
    db = SessionLocal()
    try:
        campaign = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}

        # Set to active
        campaign.status = "active"
        db.commit()

        # Check if already running
        if campaign_id in _dialer_threads and _dialer_threads[campaign_id].is_alive():
            return {"status": "already_running", "campaign_id": campaign_id}

        # Start background thread
        t = threading.Thread(target=_auto_dial_loop, args=(campaign_id,), daemon=True)
        t.start()
        _dialer_threads[campaign_id] = t

        return {"status": "started", "campaign_id": campaign_id, "message": "Auto-dialer running. Will dial M-F 10:30AM-6PM CT until paused."}
    finally:
        db.close()


@router.post("/campaigns/{campaign_id}/stop")
async def stop_auto_dialer(campaign_id: int):
    """Stop the auto-dialer by setting campaign to paused."""
    db = SessionLocal()
    try:
        campaign = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}
        campaign.status = "paused"
        db.commit()
        return {"status": "paused", "campaign_id": campaign_id, "message": "Auto-dialer will stop after current call completes."}
    finally:
        db.close()


@router.get("/campaigns/{campaign_id}/dialer-status")
def dialer_status(campaign_id: int):
    """Check auto-dialer status + number rotation pool."""
    running = campaign_id in _dialer_threads and _dialer_threads[campaign_id].is_alive()
    today = datetime.now().strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        from app.models.dialer import DialerPhoneNumber
        all_nums = db.query(DialerPhoneNumber).order_by(DialerPhoneNumber.created_at).all()

        numbers = []
        active_count = 0
        resting_count = 0
        for n in all_nums:
            key = f"{today}:{n.phone}"
            calls_today = _number_daily_counts.get(key, 0)
            days_active = (datetime.now() - n.first_used_date).days if n.first_used_date else 0

            numbers.append({
                "phone": n.phone,
                "status": n.status,
                "days_active": days_active if n.status == "active" else 0,
                "days_until_rest": max(0, ACTIVE_DAYS_BEFORE_REST - days_active) if n.status == "active" else None,
                "rest_until": n.rest_until.strftime("%m/%d/%Y") if n.rest_until else None,
                "calls_today": calls_today,
                "max_per_day": CALLS_PER_NUMBER_PER_DAY,
            })
            if n.status == "active": active_count += 1
            if n.status == "resting": resting_count += 1

        return {
            "campaign_id": campaign_id,
            "running": running,
            "active_numbers": active_count,
            "resting_numbers": resting_count,
            "total_numbers": len(all_nums),
            "numbers": numbers,
            "config": {
                "calls_per_number_per_day": CALLS_PER_NUMBER_PER_DAY,
                "active_days_before_rest": ACTIVE_DAYS_BEFORE_REST,
                "rest_days": REST_DAYS,
                "pool_size": ACTIVE_POOL_SIZE,
            },
        }
    finally:
        db.close()


# Keep old manual dial endpoint for testing
@router.post("/campaigns/{campaign_id}/dial")
async def dial_session(campaign_id: int, max_calls: Optional[int] = Query(default=None)):
    """Manual dial session — for testing. Use /start for auto-dialing."""
    db = SessionLocal()
    try:
        campaign = db.query(DialerCampaign).filter(DialerCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}
        if campaign.status != "active":
            return {"error": f"Campaign is {campaign.status} — set to active first"}

        ok, msg = is_calling_hours()
        if not ok:
            return {"error": f"Outside calling hours: {msg}"}

        session_max = max_calls or campaign.max_calls_per_session or 75
        from_number = campaign.from_number or "+12108649246"

        # Get due leads sorted by age (newest first)
        leads = db.query(DialerLead).filter(
            DialerLead.campaign_id == campaign_id,
            DialerLead.status.in_(["pending", "dialed"]),
            DialerLead.attempts < 10,
        ).all()

        due = []
        for l in leads:
            age = get_lead_age(l)
            if age > MAX_LEAD_AGE:
                l.status = "expired"
                continue
            if l.next_attempt_after and datetime.now() < l.next_attempt_after:
                continue
            # Check 4hr minimum gap
            if l.last_attempt_at and (datetime.now() - l.last_attempt_at).total_seconds() < 14400:
                continue
            due.append((l, age))

        db.commit()  # save any expired

        # Sort newest first
        due.sort(key=lambda x: x[1])
        to_dial = due[:session_max]

        if not to_dial:
            return {"dialed": 0, "message": "No leads due right now"}

        results = []
        dialed = 0
        current_slot = get_time_slot()

        for lead, age in to_dial:
            ok, _ = is_calling_hours()
            if not ok:
                break

            first_name = lead.name.split()[0] if lead.name else "there"

            resp = http_requests.post(
                "https://api.retellai.com/v2/create-phone-call",
                headers=RETELL_HEADERS,
                json={
                    "agent_id": campaign.agent_id,
                    "from_number": from_number,
                    "to_number": lead.phone,
                    "retell_llm_dynamic_variables": {
                        "lead_name": first_name,
                        "lead_full_name": lead.name,
                        "lead_address": lead.address or "",
                        "callback_number": "2108649246",
                        "lead_age_days": str(age),
                        "pitch_style": pitch_style(age),
                    },
                },
            )

            if resp.status_code == 201:
                call_id = resp.json().get("call_id", "")
                lead.attempts += 1
                lead.last_attempt_at = datetime.now()
                lead.last_time_slot = current_slot
                lead.status = "dialed"
                cids = lead.call_ids or []
                cids.append(call_id)
                lead.call_ids = cids

                # Calculate next attempt time based on cadence
                if lead.attempts < len(CADENCE):
                    next_day, _ = CADENCE[lead.attempts]
                    base = lead.request_date or lead.created_at
                    lead.next_attempt_after = base + timedelta(days=next_day)
                else:
                    lead.status = "exhausted"

                campaign.total_dialed = (campaign.total_dialed or 0) + 1
                dialed += 1
                results.append({"name": lead.name, "phone": lead.phone, "call_id": call_id, "attempt": lead.attempts, "age": age})
            else:
                err = resp.json().get("message", "")
                results.append({"name": lead.name, "phone": lead.phone, "error": err})
                if "invalid" in err.lower():
                    lead.status = "wrong_number"

            db.commit()

            # Pacing
            if dialed < len(to_dial):
                delay = random.uniform(
                    campaign.min_delay_seconds or 30,
                    campaign.max_delay_seconds or 60
                )
                import asyncio
                await asyncio.sleep(delay)

        return {"dialed": dialed, "total_due": len(due), "results": results}
    finally:
        db.close()


# ── DNC ────────────────────────────────────────────────────────

@router.post("/dnc")
async def add_dnc(request: Request):
    body = await request.json()
    phone = clean_phone(body.get("phone", ""))
    if not phone:
        return {"error": "Invalid phone"}

    db = SessionLocal()
    try:
        existing = db.query(DialerDNC).filter(DialerDNC.phone == phone).first()
        if not existing:
            db.add(DialerDNC(phone=phone, reason=body.get("reason", "manual")))

        # Mark all leads with this number
        db.query(DialerLead).filter(DialerLead.phone == phone).update({"status": "do_not_call"})
        db.commit()
        return {"phone": phone, "status": "added"}
    finally:
        db.close()


@router.get("/dnc")
def list_dnc():
    db = SessionLocal()
    try:
        entries = db.query(DialerDNC).order_by(DialerDNC.created_at.desc()).all()
        return [{"phone": d.phone, "reason": d.reason, "created_at": d.created_at.isoformat()} for d in entries]
    finally:
        db.close()


# ── DB Migration (run once) ────────────────────────────────────

@router.post("/migrate")
def run_migration():
    """Add new columns to dialer_leads if they don't exist."""
    from sqlalchemy import text
    db = SessionLocal()
    try:
        cols = [
            ("insurance_exp", "TIMESTAMP"),
            ("state", "VARCHAR"),
            ("city", "VARCHAR"),
            ("dob", "VARCHAR"),
        ]
        added = []
        for col_name, col_type in cols:
            try:
                db.execute(text(f"ALTER TABLE dialer_leads ADD COLUMN {col_name} {col_type}"))
                db.commit()
                added.append(col_name)
            except Exception as e:
                db.rollback()
                if "already exists" in str(e):
                    pass
                else:
                    added.append(f"{col_name}: {str(e)[:50]}")
        return {"migrated": added}
    finally:
        db.close()


@router.post("/campaigns/{campaign_id}/backfill")
async def backfill_leads(campaign_id: int, file: UploadFile = File(...)):
    """Re-upload CSV to backfill insurance_exp, state, city, dob on existing leads."""
    db = SessionLocal()
    try:
        content = await file.read()
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        updated = 0
        for row in reader:
            phone_raw = row.get("PHONE") or row.get("phone") or row.get("Phone") or ""
            phone = clean_phone(phone_raw)
            if not phone:
                continue

            lead = db.query(DialerLead).filter(
                DialerLead.campaign_id == campaign_id,
                DialerLead.phone == phone,
            ).first()
            if not lead:
                continue

            # Parse insexp
            insexp_raw = row.get("insexp") or row.get("InsExp") or ""
            if insexp_raw:
                try:
                    lead.insurance_exp = datetime.strptime(insexp_raw.split(" ")[0], "%m/%d/%Y")
                except:
                    pass

            lead.state = row.get("state") or row.get("State") or lead.state
            lead.city = row.get("city") or row.get("City") or row.get("CITY") or lead.city
            lead.dob = row.get("dob") or row.get("DOB") or lead.dob
            updated += 1

        db.commit()
        return {"updated": updated}
    finally:
        db.close()


@router.post("/numbers/seed")
def seed_numbers():
    """Seed the phone number pool with SA numbers."""
    db = SessionLocal()
    try:
        from app.models.dialer import DialerPhoneNumber
        nums = ["+12108649246", "+12109886575", "+12109344252", "+12108710493", "+12108791893"]
        added = 0
        for num in nums:
            existing = db.query(DialerPhoneNumber).filter(DialerPhoneNumber.phone == num).first()
            if not existing:
                db.add(DialerPhoneNumber(phone=num, status="active", first_used_date=datetime.now()))
                added += 1
        db.commit()
        all_nums = db.query(DialerPhoneNumber).all()
        return {"added": added, "total": len(all_nums), "numbers": [{"phone": n.phone, "status": n.status} for n in all_nums]}
    finally:
        db.close()
