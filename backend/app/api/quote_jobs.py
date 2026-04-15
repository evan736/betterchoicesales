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
