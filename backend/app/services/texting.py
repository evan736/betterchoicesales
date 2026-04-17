"""Texting provider facade — Twilio (primary).

This module exists solely so API/scheduler code can `from app.services.texting
import send_message` without coupling to the provider module name. If you ever
add a second provider back, this is the switchboard.

All calls route to app.services.twilio_sms.
"""
import logging

logger = logging.getLogger(__name__)
logger.info("Texting provider: Twilio SMS")

from app.services import twilio_sms as _impl

# Re-export the provider interface.
send_message            = _impl.send_message
send_bulk               = _impl.send_bulk
normalize_phone         = _impl.normalize_phone
phones_match            = _impl.phones_match
match_customer_by_phone = _impl.match_customer_by_phone
_log_message            = _impl._log_message
update_message_status   = _impl.update_message_status
get_conversation        = _impl.get_conversation
parse_inbound_webhook   = _impl.parse_inbound_webhook
parse_status_callback   = _impl.parse_status_callback


def current_provider() -> str:
    """Return active provider name."""
    return "twilio"
