"""Retention tracking API.

Provides retention analysis data — hooks into commission statement uploads
so no separate upload is needed.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.retention import RetentionRecord, RetentionSummary
from app.services.retention import run_retention_analysis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/retention", tags=["retention"])


@router.get("/summary")
def retention_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get retention summary across all analyzed periods."""
    summaries = db.query(RetentionSummary).order_by(RetentionSummary.period).all()

    if not summaries:
        return {
            "status": "no_data",
            "message": "No retention data yet. Upload commission statements to start tracking.",
            "summaries": [],
        }

    # Calculate overall stats
    total_up = sum(s.policies_up_for_renewal or 0 for s in summaries)
    total_renewed = sum(s.policies_renewed or 0 for s in summaries)
    total_moved = sum(s.policies_carrier_moved or 0 for s in summaries)
    total_rewritten = sum(s.policies_rewritten or 0 for s in summaries)
    total_lost = sum(s.policies_lost or 0 for s in summaries)
    total_pending = sum(s.policies_pending or 0 for s in summaries)

    resolved = total_up - total_pending
    retained = total_renewed + total_moved + total_rewritten
    overall_true_rate = (retained / resolved * 100) if resolved > 0 else None
    overall_policy_rate = (total_renewed / resolved * 100) if resolved > 0 else None

    total_orig_premium = sum(float(s.original_total_premium or 0) for s in summaries)
    total_lost_premium = sum(float(s.lost_premium or 0) for s in summaries)

    return {
        "overall": {
            "policies_tracked": total_up,
            "policies_resolved": resolved,
            "policies_renewed": total_renewed,
            "policies_carrier_moved": total_moved,
            "policies_rewritten": total_rewritten,
            "policies_lost": total_lost,
            "policies_pending": total_pending,
            "true_retention_rate": round(overall_true_rate, 1) if overall_true_rate else None,
            "policy_retention_rate": round(overall_policy_rate, 1) if overall_policy_rate else None,
            "total_premium_tracked": total_orig_premium,
            "premium_lost": total_lost_premium,
            "premium_retained": total_orig_premium - total_lost_premium,
        },
        "summaries": [{
            "period": s.period,
            "policies_up_for_renewal": s.policies_up_for_renewal,
            "policies_renewed": s.policies_renewed,
            "policies_carrier_moved": s.policies_carrier_moved,
            "policies_rewritten": s.policies_rewritten,
            "policies_lost": s.policies_lost,
            "policies_pending": s.policies_pending,
            "true_retention_rate": float(s.true_retention_rate) if s.true_retention_rate else None,
            "policy_retention_rate": float(s.policy_retention_rate) if s.policy_retention_rate else None,
            "original_total_premium": float(s.original_total_premium or 0),
            "renewed_total_premium": float(s.renewed_total_premium or 0),
            "lost_premium": float(s.lost_premium or 0),
            "avg_premium_change_pct": float(s.avg_premium_change_pct) if s.avg_premium_change_pct else None,
        } for s in summaries],
    }


@router.get("/details")
def retention_details(
    period: Optional[str] = None,
    outcome: Optional[str] = None,
    carrier: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    skip: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get individual retention records with filters."""
    query = db.query(RetentionRecord)

    if period:
        query = query.filter(RetentionRecord.original_period == period)
    if outcome:
        query = query.filter(RetentionRecord.outcome == outcome)
    if carrier:
        query = query.filter(RetentionRecord.carrier.ilike(f"%{carrier}%"))
    if search:
        query = query.filter(
            RetentionRecord.insured_name.ilike(f"%{search}%")
            | RetentionRecord.policy_number.ilike(f"%{search}%")
        )

    total = query.count()
    records = query.order_by(RetentionRecord.original_period.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "records": [{
            "id": r.id,
            "policy_number": r.policy_number,
            "insured_name": r.insured_name,
            "carrier": r.carrier,
            "original_period": r.original_period,
            "original_premium": float(r.original_premium or 0),
            "expected_renewal_period": r.expected_renewal_period,
            "outcome": r.outcome,
            "new_carrier": r.new_carrier,
            "new_policy_number": r.new_policy_number,
            "new_premium": float(r.new_premium or 0) if r.new_premium else None,
            "renewal_period": r.renewal_period,
            "renewal_premium": float(r.renewal_premium or 0) if r.renewal_premium else None,
            "premium_change": float(r.premium_change or 0) if r.premium_change else None,
            "premium_change_pct": float(r.premium_change_pct or 0) if r.premium_change_pct else None,
            "last_analyzed_at": r.last_analyzed_at.isoformat() if r.last_analyzed_at else None,
        } for r in records],
    }


@router.post("/analyze")
def trigger_analysis(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger retention analysis on all statement data."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    result = run_retention_analysis(db)
    return result


@router.get("/lost-customers")
def lost_customers(
    period: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get list of truly lost customers (no active policies anywhere in agency)."""
    query = db.query(RetentionRecord).filter(RetentionRecord.outcome == "lost")
    if period:
        query = query.filter(RetentionRecord.original_period == period)

    records = query.order_by(
        RetentionRecord.original_premium.desc()
    ).limit(limit).all()

    return {
        "total_lost": query.count(),
        "total_lost_premium": float(sum(float(r.original_premium or 0) for r in records)),
        "customers": [{
            "insured_name": r.insured_name,
            "policy_number": r.policy_number,
            "carrier": r.carrier,
            "original_period": r.original_period,
            "premium": float(r.original_premium or 0),
            "expected_renewal": r.expected_renewal_period,
        } for r in records],
    }


@router.get("/carrier-moves")
def carrier_moves(
    period: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get customers who moved between carriers but stayed with agency."""
    query = db.query(RetentionRecord).filter(
        RetentionRecord.outcome == "carrier_move"
    )
    if period:
        query = query.filter(RetentionRecord.original_period == period)

    records = query.order_by(RetentionRecord.original_period.desc()).limit(limit).all()

    return {
        "total_moves": query.count(),
        "moves": [{
            "insured_name": r.insured_name,
            "old_carrier": r.carrier,
            "old_policy": r.policy_number,
            "old_premium": float(r.original_premium or 0),
            "new_carrier": r.new_carrier,
            "new_policy": r.new_policy_number,
            "new_premium": float(r.new_premium or 0) if r.new_premium else None,
            "period": r.original_period,
        } for r in records],
    }
