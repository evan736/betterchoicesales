import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth, sales, commissions, statements

logger = logging.getLogger(__name__)


def init_database():
    """Initialize database tables and seed data on startup."""
    from app.core.database import engine, Base, SessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole
    from app.models.commission import CommissionTier
    from decimal import Decimal

    logger.info("Creating database tables...")
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
            {"tier_level": 1, "min_written_premium": Decimal("0"), "max_written_premium": Decimal("50000"), "commission_rate": Decimal("0.10"), "description": "Tier 1: 0-50K written premium, 10% commission"},
            {"tier_level": 2, "min_written_premium": Decimal("50001"), "max_written_premium": Decimal("100000"), "commission_rate": Decimal("0.125"), "description": "Tier 2: 50K-100K written premium, 12.5% commission"},
            {"tier_level": 3, "min_written_premium": Decimal("100001"), "max_written_premium": None, "commission_rate": Decimal("0.15"), "description": "Tier 3: 100K+ written premium, 15% commission"},
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


app = FastAPI(
    title=settings.APP_NAME,
    description="Better Choice Insurance - Sales Tracking API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Render frontend URL + local dev
allowed_origins = [
    "http://localhost:3000",
    "http://frontend:3000",
]
frontend_url = os.environ.get("FRONTEND_URL", "")
if frontend_url:
    allowed_origins.append(frontend_url)
    # Also allow without trailing slash and with https
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
