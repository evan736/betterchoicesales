"""Models for automation campaigns: renewals, UW requirements, win-back, quotes, onboarding."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, Boolean, JSON, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


# ═══════════════════════════════════════════════════════════════════
# RENEWAL TRACKING
# ═══════════════════════════════════════════════════════════════════

class RenewalNotice(Base):
    """Tracks renewal outreach for upcoming policy expirations."""
    __tablename__ = "renewal_notices"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    nowcerts_insured_id = Column(String, nullable=True, index=True)

    # Customer info
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # Policy info (primary/highest-rate policy for grouped renewals)
    policy_number = Column(String, nullable=False, index=True)
    carrier = Column(String, nullable=True)
    line_of_business = Column(String, nullable=True)
    expiration_date = Column(DateTime, nullable=False)

    # Rate change
    current_premium = Column(Numeric(10, 2), nullable=True)
    renewal_premium = Column(Numeric(10, 2), nullable=True)
    rate_change_pct = Column(Numeric(6, 2), nullable=True)
    rate_category = Column(String, nullable=True)  # high_increase, low_increase, decrease, unknown

    # All policies renewing (JSON array for multi-policy grouping)
    all_renewing_policies = Column(JSON, nullable=True)

    # Outreach tracking
    status = Column(String, default="pending")  # pending, notified_90, notified_60, notified_30, completed
    email_90_sent = Column(Boolean, default=False)
    email_60_sent = Column(Boolean, default=False)
    email_30_sent = Column(Boolean, default=False)
    email_14_sent = Column(Boolean, default=False)
    sms_sent = Column(Boolean, default=False)
    ghl_webhook_sent = Column(Boolean, default=False)

    # Agent assignment
    agent_name = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════
# UNDERWRITING REQUIREMENTS
# ═══════════════════════════════════════════════════════════════════

class UWRequirement(Base):
    """Tracks underwriting requirements that need customer action."""
    __tablename__ = "uw_requirements"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    nowcerts_insured_id = Column(String, nullable=True, index=True)

    # Customer info
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # Policy info
    policy_number = Column(String, nullable=False, index=True)
    carrier = Column(String, nullable=True)

    # Requirement details
    requirement_type = Column(String, nullable=False)
    # Types: proof_of_prior, excluded_driver, non_disclosed_driver,
    #        vehicle_registration, trampoline, inspection, dog_notification,
    #        roof_certification, occupancy_verification, other
    requirement_description = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    consequence = Column(String, nullable=True)  # e.g. "Policy will be cancelled", "Surcharge applied"

    # Status tracking
    status = Column(String, default="open")  # open, notified, reminded, received, overdue, closed
    notification_count = Column(Integer, default=0)
    last_notified_at = Column(DateTime(timezone=True), nullable=True)

    # Resolution
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # File attachment (if customer uploads proof)
    attachment_path = Column(String, nullable=True)

    # Agent
    agent_name = Column(String, nullable=True)
    created_by = Column(Integer, nullable=True)  # user_id who created it

    # NowCerts note tracking
    nowcerts_note_added = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════
# WIN-BACK CAMPAIGN
# ═══════════════════════════════════════════════════════════════════

class WinBackCampaign(Base):
    """Tracks win-back remarket campaigns for cancelled customers."""
    __tablename__ = "winback_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    nowcerts_insured_id = Column(String, nullable=True, index=True)

    # Customer info
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # Policy that was cancelled
    policy_number = Column(String, nullable=True, index=True)
    carrier = Column(String, nullable=True)
    line_of_business = Column(String, nullable=True)
    premium_at_cancel = Column(Numeric(10, 2), nullable=True)

    # Tenure tracking
    original_effective_date = Column(DateTime, nullable=True)
    cancellation_date = Column(DateTime, nullable=True)
    months_active = Column(Integer, nullable=True)  # Must be >= 6 to qualify
    cancellation_reason = Column(String, nullable=True)

    # Campaign status
    status = Column(String, default="pending")
    # pending, active, won_back, opted_out, excluded, completed
    excluded = Column(Boolean, default=False)  # Agent manually excluded
    excluded_by = Column(Integer, nullable=True)  # user_id who excluded
    excluded_reason = Column(Text, nullable=True)

    # Outreach tracking
    touchpoint_count = Column(Integer, default=0)
    last_touchpoint_at = Column(DateTime(timezone=True), nullable=True)
    next_touchpoint_at = Column(DateTime(timezone=True), nullable=True)
    ghl_webhook_sent = Column(Boolean, default=False)

    # Result
    won_back_date = Column(DateTime(timezone=True), nullable=True)
    new_policy_number = Column(String, nullable=True)

    # Agent
    agent_name = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════
# QUOTE TRACKING
# ═══════════════════════════════════════════════════════════════════

class Quote(Base):
    """Tracks insurance quotes sent to prospects."""
    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    nowcerts_insured_id = Column(String, nullable=True, index=True)

    # Prospect info
    prospect_name = Column(String, nullable=False)
    prospect_email = Column(String, nullable=True)
    prospect_phone = Column(String, nullable=True)
    prospect_address = Column(String, nullable=True)
    prospect_city = Column(String, nullable=True)
    prospect_state = Column(String, nullable=True)
    prospect_zip = Column(String, nullable=True)

    # Quote details
    carrier = Column(String, nullable=False)
    policy_type = Column(String, nullable=False)  # auto, home, renters, umbrella, life, etc.
    quoted_premium = Column(Numeric(10, 2), nullable=True)
    effective_date = Column(DateTime, nullable=True)
    quote_date = Column(DateTime(timezone=True), server_default=func.now())

    # PDF attachment
    quote_pdf_path = Column(String, nullable=True)
    quote_pdf_filename = Column(String, nullable=True)

    # Email tracking
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)

    # Follow-up tracking
    followup_3day_sent = Column(Boolean, default=False)
    followup_7day_sent = Column(Boolean, default=False)
    followup_14day_sent = Column(Boolean, default=False)

    # Conversion
    status = Column(String, default="quoted")
    # quoted, sent, following_up, converted, lost, remarket
    converted_sale_id = Column(Integer, nullable=True)  # links to Sale if won
    lost_reason = Column(String, nullable=True)

    # Remarket
    entered_remarket = Column(Boolean, default=False)
    remarket_start_date = Column(DateTime(timezone=True), nullable=True)

    # NowCerts
    nowcerts_prospect_created = Column(Boolean, default=False)
    nowcerts_note_added = Column(Boolean, default=False)

    # Producer
    producer_id = Column(Integer, nullable=False, index=True)
    producer_name = Column(String, nullable=True)

    # GHL
    ghl_webhook_sent = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════
# ONBOARDING CAMPAIGN
# ═══════════════════════════════════════════════════════════════════

class OnboardingCampaign(Base):
    """Tracks onboarding email/SMS sequence for new customers."""
    __tablename__ = "onboarding_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    sale_id = Column(Integer, nullable=True, index=True)

    # Customer info
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    policy_type = Column(String, nullable=True)

    # Sequence tracking
    status = Column(String, default="active")  # active, paused, completed
    current_step = Column(Integer, default=0)
    # Steps: 0=welcome(done), 1=day1_sms, 2=day3_email, 3=day7_email,
    #        4=day14_sms, 5=day30_email, 6=day60_email, 7=day90_review

    # Individual step tracking
    day1_sms_sent = Column(Boolean, default=False)
    day3_email_sent = Column(Boolean, default=False)
    day7_email_sent = Column(Boolean, default=False)
    day14_sms_sent = Column(Boolean, default=False)
    day30_email_sent = Column(Boolean, default=False)
    day60_email_sent = Column(Boolean, default=False)
    day90_review_sent = Column(Boolean, default=False)

    # Pause reason
    paused_reason = Column(String, nullable=True)  # claim_filed, support_ticket, etc.

    # Start date (when welcome email was sent)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════
# GHL WEBHOOK LOG
# ═══════════════════════════════════════════════════════════════════

class GHLWebhookLog(Base):
    """Logs all webhook calls to/from GoHighLevel."""
    __tablename__ = "ghl_webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    direction = Column(String, nullable=False)  # outbound, inbound
    event_type = Column(String, nullable=False, index=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
