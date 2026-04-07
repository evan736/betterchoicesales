"""Self-healing migration for renewal_surveys table."""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_migration(engine):
    """Create renewal_surveys table if it doesn't exist."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'renewal_surveys')"
        ))
        exists = result.scalar()

        if not exists:
            conn.execute(text("""
                CREATE TABLE renewal_surveys (
                    id SERIAL PRIMARY KEY,
                    customer_id INTEGER REFERENCES customers(id),
                    customer_name VARCHAR NOT NULL,
                    customer_email VARCHAR,
                    customer_phone VARCHAR,
                    policy_number VARCHAR,
                    carrier VARCHAR,
                    current_premium NUMERIC(10,2),
                    renewal_date TIMESTAMP,
                    token VARCHAR UNIQUE NOT NULL,
                    status VARCHAR DEFAULT 'pending',
                    responses JSONB DEFAULT '{}',
                    happiness_rating INTEGER,
                    is_happy BOOLEAN,
                    wants_callback BOOLEAN DEFAULT FALSE,
                    interested_rate_lock BOOLEAN DEFAULT FALSE,
                    interested_higher_deductible BOOLEAN DEFAULT FALSE,
                    filed_claim BOOLEAN DEFAULT FALSE,
                    home_updates JSONB DEFAULT '[]',
                    unhappy_reason VARCHAR,
                    feedback_text TEXT,
                    reshop_created BOOLEAN DEFAULT FALSE,
                    reshop_id INTEGER REFERENCES reshops(id),
                    nowcerts_updated BOOLEAN DEFAULT FALSE,
                    agent_notified BOOLEAN DEFAULT FALSE,
                    google_review_redirected BOOLEAN DEFAULT FALSE,
                    assigned_agent_id INTEGER REFERENCES users(id),
                    assigned_agent_name VARCHAR,
                    sent_at TIMESTAMP WITH TIME ZONE,
                    started_at TIMESTAMP WITH TIME ZONE,
                    completed_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_renewal_surveys_token ON renewal_surveys (token)"))
            conn.execute(text("CREATE INDEX ix_renewal_surveys_status ON renewal_surveys (status)"))
            conn.execute(text("CREATE INDEX ix_renewal_surveys_customer_id ON renewal_surveys (customer_id)"))
            conn.commit()
            logger.info("Created renewal_surveys table")
        else:
            logger.info("renewal_surveys table already exists")
