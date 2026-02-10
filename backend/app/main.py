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

    # Run enum migrations first (create_all can't modify existing enums)
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    -- Add new carrier types
                    ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'grange';
                    ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'safeco';
                    ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'travelers';
                    ALTER TYPE carriertype ADD VALUE IF NOT EXISTS 'hartford';
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
            conn.execute(text("""
                DO $$
                BEGIN
                    ALTER TYPE statementstatus ADD VALUE IF NOT EXISTS 'processed';
                    ALTER TYPE statementstatus ADD VALUE IF NOT EXISTS 'reconciled';
                    ALTER TYPE statementstatus ADD VALUE IF NOT EXISTS 'approved';
                EXCEPTION WHEN others THEN NULL;
                END $$;
            """))
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
            conn.commit()
            logger.info("Enum migrations applied")
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
