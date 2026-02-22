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

        # ── Quotes: premium_term, notes, policy_lines columns ──
        for col_sql in [
            "ALTER TABLE quotes ADD COLUMN premium_term VARCHAR DEFAULT '6 months'",
            "ALTER TABLE quotes ADD COLUMN notes TEXT",
            "ALTER TABLE quotes ADD COLUMN policy_lines TEXT",
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
    """Run database init on startup."""
    init_database()
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
from fastapi.responses import JSONResponse
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

# Serve static files (temp PDFs for Thanks.io, etc.)
from fastapi.staticfiles import StaticFiles
from pathlib import Path
_static_dir = Path(__file__).parent.parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
(_static_dir / "temp-letters").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
