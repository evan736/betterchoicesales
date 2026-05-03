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

    # Phase tracking (added 2026-05-02 for X-date cycle scheduler)
    # phase values: cold_wakeup, x_date_prep, dormant, won_back, suppressed
    #   cold_wakeup  = Phase 1 — first-ever winback contact (90-day rollout)
    #   x_date_prep  = Phase 2 — within 30 days of next X-date, sending pre-renewal sequence
    #   dormant      = between X-date cycles, waiting for next prep window
    #   won_back     = customer became a client again (new sale matched)
    #   suppressed   = manual opt-out / hard bounce / permanent block
    phase = Column(String, default="cold_wakeup", nullable=True, index=True)
    # X-date = our best guess at when their current (non-BCI) policy renews
    # Initially = cancellation_date + 12 months. Advances +12 months each cycle
    # after the 4-email pre-renewal sequence (-30/-21/-14/-7 days) completes.
    next_x_date = Column(DateTime(timezone=True), nullable=True, index=True)
    # How many X-date cycles we've completed (0 = not started, 1 = one annual
    # cycle done, etc.). Per Evan: keep going every cycle, no auto-stop.
    x_date_cycle_count = Column(Integer, default=0, nullable=True)
    # Touchpoints sent within the CURRENT X-date cycle (0-4). Resets when
    # next_x_date advances. Lets us know which of the 4 pre-renewal emails
    # (−30/−21/−14/−7) is next.
    cycle_touchpoint_count = Column(Integer, default=0, nullable=True)
    # Last reply detected. Set by Smart Inbox webhook when an inbound email
    # matches the customer_email. Pauses email campaign — producer takes
    # over manually from their inbox.
    last_reply_at = Column(DateTime(timezone=True), nullable=True)
    last_reply_subject = Column(String, nullable=True)

    # Bounce / complaint tracking (set by Mailgun webhook).
    #   bounce_count: incremented on each soft (temporary) bounce. Hard
    #     (permanent) bounces immediately set status='paused_bounced'
    #     regardless of count. Soft bounces auto-suppress at >= 3.
    #   last_bounce_at: timestamp of most recent bounce event.
    #   bounce_reason: most recent bounce reason string from Mailgun.
    bounce_count = Column(Integer, default=0, nullable=True)
    last_bounce_at = Column(DateTime(timezone=True), nullable=True)
    bounce_reason = Column(String, nullable=True)

    # Result
    won_back_date = Column(DateTime(timezone=True), nullable=True)
    new_policy_number = Column(String, nullable=True)

    # Agent
    agent_name = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ═══════════════════════════════════════════════════════════════════
# COLD PROSPECT OUTREACH
# ═══════════════════════════════════════════════════════════════════
# Separate from WinBackCampaign because cold prospects are categorically
# different:
#   - They were never our customer (we have NO prior relationship)
#   - Email copy can't reference "you previously were insured with us"
#   - Stop condition is sale-uploaded (became a client), not won-back
#   - Need to track bounces aggressively (cold list = high bounce risk)
#   - Need DNC compliance (Allstate Do Not Mail flag from source data)
#
# Sourced from the Allstate territorial prospect export (X-date files).
# Each row is one person with one X-date. Multiple imports can cover
# the same person — dedupe by (lower(email), state) or (last_name,
# first_name, zip5).

class ColdProspect(Base):
    """A prospect from the Allstate X-date export — never our customer.

    Lifecycle phases (mirrors WinBackCampaign for consistency):
      cold_wakeup  → Phase 1, first email (90-day rollout, premium DESC)
      x_date_prep  → Phase 2, in -30/-21/-14/-7 day window before X-date
      dormant      → between cycles, waiting for next prep window
      converted    → sale uploaded, became client (final state)
      suppressed   → bounced / replied / opted out
    """
    __tablename__ = "cold_prospects"

    id = Column(Integer, primary_key=True, index=True)

    # Identity
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    full_name = Column(String, nullable=True, index=True)
    email = Column(String, nullable=True, index=True)
    home_phone = Column(String, nullable=True)
    work_phone = Column(String, nullable=True)
    mobile_phone = Column(String, nullable=True)

    # Address
    street = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String(2), nullable=True, index=True)
    zip_code = Column(String(10), nullable=True, index=True)

    # Source policy info (the policy they had when added to the list)
    policy_type = Column(String, nullable=True)  # Auto, Home, etc
    company = Column(String, nullable=True)  # who they were with
    premium = Column(Numeric(10, 2), nullable=True)
    quoted_company = Column(String, nullable=True)  # what we'd quoted them
    quoted_premium = Column(Numeric(10, 2), nullable=True)
    customer_status = Column(String, nullable=True, index=True)
    # Values: Prospect, Former Customer, Customer (excluded), Claim Contact (excluded)

    # X-date tracking
    original_x_date = Column(DateTime(timezone=True), nullable=True)
    next_x_date = Column(DateTime(timezone=True), nullable=True, index=True)
    x_date_cycle_count = Column(Integer, default=0)
    cycle_touchpoint_count = Column(Integer, default=0)

    # Compliance flags from source
    mail_status = Column(String, nullable=True)  # OK to Mail / Do Not Mail
    call_status = Column(String, nullable=True)  # OK to Call / Do Not Call
    do_not_email = Column(Boolean, default=False, nullable=False)
    do_not_text = Column(Boolean, default=False, nullable=False)
    do_not_call = Column(Boolean, default=False, nullable=False)

    # Validation status
    email_validated = Column(Boolean, default=False, nullable=False)
    email_valid = Column(Boolean, default=False, nullable=False)
    email_validation_reason = Column(String, nullable=True)
    email_validated_at = Column(DateTime(timezone=True), nullable=True)

    # Outreach tracking
    phase = Column(String, default="cold_wakeup", nullable=False, index=True)
    status = Column(String, default="active", nullable=False, index=True)
    # Values: active, paused_replied, paused_bounced, paused_unsubscribed, converted, excluded
    touchpoint_count = Column(Integer, default=0)
    last_touchpoint_at = Column(DateTime(timezone=True), nullable=True)
    last_email_variant = Column(String, nullable=True)
    # Tracks which copy variant was last used so the next contact uses
    # a different one. 4 variants in rotation.

    # Reply / bounce tracking
    last_reply_at = Column(DateTime(timezone=True), nullable=True)
    last_reply_subject = Column(String, nullable=True)
    bounce_count = Column(Integer, default=0)
    last_bounce_at = Column(DateTime(timezone=True), nullable=True)
    bounce_reason = Column(String, nullable=True)

    # Conversion (sale uploaded for them = stop campaign)
    converted_at = Column(DateTime(timezone=True), nullable=True)
    converted_sale_id = Column(Integer, nullable=True)

    # Round-robin assignment (joseph/evan/giulian)
    assigned_producer = Column(String, nullable=True)

    # Source tracking — for audit
    source = Column(String, nullable=True)  # 'allstate_xdate_2026_csv', 'manual', etc.
    source_external_id = Column(String, nullable=True)
    excluded = Column(Boolean, default=False, nullable=False)
    excluded_reason = Column(String, nullable=True)

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
    premium_term = Column(String, nullable=True, default="6 months")  # "6 months" or "12 months"
    notes = Column(Text, nullable=True)
    policy_lines = Column(Text, nullable=True)  # JSON array of {policy_type, premium, notes}
    effective_date = Column(DateTime, nullable=True)
    quote_date = Column(DateTime(timezone=True), server_default=func.now())

    # PDF attachment(s) — quote_pdf_path is legacy single-file (kept for
    # backward compat with existing rows); quote_pdf_paths is the new
    # multi-file list. When sending email, we attach EVERY file in the
    # list, plus the legacy field if it's set and not already in the list.
    quote_pdf_path = Column(String, nullable=True)
    quote_pdf_filename = Column(String, nullable=True)
    quote_pdf_paths = Column(JSON, nullable=True)  # [{"path": "...", "filename": "..."}, ...]

    # Email tracking
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)

    # Follow-up tracking
    followup_3day_sent = Column(Boolean, default=False)
    followup_7day_sent = Column(Boolean, default=False)
    followup_14day_sent = Column(Boolean, default=False)
    followup_disabled = Column(Boolean, default=False)  # Producer can disable follow-ups
    unsubscribe_token = Column(String, nullable=True)  # Customer opt-out token

    # Conversion
    status = Column(String, default="quoted")
    # quoted, sent, following_up, converted, lost, remarket
    converted_sale_id = Column(Integer, nullable=True)  # links to Sale if won
    lost_reason = Column(String, nullable=True)

    # Remarket
    entered_remarket = Column(Boolean, default=False)
    remarket_start_date = Column(DateTime(timezone=True), nullable=True)
    last_remarket_sent_at = Column(DateTime(timezone=True), nullable=True)
    remarket_touch_count = Column(Integer, default=0)  # How many long-term remarket emails sent

    # NowCerts
    nowcerts_prospect_created = Column(Boolean, default=False)
    nowcerts_note_added = Column(Boolean, default=False)

    # Producer
    producer_id = Column(Integer, nullable=False, index=True)
    producer_name = Column(String, nullable=True)

    # GHL
    ghl_webhook_sent = Column(Boolean, default=False)

    # A/B test (Apr 2026) — variant assigned at first send and sticks
    # for all follow-ups so a single quote stays in one experimental arm.
    # 'A' = branded email with coverage limits highlighted
    # 'B' = plain-text personal-style email (no branding, no logo)
    email_variant = Column(String(1), nullable=True)
    reply_received = Column(Boolean, default=False)
    reply_received_at = Column(DateTime(timezone=True), nullable=True)

    # Coverage limits (extracted from PDF) — used by Variant A's
    # "Your Coverage Highlights" section.
    coverage_dwelling = Column(Numeric(12, 2), nullable=True)              # home: Coverage A
    coverage_personal_property = Column(Numeric(12, 2), nullable=True)     # home: Coverage C
    coverage_liability = Column(Numeric(12, 2), nullable=True)             # home: Coverage E
    auto_bi_limit = Column(String(50), nullable=True)                      # auto: Bodily Injury (e.g. "100/300")
    auto_pd_limit = Column(String(50), nullable=True)                      # auto: Property Damage
    auto_um_limit = Column(String(50), nullable=True)                      # auto: Uninsured Motorist

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


# ═══════════════════════════════════════════════════════════════════
# LIFE INSURANCE CROSS-SELL (Back9 Integration)
# ═══════════════════════════════════════════════════════════════════

class LifeCrossSell(Base):
    """Tracks life insurance cross-sell campaigns sent to P&C customers via Back9."""
    __tablename__ = "life_cross_sells"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)

    # Customer info (snapshot from sale)
    client_name = Column(String, nullable=False)
    client_email = Column(String, nullable=False)
    client_phone = Column(String, nullable=True)
    state = Column(String(2), nullable=True)

    # P&C context
    pc_carrier = Column(String, nullable=True)
    pc_policy_type = Column(String, nullable=True)
    pc_premium = Column(Numeric(10, 2), nullable=True)

    # Producer who owns the relationship
    producer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    producer_name = Column(String, nullable=True)

    # Back9 integration
    back9_apply_link = Column(String, nullable=True)
    back9_eapp_id = Column(Integer, nullable=True)
    back9_eapp_uuid = Column(String, nullable=True)
    back9_quote_premium = Column(Numeric(10, 2), nullable=True)
    back9_carrier = Column(String, nullable=True)
    back9_product = Column(String, nullable=True)
    back9_face_amount = Column(Numeric(12, 2), nullable=True)

    # Campaign tracking
    status = Column(String, default="pending")
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
    email_opened_at = Column(DateTime(timezone=True), nullable=True)
    link_clicked_at = Column(DateTime(timezone=True), nullable=True)
    app_started_at = Column(DateTime(timezone=True), nullable=True)
    app_submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    inforce_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    campaign_batch = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
