"""Survey API — public endpoints for customer feedback from welcome emails."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.survey import SurveyResponse
from app.services.welcome_email import send_welcome_email, build_welcome_email_html

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/survey", tags=["survey"])


@router.post("/submit")
def submit_survey(
    sale_id: int,
    rating: int,
    feedback: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Public endpoint — submit a survey rating (from welcome email link)."""
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    # Check if already submitted
    existing = db.query(SurveyResponse).filter(SurveyResponse.sale_id == sale_id).first()
    if existing:
        return {
            "success": True,
            "already_submitted": True,
            "redirect_to_google": existing.rating == 5 and settings.GOOGLE_REVIEW_URL,
            "google_review_url": settings.GOOGLE_REVIEW_URL if existing.rating == 5 else None,
        }

    ip = request.client.host if request and request.client else None
    
    response = SurveyResponse(
        sale_id=sale_id,
        rating=rating,
        feedback=feedback,
        redirected_to_google=(rating == 5 and bool(settings.GOOGLE_REVIEW_URL)),
        ip_address=ip,
    )
    db.add(response)
    db.commit()

    logger.info(f"Survey submitted: sale_id={sale_id}, rating={rating}")

    return {
        "success": True,
        "rating": rating,
        "redirect_to_google": rating == 5 and bool(settings.GOOGLE_REVIEW_URL),
        "google_review_url": settings.GOOGLE_REVIEW_URL if rating == 5 else None,
    }


@router.get("/info/{sale_id}")
def get_survey_info(
    sale_id: int,
    db: Session = Depends(get_db),
):
    """Public endpoint — get sale info for survey page (minimal data only)."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    producer = sale.producer
    return {
        "client_name": sale.client_name.split()[0] if sale.client_name else "Customer",
        "producer_name": producer.full_name if producer else "Your Agent",
        "carrier": sale.carrier or "",
        "policy_number": sale.policy_number,
        "already_submitted": db.query(SurveyResponse).filter(SurveyResponse.sale_id == sale_id).first() is not None,
    }


# ── Admin endpoints ──────────────────────────────────────────────────

@router.get("/responses")
def list_survey_responses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin — list all survey responses."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    responses = db.query(SurveyResponse).order_by(SurveyResponse.created_at.desc()).limit(200).all()
    
    result = []
    for r in responses:
        sale = r.sale
        result.append({
            "id": r.id,
            "sale_id": r.sale_id,
            "rating": r.rating,
            "feedback": r.feedback,
            "redirected_to_google": r.redirected_to_google,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "client_name": sale.client_name if sale else None,
            "policy_number": sale.policy_number if sale else None,
            "carrier": sale.carrier if sale else None,
            "producer_name": sale.producer.full_name if sale and sale.producer else None,
        })
    
    return result


@router.post("/send-welcome/{sale_id}")
def manually_send_welcome_email(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin — manually trigger welcome email for a sale."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if not sale.client_email:
        raise HTTPException(status_code=400, detail="Sale has no client email address")

    producer = sale.producer
    result = send_welcome_email(
        to_email=sale.client_email,
        client_name=sale.client_name,
        policy_number=sale.policy_number,
        carrier=sale.carrier or "",
        producer_name=producer.full_name if producer else "Your Agent",
        sale_id=sale.id,
        policy_type=sale.policy_type,
        producer_email=producer.email if producer else None,
    )

    if result["success"]:
        from datetime import datetime
        sale.welcome_email_sent = True
        sale.welcome_email_sent_at = datetime.utcnow()
        db.commit()

    return result


@router.get("/preview/{sale_id}")
def preview_welcome_email(
    sale_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin — preview the welcome email HTML for a sale."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    producer = sale.producer
    subject, html = build_welcome_email_html(
        client_name=sale.client_name,
        policy_number=sale.policy_number,
        carrier=sale.carrier or "",
        producer_name=producer.full_name if producer else "Your Agent",
        sale_id=sale.id,
        policy_type=sale.policy_type,
    )

    return {"subject": subject, "html": html}


@router.get("/stats")
def get_survey_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin — survey response statistics."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from sqlalchemy import func
    
    total = db.query(func.count(SurveyResponse.id)).scalar() or 0
    avg_rating = db.query(func.avg(SurveyResponse.rating)).scalar()
    five_stars = db.query(func.count(SurveyResponse.id)).filter(SurveyResponse.rating == 5).scalar() or 0
    google_redirects = db.query(func.count(SurveyResponse.id)).filter(SurveyResponse.redirected_to_google == True).scalar() or 0

    # Rating distribution
    distribution = {}
    for i in range(1, 6):
        count = db.query(func.count(SurveyResponse.id)).filter(SurveyResponse.rating == i).scalar() or 0
        distribution[str(i)] = count

    return {
        "total_responses": total,
        "average_rating": round(float(avg_rating), 1) if avg_rating else 0,
        "five_star_count": five_stars,
        "google_redirects": google_redirects,
        "distribution": distribution,
    }
