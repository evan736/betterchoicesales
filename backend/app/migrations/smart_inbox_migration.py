"""
Self-healing migration for Smart Inbox tables.
Run on startup — creates tables if they don't exist.
Uses ADD COLUMN IF NOT EXISTS for PostgreSQL compatibility.
"""
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


def _add_col(conn, table, column, col_type, default=None):
    """Safely add a column if it doesn't exist (PostgreSQL 9.6+)."""
    try:
        dflt = f" DEFAULT {default}" if default is not None else ""
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}{dflt}"))
    except Exception as e:
        logger.debug(f"Column {table}.{column}: {e}")


def migrate_smart_inbox():
    """Create inbound_emails and outbound_queue tables if missing."""
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('inbound_emails','outbound_queue')"
        ))
        existing = {row[0] for row in result}

        if "inbound_emails" not in existing:
            logger.info("Creating inbound_emails table...")
            conn.execute(text("""
                CREATE TABLE inbound_emails (
                    id SERIAL PRIMARY KEY, created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW(),
                    message_id VARCHAR UNIQUE, from_address VARCHAR NOT NULL, to_address VARCHAR,
                    subject VARCHAR, body_plain TEXT, body_html TEXT, sender_name VARCHAR, forwarded_by VARCHAR,
                    attachment_count INTEGER DEFAULT 0, attachment_names JSONB, attachment_data JSONB,
                    category VARCHAR, sensitivity VARCHAR, ai_summary TEXT, ai_analysis JSONB, confidence_score FLOAT,
                    extracted_policy_number VARCHAR, extracted_insured_name VARCHAR, extracted_carrier VARCHAR,
                    extracted_due_date TIMESTAMP, extracted_amount FLOAT,
                    nowcerts_insured_id VARCHAR, customer_name VARCHAR, customer_email VARCHAR,
                    match_method VARCHAR, match_confidence FLOAT,
                    status VARCHAR DEFAULT 'received', processing_notes TEXT,
                    nowcerts_note_logged BOOLEAN DEFAULT FALSE, nowcerts_note_id VARCHAR,
                    error_message TEXT, retry_count INTEGER DEFAULT 0,
                    is_read BOOLEAN DEFAULT FALSE, is_archived BOOLEAN DEFAULT FALSE,
                    is_batch_report BOOLEAN DEFAULT FALSE, batch_item_count INTEGER,
                    parent_email_id INTEGER REFERENCES inbound_emails(id)
                )"""))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ie_created ON inbound_emails(created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ie_status ON inbound_emails(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ie_msgid ON inbound_emails(message_id)"))
            logger.info("✓ inbound_emails created")
        else:
            _add_col(conn, "inbound_emails", "is_read", "BOOLEAN", "FALSE")
            _add_col(conn, "inbound_emails", "is_archived", "BOOLEAN", "FALSE")
            _add_col(conn, "inbound_emails", "attachment_data", "JSONB")
            _add_col(conn, "inbound_emails", "is_batch_report", "BOOLEAN", "FALSE")
            _add_col(conn, "inbound_emails", "batch_item_count", "INTEGER")
            _add_col(conn, "inbound_emails", "parent_email_id", "INTEGER REFERENCES inbound_emails(id)")

        if "outbound_queue" not in existing:
            logger.info("Creating outbound_queue table...")
            conn.execute(text("""
                CREATE TABLE outbound_queue (
                    id SERIAL PRIMARY KEY, created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW(),
                    inbound_email_id INTEGER NOT NULL REFERENCES inbound_emails(id),
                    to_email VARCHAR NOT NULL, to_name VARCHAR, cc_email VARCHAR,
                    subject VARCHAR NOT NULL, body_html TEXT NOT NULL, body_plain TEXT,
                    ai_rationale TEXT, template_used VARCHAR,
                    status VARCHAR DEFAULT 'draft', sensitivity VARCHAR,
                    approved_by VARCHAR, approved_at TIMESTAMP, rejected_reason TEXT,
                    sent_at TIMESTAMP, mailgun_message_id VARCHAR, send_error TEXT,
                    delivery_method VARCHAR DEFAULT 'email', thanksio_order_id VARCHAR
                )"""))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_oq_created ON outbound_queue(created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_oq_status ON outbound_queue(status)"))
            logger.info("✓ outbound_queue created")
        else:
            _add_col(conn, "outbound_queue", "delivery_method", "VARCHAR", "'email'")
            _add_col(conn, "outbound_queue", "thanksio_order_id", "VARCHAR")

    logger.info("✓ Smart Inbox migration complete")
