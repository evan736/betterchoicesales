"""Quote Jobs API — automated quoting queue for reshop pipeline.

Endpoints:
- POST /api/quote-jobs — create a new quote job (from reshop or manual)
- GET /api/quote-jobs — list jobs with filters
- GET /api/quote-jobs/{id} — job detail
- POST /api/quote-jobs/{id}/cancel — cancel a pending job
- POST /api/quote-jobs/from-reshop/{reshop_id} — create job from reshop record

Bot endpoints (API key auth):
- GET /api/quote-jobs/bot/next — pick up next pending job
- POST /api/quote-jobs/bot/{id}/start — mark job as quoting
- POST /api/quote-jobs/bot/{id}/result — submit carrier quote result
- POST /api/quote-jobs/bot/{id}/complete — mark job done
- POST /api/quote-jobs/bot/{id}/fail — mark job failed
"""
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.security import get_current_user
from app.models.user import User
from app.models.quote_job import QuoteJob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/quote-jobs", tags=["quote-jobs"])

BOT_API_KEY = os.environ.get("QUOTE_BOT_API_KEY", "")

# Auto/Home carrier targets
AUTO_CARRIERS = ["Travelers", "Progressive", "National General", "Safeco"]
HOME_CARRIERS = ["Travelers", "Safeco", "National General", "Grange"]


def _verify_bot_key(x_bot_key: str = Header(None, alias="X-Bot-Key")):
    """Verify bot API key for bot-only endpoints."""
    if not BOT_API_KEY:
        raise HTTPException(status_code=503, detail="QUOTE_BOT_API_KEY not configured")
    if x_bot_key != BOT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid bot API key")


def _job_to_dict(job: QuoteJob) -> dict:
    return {
        "id": job.id,
        "reshop_id": job.reshop_id,
        "customer_name": job.customer_name,
        "customer_email": job.customer_email,
        "customer_phone": job.customer_phone,
        "customer_dob": job.customer_dob,
        "address": job.address,
        "city": job.city,
        "state": job.state,
        "zip_code": job.zip_code,
        "line_of_business": job.line_of_business,
        "current_carrier": job.current_carrier,
        "current_policy_number": job.current_policy_number,
        "current_premium": float(job.current_premium) if job.current_premium else None,
        "effective_date": job.effective_date.isoformat() if job.effective_date else None,
        "policy_data": job.policy_data,
        "target_carriers": job.target_carriers,
        "status": job.status,
        "results": job.results,
        "producer_id": job.producer_id,
        "created_by": job.created_by,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }


# ── User Endpoints ──

@router.post("")
def create_quote_job(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new quote job manually."""
    lob = (request.get("line_of_business") or "").lower()
    if lob not in ("auto", "home"):
        raise HTTPException(status_code=400, detail="line_of_business must be 'auto' or 'home'")

    current_carrier = (request.get("current_carrier") or "").strip()

    # Determine target carriers (exclude current carrier)
    if lob == "auto":
        targets = [c for c in AUTO_CARRIERS if c.lower() != current_carrier.lower()]
    else:
        targets = [c for c in HOME_CARRIERS if c.lower() != current_carrier.lower()]

    # Limit to 3 quotes
    targets = targets[:3]

    job = QuoteJob(
        customer_name=request.get("customer_name", ""),
        customer_email=request.get("customer_email"),
        customer_phone=request.get("customer_phone"),
        customer_dob=request.get("customer_dob"),
        address=request.get("address"),
        city=request.get("city"),
        state=request.get("state"),
        zip_code=request.get("zip_code"),
        line_of_business=lob,
        current_carrier=current_carrier,
        current_policy_number=request.get("current_policy_number"),
        current_premium=request.get("current_premium"),
        effective_date=request.get("effective_date"),
        policy_data=request.get("policy_data"),
        target_carriers=request.get("target_carriers") or targets,
        status="pending",
        results=[],
        producer_id=request.get("producer_id") or current_user.id,
        created_by=current_user.id,
        reshop_id=request.get("reshop_id"),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Quote job #{job.id} created: {job.customer_name} | {lob} | targets={targets}")
    return _job_to_dict(job)


@router.get("")
def list_quote_jobs(
    status: Optional[str] = None,
    line_of_business: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List quote jobs with optional filters."""
    q = db.query(QuoteJob)
    if status:
        q = q.filter(QuoteJob.status == status)
    if line_of_business:
        q = q.filter(QuoteJob.line_of_business == line_of_business)

    total = q.count()
    jobs = q.order_by(desc(QuoteJob.created_at)).offset(offset).limit(limit).all()
    return {
        "total": total,
        "jobs": [_job_to_dict(j) for j in jobs],
    }


@router.get("/stats")
def quote_job_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dashboard stats for quote jobs."""
    total = db.query(QuoteJob).count()
    pending = db.query(QuoteJob).filter(QuoteJob.status == "pending").count()
    quoting = db.query(QuoteJob).filter(QuoteJob.status == "quoting").count()
    completed = db.query(QuoteJob).filter(QuoteJob.status == "completed").count()
    failed = db.query(QuoteJob).filter(QuoteJob.status == "failed").count()

    return {
        "total": total,
        "pending": pending,
        "quoting": quoting,
        "completed": completed,
        "failed": failed,
    }


@router.get("/{job_id}")
def get_quote_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single quote job detail."""
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@router.post("/{job_id}/cancel")
def cancel_quote_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending quote job."""
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in '{job.status}' status")
    job.status = "cancelled"
    db.commit()
    return {"ok": True}


# ── Bot Endpoints (API key auth) ──

@router.get("/bot/next")
def bot_get_next_job(
    x_bot_key: str = Header(None, alias="X-Bot-Key"),
    db: Session = Depends(get_db),
):
    """Bot picks up the next pending job."""
    _verify_bot_key(x_bot_key)
    job = db.query(QuoteJob).filter(
        QuoteJob.status == "pending"
    ).order_by(QuoteJob.created_at).first()

    if not job:
        return {"job": None}

    return {"job": _job_to_dict(job)}


@router.post("/bot/{job_id}/start")
def bot_start_job(
    job_id: int,
    x_bot_key: str = Header(None, alias="X-Bot-Key"),
    db: Session = Depends(get_db),
):
    """Bot marks a job as in-progress."""
    _verify_bot_key(x_bot_key)
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "quoting"
    job.started_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/bot/{job_id}/result")
def bot_submit_result(
    job_id: int,
    request: dict,
    x_bot_key: str = Header(None, alias="X-Bot-Key"),
    db: Session = Depends(get_db),
):
    """Bot submits a quote result for one carrier.
    
    Expected body:
    {
        "carrier": "Progressive",
        "status": "quoted",  // quoted, declined, error
        "premium": 1234.56,
        "quote_number": "Q123456",
        "coverages": {...},
        "details": {...},
        "error": null
    }
    """
    _verify_bot_key(x_bot_key)
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "carrier": request.get("carrier", "Unknown"),
        "status": request.get("status", "error"),
        "premium": request.get("premium"),
        "quote_number": request.get("quote_number"),
        "coverages": request.get("coverages"),
        "details": request.get("details"),
        "error": request.get("error"),
        "quoted_at": datetime.utcnow().isoformat(),
    }

    results = job.results or []
    # Replace existing result for same carrier
    results = [r for r in results if r.get("carrier") != result["carrier"]]
    results.append(result)
    job.results = results

    # Check if all carriers are done
    quoted_carriers = {r["carrier"] for r in results}
    target_carriers = set(job.target_carriers or [])
    if target_carriers.issubset(quoted_carriers):
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        logger.info(f"Quote job #{job.id} completed: {len(results)} results")

    db.commit()
    return {"ok": True, "results_count": len(results)}


@router.post("/bot/{job_id}/complete")
def bot_complete_job(
    job_id: int,
    x_bot_key: str = Header(None, alias="X-Bot-Key"),
    db: Session = Depends(get_db),
):
    """Bot marks a job as completed."""
    _verify_bot_key(x_bot_key)
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "completed"
    job.completed_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/bot/{job_id}/fail")
def bot_fail_job(
    job_id: int,
    request: dict,
    x_bot_key: str = Header(None, alias="X-Bot-Key"),
    db: Session = Depends(get_db),
):
    """Bot marks a job as failed."""
    _verify_bot_key(x_bot_key)
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = "failed"
    job.error_message = request.get("error", "Unknown error")
    job.completed_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ── Enrichment from NowCerts ──

@router.post("/{job_id}/enrich")
def enrich_quote_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enrich a quote job with full policy data from NowCerts.
    
    Pulls vehicles, drivers, properties, coverages from NowCerts
    and attaches to the job's policy_data field.
    """
    job = db.query(QuoteJob).filter(QuoteJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        from app.services.nowcerts import get_nowcerts_client
        client = get_nowcerts_client()
        if not client.is_configured:
            raise HTTPException(status_code=503, detail="NowCerts not configured")

        # Find the insured in NowCerts by name or policy number
        insured_id = None

        # Try by policy number first
        if job.current_policy_number:
            results = client.search_by_policy_number(job.current_policy_number)
            if results:
                insured_id = results[0].get("database_id")

        # Fallback: search by name
        if not insured_id and job.customer_name:
            results = client.search_insureds(job.customer_name, limit=5)
            if results:
                # Try to match by name
                for r in results:
                    rname = (r.get("commercial_name") or f"{r.get('first_name','')} {r.get('last_name','')}").lower().strip()
                    if job.customer_name.lower().strip() in rname or rname in job.customer_name.lower().strip():
                        insured_id = r.get("database_id")
                        break
                if not insured_id:
                    insured_id = results[0].get("database_id")

        if not insured_id:
            raise HTTPException(status_code=404, detail="Customer not found in NowCerts")

        # Pull full enrichment
        enrichment = client.enrich_for_quoting(insured_id, job.current_policy_number)

        # Update job with enriched data
        job.policy_data = enrichment

        # Also fill in any missing customer fields from NowCerts
        insured = enrichment.get("insured", {})
        if insured:
            if not job.customer_email:
                job.customer_email = insured.get("email")
            if not job.customer_phone:
                job.customer_phone = insured.get("phone_number") or insured.get("cell_phone")
            if not job.customer_dob:
                contacts = enrichment.get("contacts", [])
                primary = next((c for c in contacts if c.get("primary_contact")), contacts[0] if contacts else None)
                if primary and primary.get("birthday"):
                    job.customer_dob = str(primary["birthday"])
            if not job.address:
                job.address = insured.get("address_line_1")
                job.city = insured.get("city")
                job.state = insured.get("state")
                job.zip_code = insured.get("zip_code")

        db.commit()

        return {
            "ok": True,
            "insured_id": insured_id,
            "vehicles": len(enrichment.get("vehicles", [])),
            "drivers": len(enrichment.get("drivers", [])),
            "properties": len(enrichment.get("properties", [])),
            "coverages": len(enrichment.get("coverages", [])),
            "contacts": len(enrichment.get("contacts", [])),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quote job enrichment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/from-reshop/{reshop_id}")
def create_from_reshop(
    reshop_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a quote job from a reshop record, auto-enriching from NowCerts."""
    from app.models.retention import ReshopRecord

    reshop = db.query(ReshopRecord).filter(ReshopRecord.id == reshop_id).first()
    if not reshop:
        raise HTTPException(status_code=404, detail="Reshop not found")

    # Determine line of business
    policy_type = (reshop.policy_type or "").lower()
    if any(t in policy_type for t in ["auto", "vehicle", "car"]):
        lob = "auto"
    elif any(t in policy_type for t in ["home", "house", "dwelling", "condo", "landlord", "renters"]):
        lob = "home"
    else:
        lob = "home"  # default

    current_carrier = (reshop.carrier or "").strip()

    # Select target carriers
    if lob == "auto":
        targets = [c for c in AUTO_CARRIERS if c.lower() != current_carrier.lower()][:3]
    else:
        targets = [c for c in HOME_CARRIERS if c.lower() != current_carrier.lower()][:3]

    job = QuoteJob(
        reshop_id=reshop_id,
        customer_name=reshop.customer_name or "",
        line_of_business=lob,
        current_carrier=current_carrier,
        current_policy_number=reshop.policy_number,
        current_premium=reshop.current_premium,
        effective_date=reshop.expiration_date,
        target_carriers=targets,
        status="pending",
        results=[],
        producer_id=reshop.producer_id,
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Auto-enrich from NowCerts
    try:
        from app.services.nowcerts import get_nowcerts_client
        client = get_nowcerts_client()
        if client.is_configured and job.current_policy_number:
            results = client.search_by_policy_number(job.current_policy_number)
            if results:
                insured_id = results[0].get("database_id")
                if insured_id:
                    enrichment = client.enrich_for_quoting(insured_id, job.current_policy_number)
                    job.policy_data = enrichment
                    insured = enrichment.get("insured", {})
                    if insured:
                        if not job.customer_email:
                            job.customer_email = insured.get("email")
                        if not job.customer_phone:
                            job.customer_phone = insured.get("phone_number") or insured.get("cell_phone")
                        if not job.address:
                            job.address = insured.get("address_line_1")
                            job.city = insured.get("city")
                            job.state = insured.get("state")
                            job.zip_code = insured.get("zip_code")
                    db.commit()
                    logger.info(f"Auto-enriched quote job #{job.id} from NowCerts")
    except Exception as e:
        logger.warning(f"Auto-enrichment failed for job #{job.id}: {e}")

    return _job_to_dict(job)
