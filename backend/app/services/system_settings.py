"""Helpers for reading/writing SystemSetting rows.

Read order for a given key:
  1. system_settings table (if a row exists)
  2. environment variable
  3. provided default

This means: if Evan tunes a value via the UI, the DB row wins. If no
DB row exists yet, we fall back to the Render env var (preserving
current behavior). If neither is set, the default kicks in.

Designed to be cheap to call — schedulers fire it inside their tick
loop, but each call is one indexed query.
"""
import os
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)


def get_int_setting(db: Session, key: str, env_var: Optional[str], default: int) -> int:
    """Read an int setting from DB → env → default.

    `env_var` is the matching env var name (or None to skip env fallback).
    """
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row and row.value is not None:
            try:
                return int(row.value)
            except ValueError:
                logger.warning(f"SystemSetting {key} has non-int value '{row.value}', falling through")
    except Exception as e:
        # If table doesn't exist yet (first deploy before migration) or DB error,
        # silently fall through to env var. Schedulers MUST keep working.
        logger.debug(f"SystemSetting read failed for {key}: {e}")

    if env_var:
        env_val = os.getenv(env_var)
        if env_val is not None:
            try:
                return int(env_val)
            except ValueError:
                logger.warning(f"Env {env_var} has non-int value '{env_val}', using default")

    return default


def get_bool_setting(db: Session, key: str, env_var: Optional[str], default: bool) -> bool:
    """Read a bool setting from DB → env → default.

    Truthy: 'true', '1', 'yes', 'on' (case-insensitive).
    """
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row and row.value is not None:
            return row.value.strip().lower() in ("true", "1", "yes", "on")
    except Exception as e:
        logger.debug(f"SystemSetting read failed for {key}: {e}")

    if env_var:
        env_val = os.getenv(env_var)
        if env_val is not None:
            return env_val.strip().lower() in ("true", "1", "yes", "on")

    return default


def set_setting(db: Session, key: str, value: str, updated_by: Optional[str] = None) -> SystemSetting:
    """Upsert a setting. Caller must commit."""
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = str(value)
        row.updated_by = updated_by
    else:
        row = SystemSetting(key=key, value=str(value), updated_by=updated_by)
        db.add(row)
    return row
