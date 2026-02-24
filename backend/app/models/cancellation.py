"""Prior policy cancellation request models.

Tracks the full lifecycle:
1. Customer fills out form (old carrier, policy number)
2. Cancellation letter auto-generated as PDF
3. Customer e-signs via BoldSign
4. Signed letter delivered to old carrier (fax, email, or mail)
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, Boolean, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class CancellationCarrier(Base):
    """Directory of carrier cancellation contact info and preferred methods."""
    __tablename__ = "cancellation_carriers"

    id = Column(Integer, primary_key=True, index=True)
    carrier_name = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)

    # Cancellation methods — filled in order of preference
    preferred_method = Column(String, default="fax")  # fax, email, mail, phone_only
    cancellation_fax = Column(String, nullable=True)
    cancellation_email = Column(String, nullable=True)
    cancellation_mail_address = Column(Text, nullable=True)  # full mailing address
    cancellation_phone = Column(String, nullable=True)

    # Carrier-specific requirements
    requires_signature = Column(Boolean, default=True)
    requires_notarization = Column(Boolean, default=False)
    accepts_agent_submission = Column(Boolean, default=True)  # can WE send it, or must the customer?
    notes = Column(Text, nullable=True)  # any special instructions

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CancellationRequest(Base):
    """Tracks each customer's prior-policy cancellation request through the pipeline."""
    __tablename__ = "cancellation_requests"

    id = Column(Integer, primary_key=True, index=True)

    # Link to sale (the new policy they bought with us)
    sale_id = Column(Integer, nullable=True, index=True)

    # Customer info
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    customer_address = Column(Text, nullable=True)

    # Old carrier info (from customer form submission)
    old_carrier_name = Column(String, nullable=True)  # maps to CancellationCarrier
    old_policy_number = Column(String, nullable=True)
    old_policy_type = Column(String, nullable=True)  # auto, home, renters, etc.
    requested_cancel_date = Column(String, nullable=True)  # effective date

    # New policy info (auto-filled from sale)
    new_carrier = Column(String, nullable=True)
    new_policy_number = Column(String, nullable=True)
    new_effective_date = Column(String, nullable=True)

    # Pipeline status
    status = Column(String, default="pending_info")
    # pending_info → form_submitted → letter_generated → awaiting_signature →
    # signed → delivering → delivered → confirmed → error

    # Letter generation
    letter_pdf_url = Column(String, nullable=True)
    letter_generated_at = Column(DateTime(timezone=True), nullable=True)

    # E-signature (BoldSign)
    boldsign_document_id = Column(String, nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    signed_pdf_url = Column(String, nullable=True)

    # Delivery
    delivery_method = Column(String, nullable=True)  # fax, email, mail
    delivery_id = Column(String, nullable=True)  # fax job ID, email message ID, Lob letter ID
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String, nullable=True)  # sent, delivered, failed, returned
    delivery_confirmation = Column(Text, nullable=True)  # confirmation code/receipt

    # Follow-up tracking
    reminder_count = Column(Integer, default=0)
    last_reminder_at = Column(DateTime(timezone=True), nullable=True)

    # Form token (for public access without auth)
    form_token = Column(String, nullable=True, unique=True, index=True)

    # Metadata
    created_by = Column(String, nullable=True)  # system, agent name
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
