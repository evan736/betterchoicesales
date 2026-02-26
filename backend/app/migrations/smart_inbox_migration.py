"""
Self-healing migration for Smart Inbox tables.
Run on startup — creates tables if they don't exist.
"""
import logging
from sqlalchemy import text, inspect
from app.core.database import engine

logger = logging.getLogger(__name__)


def migrate_smart_inbox():
    """Create inbound_emails and outbound_queue tables if missing."""
    inspector = inspect(engine)
    existing = inspector.get_table_names()

    with engine.begin() as conn:
        if "inbound_emails" not in existing:
            logger.info("Creating inbound_emails table...")
            conn.execute(text("""
                CREATE TABLE inbound_emails (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    message_id VARCHAR UNIQUE,
                    from_address VARCHAR NOT NULL,
                    to_address VARCHAR,
                    subject VARCHAR,
                    body_plain TEXT,
                    body_html TEXT,
                    sender_name VARCHAR,
                    forwarded_by VARCHAR,
                    attachment_count INTEGER DEFAULT 0,
                    attachment_names JSONB,
                    category VARCHAR,
                    sensitivity VARCHAR,
                    ai_summary TEXT,
                    ai_analysis JSONB,
                    confidence_score FLOAT,
                    extracted_policy_number VARCHAR,
                    extracted_insured_name VARCHAR,
                    extracted_carrier VARCHAR,
                    extracted_due_date TIMESTAMP,
                    extracted_amount FLOAT,
                    nowcerts_insured_id VARCHAR,
                    customer_name VARCHAR,
                    customer_email VARCHAR,
                    match_method VARCHAR,
                    match_confidence FLOAT,
                    status VARCHAR DEFAULT 'received',
                    processing_notes TEXT,
                    nowcerts_note_logged BOOLEAN DEFAULT FALSE,
                    nowcerts_note_id VARCHAR,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0
                );
                CREATE INDEX idx_inbound_emails_created_at ON inbound_emails (created_at);
                CREATE INDEX idx_inbound_emails_status ON inbound_emails (status);
                CREATE INDEX idx_inbound_emails_message_id ON inbound_emails (message_id);
            """))
            logger.info("✓ inbound_emails table created")
        else:
            logger.info("inbound_emails table already exists")

        if "outbound_queue" not in existing:
            logger.info("Creating outbound_queue table...")
            conn.execute(text("""
                CREATE TABLE outbound_queue (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    inbound_email_id INTEGER NOT NULL REFERENCES inbound_emails(id),
                    to_email VARCHAR NOT NULL,
                    to_name VARCHAR,
                    cc_email VARCHAR,
                    subject VARCHAR NOT NULL,
                    body_html TEXT NOT NULL,
                    body_plain TEXT,
                    ai_rationale TEXT,
                    template_used VARCHAR,
                    status VARCHAR DEFAULT 'draft',
                    sensitivity VARCHAR,
                    approved_by VARCHAR,
                    approved_at TIMESTAMP,
                    rejected_reason TEXT,
                    sent_at TIMESTAMP,
                    mailgun_message_id VARCHAR,
                    send_error TEXT
                );
                CREATE INDEX idx_outbound_queue_created_at ON outbound_queue (created_at);
                CREATE INDEX idx_outbound_queue_status ON outbound_queue (status);
            """))
            logger.info("✓ outbound_queue table created")
        else:
            logger.info("outbound_queue table already exists")

        # ── Self-healing: add new columns if missing ──
        try:
            existing_cols = [c["name"] for c in inspector.get_columns("inbound_emails")]
            if "is_read" not in existing_cols:
                conn.execute(text("ALTER TABLE inbound_emails ADD COLUMN is_read BOOLEAN DEFAULT FALSE"))
                conn.execute(text("CREATE INDEX idx_inbound_emails_is_read ON inbound_emails (is_read)"))
                logger.info("✓ Added is_read column to inbound_emails")
            if "is_archived" not in existing_cols:
                conn.execute(text("ALTER TABLE inbound_emails ADD COLUMN is_archived BOOLEAN DEFAULT FALSE"))
                conn.execute(text("CREATE INDEX idx_inbound_emails_is_archived ON inbound_emails (is_archived)"))
                logger.info("✓ Added is_archived column to inbound_emails")
            if "attachment_data" not in existing_cols:
                conn.execute(text("ALTER TABLE inbound_emails ADD COLUMN attachment_data JSONB"))
                logger.info("✓ Added attachment_data column to inbound_emails")
            if "is_batch_report" not in existing_cols:
                conn.execute(text("ALTER TABLE inbound_emails ADD COLUMN is_batch_report BOOLEAN DEFAULT FALSE"))
                logger.info("✓ Added is_batch_report column to inbound_emails")
            if "batch_item_count" not in existing_cols:
                conn.execute(text("ALTER TABLE inbound_emails ADD COLUMN batch_item_count INTEGER"))
                logger.info("✓ Added batch_item_count column to inbound_emails")
            if "parent_email_id" not in existing_cols:
                conn.execute(text("ALTER TABLE inbound_emails ADD COLUMN parent_email_id INTEGER REFERENCES inbound_emails(id)"))
                logger.info("✓ Added parent_email_id column to inbound_emails")
        except Exception as e:
            logger.warning(f"Column migration check: {e}")
