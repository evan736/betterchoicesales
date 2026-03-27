"""
Self-healing migration for leads table + round-robin assignment state.
Run on startup — creates tables if they don't exist.
"""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def _add_col(conn, table, column, col_type, default=None):
    """Safely add a column if it doesn't exist."""
    try:
        dflt = f" DEFAULT {default}" if default is not None else ""
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}{dflt}"))
    except Exception as e:
        logger.debug(f"Column {table}.{column}: {e}")


def migrate_leads():
    """Create leads table and round_robin_state if missing."""
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('leads','round_robin_state')"
        ))
        existing = {row[0] for row in result}

        if "leads" not in existing:
            logger.info("Creating leads table...")
            conn.execute(text("""
                CREATE TABLE leads (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ,
                    name VARCHAR NOT NULL,
                    phone VARCHAR NOT NULL,
                    email VARCHAR,
                    dob VARCHAR,
                    address VARCHAR,
                    city VARCHAR,
                    state VARCHAR,
                    zip_code VARCHAR,
                    policy_types VARCHAR,
                    current_carrier VARCHAR,
                    current_premium VARCHAR,
                    renewal_date VARCHAR,
                    message TEXT,
                    roof_year VARCHAR,
                    home_year VARCHAR,
                    sqft VARCHAR,
                    drivers_info TEXT,
                    vehicles_info TEXT,
                    source VARCHAR,
                    utm_campaign VARCHAR,
                    assigned_to_id INTEGER REFERENCES users(id),
                    assigned_to_name VARCHAR,
                    assigned_at TIMESTAMPTZ,
                    status VARCHAR DEFAULT 'new',
                    notes TEXT,
                    contacted_at TIMESTAMPTZ,
                    quoted_at TIMESTAMPTZ,
                    closed_at TIMESTAMPTZ,
                    is_duplicate BOOLEAN DEFAULT FALSE,
                    duplicate_of_id INTEGER
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_leads_assigned ON leads(assigned_to_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC)"))
            logger.info("leads table created.")
        else:
            # Add any new columns to existing table
            _add_col(conn, "leads", "dob", "VARCHAR")
            _add_col(conn, "leads", "drivers_info", "TEXT")
            _add_col(conn, "leads", "vehicles_info", "TEXT")
            _add_col(conn, "leads", "roof_year", "VARCHAR")
            _add_col(conn, "leads", "home_year", "VARCHAR")
            _add_col(conn, "leads", "sqft", "VARCHAR")
            _add_col(conn, "leads", "is_duplicate", "BOOLEAN", "FALSE")
            _add_col(conn, "leads", "duplicate_of_id", "INTEGER")
            _add_col(conn, "leads", "contacted_at", "TIMESTAMPTZ")
            _add_col(conn, "leads", "quoted_at", "TIMESTAMPTZ")
            _add_col(conn, "leads", "closed_at", "TIMESTAMPTZ")
            logger.info("leads table already exists, columns synced.")

        if "round_robin_state" not in existing:
            logger.info("Creating round_robin_state table...")
            conn.execute(text("""
                CREATE TABLE round_robin_state (
                    id SERIAL PRIMARY KEY,
                    last_assigned_user_id INTEGER,
                    last_assigned_at TIMESTAMPTZ DEFAULT NOW(),
                    total_assigned INTEGER DEFAULT 0
                )
            """))
            # Insert initial state row
            conn.execute(text(
                "INSERT INTO round_robin_state (last_assigned_user_id, total_assigned) VALUES (NULL, 0)"
            ))
            logger.info("round_robin_state table created with initial row.")
        else:
            logger.info("round_robin_state table already exists.")
