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
        logger.info("Dialer tables migrated")
