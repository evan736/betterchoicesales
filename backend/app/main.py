import os  # v2.27.1 — redeploy
import logging
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
from app.api import missive as missive_api
from app.api import renewals as renewals_api
from app.api import quotes as quotes_api
from app.api import non_renewal as non_renewal_api
from app.api import retell as retell_api
from app.api import mia_bypass as mia_bypass_api
from app.api import sms as sms_api
from app.api import cancellation as cancellation_api
from app.api import nowcerts_poll as nowcerts_poll_api
from app.api import inspection as inspection_api
from app.api import reshop as reshop_api
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
    # ── Security check: refuse to run with default secret key ──
    if settings.SECRET_KEY == "your-secret-key-change-in-production":
        logger.critical("🚨 SECURITY: SECRET_KEY is set to the default value! Set a unique SECRET_KEY env var.")
        import secrets
        settings.SECRET_KEY = secrets.token_urlsafe(64)
        logger.warning(f"⚠️  Generated a temporary random SECRET_KEY for this session. All existing tokens are now invalid.")
        logger.warning(f"⚠️  Set SECRET_KEY in Render environment variables to fix this permanently.")

    init_database()

    # Smart Inbox tables
    from app.migrations.smart_inbox_migration import migrate_smart_inbox
    migrate_smart_inbox()

    # Retention tracking tables
    try:
        from app.migrations.retention_migration import run_retention_migration
        run_retention_migration()
        logger.info("Retention tables migrated")
    except Exception as e:
        logger.warning(f"Retention migration: {e}")

    # Requote campaign tables + column migrations
    try:
        from app.api.requote_campaigns import run_migration as run_requote_migration
        from app.core.database import engine as _rq_engine
        run_requote_migration(_rq_engine)
        logger.info("Requote campaign tables migrated")
    except Exception as e:
        logger.warning(f"Requote migration: {e}")

    # Leads + round-robin tables
    try:
        from app.migrations.leads_migration import migrate_leads
        migrate_leads()
        logger.info("Leads tables migrated")
    except Exception as e:
        logger.warning(f"Leads migration: {e}")

    # Sales records tables
    try:
        from app.migrations.sales_records_migration import migrate_sales_records
        migrate_sales_records()
        logger.info("Sales records tables migrated")
    except Exception as e:
        logger.warning(f"Sales records migration: {e}")

    # Commission tracker tables
    try:
        from app.migrations.commission_tracker_migration import run_commission_tracker_migration
        from app.core.database import engine as _ct_engine
        run_commission_tracker_migration(_ct_engine)
        logger.info("Commission tracker tables migrated")
    except Exception as e:
        logger.warning(f"Commission tracker migration: {e}")

    try:
        from app.migrations.renewal_survey_migration import run_migration as run_renewal_survey_migration
        from app.core.database import engine as _rs_engine
        run_renewal_survey_migration(_rs_engine)
        logger.info("Renewal survey tables migrated")
    except Exception as e:
        logger.warning(f"Renewal survey migration: {e}")

    # Ensure Bamboo carrier exists in AgencyConfig for dropdowns
    try:
        from app.core.database import SessionLocal as _ac_sl
        from app.models.agency_config import AgencyConfig
        _ac_db = _ac_sl()
        existing = _ac_db.query(AgencyConfig).filter(
            AgencyConfig.config_type == "carrier", AgencyConfig.name == "bamboo"
        ).first()
        if not existing:
            _ac_db.add(AgencyConfig(config_type="carrier", name="bamboo", display_name="Bamboo Insurance", is_active=True))
            _ac_db.commit()
            logger.info("Seeded Bamboo Insurance carrier")
        _ac_db.close()
    except Exception as e:
        logger.debug(f"Bamboo carrier seed: {e}")

    # Self-healing: create daily_checklist_items table
    try:
        from sqlalchemy import text as _ck_text
        from app.core.database import engine as _ck_engine
        with _ck_engine.connect() as conn:
            conn.execute(_ck_text("""CREATE TABLE IF NOT EXISTS daily_checklist_items (
                id SERIAL PRIMARY KEY,
                check_date DATE NOT NULL DEFAULT CURRENT_DATE,
                item_key VARCHAR NOT NULL,
                completed BOOLEAN DEFAULT FALSE,
                completed_by VARCHAR,
                completed_at TIMESTAMP,
                notes VARCHAR
            )"""))
            conn.commit()
        logger.info("daily_checklist_items table ready")
    except Exception as e:
        logger.warning(f"Checklist migration: {e}")

    # Self-healing: add missing FK indexes for query performance
    try:
        from sqlalchemy import text as _idx_text, inspect as _idx_inspect
        from app.core.database import engine as _idx_engine
        inspector = _idx_inspect(_idx_engine)
        
        # List of (table, column) pairs that have FKs but no index
        fk_indexes = [
            ("requote_leads", "producer_id"),
            ("chat_channels", "created_by"),
            ("chat_messages", "reply_to_id"),
            ("email_templates", "sent_by_id"),
            ("email_drafts", "created_by_id"),
            ("payroll_runs", "submitted_by_id"),
            ("reshop_activities", "user_id"),
            ("outbound_queue", "inbound_email_id"),
            ("tasks", "assigned_to_id"),
            ("timeclock_entries", "excused_by"),
        ]
        
        with _idx_engine.connect() as conn:
            for table, column in fk_indexes:
                if not inspector.has_table(table):
                    continue
                idx_name = f"ix_{table}_{column}"
                existing_indexes = {idx['name'] for idx in inspector.get_indexes(table)}
                if idx_name not in existing_indexes:
                    try:
                        conn.execute(_idx_text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})"))
                        conn.commit()
                        logger.info(f"Created index {idx_name}")
                    except Exception as ie:
                        logger.debug(f"Index {idx_name}: {ie}")
    except Exception as e:
        logger.warning(f"FK index migration: {e}")

    # Self-healing: add PDF storage columns to sales table if missing
    try:
        from sqlalchemy import text as sa_text, inspect as sa_inspect
        from app.core.database import engine
        inspector = sa_inspect(engine)
        if "sales" in inspector.get_table_names():
            existing = [c["name"] for c in inspector.get_columns("sales")]
            with engine.begin() as conn:
                if "application_pdf_data" not in existing:
                    conn.execute(sa_text("ALTER TABLE sales ADD COLUMN application_pdf_data BYTEA"))
                    logger.info("✓ Added application_pdf_data column to sales")
                if "application_pdf_name" not in existing:
                    conn.execute(sa_text("ALTER TABLE sales ADD COLUMN application_pdf_name VARCHAR"))
                    logger.info("✓ Added application_pdf_name column to sales")
    except Exception as e:
        logger.warning(f"Sales PDF column migration: {e}")

    # Performance: add missing indexes on frequently-queried columns
    try:
        from sqlalchemy import text as _idx_text
        from app.core.database import engine as _idx_engine
        with _idx_engine.begin() as conn:
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS ix_sales_sale_date ON sales (sale_date)",
                "CREATE INDEX IF NOT EXISTS ix_sales_status ON sales (status)",
                "CREATE INDEX IF NOT EXISTS ix_sales_commission_status ON sales (commission_status)",
                "CREATE INDEX IF NOT EXISTS ix_statement_lines_policy ON statement_lines (policy_number)",
                "CREATE INDEX IF NOT EXISTS ix_statement_imports_period ON statement_imports (statement_period)",
                "CREATE INDEX IF NOT EXISTS ix_requote_leads_campaign ON requote_leads (campaign_id)",
                "CREATE INDEX IF NOT EXISTS ix_requote_leads_status ON requote_leads (status)",
                "CREATE INDEX IF NOT EXISTS ix_requote_leads_t1_sched ON requote_leads (touch1_scheduled_date)",
                "CREATE INDEX IF NOT EXISTS ix_inbound_emails_status ON inbound_emails (processing_status)",
                "CREATE INDEX IF NOT EXISTS ix_customer_policies_status ON customer_policies (status)",
            ]:
                try:
                    conn.execute(_idx_text(idx_sql))
                except Exception:
                    pass  # Index may already exist
        logger.info("✓ Performance indexes verified")
    except Exception as e:
        logger.warning(f"Index migration: {e}")
    except Exception as e:
        logger.warning(f"Sales PDF column migration: {e}")

    # Fix corrupt timestamps (year > 9999 crashes PostgreSQL)
    try:
        from sqlalchemy import text as _ts_text
        from app.core.database import engine as _ts_engine
        with _ts_engine.connect() as conn:
            for col in ["sale_date", "effective_date", "created_at"]:
                r = conn.execute(_ts_text(f"""
                    UPDATE sales SET {col} = '2026-01-01'
                    WHERE {col} > '2099-12-31' OR {col} < '2000-01-01'
                """))
                if r.rowcount > 0:
                    logger.warning(f"Fixed {r.rowcount} corrupt {col} timestamps in sales table")
            conn.commit()
    except Exception as e:
        logger.warning(f"Timestamp fix: {e}")

    # Mark all sales before Jan 2026 as premium paid (pre-2026 sales)
    try:
        from sqlalchemy import text as sa_text
        from app.core.database import engine
        with engine.connect() as conn:
            r = conn.execute(sa_text(
                "UPDATE sales SET commission_status = 'paid' "
                "WHERE commission_status != 'paid' "
                "AND sale_date < '2026-01-01'"
            ))
            conn.commit()
            if r.rowcount > 0:
                logger.info(f"Marked {r.rowcount} pre-2026 sales as premium paid")
    except Exception as e:
        logger.warning(f"Pre-2026 paid update: {e}")

    # Start background follow-up checker (runs every 6 hours)
    import asyncio
    import threading
    import gc

    def _run_followups():
        """Run follow-up checks periodically."""
        import time
        time.sleep(30)  # Wait for app to fully start
        while True:
            try:
                from app.core.database import SessionLocal
                from app.api.quotes import _check_followups_logic
                db = SessionLocal()
                try:
                    result = _check_followups_logic(db)
                    if any(v > 0 for v in result.values()):
                        logger.info(f"Follow-up check results: {result}")
                except Exception as e:
                    logger.error(f"Follow-up check error: {e}")
                finally:
                    db.close()
                gc.collect()
            except Exception as e:
                logger.error(f"Follow-up scheduler error: {e}")
            time.sleep(6 * 3600)  # Every 6 hours

    followup_thread = threading.Thread(target=_run_followups, daemon=True)
    followup_thread.start()
    logger.info("Background follow-up scheduler started (every 6 hours)")

    # Start NowCerts auto-sync (runs twice daily — 6 AM and 6 PM CT)
    def _run_nowcerts_sync():
        """Sync all customers/policies from NowCerts twice daily."""
        import time
        time.sleep(120)  # Wait 2 min for app to fully start
        while True:
            try:
                from datetime import datetime
                now = datetime.utcnow()
                # Run at ~12:00 UTC (6 AM CT) and ~00:00 UTC (6 PM CT)
                hour = now.hour
                if hour in (0, 12):
                    logger.info("Starting scheduled NowCerts sync...")
                    from app.core.database import SessionLocal
                    from app.api.customers import sync_all_customers_internal
                    db = SessionLocal()
                    try:
                        result = sync_all_customers_internal(db)
                        logger.info(f"NowCerts sync complete: {result}")
                    except Exception as e:
                        logger.error(f"NowCerts sync error: {e}")
                    finally:
                        db.close()

                    # Run proactive reshop scan after sync completes
                    logger.info("Running post-sync reshop detection...")
                    db2 = SessionLocal()
                    try:
                        from app.api.reshop import _run_proactive_scan
                        scan_result = _run_proactive_scan(db2)
                        logger.info(f"Reshop scan complete: {scan_result}")
                    except Exception as e:
                        logger.error(f"Reshop scan error: {e}")
                    finally:
                        db2.close()
                    # Free memory after heavy sync
                    gc.collect()
            except Exception as e:
                logger.error(f"NowCerts sync scheduler error: {e}")
            time.sleep(3600)  # Check every hour

    sync_thread = threading.Thread(target=_run_nowcerts_sync, daemon=True)
    sync_thread.start()
    logger.info("NowCerts auto-sync scheduler started (twice daily: 6 AM / 6 PM CT)")

    # Daily agency snapshot (captures growth metrics once per day at ~7 AM CT)
    def _run_daily_snapshot():
        """Capture agency metrics snapshot daily for growth tracking."""
        import time
        time.sleep(300)  # Wait 5 min for app + sync to settle
        while True:
            try:
                from datetime import datetime
                now = datetime.utcnow()
                ct_hour = (now.hour - 6) % 24  # UTC → CT
                if ct_hour == 7:  # 7 AM CT
                    from app.core.database import SessionLocal
                    from app.models.agency_snapshot import AgencySnapshot
                    from app.models.customer import Customer, CustomerPolicy
                    from sqlalchemy import distinct, func as sqlfunc
                    from decimal import Decimal
                    from datetime import date

                    sdb = SessionLocal()
                    try:
                        today = date.today()
                        existing = sdb.query(AgencySnapshot).filter(AgencySnapshot.snapshot_date == today).first()
                        if not existing:
                            total_cust = sdb.query(sqlfunc.count(Customer.id)).scalar() or 0
                            active_subq = (
                                sdb.query(distinct(CustomerPolicy.customer_id))
                                .filter(sqlfunc.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"]))
                                .subquery()
                            )
                            active_cust = sdb.query(sqlfunc.count()).select_from(active_subq).scalar() or 0
                            active_pol = sdb.query(sqlfunc.count(CustomerPolicy.id)).filter(
                                sqlfunc.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"])
                            ).scalar() or 0
                            total_pol = sdb.query(sqlfunc.count(CustomerPolicy.id)).scalar() or 0

                            # Premium calculation via SQL (don't load all policies into memory)
                            from sqlalchemy import text as _snap_text, case
                            prem_result = sdb.execute(_snap_text("""
                                SELECT COALESCE(SUM(
                                    CASE
                                        WHEN (LOWER(line_of_business) LIKE '%auto%' OR LOWER(policy_type) LIKE '%auto%'
                                              OR LOWER(line_of_business) LIKE '%vehicle%' OR LOWER(policy_type) LIKE '%vehicle%')
                                             AND effective_date IS NOT NULL AND expiration_date IS NOT NULL
                                             AND (expiration_date - effective_date) BETWEEN 150 AND 200
                                        THEN premium * 2
                                        ELSE premium
                                    END
                                ), 0)
                                FROM customer_policies
                                WHERE LOWER(status) IN ('active', 'in force', 'inforce')
                                AND premium IS NOT NULL
                            """)).scalar()
                            total_prem = float(prem_result or 0)

                            snap = AgencySnapshot(
                                snapshot_date=today, period=today.strftime("%Y-%m"),
                                active_customers=active_cust, total_customers=total_cust,
                                active_policies=active_pol, total_policies=total_pol,
                                active_premium_annualized=float(total_prem),
                            )
                            sdb.add(snap)
                            sdb.commit()
                            logger.info(f"📊 Daily snapshot captured: {active_cust} active customers, ${float(total_prem):,.0f} premium")
                    finally:
                        sdb.close()
            except Exception as e:
                logger.error(f"Daily snapshot error: {e}")
            time.sleep(3600)  # Check every hour

    snapshot_thread = threading.Thread(target=_run_daily_snapshot, daemon=True)
    snapshot_thread.start()
    logger.info("Daily agency snapshot scheduler started")

    # Daily Sales Recap Email — 8 PM CST (2 AM UTC next day, or 1 AM UTC during CDT)
    def _run_daily_recap():
        """Send daily sales recap email at 8 PM Central Time."""
        import time
        from datetime import datetime, timedelta
        import pytz

        time.sleep(120)  # Wait 2 min for app to start
        central = pytz.timezone("America/Chicago")
        last_sent_date = None

        while True:
            try:
                now_ct = datetime.now(central)
                today_ct = now_ct.date()

                # Send at 8 PM CT if not already sent today
                if now_ct.hour >= 20 and last_sent_date != today_ct:
                    logger.info("🕗 Sending daily sales recap email...")
                    from app.services.daily_recap_email import send_daily_recap
                    from app.core.database import SessionLocal
                    rdb = SessionLocal()
                    try:
                        result = send_daily_recap(rdb, today_ct)
                        logger.info(f"Daily recap result: {result}")
                        last_sent_date = today_ct
                    finally:
                        rdb.close()
            except Exception as e:
                logger.error(f"Daily recap scheduler error: {e}")
            time.sleep(600)  # Check every 10 minutes

    recap_thread = threading.Thread(target=_run_daily_recap, daemon=True)
    recap_thread.start()
    logger.info("Daily sales recap scheduler started (8 PM CT)")

    # Daily Reshop Digest — 8:30 AM CT Monday-Friday
    def _run_reshop_digest():
        """Send daily reshop pipeline digest to retention agents."""
        import time
        from datetime import datetime
        import pytz

        time.sleep(180)  # Wait 3 min for app to start
        central = pytz.timezone("America/Chicago")
        last_sent_date = None

        while True:
            try:
                now_ct = datetime.now(central)
                today_ct = now_ct.date()

                # Send at 8:20 AM CT, Monday-Friday only
                if (now_ct.hour == 8 and now_ct.minute >= 20 and
                        now_ct.weekday() < 5 and last_sent_date != today_ct):
                    logger.info("📋 Sending daily reshop digest emails...")
                    from app.services.reshop_digest import send_reshop_digests
                    from app.core.database import SessionLocal
                    rdb = SessionLocal()
                    try:
                        result = send_reshop_digests(rdb, today_ct)
                        logger.info(f"Reshop digest result: {result}")
                        last_sent_date = today_ct
                    finally:
                        rdb.close()
            except Exception as e:
                logger.error(f"Reshop digest scheduler error: {e}")
            time.sleep(300)  # Check every 5 minutes

    reshop_digest_thread = threading.Thread(target=_run_reshop_digest, daemon=True)
    reshop_digest_thread.start()
    logger.info("Daily reshop digest scheduler started (8:20 AM CT, Mon-Fri)")

    # Daily Proactive Reshop Scan — 7 AM CT Monday-Friday (before digest at 8:30)
    def _run_reshop_scan():
        """Automatically scan for upcoming renewals and auto-assign agents."""
        import time
        from datetime import datetime
        import pytz

        time.sleep(240)  # Wait 4 min for app to start
        central = pytz.timezone("America/Chicago")
        last_scan_date = None

        while True:
            try:
                now_ct = datetime.now(central)
                today_ct = now_ct.date()

                # Run at 7 AM CT, Monday-Friday only
                if (now_ct.hour == 7 and now_ct.minute >= 0 and
                        now_ct.weekday() < 5 and last_scan_date != today_ct):
                    logger.info("🔍 Running daily proactive reshop scan...")
                    from app.api.reshop import _run_proactive_scan
                    from app.core.database import SessionLocal
                    rdb = SessionLocal()
                    try:
                        result = _run_proactive_scan(
                            rdb,
                            days_out=60,
                            increase_threshold=10.0,
                            min_annual_premium=2000.0,
                            actor_name="ORBIT Auto-Scan",
                        )
                        logger.info("Reshop scan result: %s", result)
                        last_scan_date = today_ct
                    finally:
                        rdb.close()
            except Exception as e:
                logger.error("Reshop scan scheduler error: %s", e)
            time.sleep(300)  # Check every 5 minutes

    reshop_scan_thread = threading.Thread(target=_run_reshop_scan, daemon=True)
    reshop_scan_thread.start()
    logger.info("Daily reshop scan scheduler started (7 AM CT, Mon-Fri)")

    # Monthly Report Auto-Email — 1st of each month at 9 AM CT
    def _run_monthly_report():
        """Auto-send monthly agency report on the 1st of each month."""
        import time
        from datetime import datetime
        import pytz

        time.sleep(300)  # Wait 5 min for app to start
        central = pytz.timezone("America/Chicago")
        last_sent_month = None

        while True:
            try:
                now_ct = datetime.now(central)
                current_month = (now_ct.year, now_ct.month)

                # Send on the 1st at 9 AM CT
                if (now_ct.day == 1 and now_ct.hour >= 9 and
                        last_sent_month != current_month):
                    # Report for LAST month
                    if now_ct.month == 1:
                        report_year = now_ct.year - 1
                        report_month = 12
                    else:
                        report_year = now_ct.year
                        report_month = now_ct.month - 1

                    logger.info("Sending monthly report for %d-%02d...", report_year, report_month)
                    from app.services.monthly_report import send_monthly_report_email
                    from app.core.database import SessionLocal
                    rdb = SessionLocal()
                    try:
                        result = send_monthly_report_email(rdb, report_year, report_month)
                        logger.info("Monthly report result: %s", result)
                        last_sent_month = current_month
                    finally:
                        rdb.close()
            except Exception as e:
                logger.error("Monthly report scheduler error: %s", e)
            time.sleep(600)  # Check every 10 minutes

    report_thread = threading.Thread(target=_run_monthly_report, daemon=True)
    report_thread.start()
    logger.info("Monthly report scheduler started (1st of month, 9 AM CT)")

    # Start NowCerts Pending Cancellation Poller (every 4 hours)
    def _run_pending_cancel_poll():
        """Poll NowCerts for pending cancellations and trigger non-pay emails."""
        import time
        time.sleep(180)  # Wait 3 min for app to fully start + initial sync
        while True:
            try:
                from app.services.nowcerts_cancellation_poller import run_scheduled_poll, POLL_ENABLED
                if POLL_ENABLED:
                    logger.info("Running NowCerts pending cancellation poll...")
                    run_scheduled_poll()
            except Exception as e:
                logger.error(f"NowCerts pending cancel poll scheduler error: {e}")
            time.sleep(4 * 3600)  # Every 4 hours

    cancel_poll_thread = threading.Thread(target=_run_pending_cancel_poll, daemon=True)
    cancel_poll_thread.start()
    logger.info("NowCerts pending cancellation poller scheduler started (every 4 hours)")

    # ── Auto-send campaign emails (every 5 minutes) ──
    def _run_campaign_sender():
        """Automatically send due campaign emails in batches for all active campaigns."""
        import time
        time.sleep(90)  # Wait 90s for app to fully start
        while True:
            try:
                from app.core.database import SessionLocal
                from app.api.requote_campaigns import RequoteCampaign, RequoteLead, _requote_email_html, _send_campaign_email, GlobalOptOut
                from sqlalchemy import and_, or_
                from datetime import datetime

                db = SessionLocal()
                try:
                    now = datetime.utcnow()
                    active_campaigns = db.query(RequoteCampaign).filter(
                        RequoteCampaign.status == "active"
                    ).all()

                    if not active_campaigns:
                        db.close()
                        time.sleep(300)
                        continue

                    total_sent = 0
                    total_errors = 0
                    BATCH_PER_CAMPAIGN = 15  # Send up to 15 per campaign per cycle

                    for campaign in active_campaigns:
                        if total_sent >= 50:  # Global cap per cycle to stay within API limits
                            break

                        # Touch 1
                        touch1_due = db.query(RequoteLead).filter(
                            RequoteLead.campaign_id == campaign.id,
                            RequoteLead.is_current_customer == False,
                            RequoteLead.opted_out == False,
                            RequoteLead.touch1_sent == False,
                            RequoteLead.touch1_scheduled_date != None,
                            RequoteLead.touch1_scheduled_date <= now,
                            RequoteLead.email != None,
                        ).limit(BATCH_PER_CAMPAIGN).all()

                        for lead in touch1_due:
                            if total_sent >= 50:
                                break
                            try:
                                x_date_str = lead.x_date.strftime('%B %d, %Y') if lead.x_date else "soon"
                                unsub_url = f"https://better-choice-api.onrender.com/api/campaigns/unsubscribe/{lead.unsubscribe_token}"
                                retarget_round = getattr(lead, 'retarget_round', 0) or 0
                                subject, html = _requote_email_html(
                                    lead.first_name or "Valued Customer",
                                    lead.policy_type, lead.carrier, x_date_str, 1, unsub_url,
                                    retarget_round=retarget_round,
                                    city=lead.city or "", state=lead.state or "",
                                    premium=float(lead.premium) if lead.premium else None,
                                    last_name=lead.last_name or "", email=lead.email or "",
                                    phone=lead.phone or "", address=lead.address or "", zip_code=lead.zip_code or "",
                                )
                                if _send_campaign_email(lead.email, subject, html):
                                    lead.touch1_sent = True
                                    lead.touch1_sent_at = now
                                    lead.status = "touch1_sent"
                                    total_sent += 1
                                else:
                                    total_errors += 1
                            except Exception as e:
                                logger.error(f"Campaign sender touch1 error lead {lead.id}: {e}")
                                total_errors += 1

                        # Touch 2
                        touch2_due = db.query(RequoteLead).filter(
                            RequoteLead.campaign_id == campaign.id,
                            RequoteLead.is_current_customer == False,
                            RequoteLead.opted_out == False,
                            RequoteLead.touch1_sent == True,
                            RequoteLead.touch2_sent == False,
                            RequoteLead.touch2_scheduled_date != None,
                            RequoteLead.touch2_scheduled_date <= now,
                            RequoteLead.email != None,
                        ).limit(BATCH_PER_CAMPAIGN).all()

                        for lead in touch2_due:
                            if total_sent >= 50:
                                break
                            try:
                                x_date_str = lead.x_date.strftime('%B %d, %Y') if lead.x_date else "soon"
                                unsub_url = f"https://better-choice-api.onrender.com/api/campaigns/unsubscribe/{lead.unsubscribe_token}"
                                retarget_round = getattr(lead, 'retarget_round', 0) or 0
                                subject, html = _requote_email_html(
                                    lead.first_name or "Valued Customer",
                                    lead.policy_type, lead.carrier, x_date_str, 2, unsub_url,
                                    retarget_round=retarget_round,
                                    city=lead.city or "", state=lead.state or "",
                                    premium=float(lead.premium) if lead.premium else None,
                                    last_name=lead.last_name or "", email=lead.email or "",
                                    phone=lead.phone or "", address=lead.address or "", zip_code=lead.zip_code or "",
                                )
                                if _send_campaign_email(lead.email, subject, html):
                                    lead.touch2_sent = True
                                    lead.touch2_sent_at = now
                                    lead.status = "touch2_sent"
                                    total_sent += 1
                                else:
                                    total_errors += 1
                            except Exception as e:
                                logger.error(f"Campaign sender touch2 error lead {lead.id}: {e}")
                                total_errors += 1

                        # Touch 3
                        touch3_due = db.query(RequoteLead).filter(
                            RequoteLead.campaign_id == campaign.id,
                            RequoteLead.is_current_customer == False,
                            RequoteLead.opted_out == False,
                            RequoteLead.touch2_sent == True,
                            RequoteLead.touch3_sent == False,
                            RequoteLead.touch3_scheduled_date != None,
                            RequoteLead.touch3_scheduled_date <= now,
                            RequoteLead.email != None,
                        ).limit(BATCH_PER_CAMPAIGN).all()

                        for lead in touch3_due:
                            if total_sent >= 50:
                                break
                            try:
                                x_date_str = lead.x_date.strftime('%B %d, %Y') if lead.x_date else "soon"
                                unsub_url = f"https://better-choice-api.onrender.com/api/campaigns/unsubscribe/{lead.unsubscribe_token}"
                                retarget_round = getattr(lead, 'retarget_round', 0) or 0
                                subject, html = _requote_email_html(
                                    lead.first_name or "Valued Customer",
                                    lead.policy_type, lead.carrier, x_date_str, 3, unsub_url,
                                    retarget_round=retarget_round,
                                    city=lead.city or "", state=lead.state or "",
                                    premium=float(lead.premium) if lead.premium else None,
                                    last_name=lead.last_name or "", email=lead.email or "",
                                    phone=lead.phone or "", address=lead.address or "", zip_code=lead.zip_code or "",
                                )
                                if _send_campaign_email(lead.email, subject, html):
                                    lead.touch3_sent = True
                                    lead.touch3_sent_at = now
                                    lead.status = "touch3_sent"
                                    total_sent += 1
                                else:
                                    total_errors += 1
                            except Exception as e:
                                logger.error(f"Campaign sender touch3 error lead {lead.id}: {e}")
                                total_errors += 1

                        # Update campaign email count
                        campaign.emails_sent = db.query(RequoteLead).filter(
                            RequoteLead.campaign_id == campaign.id,
                            or_(RequoteLead.touch1_sent == True, RequoteLead.touch2_sent == True, RequoteLead.touch3_sent == True),
                        ).count()

                    db.commit()
                    if total_sent > 0:
                        logger.info(f"Campaign auto-sender: sent {total_sent} emails, {total_errors} errors across {len(active_campaigns)} active campaigns")
                except Exception as e:
                    logger.error(f"Campaign sender error: {e}")
                    db.rollback()
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Campaign sender scheduler error: {e}")
            time.sleep(300)  # Every 5 minutes

    campaign_sender_thread = threading.Thread(target=_run_campaign_sender, daemon=True)
    campaign_sender_thread.start()
    logger.info("Campaign auto-sender started (every 5 min, 50 emails/cycle, 15/campaign)")

    # ── Life Cross-Sell Campaign Auto-Sender ──────────────────────────
    def _run_life_campaign_sender():
        import time
        time.sleep(180)
        while True:
            try:
                from datetime import datetime, timedelta
                now = datetime.utcnow()
                if now.hour == 16:  # 10 AM CT
                    logger.info("Running life cross-sell campaign auto-sender...")
                    from app.core.database import SessionLocal
                    from app.models.life_campaign import LifeCrossSellContact
                    from app.services.life_crosssell_campaign import (
                        TOUCH_BUILDERS, TOUCH_DELAYS, RECURRING_INTERVAL_DAYS,
                        build_touch_seasonal, build_touch_milestone, build_touch_value,
                        send_life_crosssell_email,
                    )
                    db = SessionLocal()
                    try:
                        pending = db.query(LifeCrossSellContact).filter(
                            LifeCrossSellContact.status == "active",
                            LifeCrossSellContact.next_touch_date <= now,
                        ).all()
                        sent = 0
                        for contact in pending:
                            try:
                                tn = contact.touch_number + 1
                                fn = (contact.customer_name or "").split()[0] if contact.customer_name else "there"
                                pt = contact.source_policy_type or ""
                                if tn <= 4:
                                    builder = TOUCH_BUILDERS.get(tn)
                                    if not builder:
                                        continue
                                    if tn == 2:
                                        subj, html = builder(fn, "", 0, contact.id, pt)
                                    else:
                                        subj, html = builder(fn, "", contact.id, pt)
                                else:
                                    cycle = (tn - 5) % 3
                                    if cycle == 0:
                                        subj, html = build_touch_seasonal(fn, "", contact.id, pt)
                                    elif cycle == 1:
                                        mo = max(1, int((now - contact.created_at).days / 30)) if contact.created_at else 6
                                        subj, html = build_touch_milestone(fn, contact.id, pt, mo)
                                    else:
                                        subj, html = build_touch_value(fn, contact.id, pt, (tn - 5) // 3)
                                result = send_life_crosssell_email(contact.customer_email, subj, html)
                                if result.get("success"):
                                    if tn <= 4:
                                        setattr(contact, f"touch{tn}_sent_at", now)
                                    contact.touch_number = tn
                                    contact.next_touch_date = now + timedelta(days=TOUCH_DELAYS.get(tn + 1, RECURRING_INTERVAL_DAYS))
                                    sent += 1
                            except Exception as e:
                                logger.error(f"Life send error {contact.customer_email}: {e}")
                        db.commit()
                        if sent:
                            logger.info(f"Life campaign: sent {sent}/{len(pending)} emails")
                    finally:
                        db.close()
                        gc.collect()
            except Exception as e:
                logger.error(f"Life campaign sender error: {e}")
            time.sleep(3600)

    life_thread = threading.Thread(target=_run_life_campaign_sender, daemon=True)
    life_thread.start()
    logger.info("Life cross-sell campaign auto-sender started (daily 10 AM CT)")


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
    sse_loaded = False
    try:
        from app.api.events import event_bus
        sse_loaded = True
    except Exception:
        pass
    return {"status": "healthy", "service": "better-choice-insurance-api", "version": "1.0.3", "build": "2026-03-23T15:30:00Z", "sse": sse_loaded}


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

    # Ensure is_renewal_term column on statement_lines
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE statement_lines ADD COLUMN is_renewal_term BOOLEAN"))
            conn.commit()
        results.append("OK: Added statement_lines.is_renewal_term")
    except Exception as e:
        results.append(f"SKIP statement_lines.is_renewal_term: {str(e)[:80]}")

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
app.include_router(renewals_api.router)
app.include_router(quotes_api.router)
app.include_router(non_renewal_api.router)
app.include_router(retell_api.router)
app.include_router(mia_bypass_api.router)
app.include_router(sms_api.router)
app.include_router(cancellation_api.router)
app.include_router(nowcerts_poll_api.router)
app.include_router(inspection_api.router)

from app.api import life_crosssell as life_crosssell_api
app.include_router(life_crosssell_api.router, prefix="/api")

# Life cross-sell campaign table
try:
    from sqlalchemy import inspect as _life_inspect
    _life_insp = _life_inspect(engine)
    if "life_crosssell_contacts" not in _life_insp.get_table_names():
        from app.models.life_campaign import LifeCrossSellContact
        LifeCrossSellContact.__table__.create(engine)
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

from app.api import renewal_survey as renewal_survey_api
app.include_router(renewal_survey_api.router)
