"""Self-healing migration for commission_expectations table."""
import logging
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def run_commission_tracker_migration(engine):
    """Create commission_expectations table if it doesn't exist."""
    inspector = inspect(engine)
    
    if "commission_expectations" not in inspector.get_table_names():
        logger.info("Creating commission_expectations table...")
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE commission_expectations (
                    id SERIAL PRIMARY KEY,
                    source_type VARCHAR NOT NULL,
                    source_id INTEGER,
                    policy_number VARCHAR NOT NULL,
                    customer_name VARCHAR NOT NULL,
                    carrier VARCHAR NOT NULL,
                    policy_type VARCHAR,
                    expected_premium NUMERIC(10,2),
                    expected_commission NUMERIC(10,2),
                    expected_commission_rate NUMERIC(5,4),
                    effective_date TIMESTAMP WITH TIME ZONE NOT NULL,
                    expected_payment_by TIMESTAMP WITH TIME ZONE,
                    status VARCHAR DEFAULT 'pending' NOT NULL,
                    matched_statement_line_id INTEGER REFERENCES statement_lines(id),
                    matched_amount NUMERIC(10,2),
                    matched_at TIMESTAMP WITH TIME ZONE,
                    flag_reason TEXT,
                    resolution_notes TEXT,
                    resolved_at TIMESTAMP WITH TIME ZONE,
                    resolved_by INTEGER REFERENCES users(id),
                    producer_id INTEGER REFERENCES users(id),
                    producer_name VARCHAR,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE
                )
            """))
            conn.execute(text("CREATE INDEX idx_ce_carrier ON commission_expectations(carrier)"))
            conn.execute(text("CREATE INDEX idx_ce_status ON commission_expectations(status)"))
            conn.execute(text("CREATE INDEX idx_ce_eff_date ON commission_expectations(effective_date)"))
            conn.execute(text("CREATE INDEX idx_ce_policy ON commission_expectations(policy_number)"))
            conn.execute(text("CREATE INDEX idx_ce_source ON commission_expectations(source_type)"))
        logger.info("✅ commission_expectations table created")
    else:
        logger.info("commission_expectations table already exists")
