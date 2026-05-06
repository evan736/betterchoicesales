"""Renewal Survey API — dynamic multi-question survey for homeowner renewals.

TEST MODE: No automated sending. Create surveys manually via admin endpoint.
Public survey page at /renewal-survey/{token} requires no auth.

Dynamic flow:
  Q1: Happiness (1-5 stars) → branches to happy or unhappy path
  Happy (4-5): home updates → claims → rate lock → proactive review offer
  Unhappy (1-3): biggest concern → home updates → higher deductible → rate lock → callback offer
"""
import logging
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.renewal_survey import RenewalSurvey
from app.services.google_review import get_review_url_for_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/renewal-survey", tags=["renewal-survey"])


def _review_url_for_survey(survey: RenewalSurvey) -> str:
    """Resolve the right Google review URL for a renewal survey.

    Renewal surveys are linked to a customer (customer_id FK), so we
    use Customer.state to route. If no linked customer (legacy/manual
    surveys), falls back to the IL listing inside get_review_url_for_state.
    """
    state = survey.customer.state if survey.customer else None
    return get_review_url_for_state(state)


# ── Question Definitions ─────────────────────────────────────────

QUESTIONS = {
    "happiness": {
        "id": "happiness",
        "type": "stars",
        "text": "How happy are you with your current homeowners insurance?",
        "required": True,
        "order": 1,
    },
    # ── Happy path (4-5 stars) ──
    "home_updates": {
        "id": "home_updates",
        "type": "multi_select",
        "text": "Have you made any updates to your home in the last year?",
        "options": [
            {"value": "roof", "label": "New roof"},
            {"value": "kitchen", "label": "Kitchen remodel"},
            {"value": "bathroom", "label": "Bathroom remodel"},
            {"value": "siding", "label": "New siding"},
            {"value": "electrical", "label": "Electrical update"},
            {"value": "plumbing", "label": "Plumbing update"},
            {"value": "hvac", "label": "New HVAC system"},
            {"value": "security", "label": "Security system"},
            {"value": "pool", "label": "Added pool/spa"},
            {"value": "none", "label": "No updates"},
        ],
        "order": 2,
        "show_when": {"happiness": [4, 5]},
    },
    "filed_claim": {
        "id": "filed_claim",
        "type": "yes_no",
        "text": "Did you file any homeowners claims in the last 12 months?",
        "order": 3,
        "show_when": {"happiness": [4, 5]},
    },
    "rate_lock_happy": {
        "id": "rate_lock",
        "type": "yes_no",
        "text": "Did you know you can lock in your homeowners rate for up to 3 years? Would you like to learn more?",
        "order": 4,
        "show_when": {"happiness": [4, 5]},
    },
    "proactive_review": {
        "id": "proactive_review",
        "type": "yes_no",
        "text": "Would you like us to proactively review your renewal rates before they come out?",
        "order": 5,
        "show_when": {"happiness": [4, 5]},
    },
    # ── Unhappy path (1-3 stars) ──
    "unhappy_reason": {
        "id": "unhappy_reason",
        "type": "single_select",
        "text": "We want to make it right. What's your biggest concern?",
        "options": [
            {"value": "price_too_high", "label": "Price is too high"},
            {"value": "coverage_confusion", "label": "Coverage confusion"},
            {"value": "claims_experience", "label": "Claims experience"},
            {"value": "customer_service", "label": "Customer service"},
            {"value": "other", "label": "Other"},
        ],
        "order": 2,
        "show_when": {"happiness": [1, 2, 3]},
    },
    "unhappy_detail": {
        "id": "unhappy_detail",
        "type": "text",
        "text": "Tell us more — what could we do better?",
        "placeholder": "Your feedback helps us improve...",
        "order": 3,
        "show_when": {"happiness": [1, 2, 3]},
    },
    "home_updates_unhappy": {
        "id": "home_updates",
        "type": "multi_select",
        "text": "Have you made any home improvements that might lower your rate?",
        "options": [
            {"value": "roof", "label": "New roof"},
            {"value": "kitchen", "label": "Kitchen remodel"},
            {"value": "bathroom", "label": "Bathroom remodel"},
            {"value": "siding", "label": "New siding"},
            {"value": "electrical", "label": "Electrical update"},
            {"value": "plumbing", "label": "Plumbing update"},
            {"value": "hvac", "label": "New HVAC system"},
            {"value": "security", "label": "Security system"},
            {"value": "none", "label": "No updates"},
        ],
        "order": 4,
        "show_when": {"happiness": [1, 2, 3]},
    },
    "higher_deductible": {
        "id": "higher_deductible",
        "type": "yes_no",
        "text": "Would you be interested in raising your deductible to lower your annual premium?",
        "order": 5,
        "show_when": {"happiness": [1, 2, 3]},
    },
    "rate_lock_unhappy": {
        "id": "rate_lock",
        "type": "yes_no",
        "text": "We have a product that can lock your rate for up to 3 years, limiting future increases. Interested?",
        "order": 6,
        "show_when": {"happiness": [1, 2, 3]},
    },
    "wants_callback": {
        "id": "wants_callback",
        "type": "single_select",
        "text": "Would you like one of our agents to reach out?",
        "options": [
            {"value": "call", "label": "Yes, call me"},
            {"value": "email", "label": "No thanks, email is fine"},
            {"value": "none", "label": "I don't need anything"},
        ],
        "order": 7,
        "show_when": {"happiness": [1, 2, 3]},
    },
}


def get_questions_for_path(happiness_rating: int) -> list:
    """Return ordered list of questions based on happiness rating."""
    is_happy = happiness_rating >= 4
    path_values = [4, 5] if is_happy else [1, 2, 3]

    result = [QUESTIONS["happiness"]]
    for key, q in QUESTIONS.items():
        if key == "happiness":
            continue
        show_when = q.get("show_when", {})
        if "happiness" in show_when and any(v in show_when["happiness"] for v in path_values):
            result.append(q)

    result.sort(key=lambda q: q.get("order", 99))
    return result


# ── Schemas ──────────────────────────────────────────────────────

class CreateSurveyRequest(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    current_premium: Optional[float] = None
    renewal_date: Optional[str] = None


class SubmitAnswerRequest(BaseModel):
    question_id: str
    answer: object  # int, str, bool, list depending on question type


# ── Admin Endpoints (auth required) ──────────────────────────────

@router.post("/create")
def create_survey(
    data: CreateSurveyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new renewal survey (TEST MODE — manual creation only)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    token = uuid.uuid4().hex[:16]

    renewal_dt = None
    if data.renewal_date:
        try:
            renewal_dt = datetime.fromisoformat(data.renewal_date.replace("Z", "+00:00"))
        except Exception:
            try:
                renewal_dt = datetime.strptime(data.renewal_date[:10], "%Y-%m-%d")
            except Exception:
                pass

    survey = RenewalSurvey(
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        policy_number=data.policy_number,
        carrier=data.carrier,
        current_premium=data.current_premium,
        renewal_date=renewal_dt,
        token=token,
        status="pending",
    )
    db.add(survey)
    db.commit()
    db.refresh(survey)

    survey_url = f"https://orbit.betterchoiceins.com/renewal-survey/{token}"
    # Also works on render domain
    survey_url_render = f"https://better-choice-web.onrender.com/renewal-survey/{token}"

    logger.info(f"Created renewal survey #{survey.id} for {data.customer_name} — token={token}")

    return {
        "id": survey.id,
        "token": token,
        "url": survey_url,
        "url_render": survey_url_render,
        "status": "pending",
        "customer_name": data.customer_name,
    }


@router.get("/list")
def list_surveys(
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all renewal surveys (admin)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    query = db.query(RenewalSurvey).order_by(desc(RenewalSurvey.created_at))
    if status:
        query = query.filter(RenewalSurvey.status == status)

    surveys = query.limit(200).all()
    return {
        "surveys": [_serialize(s) for s in surveys],
        "total": query.count(),
    }


@router.get("/stats")
def survey_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Survey analytics."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager only")

    total = db.query(RenewalSurvey).count()
    completed = db.query(RenewalSurvey).filter(RenewalSurvey.status == "completed").count()
    happy = db.query(RenewalSurvey).filter(RenewalSurvey.is_happy == True).count()
    unhappy = db.query(RenewalSurvey).filter(RenewalSurvey.is_happy == False).count()
    reshops = db.query(RenewalSurvey).filter(RenewalSurvey.reshop_created == True).count()
    callbacks = db.query(RenewalSurvey).filter(RenewalSurvey.wants_callback == True).count()
    rate_lock = db.query(RenewalSurvey).filter(RenewalSurvey.interested_rate_lock == True).count()

    return {
        "total_sent": total,
        "completed": completed,
        "completion_rate": f"{(completed/total*100):.0f}%" if total else "0%",
        "happy": happy,
        "unhappy": unhappy,
        "reshops_created": reshops,
        "callbacks_requested": callbacks,
        "rate_lock_interested": rate_lock,
    }


# ── Public Endpoints (no auth — accessed via token) ──────────────

@router.get("/take/{token}")
def get_survey_by_token(token: str, db: Session = Depends(get_db)):
    """Public: Load survey by token. Returns survey info + first question."""
    survey = db.query(RenewalSurvey).filter(RenewalSurvey.token == token).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    if survey.status == "completed":
        return {
            "completed": True,
            "happiness_rating": survey.happiness_rating,
            "is_happy": survey.is_happy,
            "google_review_url": _review_url_for_survey(survey),
        }
    if survey.status == "expired":
        raise HTTPException(status_code=410, detail="Survey expired")

    # Mark as started
    if survey.status == "pending":
        survey.status = "started"
        survey.started_at = datetime.utcnow()
        db.commit()

    # Determine which questions to show based on current responses
    responses = survey.responses or {}
    happiness = responses.get("happiness")

    if happiness is not None:
        questions = get_questions_for_path(int(happiness))
    else:
        questions = [QUESTIONS["happiness"]]

    # Find next unanswered question
    answered_ids = set(responses.keys())
    next_question = None
    for q in questions:
        if q["id"] not in answered_ids:
            next_question = q
            break

    return {
        "id": survey.id,
        "token": token,
        "customer_name": survey.customer_name,
        "carrier": survey.carrier,
        "renewal_date": survey.renewal_date.isoformat() if survey.renewal_date else None,
        "current_premium": float(survey.current_premium) if survey.current_premium else None,
        "responses": responses,
        "questions": questions,
        "next_question": next_question,
        "is_complete": next_question is None and happiness is not None,
        "completed": False,
        # Tell the client which Google review URL to use, routed by the
        # linked customer's state. Customers in TX/OK/LA/AR/NM are sent
        # to the Texas listing; everyone else gets the IL listing.
        # Falls back to the IL default if no customer is linked.
        "google_review_url": _review_url_for_survey(survey),
    }


@router.post("/take/{token}/answer")
def submit_answer(
    token: str,
    data: SubmitAnswerRequest,
    db: Session = Depends(get_db),
):
    """Public: Submit an answer to a survey question."""
    survey = db.query(RenewalSurvey).filter(RenewalSurvey.token == token).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    if survey.status == "completed":
        raise HTTPException(status_code=400, detail="Survey already completed")

    responses = dict(survey.responses or {})
    responses[data.question_id] = data.answer
    survey.responses = responses

    # Update computed fields
    if data.question_id == "happiness":
        rating = int(data.answer)
        survey.happiness_rating = rating
        survey.is_happy = rating >= 4

    elif data.question_id == "home_updates":
        survey.home_updates = data.answer if isinstance(data.answer, list) else [data.answer]

    elif data.question_id == "filed_claim":
        survey.filed_claim = data.answer in (True, "yes", "true", 1)

    elif data.question_id == "rate_lock":
        survey.interested_rate_lock = data.answer in (True, "yes", "true", 1)

    elif data.question_id == "higher_deductible":
        survey.interested_higher_deductible = data.answer in (True, "yes", "true", 1)

    elif data.question_id == "unhappy_reason":
        survey.unhappy_reason = str(data.answer)

    elif data.question_id == "unhappy_detail":
        survey.feedback_text = str(data.answer)

    elif data.question_id == "wants_callback":
        survey.wants_callback = data.answer in ("call", True, "yes")

    elif data.question_id == "proactive_review":
        if data.answer in (True, "yes", "true", 1):
            survey.wants_callback = True

    # Check if survey is now complete
    happiness = responses.get("happiness")
    if happiness is not None:
        questions = get_questions_for_path(int(happiness))
        answered = set(responses.keys())
        all_answered = all(q["id"] in answered for q in questions)

        if all_answered:
            survey.status = "completed"
            survey.completed_at = datetime.utcnow()
            _process_completed_survey(survey, db)

    db.commit()

    # Return next question
    if happiness is not None:
        questions = get_questions_for_path(int(happiness))
    else:
        questions = [QUESTIONS["happiness"]]

    answered_ids = set(responses.keys())
    next_question = None
    for q in questions:
        if q["id"] not in answered_ids:
            next_question = q
            break

    return {
        "ok": True,
        "next_question": next_question,
        "is_complete": survey.status == "completed",
        "responses": responses,
        # When the survey just completed and the customer is happy, the
        # frontend renders a "Leave a Google Review" CTA. Include the
        # state-routed URL so it works without a second request.
        "google_review_url": _review_url_for_survey(survey),
    }


# ── Completion Processing ────────────────────────────────────────

def _process_completed_survey(survey: RenewalSurvey, db: Session):
    """Process a completed survey — create reshop, notify agent, etc.
    
    TEST MODE: Only logs actions, does not create real reshops or send emails.
    Set RENEWAL_SURVEY_LIVE=true to enable real actions.
    """
    import os
    is_live = os.environ.get("RENEWAL_SURVEY_LIVE", "false").lower() == "true"

    logger.info(
        f"Renewal survey completed: {survey.customer_name} "
        f"rating={survey.happiness_rating} happy={survey.is_happy} "
        f"callback={survey.wants_callback} rate_lock={survey.interested_rate_lock} "
        f"deductible={survey.interested_higher_deductible} "
        f"claim={survey.filed_claim} updates={survey.home_updates}"
    )

    if not is_live:
        logger.info(f"[TEST MODE] Would process survey #{survey.id} — skipping real actions")
        return

    # ── Create reshop for unhappy customers or those wanting review ──
    should_reshop = False
    reshop_priority = "normal"
    reshop_notes = []

    if not survey.is_happy:
        should_reshop = True
        reshop_priority = "urgent" if survey.happiness_rating <= 2 else "high"
        reshop_notes.append(f"Renewal survey: rated {survey.happiness_rating}/5")
        if survey.unhappy_reason:
            reshop_notes.append(f"Concern: {survey.unhappy_reason}")
        if survey.feedback_text:
            reshop_notes.append(f"Feedback: {survey.feedback_text}")
        if survey.interested_higher_deductible:
            reshop_notes.append("Interested in higher deductible")
        if survey.interested_rate_lock:
            reshop_notes.append("Interested in rate lock product")
    elif survey.wants_callback:
        should_reshop = True
        reshop_priority = "normal"
        reshop_notes.append(f"Renewal survey: rated {survey.happiness_rating}/5 — wants proactive rate review")

    if should_reshop:
        try:
            from app.models.reshop import Reshop
            reshop = Reshop(
                customer_id=survey.customer_id,
                customer_name=survey.customer_name,
                customer_phone=survey.customer_phone,
                customer_email=survey.customer_email,
                policy_number=survey.policy_number,
                carrier=survey.carrier,
                current_premium=survey.current_premium,
                expiration_date=survey.renewal_date,
                stage="new_request",
                priority=reshop_priority,
                source="renewal_survey",
                source_detail="; ".join(reshop_notes),
                reason=survey.unhappy_reason or "proactive_review",
                notes="\n".join(reshop_notes),
            )
            db.add(reshop)
            db.flush()
            survey.reshop_created = True
            survey.reshop_id = reshop.id
            logger.info(f"Created reshop #{reshop.id} from renewal survey #{survey.id}")
        except Exception as e:
            logger.error(f"Failed to create reshop from survey: {e}")

    # Log interest flags for future use
    if survey.interested_rate_lock:
        logger.info(f"Rate lock interest: {survey.customer_name} ({survey.policy_number})")
    if survey.home_updates and survey.home_updates != ["none"]:
        logger.info(f"Home updates for {survey.customer_name}: {survey.home_updates}")


# ── Serializer ───────────────────────────────────────────────────

def _serialize(s: RenewalSurvey) -> dict:
    return {
        "id": s.id,
        "token": s.token,
        "customer_name": s.customer_name,
        "customer_email": s.customer_email,
        "carrier": s.carrier,
        "policy_number": s.policy_number,
        "current_premium": float(s.current_premium) if s.current_premium else None,
        "renewal_date": s.renewal_date.isoformat() if s.renewal_date else None,
        "status": s.status,
        "happiness_rating": s.happiness_rating,
        "is_happy": s.is_happy,
        "wants_callback": s.wants_callback,
        "interested_rate_lock": s.interested_rate_lock,
        "interested_higher_deductible": s.interested_higher_deductible,
        "filed_claim": s.filed_claim,
        "home_updates": s.home_updates,
        "unhappy_reason": s.unhappy_reason,
        "feedback_text": s.feedback_text,
        "reshop_created": s.reshop_created,
        "responses": s.responses,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
