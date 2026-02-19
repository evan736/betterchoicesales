"""Survey API — public endpoints for customer feedback from welcome emails."""
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
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
        is_positive = existing.rating >= 4
        return {
            "success": True,
            "already_submitted": True,
            "redirect_to_google": is_positive and bool(settings.GOOGLE_REVIEW_URL),
            "google_review_url": settings.GOOGLE_REVIEW_URL if is_positive else None,
            "show_feedback_form": existing.rating <= 3,
        }

    ip = request.client.host if request and request.client else None
    is_positive = rating >= 4
    
    response = SurveyResponse(
        sale_id=sale_id,
        rating=rating,
        feedback=feedback,
        redirected_to_google=(is_positive and bool(settings.GOOGLE_REVIEW_URL)),
        ip_address=ip,
    )
    db.add(response)
    db.commit()

    logger.info(f"Survey submitted: sale_id={sale_id}, rating={rating}")

    return {
        "success": True,
        "rating": rating,
        "redirect_to_google": is_positive and bool(settings.GOOGLE_REVIEW_URL),
        "google_review_url": settings.GOOGLE_REVIEW_URL if is_positive else None,
        "show_feedback_form": rating <= 3,
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
async def manually_send_welcome_email(
    sale_id: int,
    file: UploadFile = File(None),
    attach_saved_pdf: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin — manually trigger welcome email for a sale.

    Optionally attach a PDF:
      - Upload a file directly via the `file` field
      - Or set attach_saved_pdf=true to use the sale's saved application PDF
    """
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    if not sale.client_email:
        raise HTTPException(status_code=400, detail="Sale has no client email address")

    # Resolve attachment
    attachment = None
    if file and file.filename:
        att_bytes = await file.read()
        att_name = file.filename
        attachment = (att_name, att_bytes)
    elif attach_saved_pdf and sale.application_pdf_path:
        pdf_path = Path(sale.application_pdf_path)
        if pdf_path.exists():
            att_bytes = pdf_path.read_bytes()
            att_name = f"{sale.carrier or 'Policy'}_{sale.policy_number or sale.id}_Application.pdf"
            attachment = (att_name, att_bytes)

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
        attachment=attachment,
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


from pydantic import BaseModel as FeedbackBase

class FeedbackRequest(FeedbackBase):
    sale_id: int
    name: Optional[str] = ''
    email: Optional[str] = ''
    message: str
    rating: Optional[int] = None


@router.post("/feedback")
def submit_feedback(
    data: FeedbackRequest,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Public endpoint — receive detailed feedback from unhappy customers (1-3 stars).
    Sends an email notification to the agency and updates the survey record."""
    sale = db.query(Sale).filter(Sale.id == data.sale_id).first()

    # Update existing survey response with the detailed feedback
    existing = db.query(SurveyResponse).filter(SurveyResponse.sale_id == data.sale_id).first()
    if existing and data.message:
        detail_prefix = '\n\n--- Detailed Feedback ---\n' if existing.feedback else ''
        existing.feedback = (existing.feedback or '') + detail_prefix + data.message
        db.commit()

    # Send email notification to Evan
    try:
        import requests as http_requests
        if settings.MAILGUN_API_KEY and settings.MAILGUN_DOMAIN:
            policy_num = sale.policy_number if sale else 'Unknown'
            carrier = sale.carrier if sale else 'Unknown'
            client_name = sale.client_name if sale else data.name

            email_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: #dc2626; color: white; padding: 20px; border-radius: 12px 12px 0 0;">
                    <h2 style="margin: 0;">⚠️ Low Rating Feedback Received</h2>
                </div>
                <div style="background: #fff; padding: 24px; border: 1px solid #e5e7eb; border-radius: 0 0 12px 12px;">
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
                        <tr><td style="padding: 8px 0; color: #6b7280; width: 100px;">Customer:</td><td style="padding: 8px 0; font-weight: 600;">{client_name}</td></tr>
                        <tr><td style="padding: 8px 0; color: #6b7280;">Email:</td><td style="padding: 8px 0;"><a href="mailto:{data.email}">{data.email or 'Not provided'}</a></td></tr>
                        <tr><td style="padding: 8px 0; color: #6b7280;">Policy:</td><td style="padding: 8px 0;">{policy_num}</td></tr>
                        <tr><td style="padding: 8px 0; color: #6b7280;">Carrier:</td><td style="padding: 8px 0;">{carrier}</td></tr>
                        <tr><td style="padding: 8px 0; color: #6b7280;">Rating:</td><td style="padding: 8px 0; font-size: 20px;">{'⭐' * (data.rating or 0)} ({data.rating}/5)</td></tr>
                    </table>
                    <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px; margin-top: 12px;">
                        <p style="color: #991b1b; font-weight: 600; margin: 0 0 8px 0;">Customer Feedback:</p>
                        <p style="color: #1f2937; margin: 0; white-space: pre-wrap;">{data.message}</p>
                    </div>
                    {f'<p style="margin-top: 16px;"><a href="mailto:{data.email}?subject=Re: Your Better Choice Insurance Experience&body=Hi {data.name}," style="background: #2563eb; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; display: inline-block;">Reply to Customer</a></p>' if data.email else ''}
                </div>
            </div>
            """

            http_requests.post(
                f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
                auth=("api", settings.MAILGUN_API_KEY),
                data={
                    "from": f"{settings.MAILGUN_FROM_NAME} <{settings.MAILGUN_FROM_EMAIL}>",
                    "to": "evan@betterchoiceins.com",
                    "subject": f"⚠️ Low Rating ({data.rating} star) - {client_name} - {policy_num}",
                    "html": email_html,
                },
                timeout=15,
            )
            logger.info(f"Feedback notification sent for sale_id={data.sale_id}")
    except Exception as e:
        logger.error(f"Failed to send feedback notification: {e}")

    logger.info(f"Detailed feedback received: sale_id={data.sale_id}, rating={data.rating}, from={data.name}")
    return {"success": True}


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


# ── Welcome Email Template Endpoints ────────────────────────────────

@router.get("/welcome-templates")
def list_welcome_templates(
    current_user: User = Depends(get_current_user),
):
    """List all available welcome email templates with carrier info."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from app.services.welcome_email import CARRIER_INFO

    templates = []
    for key, info in CARRIER_INFO.items():
        templates.append({
            "key": key,
            "display_name": info["display_name"],
            "accent_color": info["accent_color"],
            "has_mobile_app": bool(info.get("mobile_app_url")),
            "has_claims_phone": bool(info.get("claims_phone")),
            "has_customer_service": bool(info.get("customer_service")),
            "has_payment_url": bool(info.get("payment_url")),
            "has_online_account": bool(info.get("online_account_url")),
            "extra_tip": info.get("extra_tip", ""),
        })

    # Sort alphabetically by display name
    templates.sort(key=lambda t: t["display_name"])
    return {"templates": templates, "count": len(templates), "has_generic_fallback": True}


@router.get("/welcome-templates/{carrier_key}/preview")
def preview_welcome_template(
    carrier_key: str,
    current_user: User = Depends(get_current_user),
):
    """Generate a preview of a welcome email template with sample data."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from app.services.welcome_email import build_welcome_email_html, CARRIER_INFO

    # Use "generic" key for the generic/fallback template
    if carrier_key == "generic":
        carrier_for_build = "unknown_carrier_for_generic_preview"
    else:
        if carrier_key not in CARRIER_INFO:
            raise HTTPException(status_code=404, detail=f"Template '{carrier_key}' not found")
        carrier_for_build = carrier_key

    subject, html = build_welcome_email_html(
        client_name="Jane Smith",
        policy_number="SAMPLE-12345",
        carrier=carrier_for_build,
        producer_name=current_user.full_name or "Your Agent",
        sale_id=0,
        policy_type="auto",
    )

    return {"subject": subject, "html": html, "carrier_key": carrier_key}
