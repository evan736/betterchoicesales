import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth, sales, commissions, statements, analytics

logger = logging.getLogger(__name__)


def init_database():
    """Initialize database tables and seed data on startup."""
    from app.core.database import engine, Base, SessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole
    from app.models.commission import CommissionTier
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
        except Exception as e:
            logger.warning(f"Enum migration warning (may be OK): {e}")

    Base.metadata.create_all(bind=engine)
    logger.info("Tables created successfully")

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
                role=UserRole.ADMIN,
                is_superuser=True,
                producer_code="ADMIN001",
            )
            db.add(admin)
            logger.info("Admin user created")

        producer = db.query(User).filter(User.username == "producer1").first()
        if not producer:
            producer = User(
                email="producer@insurance.com",
                username="producer1",
                full_name="John Producer",
                hashed_password=get_password_hash("producer123"),
                role=UserRole.PRODUCER,
                producer_code="PROD001",
            )
            db.add(producer)
            logger.info("Sample producer created")

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

# CORS — allow Render frontend URL + local dev
allowed_origins = [
    "http://localhost:3000",
    "http://frontend:3000",
]
frontend_url = os.environ.get("FRONTEND_URL", "")
if frontend_url:
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


@app.get("/")
def root():
    return {"message": "Better Choice Insurance API", "version": "1.0.0", "docs": "/docs"}


# Include routers
app.include_router(auth.router)
app.include_router(sales.router)
app.include_router(commissions.router)
app.include_router(statements.router)
app.include_router(analytics.router)
