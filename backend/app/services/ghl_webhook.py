"""GoHighLevel webhook integration service.

Fires webhooks to GHL when key events occur in BCI CRM.
Logs all webhook calls for audit trail.
"""
import logging
import requests
from typing import Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)


class GHLWebhookService:
    """Sends webhook payloads to GoHighLevel inbound webhook URLs."""

    def __init__(self):
        self.base_timeout = 15
        # GHL webhook URLs - set via env vars
        self.nonpay_webhook_url = getattr(settings, 'GHL_NONPAY_WEBHOOK_URL', None)
        self.renewal_webhook_url = getattr(settings, 'GHL_RENEWAL_WEBHOOK_URL', None)
        self.onboarding_webhook_url = getattr(settings, 'GHL_ONBOARDING_WEBHOOK_URL', None)
        self.quote_webhook_url = getattr(settings, 'GHL_QUOTE_WEBHOOK_URL', None)
        self.winback_webhook_url = getattr(settings, 'GHL_WINBACK_WEBHOOK_URL', None)
        self.crosssell_webhook_url = getattr(settings, 'GHL_CROSSSELL_WEBHOOK_URL', None)
        self.uw_webhook_url = getattr(settings, 'GHL_UW_WEBHOOK_URL', None)

    def _fire(self, url: str, payload: dict, event_type: str) -> dict:
        """Fire a webhook and log the result."""
        if not url:
            logger.debug(f"GHL webhook URL not configured for {event_type}, skipping")
            return {"skipped": True, "reason": "no_url_configured"}

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-BCI-Event": event_type,
                    "X-BCI-Timestamp": datetime.utcnow().isoformat(),
                },
                timeout=self.base_timeout,
            )

            result = {
                "success": resp.status_code < 400,
                "status_code": resp.status_code,
                "response": resp.text[:500],
            }

            # Log to database
            self._log_webhook("outbound", event_type, payload, result)

            if resp.status_code >= 400:
                logger.warning(f"GHL webhook {event_type} returned {resp.status_code}: {resp.text[:200]}")
            else:
                logger.info(f"GHL webhook {event_type} sent successfully ({resp.status_code})")

            return result

        except Exception as e:
            logger.error(f"GHL webhook {event_type} failed: {e}")
            result = {"success": False, "error": str(e)}
            self._log_webhook("outbound", event_type, payload, result)
            return result

    def _log_webhook(self, direction: str, event_type: str, payload: dict, result: dict):
        """Log webhook to database (non-blocking)."""
        try:
            from app.core.database import SessionLocal
            from app.models.campaign import GHLWebhookLog
            db = SessionLocal()
            try:
                log = GHLWebhookLog(
                    direction=direction,
                    event_type=event_type,
                    customer_name=payload.get("first_name", "") + " " + payload.get("last_name", ""),
                    customer_email=payload.get("email"),
                    payload=payload,
                    response_status=result.get("status_code"),
                    response_body=result.get("response", ""),
                    error=result.get("error"),
                )
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"Failed to log GHL webhook: {e}")

    # ── Event-specific webhook methods ──

    def fire_nonpay_sent(self, customer_name: str, email: str, phone: str,
                         policy_number: str, carrier: str, amount_due: str,
                         due_date: str, carrier_phone: str) -> dict:
        """Fire webhook when non-pay email is sent."""
        parts = customer_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "policy_number": policy_number,
            "carrier": carrier,
            "amount_due": amount_due,
            "due_date": due_date,
            "carrier_phone": carrier_phone,
            "event_type": "nonpay_email_sent",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.nonpay_webhook_url, payload, "nonpay_email_sent")

    def fire_renewal_approaching(self, customer_name: str, email: str, phone: str,
                                  days_until: int, highest_rate_pct: float,
                                  rate_category: str, policies: list) -> dict:
        """Fire webhook for upcoming renewal."""
        parts = customer_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "event_type": "renewal_approaching",
            "days_until_renewal": days_until,
            "highest_rate_change_pct": highest_rate_pct,
            "rate_category": rate_category,
            "policies": policies,
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.renewal_webhook_url, payload, "renewal_approaching")

    def fire_welcome_sent(self, customer_name: str, email: str, phone: str,
                          carrier: str, policy_type: str, policy_number: str) -> dict:
        """Fire webhook when welcome email sent (triggers onboarding in GHL)."""
        parts = customer_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "carrier": carrier,
            "policy_type": policy_type,
            "policy_number": policy_number,
            "event_type": "welcome_email_sent",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.onboarding_webhook_url, payload, "welcome_email_sent")

    def fire_quote_sent(self, prospect_name: str, email: str, phone: str,
                        carrier: str, policy_type: str, premium: str,
                        producer_name: str) -> dict:
        """Fire webhook when quote is emailed to prospect."""
        parts = prospect_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "carrier": carrier,
            "policy_type": policy_type,
            "quoted_premium": premium,
            "producer_name": producer_name,
            "event_type": "quote_sent",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.quote_webhook_url, payload, "quote_sent")

    def fire_quote_followup(self, prospect_name: str, email: str, phone: str,
                            carrier: str, policy_type: str, days_since: int,
                            producer_name: str) -> dict:
        """Fire webhook for quote follow-up (3/7/14 day)."""
        parts = prospect_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "carrier": carrier,
            "policy_type": policy_type,
            "days_since_quote": days_since,
            "producer_name": producer_name,
            "event_type": f"quote_not_converted_{days_since}d",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.quote_webhook_url, payload, f"quote_not_converted_{days_since}d")

    def fire_winback(self, customer_name: str, email: str, phone: str,
                     carrier: str, policy_type: str, months_active: int,
                     cancel_reason: str) -> dict:
        """Fire webhook for win-back campaign."""
        parts = customer_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "carrier": carrier,
            "policy_type": policy_type,
            "months_active": months_active,
            "cancellation_reason": cancel_reason or "unknown",
            "event_type": "winback_campaign",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.winback_webhook_url, payload, "winback_campaign")

    def fire_uw_requirement(self, customer_name: str, email: str, phone: str,
                            policy_number: str, carrier: str,
                            requirement_type: str, description: str,
                            due_date: str) -> dict:
        """Fire webhook for underwriting requirement notification."""
        parts = customer_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "policy_number": policy_number,
            "carrier": carrier,
            "requirement_type": requirement_type,
            "requirement_description": description,
            "due_date": due_date or "",
            "event_type": "uw_requirement",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.uw_webhook_url, payload, "uw_requirement")

    def fire_crosssell_life(self, customer_name: str, email: str, phone: str,
                            existing_policies: list) -> dict:
        """Fire webhook for life insurance cross-sell."""
        parts = customer_name.strip().split(maxsplit=1)
        payload = {
            "first_name": parts[0] if parts else "",
            "last_name": parts[1] if len(parts) > 1 else "",
            "email": email or "",
            "phone": phone or "",
            "existing_policies": existing_policies,
            "event_type": "life_cross_sell",
            "sent_at": datetime.utcnow().isoformat(),
        }
        return self._fire(self.crosssell_webhook_url, payload, "life_cross_sell")


def get_ghl_service() -> GHLWebhookService:
    return GHLWebhookService()
