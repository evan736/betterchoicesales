"""
Database initialization script
Run this to create tables and seed initial data
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import engine, Base, SessionLocal
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.commission import CommissionTier
from decimal import Decimal


def init_db():
    """Initialize database with tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created successfully")


def seed_data():
    """Seed initial data"""
    db = SessionLocal()
    
    try:
        print("\nSeeding initial data...")
        
        # Create admin user
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                email="admin@insurance.com",
                username="admin",
                full_name="System Administrator",
                hashed_password=get_password_hash("admin123"),
                role=UserRole.ADMIN,
                is_superuser=True,
                producer_code="ADMIN001"
            )
            db.add(admin)
            print("✓ Admin user created (username: admin, password: admin123)")
        
        # Create sample producer
        producer = db.query(User).filter(User.username == "producer1").first()
        if not producer:
            producer = User(
                email="producer@insurance.com",
                username="producer1",
                full_name="John Producer",
                hashed_password=get_password_hash("producer123"),
                role=UserRole.PRODUCER,
                producer_code="PROD001"
            )
            db.add(producer)
            print("✓ Sample producer created (username: producer1, password: producer123)")
        
        # Create commission tiers
        tiers = [
            {
                "tier_level": 1,
                "min_written_premium": Decimal("0"),
                "max_written_premium": Decimal("39999.99"),
                "commission_rate": Decimal("0.03"),
                "description": "Under 40K - 3%"
            },
            {
                "tier_level": 2,
                "min_written_premium": Decimal("40000"),
                "max_written_premium": Decimal("49999.99"),
                "commission_rate": Decimal("0.03"),
                "description": "40K - 3%"
            },
            {
                "tier_level": 3,
                "min_written_premium": Decimal("50000"),
                "max_written_premium": Decimal("59999.99"),
                "commission_rate": Decimal("0.04"),
                "description": "50K - 4%"
            },
            {
                "tier_level": 4,
                "min_written_premium": Decimal("60000"),
                "max_written_premium": Decimal("99999.99"),
                "commission_rate": Decimal("0.05"),
                "description": "60K - 5%"
            },
            {
                "tier_level": 5,
                "min_written_premium": Decimal("100000"),
                "max_written_premium": Decimal("149999.99"),
                "commission_rate": Decimal("0.06"),
                "description": "100K - 6%"
            },
            {
                "tier_level": 6,
                "min_written_premium": Decimal("150000"),
                "max_written_premium": Decimal("199999.99"),
                "commission_rate": Decimal("0.07"),
                "description": "150K - 7%"
            },
            {
                "tier_level": 7,
                "min_written_premium": Decimal("200000"),
                "max_written_premium": None,
                "commission_rate": Decimal("0.08"),
                "description": "200K+ - 8%"
            }
        ]
        
        for tier_data in tiers:
            existing = db.query(CommissionTier).filter(
                CommissionTier.tier_level == tier_data["tier_level"]
            ).first()
            
            if not existing:
                tier = CommissionTier(**tier_data)
                db.add(tier)
                print(f"✓ Created {tier_data['description']}")
        
        db.commit()
        print("\n✓ Database seeded successfully!")
        
    except Exception as e:
        print(f"\n✗ Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Insurance Agency OS - Database Initialization")
    print("=" * 60)
    
    init_db()
    seed_data()
    
    print("\n" + "=" * 60)
    print("Initialization complete!")
    print("=" * 60)
    print("\nYou can now access:")
    print("  - API: http://localhost:8000")
    print("  - API Docs: http://localhost:8000/docs")
    print("  - Frontend: http://localhost:3000")
    print("\nDefault credentials:")
    print("  Admin - username: admin, password: admin123")
    print("  Producer - username: producer1, password: producer123")
    print("=" * 60)
