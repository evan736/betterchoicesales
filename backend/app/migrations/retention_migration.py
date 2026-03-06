"""Self-healing migration for retention tracking tables."""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def run_retention_migration():
    """Create retention tables if they don't exist."""
    with engine.connect() as conn:
        # Check if tables exist and have correct schema
        result = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE tablename IN ('retention_records', 'retention_summaries')"
        ))
        existing = {row[0] for row in result}
        
        # Check if schema needs fixing (NUMERIC(5,2) -> NUMERIC(8,2))
        if "retention_records" in existing:
            col_check = conn.execute(text(
                "SELECT numeric_precision FROM information_schema.columns "
                "WHERE table_name='retention_records' AND column_name='premium_change_pct'"
            ))
            row = col_check.fetchone()
            if row and row[0] == 5:
                # Old schema — drop and recreate
                conn.execute(text("DROP TABLE IF EXISTS retention_records CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS retention_summaries CASCADE"))
                conn.commit()
                existing = set()

        if "retention_records" not in existing:
            conn.execute(text("""
                CREATE TABLE retention_records (
                    id SERIAL PRIMARY KEY,
                    policy_number VARCHAR NOT NULL,
                    insured_name VARCHAR,
                    carrier VARCHAR,
                    original_period VARCHAR NOT NULL,
                    original_premium NUMERIC(10,2),
                    expected_renewal_period VARCHAR,
                    term_months INTEGER DEFAULT 12,
                    outcome VARCHAR,
                    new_policy_number VARCHAR,
                    new_carrier VARCHAR,
                    new_premium NUMERIC(10,2),
                    customer_id INTEGER,
                    customer_name_normalized VARCHAR,
                    renewal_period VARCHAR,
                    renewal_premium NUMERIC(10,2),
                    premium_change NUMERIC(10,2),
                    premium_change_pct NUMERIC(8,2),
                    last_analyzed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ
                )
            """))
            conn.execute(text("CREATE INDEX idx_retention_policy ON retention_records(policy_number)"))
            conn.execute(text("CREATE INDEX idx_retention_period ON retention_records(original_period)"))
            conn.execute(text("CREATE INDEX idx_retention_outcome ON retention_records(outcome)"))
            conn.execute(text("CREATE INDEX idx_retention_name ON retention_records(customer_name_normalized)"))
            conn.execute(text("CREATE INDEX idx_retention_customer ON retention_records(customer_id)"))
            logger.info("Created retention_records table")

        if "retention_summaries" not in existing:
            conn.execute(text("""
                CREATE TABLE retention_summaries (
                    id SERIAL PRIMARY KEY,
                    period VARCHAR NOT NULL UNIQUE,
                    policies_up_for_renewal INTEGER DEFAULT 0,
                    policies_renewed INTEGER DEFAULT 0,
                    policies_carrier_moved INTEGER DEFAULT 0,
                    policies_rewritten INTEGER DEFAULT 0,
                    policies_lost INTEGER DEFAULT 0,
                    policies_pending INTEGER DEFAULT 0,
                    true_retention_rate NUMERIC(8,2),
                    policy_retention_rate NUMERIC(8,2),
                    original_total_premium NUMERIC(12,2),
                    renewed_total_premium NUMERIC(12,2),
                    lost_premium NUMERIC(12,2),
                    avg_premium_change_pct NUMERIC(8,2),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ
                )
            """))
            conn.execute(text("CREATE INDEX idx_retention_summary_period ON retention_summaries(period)"))
            logger.info("Created retention_summaries table")

        # Fix precision if table already exists with wrong precision
        try:
            conn.execute(text(
                "ALTER TABLE retention_records ALTER COLUMN premium_change_pct TYPE NUMERIC(8,2)"
            ))
            conn.execute(text(
                "ALTER TABLE retention_summaries ALTER COLUMN true_retention_rate TYPE NUMERIC(8,2)"
            ))
            conn.execute(text(
                "ALTER TABLE retention_summaries ALTER COLUMN policy_retention_rate TYPE NUMERIC(8,2)"
            ))
            conn.execute(text(
                "ALTER TABLE retention_summaries ALTER COLUMN avg_premium_change_pct TYPE NUMERIC(8,2)"
            ))
        except Exception:
            pass

        conn.commit()
        logger.info("Retention migration complete")
