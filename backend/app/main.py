import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth, sales, commissions, statements, analytics
from app.api import payroll as payroll_api
from app.api import retention as retention_api
from app.api import survey as survey_api
from app.api import admin as admin_api
from app.api import timeclock as timeclock_api
from app.api import customers as customers_api
from app.api import nonpay as nonpay_api
from app.api import uw_requirements as uw_api
from app.api import winback as winback_api
from app.api import renewals as renewals_api
from app.api import quotes as quotes_api
from app.api import non_renewal as non_renewal_api

logger = logging.getLogger(__name__)


def init_database():
    """Initialize database tables and seed data on startup."""
    from app.core.database import engine, Base, SessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole
    from app.models.commission import CommissionTier
    from app.models.timeclock import TimeClockEntry  # ensure table is created
    from app.models.nonpay import NonPayNotice, NonPayEmail  # ensure tables created
    from app.models.campaign import (  # ensure campaign tables created
        RenewalNotice, UWRequirement, WinBackCampaign,
        Quote, OnboardingCampaign, GHLWebhookLog
    )
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
        logger.info("Quotes columns verified")

    db = SessionLocal()
    try:
        # Create admin user if not exists
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                email="admin@insurance.com",
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
            {"tier_level": 1, "min_written_premium": Decimal("0"), "max_written_premium": Decimal("39999.99"), "commission_rate": Decimal("0.03"), "description": "Under 40K - 3%"},
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

        db.commit()
        logger.info("Database seeded successfully")
    except Exception as e:
        logger.error(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database init on startup + start background scheduler."""
    init_database()

    # Start background follow-up checker (runs every 6 hours)
    import asyncio
    import threading

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
            except Exception as e:
                logger.error(f"Follow-up scheduler error: {e}")
            time.sleep(6 * 3600)  # Every 6 hours

    followup_thread = threading.Thread(target=_run_followups, daemon=True)
    followup_thread.start()
    logger.info("Background follow-up scheduler started (every 6 hours)")

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

# CORS — allow Render frontend URL + local dev
allowed_origins = [
    "http://localhost:3000",
    "http://frontend:3000",
    "https://better-choice-web.onrender.com",
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


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "better-choice-insurance-api", "version": "1.0.0"}


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
    ]:
        try:
            with engine.connect() as conn:
                conn.execute(sa_text(col_sql))
                conn.commit()
            results.append(f"OK: {col_sql}")
        except Exception as e:
            results.append(f"SKIP: {str(e)[:80]}")
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
          Tap the button below to confirm and your advisor will reach out shortly to finalize everything.
        </p>
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

        <div style="margin-top:20px;">
          <a href="tel:8479085665" class="btn-outline">
            Can't wait? Call (847) 908-5665
          </a>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
async function confirmBind() {{
  const btn = document.getElementById('bindBtn');
  btn.textContent = 'Confirming...';
  btn.style.opacity = '0.6';
  btn.style.pointerEvents = 'none';
  try {{
    const resp = await fetch('/api/bind/{quote_id}/confirm', {{ method: 'POST' }});
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
def confirm_bind(quote_id: int):
    """Process bind confirmation — update quote status and alert the producer."""
    from app.core.database import SessionLocal
    from app.models.campaign import Quote as QuoteModel
    from app.models.user import User as UserModel
    from datetime import datetime
    import pytz

    db = SessionLocal()
    try:
        quote = db.query(QuoteModel).filter(QuoteModel.id == quote_id).first()
        if not quote:
            return {"ok": False}

        # Mark quote as bind-requested
        quote.status = "bind_requested"
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
        <tr><td style="color:#64748B;font-size:12px;padding:4px 0;">Phone</td><td style="color:#1e293b;text-align:right;padding:4px 0;">{quote.prospect_phone or 'N/A'}</td></tr>
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
            import requests as req
            if settings.MAILGUN_API_KEY and settings.MAILGUN_DOMAIN:
                req.post(
                    f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
                    auth=("api", settings.MAILGUN_API_KEY),
                    data={
                        "from": f"Better Choice Alerts <alerts@{settings.MAILGUN_DOMAIN}>",
                        "to": [producer_email, "evan@betterchoiceins.com"],
                        "subject": f"🔔 BIND REQUEST — {quote.prospect_name} wants {carrier_name} ({premium_str}/{term})",
                        "html": alert_html,
                    },
                )
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
