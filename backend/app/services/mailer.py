"""Centralized Mailgun deliverability defaults.

This module hooks into `requests.post` at app startup. Any call to the
Mailgun /messages endpoint (no matter which sender file made it) gets:

  1. Click tracking forced OFF (transactional emails don't need it,
     and the URL rewriting is a spam-score trigger)
  2. Open tracking forced ON (small spam impact, big analytics win)
  3. Auto-Submitted: auto-generated header (positive signal for
     transactional traffic recognition)
  4. List-Unsubscribe headers — but ONLY for emails that look like
     bulk/marketing sends (see _is_marketing_email() for the logic).
     Transactional welcomes, UW notifications, compliance reminders,
     and password resets do NOT get unsubscribe headers, because we
     legally need to send those regardless of marketing preferences.

The decision rule for List-Unsubscribe:
  - Add it when v:email_type ∈ {quote, quote_followup, digest,
    remarket, prospect, winback, life_crosssell, marketing_promo}
  - Skip it for everything else (welcome emails, UW alerts,
    inspection emails, password resets, internal notifications, etc.)

Callers who want explicit control can set their own h:List-Unsubscribe
in the request data — we use setdefault, so caller intent is preserved.

The hook is installed by calling install_mailgun_hook() once at app
startup (lifespan in main.py). It only intercepts Mailgun's /messages
endpoint — other requests.post calls (NowCerts, BoldSign, Anthropic,
etc.) pass through unchanged.
"""
import logging
import os
import requests

logger = logging.getLogger(__name__)

_INSTALLED = False
_ORIGINAL_POST = None

# Email types that are marketing/bulk and SHOULD have List-Unsubscribe.
# Anything not in this set is treated as transactional and gets no
# unsubscribe header (we still need to send transactional regardless
# of marketing preferences).
_MARKETING_EMAIL_TYPES = {
    "quote",
    "quote_followup",
    "digest",
    "remarket",
    "prospect",
    "winback",
    "life_crosssell",
    "marketing_promo",
    "campaign",
    "ab_digest",
}


def _is_marketing_email(data: dict) -> bool:
    """True if this Mailgun send is a marketing/bulk email that needs
    a List-Unsubscribe header. False for transactional emails.

    We check the v:email_type custom variable that senders set on each
    message. If it's not set, default to False (treat as transactional)
    since the safer side of the tradeoff is keeping the customer on the
    list when in doubt.
    """
    if not isinstance(data, dict):
        return False
    email_type = (data.get("v:email_type") or "").lower()
    return email_type in _MARKETING_EMAIL_TYPES


def _build_unsubscribe_headers() -> dict:
    """Return List-Unsubscribe + List-Unsubscribe-Post headers.

    The mailto: address is a real inbox we monitor for unsubscribe
    requests. The https: link goes to the unsubscribe page that
    handles the bulk unsubscribe token flow.
    """
    app_url = os.environ.get("APP_URL", "https://orbit.betterchoiceins.com")
    return {
        "h:List-Unsubscribe": f"<mailto:unsubscribe@betterchoiceins.com>, <{app_url}/unsubscribe>",
        # RFC 8058 one-click unsubscribe — Gmail/Outlook honor this for
        # the inbox-level "Unsubscribe" link without a confirmation.
        "h:List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


# Defaults applied to EVERY Mailgun send regardless of email type.
_UNIVERSAL_DEFAULTS = {
    "o:tracking-clicks": "no",
    "o:tracking-opens": "yes",
    "h:Auto-Submitted": "auto-generated",
}


def _apply_defaults(data: dict) -> None:
    """Mutate `data` in place to add deliverability defaults.

    For tracking-clicks we OVERRIDE any existing value to "no" — link
    rewriting is a spam-score trigger and there's no scenario where
    we need it on for ORBIT's transactional/follow-up flows. (If a
    future marketing campaign legitimately needs click attribution,
    revisit by adding an opt-in escape hatch via a special v: variable.)

    For everything else we use setdefault — caller intent wins.
    """
    if not isinstance(data, dict):
        return
    # Hard override for click tracking — this is the spam-score fix
    data["o:tracking-clicks"] = "no"
    # Soft defaults for the rest
    data.setdefault("o:tracking-opens", "yes")
    data.setdefault("h:Auto-Submitted", "auto-generated")
    if _is_marketing_email(data):
        for k, v in _build_unsubscribe_headers().items():
            data.setdefault(k, v)


def install_mailgun_hook() -> None:
    """Install a wrapper around requests.post that injects deliverability
    defaults for any Mailgun /messages call.

    Idempotent — calling twice is a no-op.
    """
    global _INSTALLED, _ORIGINAL_POST
    if _INSTALLED:
        return
    _ORIGINAL_POST = requests.post

    def _wrapped_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        # Match any Mailgun /messages endpoint regardless of region/domain
        if isinstance(url, str) and "api.mailgun.net" in url and "/messages" in url:
            data = kwargs.get("data")
            if data is not None and isinstance(data, dict):
                _apply_defaults(data)
                logger.debug(
                    "Mailgun deliverability defaults applied: tracking-clicks=%s, marketing=%s",
                    data.get("o:tracking-clicks"),
                    _is_marketing_email(data),
                )
        return _ORIGINAL_POST(*args, **kwargs)

    requests.post = _wrapped_post
    _INSTALLED = True
    logger.info("Mailgun deliverability hook installed — tracking-clicks=no for all, List-Unsubscribe for marketing emails only")


def uninstall_mailgun_hook() -> None:
    """For testing — restore the original requests.post."""
    global _INSTALLED, _ORIGINAL_POST
    if _INSTALLED and _ORIGINAL_POST is not None:
        requests.post = _ORIGINAL_POST
        _INSTALLED = False
