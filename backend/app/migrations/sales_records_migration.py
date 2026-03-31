"""Self-healing migration for sales_records table."""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def migrate_sales_records():
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='sales_records'"
        ))
        if not result.fetchone():
            logger.info("Creating sales_records table...")
            conn.execute(text("""
                CREATE TABLE sales_records (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    record_type VARCHAR NOT NULL,
                    period_label VARCHAR NOT NULL,
                    premium NUMERIC(12,2) NOT NULL,
                    sale_count INTEGER NOT NULL,
                    previous_record_premium NUMERIC(12,2),
                    previous_record_count INTEGER,
                    previous_record_period VARCHAR,
                    notified VARCHAR DEFAULT 'pending',
                    notes TEXT
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sales_records_type ON sales_records(record_type)"))
            logger.info("sales_records table created.")
        else:
            logger.info("sales_records table exists.")
