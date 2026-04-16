"""Texting provider facade.

Exposes a single set of functions the API/schedulers import. Routes to either
Sendblue or LoopMessage under the hood based on `TEXTING_PROVIDER` env var.

Default: sendblue (current production provider).
Flip to loopmessage by setting TEXTING_PROVIDER=loopmessage in Render.
No redeploy needed for the flip — just an env var change + service restart.

Both underlying services read/write the SAME `text_messages` table and match
customers via the SAME logic, so conversation history is preserved across a
provider switch — existing threads keep working.
"""
import os
import logging

logger = logging.getLogger(__name__)

_PROVIDER = os.getenv("TEXTING_PROVIDER", "sendblue").strip().lower()

if _PROVIDER == "loopmessage":
    from app.services import loopmessage as _impl
    logger.info("Texting provider: LoopMessage")
else:
    from app.services import sendblue as _impl
    if _PROVIDER not in ("sendblue", ""):
        logger.warning("Unknown TEXTING_PROVIDER=%r — falling back to sendblue", _PROVIDER)
    logger.info("Texting provider: Sendblue")


# Re-export the provider interface.
send_message          = _impl.send_message
send_bulk             = _impl.send_bulk
normalize_phone       = _impl.normalize_phone
phones_match          = _impl.phones_match
match_customer_by_phone = _impl.match_customer_by_phone
_log_message          = _impl._log_message
update_message_status = _impl.update_message_status
get_conversation      = _impl.get_conversation


def current_provider() -> str:
    """Return the active provider name (for diagnostics / UI badges)."""
    return _PROVIDER if _PROVIDER in ("sendblue", "loopmessage") else "sendblue"
