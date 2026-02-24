"""NowCerts note pushing utility."""
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def push_nowcerts_note(db: Session, policy_number: str, note_text: str, subject: str = None):
    """Push a note to NowCerts for a given policy number.
    
    Looks up the customer by policy number, then pushes a note via NowCerts API.
    """
    from app.services.nowcerts import get_nowcerts_client
    from app.models.customer import Customer, CustomerPolicy

    nc = get_nowcerts_client()
    if not nc.is_configured:
        logger.debug("NowCerts not configured — skipping note")
        return False

    # Look up customer
    policy = db.query(CustomerPolicy).filter(
        CustomerPolicy.policy_number == policy_number
    ).first()

    if not policy:
        # Try partial match
        clean = policy_number.replace(" ", "").strip()
        policy = db.query(CustomerPolicy).filter(
            CustomerPolicy.policy_number.ilike(f"%{clean}%")
        ).first()

    if not policy:
        logger.warning("Cannot push NowCerts note — policy %s not found", policy_number)
        return False

    customer = db.query(Customer).filter(Customer.id == policy.customer_id).first()
    if not customer:
        logger.warning("Cannot push NowCerts note — customer not found for policy %s", policy_number)
        return False

    if not subject:
        subject = f"📧 ORBIT: Communication sent — {policy_number}"

    try:
        nc.insert_note({
            "subject": subject,
            "text": note_text,
            "insured_commercial_name": customer.full_name,
            "insured_email": customer.email or "",
            "insured_database_id": customer.nowcerts_insured_id or "",
            "creator_name": "ORBIT System",
            "type": "Email",
        })
        logger.info("NowCerts note pushed for policy %s", policy_number)
        return True
    except Exception as e:
        logger.warning("NowCerts note push failed for %s: %s", policy_number, e)
        return False
