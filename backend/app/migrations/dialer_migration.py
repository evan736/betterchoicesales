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

        # Add concurrency_cap and session config to campaigns
        _add_col(conn, "dialer_campaigns", "concurrency_cap", "INTEGER", 1)
        _add_col(conn, "dialer_campaigns", "max_calls_per_session", "INTEGER", 500)

        # Add daily call tracking to phone numbers (persists across deploys)
        _add_col(conn, "dialer_phone_numbers", "calls_today", "INTEGER", 0)
        _add_col(conn, "dialer_phone_numbers", "calls_today_date", "VARCHAR")

        logger.info("Dialer tables migrated")

    # Auto-resume active campaigns after deploy/restart
    _auto_resume_active_campaigns()


def _auto_resume_active_campaigns():
    """Restart dialer threads for any campaigns that were active before deploy."""
    try:
        from app.core.database import SessionLocal
        from app.models.dialer import DialerCampaign
        db = SessionLocal()
        try:
            active = db.query(DialerCampaign).filter(DialerCampaign.status == "active").all()
            for c in active:
                try:
                    from app.api.dialer import _auto_dial_loop, _dialer_threads
                    import threading
                    if c.id not in _dialer_threads or not _dialer_threads[c.id].is_alive():
                        t = threading.Thread(target=_auto_dial_loop, args=(c.id,), daemon=True)
                        t.start()
                        _dialer_threads[c.id] = t
                        logger.info(f"[AutoDialer] Auto-resumed campaign {c.id}: {c.name}")
                except Exception as e:
                    logger.warning(f"[AutoDialer] Failed to auto-resume campaign {c.id}: {e}")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[AutoDialer] Auto-resume failed: {e}")
