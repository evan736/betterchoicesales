import os  # v2.27.1 — redeploy
import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.api import auth, sales, commissions, statements, analytics
from app.api import reports as reports_api
from app.api import payroll as payroll_api
from app.api import retention as retention_api
from app.api import chat as chat_api
from app.api import survey as survey_api
from app.api import admin as admin_api
from app.api import timeclock as timeclock_api
from app.api import customers as customers_api
from app.api import nonpay as nonpay_api
from app.api import uw_requirements as uw_api
from app.api import winback as winback_api
from app.api import cold_prospects as cold_prospects_api
from app.api import email_preview as email_preview_api
from app.api import missive as missive_api
from app.api import renewals as renewals_api
from app.api import quotes as quotes_api
from app.api import non_renewal as non_renewal_api
from app.api import retell as retell_api
from app.api import mia_bypass as mia_bypass_api
from app.api import dialer as dialer_api
from app.api import sms as sms_api
from app.api import cancellation as cancellation_api
from app.api import nowcerts_poll as nowcerts_poll_api
from app.api import inspection as inspection_api
from app.api import reshop as reshop_api
from app.api import id_cards as id_cards_api
from app.api import leads as leads_api
from app.api import sales_records as sales_records_api
from app.models.inspection import InspectionDraft

logger = logging.getLogger(__name__)


def init_database():
    """Initialize database tables and seed data on startup."""
    from app.core.database import engine, Base, SessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole
    from app.models.commission import CommissionTier
    from app.models.timeclock import TimeClockEntry  # ensure table is created
    from app.models.nonpay import NonPayNotice, NonPayEmail  # ensure tables created
    from app.models.task import Task, NonRenewalNotification  # ensure task tables created
    from app.models.compliance_reminder import ComplianceReminder  # ensure reminder table created
    from app.models.campaign import (  # ensure campaign tables created
        RenewalNotice, UWRequirement, WinBackCampaign,
        Quote, OnboardingCampaign, GHLWebhookLog
    )
    from app.models.cancellation import CancellationRequest, CancellationCarrier  # ensure tables
    from app.models.mia_bypass import VipBypass, TempAuthorization  # ensure MIA bypass tables
    from app.models.dialer import DialerCampaign, DialerLead, DialerDNC, DialerPhoneNumber  # dialer tables
    from app.models.uw_item import UWItem, UWActivity  # UW tracker tables
    from decimal import Decimal

    logger.info("Creating database tables...")

    # Run enum migrations first (ALTER TYPE ADD VALUE needs autocommit)
    from sqlalchemy import text

    # Enum additions must run outside transactions
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            # Add new carrier types
            for val in ['grange', 'safeco', 'travelers', 'hartford']:
                try:
                    conn.execute(text(f"ALTER TYPE carriertype ADD VALUE IF NOT EXISTS '{val}'"))
                except Exception:
                    pass

            # Add new statement status values (skip - using existing values)

            # Create transaction type enum if not exists
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactiontype') THEN
                        CREATE TYPE transactiontype AS ENUM (
                            'new_business', 'renewal', 'endorsement', 'cancellation',
                            'reinstatement', 'audit', 'adjustment', 'other'
                        );
                    END IF;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))

            logger.info("Enum migrations applied")
        except Exception as e:
            logger.warning(f"Enum migration warning (may be OK): {e}")

    # Column migrations (can run in normal transaction)
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    -- Convert carrier from enum to varchar
                    ALTER TABLE statement_imports ALTER COLUMN carrier TYPE VARCHAR USING carrier::VARCHAR;

                    -- statement_imports new columns
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_imports' AND column_name='total_premium') THEN
                        ALTER TABLE statement_imports ADD COLUMN total_premium NUMERIC(12,2) DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_imports' AND column_name='total_commission') THEN
                        ALTER TABLE statement_imports ADD COLUMN total_commission NUMERIC(12,2) DEFAULT 0;
                    END IF;

                    -- statement_lines new columns
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='insured_name') THEN
                        ALTER TABLE statement_lines ADD COLUMN insured_name VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='transaction_type_raw') THEN
                        ALTER TABLE statement_lines ADD COLUMN transaction_type_raw VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='effective_date') THEN
                        ALTER TABLE statement_lines ADD COLUMN effective_date TIMESTAMPTZ;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='commission_rate') THEN
                        ALTER TABLE statement_lines ADD COLUMN commission_rate NUMERIC(5,4);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='producer_name') THEN
                        ALTER TABLE statement_lines ADD COLUMN producer_name VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='product_type') THEN
                        ALTER TABLE statement_lines ADD COLUMN product_type VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='line_of_business') THEN
                        ALTER TABLE statement_lines ADD COLUMN line_of_business VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='state') THEN
                        ALTER TABLE statement_lines ADD COLUMN state VARCHAR(2);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='term_months') THEN
                        ALTER TABLE statement_lines ADD COLUMN term_months INTEGER;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='is_renewal_term') THEN
                        ALTER TABLE statement_lines ADD COLUMN is_renewal_term BOOLEAN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='match_confidence') THEN
                        ALTER TABLE statement_lines ADD COLUMN match_confidence VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='assigned_agent_id') THEN
                        ALTER TABLE statement_lines ADD COLUMN assigned_agent_id INTEGER REFERENCES users(id);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='agent_commission_amount') THEN
                        ALTER TABLE statement_lines ADD COLUMN agent_commission_amount NUMERIC(12,2);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='statement_lines' AND column_name='agent_commission_rate') THEN
                        ALTER TABLE statement_lines ADD COLUMN agent_commission_rate NUMERIC(5,4);
                    END IF;

                    -- Add FK from statement_lines to statement_imports if missing
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'statement_lines_statement_import_id_fkey'
                    ) THEN
                        BEGIN
                            ALTER TABLE statement_lines ADD CONSTRAINT statement_lines_statement_import_id_fkey
                                FOREIGN KEY (statement_import_id) REFERENCES statement_imports(id);
                        EXCEPTION WHEN others THEN NULL;
                        END;
                    END IF;

                    -- Add FK from statement_lines to sales if missing
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'statement_lines_matched_sale_id_fkey'
                    ) THEN
                        BEGIN
                            ALTER TABLE statement_lines ADD CONSTRAINT statement_lines_matched_sale_id_fkey
                                FOREIGN KEY (matched_sale_id) REFERENCES sales(id);
                        EXCEPTION WHEN others THEN NULL;
                        END;
                    END IF;
                END $$;
            """))
            conn.commit()
            logger.info("Column migrations applied")

            # Payroll agent lines: add override columns if missing
            conn.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='payroll_agent_lines') THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payroll_agent_lines' AND column_name='rate_adjustment') THEN
                            ALTER TABLE payroll_agent_lines ADD COLUMN rate_adjustment NUMERIC(5,4) DEFAULT 0;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payroll_agent_lines' AND column_name='bonus') THEN
                            ALTER TABLE payroll_agent_lines ADD COLUMN bonus NUMERIC(12,2) DEFAULT 0;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payroll_agent_lines' AND column_name='grand_total') THEN
                            ALTER TABLE payroll_agent_lines ADD COLUMN grand_total NUMERIC(12,2) DEFAULT 0;
                        END IF;
                    END IF;
                END $$;
            """))
            conn.commit()
            logger.info("Payroll column migrations applied")
        except Exception as e:
            logger.warning(f"Enum migration warning (may be OK): {e}")

    # Convert enum columns to varchar for flexibility
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    ALTER TABLE users ALTER COLUMN role TYPE VARCHAR USING role::VARCHAR;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='commission_rate_override') THEN
                        ALTER TABLE users ADD COLUMN commission_rate_override NUMERIC(5,4);
                    END IF;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='must_change_password') THEN
                        ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            # Reshop outreach attempt tracking (3-attempt workflow)
            for colname in ["attempt_1_at","attempt_2_at","attempt_3_at"]:
                conn.execute(text(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='reshops' AND column_name='{colname}') THEN
                            ALTER TABLE reshops ADD COLUMN {colname} TIMESTAMP WITH TIME ZONE;
                        END IF;
                    EXCEPTION WHEN others THEN NULL;
                    END $$;
                """))
            for colname in ["attempt_1_answered","attempt_2_answered","attempt_3_answered"]:
                conn.execute(text(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='reshops' AND column_name='{colname}') THEN
                            ALTER TABLE reshops ADD COLUMN {colname} BOOLEAN;
                        END IF;
                    EXCEPTION WHEN others THEN NULL;
                    END $$;
                """))
            conn.commit()
            # survey_responses: make sale_id nullable, add customer_id + source
            conn.execute(text("""
                DO $$
                BEGIN
                    ALTER TABLE survey_responses ALTER COLUMN sale_id DROP NOT NULL;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='survey_responses' AND column_name='customer_id') THEN
                        ALTER TABLE survey_responses ADD COLUMN customer_id INTEGER REFERENCES customers(id);
                        CREATE INDEX IF NOT EXISTS ix_survey_responses_customer_id ON survey_responses (customer_id);
                    END IF;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='survey_responses' AND column_name='source') THEN
                        ALTER TABLE survey_responses ADD COLUMN source VARCHAR;
                        CREATE INDEX IF NOT EXISTS ix_survey_responses_source ON survey_responses (source);
                    END IF;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    id SERIAL PRIMARY KEY,
                    address_hash VARCHAR(64) UNIQUE NOT NULL,
                    address_full VARCHAR NOT NULL,
                    lat DOUBLE PRECISION,
                    lng DOUBLE PRECISION,
                    provider VARCHAR,
                    failed BOOLEAN DEFAULT FALSE,
                    failure_reason VARCHAR,
                    raw_response TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_geocode_cache_address_hash ON geocode_cache (address_hash);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_geocode_cache_failed ON geocode_cache (failed);"))
            conn.commit()
            conn.commit()
            conn.execute(text("""
                DO $$
                BEGIN
                    ALTER TABLE sales ALTER COLUMN lead_source TYPE VARCHAR USING lead_source::VARCHAR;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    ALTER TABLE sales ALTER COLUMN policy_type TYPE VARCHAR USING policy_type::VARCHAR;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    ALTER TABLE sales ALTER COLUMN status TYPE VARCHAR USING status::VARCHAR;
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.commit()
            logger.info("Enum columns converted to varchar")
        except Exception as e:
            logger.warning(f"Column conversion warning: {e}")

    Base.metadata.create_all(bind=engine)
    logger.info("Tables created successfully")

    # ── Tasks table: add missing columns ──
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='tasks') THEN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='last_notification_tier') THEN
                            ALTER TABLE tasks ADD COLUMN last_notification_tier VARCHAR;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='notifications_disabled') THEN
                            ALTER TABLE tasks ADD COLUMN notifications_disabled BOOLEAN DEFAULT FALSE;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='customer_notified') THEN
                            ALTER TABLE tasks ADD COLUMN customer_notified BOOLEAN DEFAULT FALSE;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='customer_email') THEN
                            ALTER TABLE tasks ADD COLUMN customer_email VARCHAR;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='last_sent_at') THEN
                            ALTER TABLE tasks ADD COLUMN last_sent_at TIMESTAMP WITH TIME ZONE;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='send_count') THEN
                            ALTER TABLE tasks ADD COLUMN send_count INTEGER DEFAULT 0;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='last_send_method') THEN
                            ALTER TABLE tasks ADD COLUMN last_send_method VARCHAR;
                        END IF;
                    END IF;
                END $$;
            """))
            conn.commit()
            logger.info("Tasks columns migration complete")
        except Exception as e:
            logger.warning(f"Tasks column migration warning: {e}")

    # Ensure sale_line_items table exists
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sale_line_items (
                    id SERIAL PRIMARY KEY,
                    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
                    policy_type VARCHAR NOT NULL,
                    policy_suffix VARCHAR,
                    premium NUMERIC(10,2) NOT NULL,
                    description VARCHAR,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sale_line_items_sale_id ON sale_line_items(sale_id)"))
            conn.commit()
            logger.info("sale_line_items table ready")
        except Exception as e:
            logger.warning(f"sale_line_items migration: {e}")

    # Ensure agency_snapshots table exists
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agency_snapshots (
                    id SERIAL PRIMARY KEY,
                    snapshot_date DATE NOT NULL UNIQUE,
                    period VARCHAR NOT NULL,
                    active_customers INTEGER NOT NULL DEFAULT 0,
                    total_customers INTEGER NOT NULL DEFAULT 0,
                    active_policies INTEGER NOT NULL DEFAULT 0,
                    total_policies INTEGER NOT NULL DEFAULT 0,
                    active_premium_annualized NUMERIC(14,2) NOT NULL DEFAULT 0,
                    new_sales_count INTEGER DEFAULT 0,
                    new_sales_premium NUMERIC(12,2) DEFAULT 0,
                    cancellations_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agency_snapshots_period ON agency_snapshots(period)"))
            conn.commit()
            logger.info("agency_snapshots table ready")
        except Exception as e:
            logger.warning(f"agency_snapshots migration: {e}")

    # Winback Phase 2 columns (added 2026-05-02 for X-date cycle scheduler)
    # Five new columns: phase, next_x_date, x_date_cycle_count,
    # cycle_touchpoint_count, last_reply_at, last_reply_subject
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='phase') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN phase VARCHAR DEFAULT 'cold_wakeup';
                        CREATE INDEX IF NOT EXISTS ix_winback_campaigns_phase ON winback_campaigns(phase);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='next_x_date') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN next_x_date TIMESTAMPTZ;
                        CREATE INDEX IF NOT EXISTS ix_winback_campaigns_next_x_date ON winback_campaigns(next_x_date);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='x_date_cycle_count') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN x_date_cycle_count INTEGER DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='cycle_touchpoint_count') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN cycle_touchpoint_count INTEGER DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='last_reply_at') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN last_reply_at TIMESTAMPTZ;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='last_reply_subject') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN last_reply_subject VARCHAR;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='bounce_count') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN bounce_count INTEGER DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='last_bounce_at') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN last_bounce_at TIMESTAMPTZ;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='winback_campaigns' AND column_name='bounce_reason') THEN
                        ALTER TABLE winback_campaigns ADD COLUMN bounce_reason VARCHAR;
                    END IF;
                END $$;
            """))
            conn.commit()
            logger.info("winback_campaigns Phase 2 columns ready")
        except Exception as e:
            logger.warning(f"winback Phase 2 migration: {e}")

    # Cold prospect outreach table (Allstate X-date prospects)
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cold_prospects (
                    id SERIAL PRIMARY KEY,
                    first_name VARCHAR,
                    last_name VARCHAR,
                    full_name VARCHAR,
                    email VARCHAR,
                    home_phone VARCHAR,
                    work_phone VARCHAR,
                    mobile_phone VARCHAR,
                    street VARCHAR,
                    city VARCHAR,
                    state VARCHAR(2),
                    zip_code VARCHAR(10),
                    policy_type VARCHAR,
                    company VARCHAR,
                    premium NUMERIC(10,2),
                    quoted_company VARCHAR,
                    quoted_premium NUMERIC(10,2),
                    customer_status VARCHAR,
                    original_x_date TIMESTAMPTZ,
                    next_x_date TIMESTAMPTZ,
                    x_date_cycle_count INTEGER DEFAULT 0,
                    cycle_touchpoint_count INTEGER DEFAULT 0,
                    mail_status VARCHAR,
                    call_status VARCHAR,
                    do_not_email BOOLEAN DEFAULT FALSE NOT NULL,
                    do_not_text BOOLEAN DEFAULT FALSE NOT NULL,
                    do_not_call BOOLEAN DEFAULT FALSE NOT NULL,
                    email_validated BOOLEAN DEFAULT FALSE NOT NULL,
                    email_valid BOOLEAN DEFAULT FALSE NOT NULL,
                    email_validation_reason VARCHAR,
                    email_validated_at TIMESTAMPTZ,
                    phase VARCHAR DEFAULT 'cold_wakeup' NOT NULL,
                    status VARCHAR DEFAULT 'active' NOT NULL,
                    touchpoint_count INTEGER DEFAULT 0,
                    last_touchpoint_at TIMESTAMPTZ,
                    last_email_variant VARCHAR,
                    last_reply_at TIMESTAMPTZ,
                    last_reply_subject VARCHAR,
                    bounce_count INTEGER DEFAULT 0,
                    last_bounce_at TIMESTAMPTZ,
                    bounce_reason VARCHAR,
                    converted_at TIMESTAMPTZ,
                    converted_sale_id INTEGER,
                    assigned_producer VARCHAR,
                    source VARCHAR,
                    source_external_id VARCHAR,
                    excluded BOOLEAN DEFAULT FALSE NOT NULL,
                    excluded_reason VARCHAR,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_email ON cold_prospects(LOWER(email))"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_phase ON cold_prospects(phase)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_status ON cold_prospects(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_state ON cold_prospects(state)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_zip ON cold_prospects(zip_code)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_full_name ON cold_prospects(full_name)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_x_date ON cold_prospects(next_x_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cold_prospects_customer_status ON cold_prospects(customer_status)"))
            conn.commit()
            logger.info("cold_prospects table ready")
        except Exception as e:
            logger.warning(f"cold_prospects migration: {e}")

    # Ensure chat tables exist
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_channels (
                    id SERIAL PRIMARY KEY,
                    channel_type VARCHAR NOT NULL DEFAULT 'office',
                    name VARCHAR,
                    created_by INTEGER REFERENCES users(id),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_channel_members (
                    id SERIAL PRIMARY KEY,
                    channel_id INTEGER NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    last_read_at TIMESTAMPTZ,
                    joined_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    channel_id INTEGER NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    content TEXT,
                    message_type VARCHAR DEFAULT 'text',
                    file_name VARCHAR,
                    file_path VARCHAR,
                    file_type VARCHAR,
                    file_size INTEGER,
                    mentions JSONB,
                    reactions JSONB,
                    reply_to_id INTEGER REFERENCES chat_messages(id),
                    is_edited BOOLEAN DEFAULT FALSE,
                    is_deleted BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_messages_channel ON chat_messages(channel_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_members_channel ON chat_channel_members(channel_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_members_user ON chat_channel_members(user_id)"))
            conn.commit()
            logger.info("Chat tables ready")
        except Exception as e:
            logger.warning(f"Chat migration: {e}")

    # Ensure timeclock_entries table exists with ALL columns
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS timeclock_entries (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    work_date DATE NOT NULL,
                    clock_in TIMESTAMPTZ NOT NULL,
                    clock_out TIMESTAMPTZ,
                    expected_start TIME,
                    is_late BOOLEAN DEFAULT FALSE,
                    minutes_late INTEGER DEFAULT 0,
                    note VARCHAR,
                    latitude NUMERIC(10, 7),
                    longitude NUMERIC(10, 7),
                    gps_accuracy NUMERIC(8, 2),
                    location_address VARCHAR,
                    is_at_office BOOLEAN,
                    excused BOOLEAN DEFAULT FALSE,
                    excused_by INTEGER REFERENCES users(id),
                    excused_note VARCHAR,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ
                );
            """))
            # Add any missing columns to existing table
            for col, col_type in [
                ("latitude", "NUMERIC(10,7)"),
                ("longitude", "NUMERIC(10,7)"),
                ("gps_accuracy", "NUMERIC(8,2)"),
                ("location_address", "VARCHAR"),
                ("is_at_office", "BOOLEAN"),
                ("excused", "BOOLEAN DEFAULT FALSE"),
                ("excused_by", "INTEGER"),
                ("excused_note", "VARCHAR"),
                ("expected_start", "TIME"),
                ("is_late", "BOOLEAN DEFAULT FALSE"),
                ("minutes_late", "INTEGER DEFAULT 0"),
                ("note", "VARCHAR"),
                ("updated_at", "TIMESTAMPTZ"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE timeclock_entries ADD COLUMN IF NOT EXISTS {col} {col_type};"))
                except Exception:
                    pass
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_timeclock_entries_user_id ON timeclock_entries(user_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_timeclock_entries_work_date ON timeclock_entries(work_date);"))
            conn.commit()
            logger.info("timeclock_entries table verified with all columns")
        except Exception as e:
            logger.warning(f"timeclock_entries migration warning: {e}")

    # New column migrations for sales commission tracking & cancellation tracking
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    -- Commission status on sales
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='commission_status') THEN
                        ALTER TABLE sales ADD COLUMN commission_status VARCHAR DEFAULT 'pending';
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='commission_paid_date') THEN
                        ALTER TABLE sales ADD COLUMN commission_paid_date TIMESTAMPTZ;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='commission_paid_period') THEN
                        ALTER TABLE sales ADD COLUMN commission_paid_period VARCHAR;
                    END IF;

                    -- Cancellation tracking on sales
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='cancelled_date') THEN
                        ALTER TABLE sales ADD COLUMN cancelled_date TIMESTAMPTZ;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='days_to_cancel') THEN
                        ALTER TABLE sales ADD COLUMN days_to_cancel INTEGER;
                    END IF;
                    
                    -- Welcome email tracking
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='welcome_email_sent') THEN
                        ALTER TABLE sales ADD COLUMN welcome_email_sent BOOLEAN DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sales' AND column_name='welcome_email_sent_at') THEN
                        ALTER TABLE sales ADD COLUMN welcome_email_sent_at TIMESTAMPTZ;
                    END IF;
                END $$;
            """))
            conn.commit()
            logger.info("Sales commission/cancellation columns added")
        except Exception as e:
            logger.warning(f"Sales column migration warning: {e}")

        # ── Quotes: premium_term, notes, policy_lines, followup_disabled, unsubscribe_token columns ──
        for col_sql in [
            "ALTER TABLE quotes ADD COLUMN premium_term VARCHAR DEFAULT '6 months'",
            "ALTER TABLE quotes ADD COLUMN notes TEXT",
            "ALTER TABLE quotes ADD COLUMN policy_lines TEXT",
            "ALTER TABLE quotes ADD COLUMN followup_disabled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE quotes ADD COLUMN unsubscribe_token VARCHAR",
            "ALTER TABLE quotes ADD COLUMN last_remarket_sent_at TIMESTAMPTZ",
            "ALTER TABLE quotes ADD COLUMN remarket_touch_count INTEGER DEFAULT 0",
            # A/B test fields (Apr 2026)
            "ALTER TABLE quotes ADD COLUMN email_variant VARCHAR(1)",  # 'A' or 'B'
            "ALTER TABLE quotes ADD COLUMN reply_received BOOLEAN DEFAULT FALSE",
            "ALTER TABLE quotes ADD COLUMN reply_received_at TIMESTAMPTZ",
            # Coverage limits (extracted from PDF)
            "ALTER TABLE quotes ADD COLUMN coverage_dwelling NUMERIC(12, 2)",
            "ALTER TABLE quotes ADD COLUMN coverage_personal_property NUMERIC(12, 2)",
            "ALTER TABLE quotes ADD COLUMN coverage_liability NUMERIC(12, 2)",
            # Auto-specific limits
            "ALTER TABLE quotes ADD COLUMN auto_bi_limit VARCHAR(50)",   # e.g. "100/300"
            "ALTER TABLE quotes ADD COLUMN auto_pd_limit VARCHAR(50)",   # e.g. "100"
            "ALTER TABLE quotes ADD COLUMN auto_um_limit VARCHAR(50)",   # e.g. "100/300"
            # Multi-PDF (Apr 2026) — list of attached PDFs
            "ALTER TABLE quotes ADD COLUMN quote_pdf_paths JSON",
        ]:
            try:
                with engine.connect() as conn:
                    conn.execute(text(col_sql))
                    conn.commit()
            except Exception:
                pass

        # ── Requote leads: email content storage ──
        for col_sql in [
            "ALTER TABLE requote_leads ADD COLUMN last_email_subject VARCHAR",
            "ALTER TABLE requote_leads ADD COLUMN last_email_html TEXT",
            "ALTER TABLE requote_leads ADD COLUMN last_email_touch INTEGER",
        ]:
            try:
                with engine.connect() as conn:
                    conn.execute(text(col_sql))
                    conn.commit()
            except Exception:
                pass

        # ── Life Cross-Sell table ──
        try:
            with engine.connect() as conn:
                conn.execute(text("""CREATE TABLE IF NOT EXISTS life_cross_sells (
                    id SERIAL PRIMARY KEY, sale_id INTEGER REFERENCES sales(id),
                    client_name VARCHAR NOT NULL, client_email VARCHAR NOT NULL,
                    client_phone VARCHAR, state VARCHAR(2),
                    pc_carrier VARCHAR, pc_policy_type VARCHAR, pc_premium NUMERIC(10,2),
                    producer_id INTEGER REFERENCES users(id), producer_name VARCHAR,
                    back9_apply_link VARCHAR, back9_eapp_id INTEGER, back9_eapp_uuid VARCHAR,
                    back9_quote_premium NUMERIC(10,2), back9_carrier VARCHAR, back9_product VARCHAR,
                    back9_face_amount NUMERIC(12,2),
                    status VARCHAR DEFAULT 'pending',
                    email_sent_at TIMESTAMP WITH TIME ZONE, email_opened_at TIMESTAMP WITH TIME ZONE,
                    link_clicked_at TIMESTAMP WITH TIME ZONE, app_started_at TIMESTAMP WITH TIME ZONE,
                    app_submitted_at TIMESTAMP WITH TIME ZONE, approved_at TIMESTAMP WITH TIME ZONE,
                    inforce_at TIMESTAMP WITH TIME ZONE,
                    campaign_batch VARCHAR, notes TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE
                )"""))
                conn.commit()
                logger.info("life_cross_sells table ready")
        except Exception as e:
            logger.info(f"life_cross_sells table: {e}")
        logger.info("Quotes columns verified")

    db = SessionLocal()
    try:
        # Create admin user if not exists
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                email="admin@betterchoiceins.com",
                username="admin",
                full_name="System Administrator",
                hashed_password=get_password_hash("admin123"),
                role="admin",
                is_superuser=True,
                producer_code="ADMIN001",
            )
            db.add(admin)
            logger.info("Admin user created")

        # Evan Larson - admin/producer
        evan = db.query(User).filter(User.email == "evan@betterchoiceins.com").first()
        if not evan:
            evan = User(
                email="evan@betterchoiceins.com",
                username="evan.larson",
                full_name="Evan Larson",
                hashed_password=get_password_hash("BetterChoice2026!"),
                role="admin",
                is_superuser=True,
                producer_code="EVAN001",
            )
            db.add(evan)
            logger.info("Evan Larson account created")

        # Giulian Baez - New Business Producer
        giulian = db.query(User).filter(User.email == "giulian@betterchoiceins.com").first()
        if not giulian:
            giulian = User(
                email="giulian@betterchoiceins.com",
                username="giulian.baez",
                full_name="Giulian Baez",
                hashed_password=get_password_hash("BetterChoice2026!"),
                role="producer",
                producer_code="GIUL001",
            )
            db.add(giulian)
            logger.info("Giulian Baez account created")

        # Joseph Rivera - New Business Producer
        joseph = db.query(User).filter(User.email == "joseph@betterchoiceins.com").first()
        if not joseph:
            joseph = User(
                email="joseph@betterchoiceins.com",
                username="joseph.rivera",
                full_name="Joseph Rivera",
                hashed_password=get_password_hash("BetterChoice2026!"),
                role="producer",
                producer_code="JOSE001",
            )
            db.add(joseph)
            logger.info("Joseph Rivera account created")

        # Salma Marquez - Retention Specialist
        salma = db.query(User).filter(User.email == "salma@betterchoiceins.com").first()
        if not salma:
            salma = User(
                email="salma@betterchoiceins.com",
                username="salma.marquez",
                full_name="Salma Marquez",
                hashed_password=get_password_hash("BetterChoice2026!"),
                role="retention_specialist",
                producer_code="SALM001",
            )
            db.add(salma)
            logger.info("Salma Marquez account created")

        # Michelle Robles - Retention Specialist
        michelle = db.query(User).filter(User.email == "michelle@betterchoiceins.com").first()
        if not michelle:
            michelle = User(
                email="michelle@betterchoiceins.com",
                username="michelle.robles",
                full_name="Michelle Robles",
                hashed_password=get_password_hash("BetterChoice2026!"),
                role="retention_specialist",
                producer_code="MICH001",
            )
            db.add(michelle)
            logger.info("Michelle Robles account created")

        # Remove old sample producer if exists
        old_producer = db.query(User).filter(User.username == "producer1").first()
        if old_producer:
            # Only delete if they have no sales
            if not old_producer.sales:
                db.delete(old_producer)
                logger.info("Removed sample producer1")

        # Create commission tiers
        tiers = [
            {"tier_level": 1, "min_written_premium": Decimal("0"), "max_written_premium": Decimal("39999.99"), "commission_rate": Decimal("0.00"), "description": "Under 40K - 0%"},
            {"tier_level": 2, "min_written_premium": Decimal("40000"), "max_written_premium": Decimal("49999.99"), "commission_rate": Decimal("0.03"), "description": "40K - 3%"},
            {"tier_level": 3, "min_written_premium": Decimal("50000"), "max_written_premium": Decimal("59999.99"), "commission_rate": Decimal("0.04"), "description": "50K - 4%"},
            {"tier_level": 4, "min_written_premium": Decimal("60000"), "max_written_premium": Decimal("99999.99"), "commission_rate": Decimal("0.05"), "description": "60K - 5%"},
            {"tier_level": 5, "min_written_premium": Decimal("100000"), "max_written_premium": Decimal("149999.99"), "commission_rate": Decimal("0.06"), "description": "100K - 6%"},
            {"tier_level": 6, "min_written_premium": Decimal("150000"), "max_written_premium": Decimal("199999.99"), "commission_rate": Decimal("0.07"), "description": "150K - 7%"},
            {"tier_level": 7, "min_written_premium": Decimal("200000"), "max_written_premium": None, "commission_rate": Decimal("0.08"), "description": "200K+ - 8%"},
        ]
        for tier_data in tiers:
            existing = db.query(CommissionTier).filter(CommissionTier.tier_level == tier_data["tier_level"]).first()
            if not existing:
                db.add(CommissionTier(**tier_data))
                logger.info(f"Created {tier_data['description']}")
            else:
                # Update existing tier if rate or thresholds changed
                changed = False
                for key, val in tier_data.items():
                    if key == "tier_level":
                        continue
                    if getattr(existing, key, None) != val:
                        setattr(existing, key, val)
                        changed = True
                if changed:
                    logger.info(f"Updated tier {tier_data['tier_level']}: {tier_data['description']}")

        db.commit()
        logger.info("Database seeded successfully")

        # ── Seed Cancellation Carrier Directory ──
        try:
            existing_count = db.query(CancellationCarrier).count()
            if existing_count == 0:
                carriers_seed = [
                    {
                        "carrier_name": "state_farm",
                        "display_name": "State Farm",
                        "preferred_method": "mail",
                        "cancellation_phone": "1-800-782-8332",
                        "cancellation_mail_address": "Attn: Policy Cancellation\nState Farm Insurance\nPO Box 2001\nBloomington, IL 61702-2001",
                        "notes": "Must be policyholder request. Phone or mail only — no fax/email. Call 800-STATEFARM or mail signed letter.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "allstate",
                        "display_name": "Allstate",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-255-7828",
                        "cancellation_mail_address": "Allstate Insurance Company\nPO Box 660598\nDallas, TX 75266-0598",
                        "notes": "Customer must call local agent or 1-800-ALLSTATE. Some agents accept fax. Written letter also accepted by mail.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "geico",
                        "display_name": "GEICO",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-841-3000",
                        "cancellation_mail_address": "GEICO\nOne GEICO Plaza\nWashington, DC 20076",
                        "notes": "Customer must call GEICO directly. No online cancellation. Written request also accepted by mail.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "progressive",
                        "display_name": "Progressive",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-888-671-4405",
                        "cancellation_fax": "1-888-375-5765",
                        "notes": "Can cancel by phone, fax, or online at progressive.com. Fax accepts signed cancellation letters.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "farmers",
                        "display_name": "Farmers Insurance",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-888-327-6335",
                        "notes": "Customer contacts local agent or calls 1-888-FARMERS. Written request also accepted.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "liberty_mutual",
                        "display_name": "Liberty Mutual",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-290-8711",
                        "cancellation_mail_address": "Liberty Mutual Insurance\n175 Berkeley Street\nBoston, MA 02116",
                        "notes": "Can cancel by phone, mail, or through local agent. Online cancellation available for some policies.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "nationwide",
                        "display_name": "Nationwide",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-877-669-6877",
                        "cancellation_mail_address": "Nationwide Insurance\nOne Nationwide Plaza\nColumbus, OH 43215",
                        "notes": "Call or contact local agent. Written cancellation requests accepted by mail.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "american_family",
                        "display_name": "American Family Insurance",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-692-6326",
                        "cancellation_mail_address": "American Family Insurance\n6000 American Parkway\nMadison, WI 53783",
                        "notes": "Contact local agent or call customer service. Written request accepted.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "erie",
                        "display_name": "Erie Insurance",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-458-0811",
                        "cancellation_mail_address": "Erie Insurance Group\n100 Erie Insurance Place\nErie, PA 16530",
                        "notes": "Must go through local Erie agent. Written cancellation accepted by mail.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "usaa",
                        "display_name": "USAA",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-531-8722",
                        "notes": "Members call USAA directly. Online cancellation available. Military/veteran exclusive.",
                        "accepts_agent_submission": False,
                    },
                    {
                        "carrier_name": "travelers",
                        "display_name": "Travelers",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-842-5075",
                        "cancellation_fax": "1-866-336-2077",
                        "cancellation_mail_address": "Travelers Insurance\nOne Tower Square\nHartford, CT 06183",
                        "notes": "Accepts cancellation by phone, fax, or mail. Agent can submit on behalf of customer.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "auto_owners",
                        "display_name": "Auto-Owners Insurance",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-346-0346",
                        "cancellation_mail_address": "Auto-Owners Insurance\n6101 Anacapri Blvd\nLansing, MI 48917",
                        "notes": "Contact local agent or company directly.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "the_hartford",
                        "display_name": "The Hartford",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-243-5860",
                        "cancellation_mail_address": "The Hartford\nOne Hartford Plaza\nHartford, CT 06155",
                        "notes": "Call or contact through AARP if applicable. Written request accepted.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "mercury",
                        "display_name": "Mercury Insurance",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-956-3728",
                        "notes": "Contact local agent or call Mercury directly.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "metlife",
                        "display_name": "MetLife",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-438-6388",
                        "cancellation_mail_address": "MetLife Auto & Home\nPO Box 350\nWarwick, RI 02887-9954",
                        "notes": "Call customer service or mail written request.",
                        "accepts_agent_submission": True,
                    },
                    {
                        "carrier_name": "amica",
                        "display_name": "Amica Mutual",
                        "preferred_method": "phone",
                        "cancellation_phone": "1-800-242-6422",
                        "cancellation_mail_address": "Amica Mutual Insurance\n100 Amica Way\nLincoln, RI 02865",
                        "notes": "Call or mail written request. Known for smooth cancellation process.",
                        "accepts_agent_submission": True,
                    },
                ]

                for cd in carriers_seed:
                    carrier = CancellationCarrier(**cd)
                    db.add(carrier)
                db.commit()
                logger.info(f"Seeded {len(carriers_seed)} cancellation carriers")
        except Exception as e:
            logger.error(f"Error seeding cancellation carriers: {e}")
            db.rollback()
    except Exception as e:
        logger.error(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database init on startup + start background scheduler."""
    # ── Install Mailgun deliverability hook BEFORE any sender can fire ──
    # Forces o:tracking-clicks=no, adds List-Unsubscribe headers for Gmail
    # 2024 compliance, marks as Auto-Submitted. Applies to every Mailgun
    # /messages call regardless of which sender file made it.
    try:
        from app.services.mailer import install_mailgun_hook
        install_mailgun_hook()
    except Exception as e:
        logger.error(f"Failed to install Mailgun deliverability hook: {e}")

    # ── Security check: refuse to run with default secret key ──
    if settings.SECRET_KEY == "your-secret-key-change-in-production":
        logger.critical("🚨 SECURITY: SECRET_KEY is set to the default value! Set a unique SECRET_KEY env var.")
        import secrets
        settings.SECRET_KEY = secrets.token_urlsafe(64)
        logger.warning(f"⚠️  Generated a temporary random SECRET_KEY for this session. All existing tokens are now invalid.")
        logger.warning(f"⚠️  Set SECRET_KEY in Render environment variables to fix this permanently.")

    # Run critical DB init synchronously (fast)
    init_database()

    # ── Run ALL migrations in background thread so health check passes immediately ──
    def _run_all_migrations():
        import time as _time
        _time.sleep(2)  # tiny delay to ensure uvicorn is fully up
        logger.info("[Startup] Running background migrations...")

        try:
            from app.migrations.smart_inbox_migration import migrate_smart_inbox
            migrate_smart_inbox()
        except Exception as e:
            logger.warning(f"Smart inbox migration: {e}")

        try:
            from app.migrations.retention_migration import run_retention_migration
            run_retention_migration()
        except Exception as e:
            logger.warning(f"Retention migration: {e}")

        try:
            from app.api.requote_campaigns import run_migration as run_requote_migration
            from app.core.database import engine as _rq_engine
            run_requote_migration(_rq_engine)
        except Exception as e:
            logger.warning(f"Requote migration: {e}")

        try:
            from app.migrations.leads_migration import migrate_leads
            migrate_leads()
        except Exception as e:
            logger.warning(f"Leads migration: {e}")

        try:
            from app.core.database import engine as _qj_engine
            from sqlalchemy import inspect as _qj_inspect
            _qj_insp = _qj_inspect(_qj_engine)
            if "quote_jobs" not in _qj_insp.get_table_names():
                from app.models.quote_job import QuoteJob
                QuoteJob.__table__.create(_qj_engine)
                logger.info("Created quote_jobs table")
        except Exception as e:
            logger.warning(f"Quote jobs migration: {e}")

        try:
            from app.api.texting import run_texting_migration
            run_texting_migration()
        except Exception as e:
            logger.warning(f"Texting migration: {e}")

        try:
            from app.migrations.dialer_migration import migrate_dialer
            migrate_dialer()
        except Exception as e:
            logger.warning(f"Dialer migration: {e}")

        try:
            from app.migrations.sales_records_migration import migrate_sales_records
            migrate_sales_records()
        except Exception as e:
            logger.warning(f"Sales records migration: {e}")

        try:
            from app.migrations.commission_tracker_migration import run_commission_tracker_migration
            from app.core.database import engine as _ct_engine
            run_commission_tracker_migration(_ct_engine)
        except Exception as e:
            logger.warning(f"Commission tracker migration: {e}")

        try:
            from app.migrations.renewal_survey_migration import run_migration as run_renewal_survey_migration
            from app.core.database import engine as _rs_engine
            run_renewal_survey_migration(_rs_engine)
        except Exception as e:
            logger.warning(f"Renewal survey migration: {e}")

        try:
            from sqlalchemy import text as _cr_text
            from app.core.database import engine as _cr_engine
            with _cr_engine.connect() as conn:
                conn.execute(_cr_text("""CREATE TABLE IF NOT EXISTS chat_message_reads (
                    id SERIAL PRIMARY KEY,
                    message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    read_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(message_id, user_id)
                )"""))
                conn.execute(_cr_text("CREATE INDEX IF NOT EXISTS ix_chat_message_reads_message_id ON chat_message_reads(message_id)"))
                conn.execute(_cr_text("CREATE INDEX IF NOT EXISTS ix_chat_message_reads_user_id ON chat_message_reads(user_id)"))
                conn.commit()
        except Exception as e:
            logger.warning(f"Chat message reads migration: {e}")

        try:
            from sqlalchemy import text as _ck_text
            from app.core.database import engine as _ck_engine
            with _ck_engine.connect() as conn:
                conn.execute(_ck_text("""CREATE TABLE IF NOT EXISTS daily_checklist_items (
                    id SERIAL PRIMARY KEY, check_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    item_key VARCHAR NOT NULL, completed BOOLEAN DEFAULT FALSE,
                    completed_by VARCHAR, completed_at TIMESTAMP, notes VARCHAR
                )"""))
                conn.commit()
        except Exception as e:
            logger.warning(f"Checklist migration: {e}")

        # Run the big init_database column migrations in background too
        try:
            from app.core.database import engine as _bg_engine
            from sqlalchemy import text as _bg_text, inspect as _bg_inspect
            inspector = _bg_inspect(_bg_engine)
            fk_indexes = [
                ("requote_leads", "producer_id"), ("chat_channels", "created_by"),
                ("chat_messages", "reply_to_id"), ("email_templates", "sent_by_id"),
                ("email_drafts", "created_by_id"), ("payroll_runs", "submitted_by_id"),
                ("reshop_activities", "user_id"), ("outbound_queue", "inbound_email_id"),
                ("tasks", "assigned_to_id"), ("timeclock_entries", "excused_by"),
            ]
            with _bg_engine.connect() as conn:
                for table, column in fk_indexes:
                    if not inspector.has_table(table):
                        continue
                    idx_name = f"ix_{table}_{column}"
                    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
                    if idx_name not in existing_indexes:
                        try:
                            conn.execute(_bg_text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})"))
                            conn.commit()
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"FK index migration: {e}")

        # Auto-restart active dialer campaigns
        try:
            from app.api.dialer import _auto_dial_loop, _dialer_threads
            from app.models.dialer import DialerCampaign
            import threading as _t
            restart_db = SessionLocal()
            active_campaigns = restart_db.query(DialerCampaign).filter(DialerCampaign.status == "active").all()
            for campaign in active_campaigns:
                if campaign.id not in _dialer_threads or not _dialer_threads[campaign.id].is_alive():
                    t = _t.Thread(target=_auto_dial_loop, args=(campaign.id,), daemon=True)
                    t.start()
                    _dialer_threads[campaign.id] = t
                    logger.info(f"[Startup] Auto-resumed dialer campaign {campaign.id}: {campaign.name}")
            restart_db.close()
        except Exception as e:
            logger.warning(f"Dialer auto-restart: {e}")

        logger.info("[Startup] Background migrations complete")

    threading.Thread(target=_run_all_migrations, daemon=True).start()

    # ── Daily reshop digest scheduler (8:20 AM CT, Mon-Fri) ─────────
    def _reshop_digest_scheduler():
        import time as _time
        from datetime import datetime as _datetime
        _time.sleep(30)  # Wait for migrations to finish
        logger.info("Reshop digest scheduler started (8:20 AM CT, Mon-Fri)")
        _last_sent_date = None

        while True:
            try:
                from zoneinfo import ZoneInfo
                now_ct = _datetime.now(ZoneInfo("America/Chicago"))
                today_ct = now_ct.date()

                # Send at 8:20 AM CT, Monday-Friday only
                if (now_ct.hour == 8 and now_ct.minute >= 20 and now_ct.minute < 35 and
                        now_ct.weekday() < 5 and _last_sent_date != today_ct):
                    logger.info("Sending daily reshop digest...")
                    try:
                        from app.core.database import SessionLocal
                        from app.services.reshop_digest import send_reshop_digests
                        _db = SessionLocal()
                        try:
                            result = send_reshop_digests(_db, today_ct)
                            logger.info("Reshop digest result: %s", result)
                        finally:
                            _db.close()
                        _last_sent_date = today_ct
                    except Exception as de:
                        logger.error("Reshop digest send error: %s", de)
                        _last_sent_date = today_ct  # Don't retry today
            except Exception as e:
                logger.error("Reshop digest scheduler error: %s", e)

            _time.sleep(60)  # Check every minute

    threading.Thread(target=_reshop_digest_scheduler, daemon=True).start()

    # ── UW Tracker daily digest + proximity reminders (7:30 AM CT, every day) ─
    def _uw_tracker_scheduler():
        import time as _time
        from datetime import datetime as _datetime
        _time.sleep(45)  # Wait for migrations to finish
        logger.info("UW Tracker scheduler started (7:30 AM CT daily)")
        _last_digest_date = None
        _last_proximity_date = None

        while True:
            try:
                from zoneinfo import ZoneInfo
                now_ct = _datetime.now(ZoneInfo("America/Chicago"))
                today_ct = now_ct.date()

                # Daily digest at 7:30 AM CT (every day, including weekends —
                # carriers don't care about weekends and UW deadlines tick over
                # regardless)
                if (now_ct.hour == 7 and now_ct.minute >= 30 and now_ct.minute < 45
                        and _last_digest_date != today_ct):
                    logger.info("Sending UW daily digest...")
                    try:
                        from app.core.database import SessionLocal
                        from app.services.uw_digest import send_daily_digests
                        _db = SessionLocal()
                        try:
                            result = send_daily_digests(_db)
                            logger.info("UW digest result: %s", result)
                        finally:
                            _db.close()
                        _last_digest_date = today_ct
                    except Exception as de:
                        logger.error("UW digest send error: %s", de)
                        _last_digest_date = today_ct

                # Proximity reminders at 7:35 AM CT (5 min after digest so we
                # don't double-blast the assignee with two emails at once
                # for the same item)
                if (now_ct.hour == 7 and now_ct.minute >= 35 and now_ct.minute < 50
                        and _last_proximity_date != today_ct):
                    logger.info("Sending UW proximity reminders...")
                    try:
                        from app.core.database import SessionLocal
                        from app.services.uw_digest import send_proximity_reminders
                        _db = SessionLocal()
                        try:
                            result = send_proximity_reminders(_db)
                            logger.info("UW proximity result: %s", result)
                        finally:
                            _db.close()
                        _last_proximity_date = today_ct
                    except Exception as de:
                        logger.error("UW proximity send error: %s", de)
                        _last_proximity_date = today_ct
            except Exception as e:
                logger.error("UW scheduler error: %s", e)

            _time.sleep(60)  # Check every minute

    threading.Thread(target=_uw_tracker_scheduler, daemon=True).start()

    # ── A/B Test weekly digest (Friday 8 AM CT) ─────────────────────
    # Runs once per Friday morning. Skips weeks with no activity.
    def _ab_weekly_digest_scheduler():
        import time as _time
        from datetime import datetime as _datetime
        _time.sleep(60)  # Wait for migrations
        logger.info("A/B weekly digest scheduler started (Fridays 8 AM CT)")
        _last_run_date = None
        while True:
            try:
                from zoneinfo import ZoneInfo
                now_ct = _datetime.now(ZoneInfo("America/Chicago"))
                # Friday is weekday() == 4
                if (now_ct.weekday() == 4 and now_ct.hour == 8 and now_ct.minute < 15
                        and _last_run_date != now_ct.date()):
                    logger.info("Sending A/B weekly digest...")
                    try:
                        from app.core.database import SessionLocal
                        from app.services.ab_digest import send_weekly_digest
                        _db = SessionLocal()
                        try:
                            result = send_weekly_digest(_db)
                            logger.info("A/B digest result: %s", result)
                        finally:
                            _db.close()
                        _last_run_date = now_ct.date()
                    except Exception as de:
                        logger.error("A/B digest send error: %s", de)
                        _last_run_date = now_ct.date()
            except Exception as e:
                logger.error("A/B digest scheduler error: %s", e)
            _time.sleep(60)

    threading.Thread(target=_ab_weekly_digest_scheduler, daemon=True).start()

    # ── Quote follow-up scheduler (hourly) ─────────────────────────
    def _quote_followup_scheduler():
        import time as _time
        _time.sleep(60)  # Wait for migrations
        logger.info("Quote follow-up scheduler started (runs every 60 min)")
        while True:
            try:
                from app.core.database import SessionLocal
                from app.api.quotes import _check_followups_logic
                _db = SessionLocal()
                try:
                    result = _check_followups_logic(_db)
                    sent_total = (result.get("day3", 0) + result.get("day7", 0) +
                                  result.get("day14", 0) + result.get("day90", 0) +
                                  result.get("retarget", 0))
                    if sent_total > 0:
                        logger.info("Quote follow-ups sent: %s", result)
                finally:
                    _db.close()
            except Exception as e:
                logger.error("Quote follow-up scheduler error: %s", e)
            _time.sleep(3600)  # Every hour

    threading.Thread(target=_quote_followup_scheduler, daemon=True).start()

    # ── Requote campaign auto-sender (every 15 min) ────────────────
    def _requote_campaign_scheduler():
        import time as _time
        _time.sleep(90)  # Wait for migrations + other schedulers to start
        logger.info("Requote campaign auto-sender started (runs every 15 min)")
        while True:
            try:
                from app.core.database import SessionLocal
                from app.api.requote_campaigns import _send_due_emails_logic, RequoteCampaign
                _db = SessionLocal()
                try:
                    # Get all active campaigns
                    active_campaigns = _db.query(RequoteCampaign).filter(
                        RequoteCampaign.status == "active"
                    ).all()
                    total_sent = 0
                    for campaign in active_campaigns:
                        try:
                            # Batch of 50 per campaign per run — keeps sends paced
                            result = _send_due_emails_logic(campaign.id, 50, _db)
                            if result.get("sent", 0) > 0:
                                logger.info("Campaign %s: sent %d emails (%d remaining)", 
                                            campaign.id, result["sent"], result.get("remaining", 0))
                                total_sent += result["sent"]
                        except Exception as ce:
                            logger.error("Campaign %s send error: %s", campaign.id, ce)
                    if total_sent > 0:
                        logger.info("Requote auto-sender total this cycle: %d emails across %d campaigns",
                                    total_sent, len(active_campaigns))
                finally:
                    _db.close()
            except Exception as e:
                logger.error("Requote campaign scheduler error: %s", e)
            _time.sleep(900)  # Every 15 minutes

    threading.Thread(target=_requote_campaign_scheduler, daemon=True).start()

    # ── Winback scheduler (every 30 min during business hours) ─────
    # Runs the Phase 1 cold wake-up + Phase 2 X-date prep emails.
    # Self-gates on business hours (9am-6pm CT M-F) inside the
    # scheduler-tick logic, so this thread fires every 30 min and
    # the tick itself decides whether to send.
    #
    # Default pace: 4 emails per tick × 2 ticks/hr × 9 business hrs
    # × 5 weekdays = 360/week, completing 1,456 records in ~4 weeks.
    # Bump max_emails_per_tick up to send faster.
    #
    # GATE: env var WINBACK_SCHEDULER_ENABLED must be 'true'. Default
    # is 'false' so this never fires accidentally on a fresh deploy.
    # Flip the env var on Render to start sending.
    def _winback_scheduler():
        import time as _time
        import os
        _time.sleep(120)  # Wait for migrations + other schedulers
        logger.info("Winback scheduler started (runs every 30 min, gated on WINBACK_SCHEDULER_ENABLED)")
        while True:
            try:
                if os.getenv("WINBACK_SCHEDULER_ENABLED", "false").lower() == "true":
                    from app.core.database import SessionLocal
                    from app.api.winback import (
                        WinBackCampaign, _send_winback_email,
                        _get_assigned_producer,
                    )
                    from datetime import datetime as _dt, timedelta as _td
                    from zoneinfo import ZoneInfo
                    _db = SessionLocal()
                    try:
                        # Business-hours guard inline (avoid HTTP roundtrip)
                        now_ct = _dt.utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Chicago"))
                        weekday = now_ct.weekday()
                        hour = now_ct.hour
                        if weekday >= 5 or hour < 9 or hour >= 15:
                            pass  # outside business hours, skip silently
                        else:
                            max_per_tick = int(os.getenv("WINBACK_MAX_PER_TICK", "4"))
                            sent = 0
                            # Phase 2 (X-date prep) priority — same logic as scheduler-tick
                            offset_map = {0: 30, 1: 21, 2: 14, 3: 7}
                            phase_2_candidates = _db.query(WinBackCampaign).filter(
                                WinBackCampaign.excluded == False,
                                WinBackCampaign.last_reply_at.is_(None),
                                (WinBackCampaign.bounce_count == None) | (WinBackCampaign.bounce_count < 3),
                                WinBackCampaign.status != "won_back",
                                WinBackCampaign.customer_email.isnot(None),
                                WinBackCampaign.next_x_date.isnot(None),
                                WinBackCampaign.next_x_date <= _dt.utcnow() + _td(days=35),
                                WinBackCampaign.next_x_date >= _dt.utcnow() - _td(days=2),
                                WinBackCampaign.cycle_touchpoint_count < 4,
                            ).order_by(
                                WinBackCampaign.next_x_date.asc(),
                                WinBackCampaign.premium_at_cancel.desc().nullslast(),
                            ).limit(max_per_tick * 3).all()
                            for c in phase_2_candidates:
                                if sent >= max_per_tick:
                                    break
                                cycle_tc = c.cycle_touchpoint_count or 0
                                offset_days = offset_map.get(cycle_tc, 7)
                                due_at = c.next_x_date - _td(days=offset_days)
                                due_naive = due_at.replace(tzinfo=None) if due_at.tzinfo else due_at
                                if _dt.utcnow() < due_naive:
                                    continue
                                if c.last_touchpoint_at:
                                    lt = c.last_touchpoint_at.replace(tzinfo=None) if c.last_touchpoint_at.tzinfo else c.last_touchpoint_at
                                    if (_dt.utcnow() - lt).days < 5:
                                        continue
                                if _send_winback_email(c, touchpoint=1 if cycle_tc == 0 else 2):
                                    c.touchpoint_count = (c.touchpoint_count or 0) + 1
                                    c.cycle_touchpoint_count = cycle_tc + 1
                                    c.last_touchpoint_at = _dt.utcnow()
                                    c.phase = "x_date_prep"
                                    c.status = "active"
                                    if c.cycle_touchpoint_count >= 4:
                                        c.next_x_date = c.next_x_date + _td(days=365)
                                        c.cycle_touchpoint_count = 0
                                        c.x_date_cycle_count = (c.x_date_cycle_count or 0) + 1
                                        c.phase = "dormant"
                                    sent += 1
                            # Phase 1 cold wake-up
                            if sent < max_per_tick:
                                p1 = _db.query(WinBackCampaign).filter(
                                    WinBackCampaign.excluded == False,
                                    WinBackCampaign.last_reply_at.is_(None),
                                    (WinBackCampaign.bounce_count == None) | (WinBackCampaign.bounce_count < 3),
                                    WinBackCampaign.status != "won_back",
                                    WinBackCampaign.customer_email.isnot(None),
                                    WinBackCampaign.touchpoint_count == 0,
                                ).filter(
                                    (WinBackCampaign.phase == "cold_wakeup") | (WinBackCampaign.phase.is_(None))
                                ).order_by(
                                    WinBackCampaign.premium_at_cancel.desc().nullslast(),
                                ).limit(max_per_tick - sent).all()
                                for c in p1:
                                    # Skip if X-date soon (Phase 2 will handle)
                                    if c.next_x_date:
                                        nx = c.next_x_date.replace(tzinfo=None) if c.next_x_date.tzinfo else c.next_x_date
                                        days_until = (nx - _dt.utcnow()).days
                                        if 0 < days_until < 60:
                                            c.phase = "x_date_prep"
                                            continue
                                    if _send_winback_email(c, touchpoint=1):
                                        c.touchpoint_count = 1
                                        c.last_touchpoint_at = _dt.utcnow()
                                        c.status = "active"
                                        if not c.next_x_date and c.cancellation_date:
                                            cn = c.cancellation_date.replace(tzinfo=None) if c.cancellation_date.tzinfo else c.cancellation_date
                                            t = cn + _td(days=365)
                                            while t < _dt.utcnow():
                                                t = t + _td(days=365)
                                            c.next_x_date = t
                                        c.phase = "dormant"
                                        sent += 1
                            _db.commit()
                            if sent > 0:
                                logger.info(f"Winback scheduler: sent {sent} email(s)")
                    finally:
                        _db.close()
            except Exception as e:
                logger.error("Winback scheduler error: %s", e)
            _time.sleep(1800)  # Every 30 minutes

    threading.Thread(target=_winback_scheduler, daemon=True).start()

    # ── Cold prospect scheduler (every 30 min during business hours) ──
    # Same Phase 1 + Phase 2 logic as winback but for the separate
    # cold_prospects table (Allstate X-date prospects).
    #
    # GATE: env var COLD_PROSPECT_SCHEDULER_ENABLED must be 'true'.
    # Default false so this never auto-fires on a fresh deploy.
    #
    # Default pace: COLD_MAX_PER_TICK env var (default 4). With 4 emails
    # per tick × 12 ticks/business-day (9-3pm) = ~48/day. Tunable.
    def _cold_prospect_scheduler():
        import time as _time
        import os
        _time.sleep(180)  # Wait for migrations + winback scheduler
        logger.info("Cold prospect scheduler started (gated on COLD_PROSPECT_SCHEDULER_ENABLED)")
        while True:
            try:
                if os.getenv("COLD_PROSPECT_SCHEDULER_ENABLED", "false").lower() == "true":
                    from app.core.database import SessionLocal
                    from app.api.cold_prospects import _send_cold_email, _get_assigned_producer
                    from app.models.campaign import ColdProspect
                    from datetime import datetime as _dt, timedelta as _td
                    from zoneinfo import ZoneInfo
                    _db = SessionLocal()
                    try:
                        now_ct = _dt.utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Chicago"))
                        weekday = now_ct.weekday()
                        hour = now_ct.hour
                        # Per Evan: 9 AM - 3 PM CT, M-F
                        if weekday >= 5 or hour < 9 or hour >= 15:
                            pass
                        else:
                            max_per_tick = int(os.getenv("COLD_MAX_PER_TICK", "4"))
                            sent = 0
                            base_filter = [
                                ColdProspect.excluded == False,
                                ColdProspect.status == "active",
                                ColdProspect.email_valid == True,
                                ColdProspect.do_not_email == False,
                                ColdProspect.email.isnot(None),
                                ColdProspect.last_reply_at.is_(None),
                                ColdProspect.bounce_count < 2,
                            ]

                            # Phase 2 priority
                            offset_map = {0: 30, 1: 21, 2: 14, 3: 7}
                            p2_candidates = _db.query(ColdProspect).filter(
                                *base_filter,
                                ColdProspect.next_x_date.isnot(None),
                                ColdProspect.next_x_date <= _dt.utcnow() + _td(days=35),
                                ColdProspect.next_x_date >= _dt.utcnow() - _td(days=2),
                                ColdProspect.cycle_touchpoint_count < 4,
                            ).order_by(
                                ColdProspect.next_x_date.asc(),
                                ColdProspect.premium.desc().nullslast(),
                            ).limit(max_per_tick * 3).all()

                            for c in p2_candidates:
                                if sent >= max_per_tick:
                                    break
                                cycle_tc = c.cycle_touchpoint_count or 0
                                offset_days = offset_map.get(cycle_tc, 7)
                                due_at = c.next_x_date - _td(days=offset_days)
                                due_naive = due_at.replace(tzinfo=None) if due_at.tzinfo else due_at
                                if _dt.utcnow() < due_naive:
                                    continue
                                if c.last_touchpoint_at:
                                    lt = c.last_touchpoint_at.replace(tzinfo=None) if c.last_touchpoint_at.tzinfo else c.last_touchpoint_at
                                    if (_dt.utcnow() - lt).days < 5:
                                        continue
                                if _send_cold_email(c, _db):
                                    c.touchpoint_count = (c.touchpoint_count or 0) + 1
                                    c.cycle_touchpoint_count = cycle_tc + 1
                                    c.last_touchpoint_at = _dt.utcnow()
                                    c.phase = "x_date_prep"
                                    if c.cycle_touchpoint_count >= 4:
                                        c.next_x_date = c.next_x_date + _td(days=365)
                                        c.cycle_touchpoint_count = 0
                                        c.x_date_cycle_count = (c.x_date_cycle_count or 0) + 1
                                        c.phase = "dormant"
                                    sent += 1

                            # Phase 1 fills the rest
                            if sent < max_per_tick:
                                p1 = _db.query(ColdProspect).filter(
                                    *base_filter,
                                    ColdProspect.touchpoint_count == 0,
                                ).filter(
                                    (ColdProspect.phase == "cold_wakeup") | (ColdProspect.phase.is_(None))
                                ).order_by(
                                    ColdProspect.premium.desc().nullslast(),
                                    ColdProspect.created_at.asc(),
                                ).limit(max_per_tick - sent).all()
                                for c in p1:
                                    if c.next_x_date:
                                        nx = c.next_x_date.replace(tzinfo=None) if c.next_x_date.tzinfo else c.next_x_date
                                        days_until = (nx - _dt.utcnow()).days
                                        if 0 < days_until < 60:
                                            c.phase = "x_date_prep"
                                            continue
                                    if _send_cold_email(c, _db):
                                        c.touchpoint_count = 1
                                        c.last_touchpoint_at = _dt.utcnow()
                                        c.phase = "dormant"
                                        sent += 1

                            _db.commit()
                            if sent > 0:
                                logger.info(f"Cold prospect scheduler: sent {sent} email(s)")
                    finally:
                        _db.close()
            except Exception as e:
                logger.error("Cold prospect scheduler error: %s", e)
            _time.sleep(1800)

    threading.Thread(target=_cold_prospect_scheduler, daemon=True).start()

    # Life cross-sell campaign sending available via POST /api/life-campaign/send-pending
    logger.info("Life cross-sell campaign send available via API endpoint")

    yield


# Disable API docs in production
docs_url = "/docs" if settings.ENVIRONMENT != "production" else None
redoc_url = "/redoc" if settings.ENVIRONMENT != "production" else None

app = FastAPI(
    title=settings.APP_NAME,
    description="Better Choice Insurance - Sales Tracking API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
)

# Rate limiting — handle 429 Too Many Requests
from app.api.auth import limiter as auth_limiter
app.state.limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Global exception handler - always return JSON (never plain text)
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    logger.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal error: {str(exc)}"},
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# CORS — allow Render frontend URL + custom domains + local dev
allowed_origins = [
    "http://localhost:3000",
    "http://frontend:3000",
    "https://better-choice-web.onrender.com",
    "https://orbit.betterchoiceins.com",
    "https://quote.betterchoiceins.com",
]
frontend_url = os.environ.get("FRONTEND_URL", "")
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)
    if not frontend_url.startswith("https"):
        allowed_origins.append(frontend_url.replace("http://", "https://"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request-level safety middleware ──
@app.middleware("http")
async def safety_middleware(request, call_next):
    """Log slow requests and catch any unhandled middleware-level errors."""
    import time as _time
    start = _time.time()
    try:
        response = await call_next(request)
        elapsed = _time.time() - start
        if elapsed > 10:
            logger.warning(f"SLOW REQUEST: {request.method} {request.url.path} took {elapsed:.1f}s")
        return response
    except Exception as e:
        elapsed = _time.time() - start
        logger.error(f"MIDDLEWARE ERROR: {request.method} {request.url.path} after {elapsed:.1f}s: {e}")
        return JSONResponse(status_code=500, content={"detail": f"Server error: {str(e)[:200]}"})


@app.get("/health")
def health_check():
    """Trivial health check — must respond in <5s always. No imports, no DB, no work."""
    return {"status": "healthy", "service": "better-choice-insurance-api", "version": "1.0.5"}


@app.post("/admin/force-migrate")
def force_migrate():
    """Force run database migrations for missing columns."""
    from app.core.database import engine
    from sqlalchemy import text as sa_text
    results = []
    for col_sql in [
        "ALTER TABLE quotes ADD COLUMN premium_term VARCHAR DEFAULT '6 months'",
        "ALTER TABLE quotes ADD COLUMN notes TEXT",
        "ALTER TABLE quotes ADD COLUMN policy_lines TEXT",
        "ALTER TABLE quotes ADD COLUMN followup_disabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE quotes ADD COLUMN unsubscribe_token VARCHAR",
        "ALTER TABLE quotes ADD COLUMN last_remarket_sent_at TIMESTAMPTZ",
        "ALTER TABLE quotes ADD COLUMN remarket_touch_count INTEGER DEFAULT 0",
        # A/B test fields (Apr 2026)
        "ALTER TABLE quotes ADD COLUMN email_variant VARCHAR(1)",
        "ALTER TABLE quotes ADD COLUMN reply_received BOOLEAN DEFAULT FALSE",
        "ALTER TABLE quotes ADD COLUMN reply_received_at TIMESTAMPTZ",
        "ALTER TABLE quotes ADD COLUMN coverage_dwelling NUMERIC(12, 2)",
        "ALTER TABLE quotes ADD COLUMN coverage_personal_property NUMERIC(12, 2)",
        "ALTER TABLE quotes ADD COLUMN coverage_liability NUMERIC(12, 2)",
        "ALTER TABLE quotes ADD COLUMN auto_bi_limit VARCHAR(50)",
        "ALTER TABLE quotes ADD COLUMN auto_pd_limit VARCHAR(50)",
        "ALTER TABLE quotes ADD COLUMN auto_um_limit VARCHAR(50)",
        "ALTER TABLE quotes ADD COLUMN quote_pdf_paths JSON",
        # Winback Phase 2 (X-date cycle scheduler)
        "ALTER TABLE winback_campaigns ADD COLUMN phase VARCHAR DEFAULT 'cold_wakeup'",
        "ALTER TABLE winback_campaigns ADD COLUMN next_x_date TIMESTAMPTZ",
        "ALTER TABLE winback_campaigns ADD COLUMN x_date_cycle_count INTEGER DEFAULT 0",
        "ALTER TABLE winback_campaigns ADD COLUMN cycle_touchpoint_count INTEGER DEFAULT 0",
        "ALTER TABLE winback_campaigns ADD COLUMN last_reply_at TIMESTAMPTZ",
        "ALTER TABLE winback_campaigns ADD COLUMN last_reply_subject VARCHAR",
        """CREATE TABLE IF NOT EXISTS life_cross_sells (
            id SERIAL PRIMARY KEY,
            sale_id INTEGER REFERENCES sales(id),
            client_name VARCHAR NOT NULL,
            client_email VARCHAR NOT NULL,
            client_phone VARCHAR,
            state VARCHAR(2),
            pc_carrier VARCHAR,
            pc_policy_type VARCHAR,
            pc_premium NUMERIC(10,2),
            producer_id INTEGER REFERENCES users(id),
            producer_name VARCHAR,
            back9_apply_link VARCHAR,
            back9_eapp_id INTEGER,
            back9_eapp_uuid VARCHAR,
            back9_quote_premium NUMERIC(10,2),
            back9_carrier VARCHAR,
            back9_product VARCHAR,
            back9_face_amount NUMERIC(12,2),
            status VARCHAR DEFAULT 'pending',
            email_sent_at TIMESTAMP WITH TIME ZONE,
            email_opened_at TIMESTAMP WITH TIME ZONE,
            link_clicked_at TIMESTAMP WITH TIME ZONE,
            app_started_at TIMESTAMP WITH TIME ZONE,
            app_submitted_at TIMESTAMP WITH TIME ZONE,
            approved_at TIMESTAMP WITH TIME ZONE,
            inforce_at TIMESTAMP WITH TIME ZONE,
            campaign_batch VARCHAR,
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )""",
        """CREATE TABLE IF NOT EXISTS reshops (
            id SERIAL PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(id),
            customer_name VARCHAR NOT NULL,
            customer_phone VARCHAR,
            customer_email VARCHAR,
            policy_number VARCHAR,
            carrier VARCHAR,
            line_of_business VARCHAR,
            current_premium NUMERIC(10,2),
            expiration_date TIMESTAMP,
            stage VARCHAR NOT NULL DEFAULT 'new_request',
            priority VARCHAR DEFAULT 'normal',
            source VARCHAR,
            source_detail TEXT,
            referred_by VARCHAR,
            assigned_to INTEGER REFERENCES users(id),
            quoter VARCHAR,
            presenter VARCHAR,
            quoted_carrier VARCHAR,
            quoted_premium NUMERIC(10,2),
            premium_savings NUMERIC(10,2),
            quote_notes TEXT,
            outcome VARCHAR,
            outcome_notes TEXT,
            bound_carrier VARCHAR,
            bound_premium NUMERIC(10,2),
            bound_date TIMESTAMP,
            reason VARCHAR,
            reason_detail TEXT,
            notes TEXT,
            is_proactive BOOLEAN DEFAULT FALSE,
            renewal_premium NUMERIC(10,2),
            premium_change_pct NUMERIC(5,2),
            requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            stage_updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )""",
        "CREATE INDEX IF NOT EXISTS idx_reshops_stage ON reshops(stage)",
        "CREATE INDEX IF NOT EXISTS idx_reshops_customer ON reshops(customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_reshops_assigned ON reshops(assigned_to)",
        """CREATE TABLE IF NOT EXISTS reshop_activities (
            id SERIAL PRIMARY KEY,
            reshop_id INTEGER NOT NULL REFERENCES reshops(id),
            user_id INTEGER REFERENCES users(id),
            user_name VARCHAR,
            action VARCHAR NOT NULL,
            detail TEXT,
            old_value VARCHAR,
            new_value VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_reshop_activities_reshop ON reshop_activities(reshop_id)",
        # Lead Providers table
        """CREATE TABLE IF NOT EXISTS lead_providers (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            slug VARCHAR NOT NULL UNIQUE,
            portal_url VARCHAR,
            pause_url VARCHAR,
            logo_emoji VARCHAR,
            is_paused BOOLEAN DEFAULT FALSE,
            last_status_change TIMESTAMP WITH TIME ZONE,
            last_status_by VARCHAR,
            notes TEXT,
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
        # BEACON Knowledge Base
        """CREATE TABLE IF NOT EXISTS beacon_knowledge (
            id SERIAL PRIMARY KEY,
            source_type VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            content TEXT NOT NULL,
            summary TEXT,
            tags VARCHAR,
            carrier VARCHAR,
            status VARCHAR DEFAULT 'pending',
            submitted_by INTEGER,
            submitted_by_name VARCHAR,
            reviewed_by INTEGER,
            reviewed_by_name VARCHAR,
            reviewed_at TIMESTAMP WITH TIME ZONE,
            review_note TEXT,
            original_filename VARCHAR,
            file_hash VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_beacon_kb_status ON beacon_knowledge(status)",
        "CREATE INDEX IF NOT EXISTS idx_beacon_kb_type ON beacon_knowledge(source_type)",
        # Property Lookup Cache
        """CREATE TABLE IF NOT EXISTS property_lookup_cache (
            id SERIAL PRIMARY KEY,
            address_hash VARCHAR UNIQUE,
            address_raw VARCHAR NOT NULL,
            latitude FLOAT,
            longitude FLOAT,
            street VARCHAR,
            city VARCHAR,
            state VARCHAR,
            zip_code VARCHAR,
            county VARCHAR,
            year_built INTEGER,
            square_footage INTEGER,
            assessed_value FLOAT,
            market_value FLOAT,
            property_class VARCHAR,
            bedrooms INTEGER,
            bathrooms FLOAT,
            stories INTEGER,
            lot_size_sqft INTEGER,
            flood_zone VARCHAR,
            flood_zone_desc VARCHAR,
            in_sfha VARCHAR,
            street_view_url VARCHAR,
            zillow_url VARCHAR,
            data_sources JSONB,
            raw_data JSONB,
            looked_up_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""",
    ]:
        try:
            with engine.connect() as conn:
                conn.execute(sa_text(col_sql))
                conn.commit()
            results.append(f"OK: {col_sql}")
        except Exception as e:
            results.append(f"SKIP: {str(e)[:80]}")

    # Ensure commission_rate_override column on users
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE users ADD COLUMN commission_rate_override NUMERIC(5,4)"))
            conn.commit()
        results.append("OK: Added users.commission_rate_override")
    except Exception as e:
        results.append(f"SKIP users.commission_rate_override: {str(e)[:80]}")

    # Ensure must_change_password column on users
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE"))
            conn.commit()
        results.append("OK: Added users.must_change_password")
    except Exception as e:
        results.append(f"SKIP users.must_change_password: {str(e)[:80]}")

    # Ensure is_renewal_term column on statement_lines
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE statement_lines ADD COLUMN is_renewal_term BOOLEAN"))
            conn.commit()
        results.append("OK: Added statement_lines.is_renewal_term")
    except Exception as e:
        results.append(f"SKIP statement_lines.is_renewal_term: {str(e)[:80]}")

    # Reshop outreach attempt tracking (3-attempt workflow)
    for colname in ["attempt_1_at","attempt_2_at","attempt_3_at"]:
        try:
            with engine.connect() as conn:
                conn.execute(sa_text(f"ALTER TABLE reshops ADD COLUMN {colname} TIMESTAMP WITH TIME ZONE"))
                conn.commit()
            results.append(f"OK: Added reshops.{colname}")
        except Exception as e:
            results.append(f"SKIP reshops.{colname}: {str(e)[:80]}")
    for colname in ["attempt_1_answered","attempt_2_answered","attempt_3_answered"]:
        try:
            with engine.connect() as conn:
                conn.execute(sa_text(f"ALTER TABLE reshops ADD COLUMN {colname} BOOLEAN"))
                conn.commit()
            results.append(f"OK: Added reshops.{colname}")
        except Exception as e:
            results.append(f"SKIP reshops.{colname}: {str(e)[:80]}")

    # survey_responses: make sale_id nullable, add customer_id + source
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE survey_responses ALTER COLUMN sale_id DROP NOT NULL"))
            conn.commit()
        results.append("OK: survey_responses.sale_id now nullable")
    except Exception as e:
        results.append(f"SKIP survey_responses.sale_id nullable: {str(e)[:80]}")
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE survey_responses ADD COLUMN customer_id INTEGER REFERENCES customers(id)"))
            conn.commit()
        results.append("OK: Added survey_responses.customer_id")
    except Exception as e:
        results.append(f"SKIP survey_responses.customer_id: {str(e)[:80]}")
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE survey_responses ADD COLUMN source VARCHAR"))
            conn.commit()
        results.append("OK: Added survey_responses.source")
    except Exception as e:
        results.append(f"SKIP survey_responses.source: {str(e)[:80]}")

    # geocode_cache — for the /claim-map feature
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("""
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    id SERIAL PRIMARY KEY,
                    address_hash VARCHAR(64) UNIQUE NOT NULL,
                    address_full VARCHAR NOT NULL,
                    lat DOUBLE PRECISION,
                    lng DOUBLE PRECISION,
                    provider VARCHAR,
                    failed BOOLEAN DEFAULT FALSE,
                    failure_reason VARCHAR,
                    raw_response TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_geocode_cache_address_hash ON geocode_cache (address_hash);"))
            conn.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_geocode_cache_failed ON geocode_cache (failed);"))
            conn.commit()
        results.append("OK: geocode_cache table ready")
    except Exception as e:
        results.append(f"SKIP geocode_cache: {str(e)[:80]}")

    # Add file_data BYTEA column to chat_messages for persistent file storage
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE chat_messages ADD COLUMN file_data BYTEA"))
            conn.commit()
        results.append("OK: Added chat_messages.file_data")
    except Exception as e:
        results.append(f"SKIP chat_messages.file_data: {str(e)[:80]}")

    # Mark all sales before Jan 2026 as premium paid
    try:
        with engine.connect() as conn:
            r = conn.execute(sa_text(
                "UPDATE sales SET commission_status = 'paid' "
                "WHERE commission_status != 'paid' "
                "AND sale_date < '2026-01-01'"
            ))
            conn.commit()
            results.append(f"OK: Marked {r.rowcount} pre-2026 sales as premium paid")
    except Exception as e:
        results.append(f"SKIP pre-2026 paid: {str(e)[:80]}")

    return {"results": results}


@app.get("/")
def root():
    return {"message": "Better Choice Insurance API", "version": "1.0.0", "docs": "/docs"}


# Include routers
app.include_router(auth.router)
app.include_router(sales.router)
app.include_router(commissions.router)
app.include_router(statements.router)
app.include_router(analytics.router)
app.include_router(reports_api.router)
app.include_router(payroll_api.router)
app.include_router(retention_api.router)
app.include_router(survey_api.router)
app.include_router(admin_api.router)
app.include_router(timeclock_api.router)
app.include_router(customers_api.router)
app.include_router(nonpay_api.router)
app.include_router(uw_api.router)
app.include_router(winback_api.router)
app.include_router(cold_prospects_api.router)
app.include_router(email_preview_api.router)
app.include_router(renewals_api.router)
app.include_router(quotes_api.router)
app.include_router(non_renewal_api.router)
app.include_router(retell_api.router)
app.include_router(mia_bypass_api.router)
app.include_router(dialer_api.router)
app.include_router(sms_api.router)
app.include_router(cancellation_api.router)
app.include_router(nowcerts_poll_api.router)
app.include_router(inspection_api.router)

from app.api import claim_map as claim_map_api
app.include_router(claim_map_api.router)

from app.api import uw_tracker as uw_tracker_api
app.include_router(uw_tracker_api.router)

from app.api import life_crosssell as life_crosssell_api
app.include_router(life_crosssell_api.router, prefix="/api")

# Life cross-sell campaign table
try:
    from sqlalchemy import inspect as _life_inspect
    from app.core.database import engine as _life_engine
    _life_insp = _life_inspect(_life_engine)
    if "life_crosssell_contacts" not in _life_insp.get_table_names():
        from app.models.life_campaign import LifeCrossSellContact
        LifeCrossSellContact.__table__.create(_life_engine)
        logger.info("Created life_crosssell_contacts table")
except Exception as e:
    logger.warning(f"Life campaign table check: {e}")
from app.api.life_campaign import router as life_campaign_router

app.include_router(life_campaign_router)

from app.api import tasks as tasks_api
app.include_router(tasks_api.router)
app.include_router(missive_api.router)
app.include_router(chat_api.router)

from app.api import email_inbox as email_inbox_api
app.include_router(email_inbox_api.router)

from app.api.email_tracking import router as email_tracking_router
app.include_router(email_tracking_router)

from app.api import gmail_sync as gmail_sync_api
app.include_router(gmail_sync_api.router)

from app.api import smart_inbox as smart_inbox_api
app.include_router(smart_inbox_api.router)

from app.api import tickets as tickets_api
app.include_router(tickets_api.router)
try:
    tickets_api.ensure_tickets_table()
except Exception as e:
    logger.warning(f"Tickets table migration: {e}")

try:
    from app.api import events as events_api
    app.include_router(events_api.router)
    logger.info("Events SSE router loaded successfully")
except Exception as e:
    logger.error(f"Failed to load events router: {e}")

app.include_router(reshop_api.router)
app.include_router(id_cards_api.router)

from app.api import revenue_tracker as revenue_tracker_api
app.include_router(revenue_tracker_api.router)

from app.api import lead_providers as lead_providers_api
from app.api import daily_checklist as daily_checklist_api
app.include_router(lead_providers_api.router)
app.include_router(daily_checklist_api.router)
try:
    lead_providers_api.ensure_automation_table()
except Exception as e:
    logger.warning(f"Lead automation table migration: {e}")

from app.api import beacon_kb as beacon_kb_api
app.include_router(beacon_kb_api.router)

from app.api import requote_campaigns as requote_campaigns_api
app.include_router(requote_campaigns_api.router)

from app.api import property as property_api
app.include_router(property_api.router)
app.include_router(leads_api.router)
app.include_router(sales_records_api.router)

from app.api import commission_tracker as commission_tracker_api
app.include_router(commission_tracker_api.router)

from app.api import renewal_survey as renewal_survey_api
app.include_router(renewal_survey_api.router)

from app.api import quote_jobs as quote_jobs_api
app.include_router(quote_jobs_api.router)

from app.api import texting as texting_api
app.include_router(texting_api.router)


# ── Public bind confirmation endpoint (no auth — customer-facing) ──
@app.get("/api/bind/{quote_id}")
def bind_confirmation_page(quote_id: int):
    """Return a branded 'Ready to Bind' confirmation page for the customer."""
    from app.core.database import SessionLocal
    from app.models.campaign import Quote as QuoteModel

    db = SessionLocal()
    try:
        quote = db.query(QuoteModel).filter(QuoteModel.id == quote_id).first()
        if not quote:
            return HTMLResponse("<h1>Quote not found</h1>", status_code=404)

        from app.services.welcome_email import CARRIER_INFO, BCI_NAVY, BCI_CYAN
        carrier_key = (quote.carrier or "").lower().replace(" ", "_")
        cinfo = CARRIER_INFO.get(carrier_key, {})
        accent = cinfo.get("accent_color", BCI_CYAN)
        carrier_name = cinfo.get("display_name", (quote.carrier or "").title())
        first_name = quote.prospect_name.split()[0] if quote.prospect_name else "there"
        prospect_phone = quote.prospect_phone or ""
        premium_str = f"${float(quote.quoted_premium):,.2f}" if quote.quoted_premium else ""
        term = quote.premium_term or "6 months"

        # Policy lines
        lines_html = ""
        if quote.policy_lines:
            import json as jsonlib
            lines = jsonlib.loads(quote.policy_lines) if isinstance(quote.policy_lines, str) else quote.policy_lines
            if len(lines) > 1:
                rows = ""
                for line in lines:
                    pt = (line.get("policy_type") or "").replace("_", " ").title()
                    pr = f"${float(line.get('premium') or 0):,.2f}"
                    rows += f'<div style="display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #E2E8F0;"><span style="color:#334155;font-weight:600;">{pt}</span><span style="color:{accent};font-weight:700;font-size:18px;">{pr}</span></div>'
                lines_html = f'<div style="margin:20px 0;padding:0 4px;">{rows}</div>'

        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ready to Bind — Better Choice Insurance</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f1f5f9; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px; }}
  .card {{ background:white; border-radius:16px; max-width:520px; width:100%; overflow:hidden; box-shadow:0 20px 60px rgba(0,0,0,0.12); }}
  .header {{ background:linear-gradient(135deg,#1a2b5f 0%,#162249 60%,#0c4a6e 100%); padding:32px; text-align:center; }}
  .body {{ padding:32px; }}
  .checkmark {{ width:72px; height:72px; background:linear-gradient(135deg,{accent},#10b981); border-radius:50%; margin:0 auto 16px; display:flex; align-items:center; justify-content:center; }}
  .checkmark svg {{ width:36px; height:36px; color:white; }}
  .premium-box {{ background:linear-gradient(135deg,{accent}10,{accent}05); border:2px solid {accent}40; border-radius:12px; padding:24px; text-align:center; margin:24px 0; }}
  .btn {{ display:inline-block; background:{accent}; color:white; padding:14px 40px; border-radius:8px; text-decoration:none; font-weight:700; font-size:15px; margin:8px 4px; }}
  .btn-outline {{ display:inline-block; background:transparent; color:{accent}; border:2px solid {accent}; padding:12px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:14px; margin:8px 4px; }}
  #confirmSection {{ display:block; }}
  #successSection {{ display:none; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1 style="color:white;font-size:18px;font-weight:700;margin-bottom:4px;">Better Choice Insurance Group</h1>
    <p style="color:{accent};font-size:13px;font-weight:600;">{carrier_name}</p>
  </div>
  <div class="body">

    <!-- Confirm Section -->
    <div id="confirmSection">
      <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:48px;margin-bottom:8px;">🎉</div>
        <h2 style="color:#1e293b;font-size:22px;font-weight:800;margin-bottom:8px;">Great Choice, {first_name}!</h2>
        <p style="color:#64748B;font-size:15px;line-height:1.5;">You're one step away from getting covered with {carrier_name}.</p>
      </div>

      <div class="premium-box">
        <p style="color:#64748B;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">Your Quote</p>
        <p style="color:#1e293b;font-size:38px;font-weight:800;letter-spacing:-1px;margin:4px 0;">{premium_str}</p>
        <p style="color:#64748B;font-size:14px;">per {term}</p>
      </div>

      {lines_html}

      <div style="text-align:center;margin:24px 0;">
        <p style="color:#334155;font-size:14px;line-height:1.6;margin-bottom:20px;">
          Enter your best contact number and tap confirm — your advisor will reach out shortly to finalize everything.
        </p>
        <div style="margin:0 auto 20px auto;max-width:280px;">
          <label style="display:block;text-align:left;font-size:12px;color:#64748B;font-weight:600;margin-bottom:6px;">Best Number to Reach You</label>
          <input id="phoneInput" type="tel" placeholder="(555) 555-1234" 
            style="width:100%;padding:12px 16px;border:2px solid #E2E8F0;border-radius:8px;font-size:16px;color:#1e293b;outline:none;transition:border 0.2s;"
            onfocus="this.style.borderColor='{accent}'" onblur="this.style.borderColor='#E2E8F0'"
            oninput="formatPhone(this)" value="{prospect_phone}" />
        </div>
        <a href="javascript:void(0)" onclick="confirmBind()" class="btn" id="bindBtn">
          ✓ Confirm — I Want This Coverage!
        </a>
        <br>
        <a href="tel:8479085665" class="btn-outline" style="margin-top:12px;">
          📞 Call Us Instead: (847) 908-5665
        </a>
      </div>

      <div style="text-align:center;margin-top:16px;">
        <p style="color:#94a3b8;font-size:11px;">By confirming, your insurance advisor will contact you to complete the application and process payment. Our office hours are Monday–Friday, 9 AM – 6 PM Central.</p>
      </div>
    </div>

    <!-- Success Section (shown after confirm) -->
    <div id="successSection">
      <div style="text-align:center;">
        <div class="checkmark">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
        </div>
        <h2 style="color:#1e293b;font-size:24px;font-weight:800;margin-bottom:8px;">You're All Set!</h2>
        <p style="color:#64748B;font-size:15px;line-height:1.6;margin-bottom:24px;">
          We've notified your advisor and they'll be in touch shortly to finalize your {carrier_name} coverage.
        </p>

        <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:10px;padding:20px;margin:20px 0;text-align:left;">
          <p style="color:#166534;font-size:13px;font-weight:600;margin-bottom:8px;">📋 What happens next:</p>
          <p id="responseTimeMsg" style="color:#166534;font-size:13px;line-height:1.8;">
            1. Your advisor has been notified and will reach out shortly<br>
            2. We'll walk you through any final questions<br>
            3. Once confirmed, your coverage starts on your effective date
          </p>
        </div>

        <div id="afterHoursNotice" style="display:none;background:#FEF3C7;border:1px solid #FDE68A;border-radius:10px;padding:16px;margin:16px 0;text-align:left;">
          <p style="color:#92400E;font-size:13px;line-height:1.6;">
            <strong>⏰ After Hours Notice:</strong> <span id="afterHoursText"></span>
          </p>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
function formatPhone(el) {{
  let v = el.value.replace(/\\D/g, '');
  if (v.length > 10) v = v.slice(0, 10);
  if (v.length >= 7) el.value = '(' + v.slice(0,3) + ') ' + v.slice(3,6) + '-' + v.slice(6);
  else if (v.length >= 4) el.value = '(' + v.slice(0,3) + ') ' + v.slice(3);
  else if (v.length > 0) el.value = '(' + v;
  else el.value = '';
}}

async function confirmBind() {{
  const btn = document.getElementById('bindBtn');
  const phone = document.getElementById('phoneInput').value.trim();
  
  if (!phone || phone.replace(/\\D/g, '').length < 10) {{
    document.getElementById('phoneInput').style.borderColor = '#EF4444';
    document.getElementById('phoneInput').focus();
    return;
  }}
  
  btn.textContent = 'Confirming...';
  btn.style.opacity = '0.6';
  btn.style.pointerEvents = 'none';
  try {{
    const resp = await fetch('/api/bind/{quote_id}/confirm', {{ 
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ phone: phone }})
    }});
    const data = await resp.json();
    
    // Update response time message
    if (data.response_msg) {{
      document.getElementById('responseTimeMsg').innerHTML = 
        '1. ' + data.response_msg + '<br>' +
        '2. We\\'ll walk you through any final questions<br>' +
        '3. Once confirmed, your coverage starts on your effective date';
    }}
    
    // Show after hours notice if applicable
    if (data.after_hours_notice) {{
      document.getElementById('afterHoursNotice').style.display = 'block';
      document.getElementById('afterHoursText').textContent = data.after_hours_notice;
    }}
  }} catch(e) {{}}
  document.getElementById('confirmSection').style.display = 'none';
  document.getElementById('successSection').style.display = 'block';
}}
</script>
</body></html>"""
        return HTMLResponse(html)
    finally:
        db.close()


@app.post("/api/bind/{quote_id}/confirm")
def confirm_bind(quote_id: int, body: dict = None):
    """Process bind confirmation — update quote status and alert the producer."""
    from app.core.database import SessionLocal
    from app.models.campaign import Quote as QuoteModel
    from app.models.user import User as UserModel
    from datetime import datetime
    import pytz

    # Parse phone from request body
    contact_phone = ""
    if body and isinstance(body, dict):
        contact_phone = body.get("phone", "")

    db = SessionLocal()
    try:
        quote = db.query(QuoteModel).filter(QuoteModel.id == quote_id).first()
        if not quote:
            return {"ok": False}

        # Mark quote as bind-requested and update phone
        quote.status = "bind_requested"
        if contact_phone:
            quote.prospect_phone = contact_phone
        db.commit()

        # ── Calculate smart response time based on business hours ──
        # Business hours: M-F 9 AM - 6 PM Central
        try:
            ct = pytz.timezone("America/Chicago")
            now_ct = datetime.now(ct)
        except Exception:
            from datetime import timezone, timedelta as td
            now_ct = datetime.now(timezone(td(hours=-6)))
        
        weekday = now_ct.weekday()  # 0=Mon, 6=Sun
        hour = now_ct.hour
        minute = now_ct.minute

        response_msg = ""
        after_hours_notice = ""

        if weekday < 5 and 9 <= hour < 17:
            # During business hours (before 5 PM to leave buffer)
            response_msg = "Your advisor has been notified and will reach out within the next few hours"
        elif weekday < 5 and 17 <= hour < 18:
            # Late in the day (5-6 PM)
            response_msg = "Your advisor has been notified and will reach out by end of day today or first thing tomorrow morning"
            after_hours_notice = (
                "You submitted your request near the end of our business day. "
                "Your advisor may follow up this evening or first thing tomorrow morning by 10 AM."
            )
        elif weekday == 4 and hour >= 18:
            # Friday evening
            response_msg = "Your advisor has been notified and will reach out first thing Monday morning"
            after_hours_notice = (
                "Our office is closed for the weekend (Sat-Sun). "
                "Your advisor will contact you Monday morning by 10 AM. "
                "Your request is saved and you're first in line!"
            )
        elif weekday == 5:
            # Saturday
            response_msg = "Your advisor has been notified and will reach out first thing Monday morning"
            after_hours_notice = (
                "Our office is closed on weekends. Your advisor will contact you "
                "Monday morning by 10 AM. Your request is saved and you're first in line!"
            )
        elif weekday == 6:
            # Sunday
            response_msg = "Your advisor has been notified and will reach out tomorrow morning"
            after_hours_notice = (
                "Our office reopens Monday at 9 AM. Your advisor will contact you "
                "by 10 AM. Your request is saved and you're first in line!"
            )
        elif weekday < 5 and hour < 9:
            # Before 9 AM weekday
            response_msg = "Your advisor has been notified and will reach out when our office opens at 9 AM"
            after_hours_notice = (
                "Our office opens at 9 AM Central Time. "
                "Your advisor will reach out shortly after."
            )
        else:
            # After 6 PM weekday (Mon-Thu)
            response_msg = "Your advisor has been notified and will reach out first thing tomorrow morning"
            after_hours_notice = (
                "Our office hours are Monday–Friday, 9 AM – 6 PM Central. "
                "Your advisor will contact you tomorrow morning by 10 AM."
            )

        # Send alert email to the producer
        from app.services.welcome_email import CARRIER_INFO, BCI_CYAN
        carrier_key = (quote.carrier or "").lower().replace(" ", "_")
        cinfo = CARRIER_INFO.get(carrier_key, {})
        carrier_name = cinfo.get("display_name", (quote.carrier or "").title())
        accent = cinfo.get("accent_color", BCI_CYAN)
        premium_str = f"${float(quote.quoted_premium):,.2f}" if quote.quoted_premium else "N/A"
        term = quote.premium_term or "6 months"

        # Find producer email
        producer = db.query(UserModel).filter(UserModel.id == quote.producer_id).first()
        producer_email = producer.email if producer and producer.email else "evan@betterchoiceins.com"
        producer_name = quote.producer_name or "Team"

        alert_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:20px;">
  <div style="background:linear-gradient(135deg,#059669,#10b981);padding:24px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <p style="font-size:36px;margin:0;">🔔</p>
    <h1 style="color:white;font-size:20px;margin:8px 0 0 0;">Bind Request Received!</h1>
  </div>
  <div style="background:white;padding:28px 32px;border-radius:0 0 12px 12px;border:1px solid #E2E8F0;border-top:none;">
    <p style="color:#1e293b;font-size:16px;margin:0 0 16px 0;">Hey {producer_name.split()[0]},</p>
    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 20px 0;">
      <strong>{quote.prospect_name}</strong> just confirmed they want to bind their {carrier_name} coverage! 🎉
    </p>
    <div style="background:#F0FDF4;border:2px solid #BBF7D0;border-radius:10px;padding:20px;margin:16px 0;">
      <table style="width:100%;">
        <tr><td style="color:#64748B;font-size:12px;padding:4px 0;">Customer</td><td style="color:#1e293b;font-weight:700;text-align:right;padding:4px 0;">{quote.prospect_name}</td></tr>
        <tr><td style="color:#64748B;font-size:12px;padding:4px 0;">Email</td><td style="color:#1e293b;text-align:right;padding:4px 0;">{quote.prospect_email or 'N/A'}</td></tr>
        <tr><td style="color:#64748B;font-size:12px;padding:4px 0;">Phone</td><td style="color:#1e293b;font-weight:700;font-size:15px;text-align:right;padding:4px 0;">📱 {quote.prospect_phone or 'N/A'}</td></tr>
        <tr><td style="color:#64748B;font-size:12px;padding:4px 0;">Carrier</td><td style="color:#1e293b;font-weight:600;text-align:right;padding:4px 0;">{carrier_name}</td></tr>
        <tr><td style="color:#64748B;font-size:12px;padding:4px 0;">Premium</td><td style="color:{accent};font-weight:800;font-size:18px;text-align:right;padding:4px 0;">{premium_str}/{term}</td></tr>
      </table>
    </div>
    <p style="color:#334155;font-size:14px;line-height:1.6;margin:16px 0;">
      <strong style="color:#DC2626;">⚡ Respond as quickly as possible!</strong> This customer clicked "I Want This Coverage" 
      and is ready to bind right now. The faster you reach out, the higher the close rate.
    </p>
    <p style="color:#64748B;font-size:12px;margin:8px 0 0 0;font-style:italic;">
      Customer was told: "{response_msg}"
    </p>
    <div style="text-align:center;margin:20px 0;">
      <a href="mailto:{quote.prospect_email}" style="display:inline-block;background:{accent};color:white;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:14px;">
        Email {quote.prospect_name.split()[0]}
      </a>
      <a href="tel:{quote.prospect_phone or ''}" style="display:inline-block;background:transparent;color:{accent};border:2px solid {accent};padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin-left:8px;">
        Call Now
      </a>
    </div>
  </div>
</div>
</body></html>"""

        # Send via Mailgun
        try:
            import httpx as _hx
            _mg_key = os.environ.get("MAILGUN_API_KEY") or (settings.MAILGUN_API_KEY if hasattr(settings, "MAILGUN_API_KEY") else "")
            _mg_domain = os.environ.get("MAILGUN_DOMAIN") or (settings.MAILGUN_DOMAIN if hasattr(settings, "MAILGUN_DOMAIN") else "")
            _from_email = os.environ.get("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")
            if _mg_key and _mg_domain:
                _resp = _hx.post(
                    f"https://api.mailgun.net/v3/{_mg_domain}/messages",
                    auth=("api", _mg_key),
                    data={
                        "from": f"ORBIT Bind Alert <{_from_email}>",
                        "to": [producer_email],
                        "cc": ["evan@betterchoiceins.com"],
                        "subject": f"🔔 BIND REQUEST — {quote.prospect_name} wants {carrier_name} ({premium_str}/{term})",
                        "html": alert_html,
                    },
                )
                logger.info(f"Bind alert sent for quote {quote_id} to {producer_email} (status: {_resp.status_code})")
                if _resp.status_code >= 400:
                    logger.error(f"Bind alert Mailgun error: {_resp.text}")
            else:
                logger.error(f"Bind alert NOT sent — missing MAILGUN_API_KEY or MAILGUN_DOMAIN")
                logger.info(f"Bind alert sent for quote {quote_id} to {producer_email}")
        except Exception as e:
            logger.error(f"Bind alert email failed: {e}")

        return {
            "ok": True,
            "quote_id": quote_id,
            "response_msg": response_msg,
            "after_hours_notice": after_hours_notice,
        }
    finally:
        db.close()


# ── Public unsubscribe endpoint (no auth — customer-facing) ──
@app.get("/api/unsubscribe/{token}")
def unsubscribe_page(token: str):
    """Opt out of follow-up emails for a quote."""
    from app.core.database import SessionLocal
    from app.models.campaign import Quote as QuoteModel

    db = SessionLocal()
    try:
        # Find all quotes with this token OR same prospect email
        quote = db.query(QuoteModel).filter(QuoteModel.unsubscribe_token == token).first()
        if not quote:
            return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe</title></head><body style="font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f1f5f9;margin:0;">
<div style="background:white;border-radius:12px;padding:40px;max-width:440px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
<p style="font-size:16px;color:#64748B;">This link is no longer valid or has already been used.</p>
<p style="font-size:14px;color:#94a3b8;margin-top:12px;">If you need assistance, call us at (847) 908-5665.</p>
</div></body></html>""", status_code=404)

        prospect_name = quote.prospect_name or "there"
        first_name = prospect_name.split()[0]

        # Disable follow-ups for ALL quotes for this email
        if quote.prospect_email:
            related = db.query(QuoteModel).filter(
                QuoteModel.prospect_email == quote.prospect_email,
                QuoteModel.followup_disabled == False,
            ).all()
            for q in related:
                q.followup_disabled = True
        else:
            quote.followup_disabled = True
        db.commit()

        return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribed — Better Choice Insurance</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}</style>
</head><body>
<div style="background:white;border-radius:16px;max-width:480px;width:100%;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.12);">
  <div style="background:linear-gradient(135deg,#1a2b5f,#0c4a6e);padding:28px 32px;text-align:center;">
    <h1 style="color:white;font-size:18px;">Better Choice Insurance Group</h1>
  </div>
  <div style="padding:32px;text-align:center;">
    <div style="font-size:48px;margin-bottom:12px;">✉️</div>
    <h2 style="color:#1e293b;font-size:20px;margin-bottom:12px;">You've Been Unsubscribed</h2>
    <p style="color:#64748B;font-size:14px;line-height:1.6;margin-bottom:20px;">
      No worries, {first_name}! We've stopped all follow-up emails for your quote. 
      You won't receive any more reminders from us.
    </p>
    <div style="background:#F8FAFC;border-radius:8px;padding:16px;border:1px solid #E2E8F0;">
      <p style="color:#334155;font-size:13px;line-height:1.6;">
        If you change your mind or want to move forward with your quote, 
        you can always reach us at <a href="tel:8479085665" style="color:#0ea5e9;font-weight:600;">(847) 908-5665</a> 
        or email <a href="mailto:service@betterchoiceins.com" style="color:#0ea5e9;font-weight:600;">service@betterchoiceins.com</a>.
      </p>
    </div>
  </div>
</div>
</body></html>""")
    finally:
        db.close()

# Serve static files (temp PDFs for Thanks.io, etc.)
from fastapi.staticfiles import StaticFiles
from pathlib import Path
_static_dir = Path(__file__).parent.parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
(_static_dir / "temp-letters").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
