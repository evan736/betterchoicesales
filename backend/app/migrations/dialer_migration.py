"""
Self-healing migration for dialer tables.
Adds new columns to existing dialer_leads table.
"""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def _add_col(conn, table, column, col_type, default=None):
    try:
        dflt = f" DEFAULT {default}" if default is not None else ""
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}{dflt}"))
    except Exception as e:
        logger.debug(f"Column {table}.{column}: {e}")


def migrate_dialer():
    with engine.begin() as conn:
        # Add new columns to dialer_leads
        _add_col(conn, "dialer_leads", "insurance_exp", "TIMESTAMP")
        _add_col(conn, "dialer_leads", "state", "VARCHAR")
        _add_col(conn, "dialer_leads", "city", "VARCHAR")
        _add_col(conn, "dialer_leads", "dob", "VARCHAR")

        # Create dialer_phone_numbers if not exists
        result = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='dialer_phone_numbers'"
        ))
        if not list(result):
            conn.execute(text("""
                CREATE TABLE dialer_phone_numbers (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR UNIQUE NOT NULL,
                    status VARCHAR DEFAULT 'active',
                    first_used_date TIMESTAMP,
                    rest_until TIMESTAMP,
                    total_calls INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            # Seed existing 5 SA numbers
            for num in ['+12108649246', '+12109886575', '+12109344252', '+12108710493', '+12108791893']:
                conn.execute(text(
                    "INSERT INTO dialer_phone_numbers (phone, status) VALUES (:phone, 'active') ON CONFLICT (phone) DO NOTHING"
                ), {"phone": num})
            logger.info("Created dialer_phone_numbers table with 5 SA numbers")

        logger.info("Dialer tables migrated")
