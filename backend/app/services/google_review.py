"""Google review URL routing.

BCI has two physical agency locations on Google:
  - Illinois (Saint Charles, IL) — primary / original location
  - Texas — second location

Customers in Texas and the immediately surrounding southern states
should be directed to leave their review on the Texas profile so the
review accrues to the correct local listing. Everyone else gets the
Illinois profile.

This is the SINGLE place that decides which URL to use. All survey
endpoints (welcome-email survey, customer survey, renewal survey)
must call get_review_url_for_state() rather than reading
settings.GOOGLE_REVIEW_URL directly. That way, if Evan adds a third
location later, only this file changes.
"""
import os
from typing import Optional


# Texas + states geographically adjacent to TX. A customer in any of
# these states is more likely to interact with the TX office, so we
# steer their review there.
TX_REGION_STATES = {"TX", "OK", "LA", "AR", "NM"}

# Hardcoded fallbacks — these are the actual production review URLs.
# We keep them here (not just in env vars) so a missing env var
# doesn't silently break the survey. Evan can override either via
# GOOGLE_REVIEW_URL_IL / GOOGLE_REVIEW_URL_TX env vars on Render.
DEFAULT_IL_URL = "https://g.page/r/CcqT2a9FrSoXEBM/review"
DEFAULT_TX_URL = "https://g.page/r/Cd6Tzj4Pdo6tEBI/review"


def _normalize_state(state: Optional[str]) -> Optional[str]:
    """Return uppercase 2-letter state code, or None if unparseable.

    Handles both 'TX' and 'Texas' style inputs defensively, since
    Sale.state is varchar(2) but Customer.state is just String — older
    records might have full names.
    """
    if not state:
        return None
    s = state.strip().upper()
    if len(s) == 2:
        return s
    # Full-name fallback for the TX-region states only — we don't need
    # a full 50-state lookup since everywhere else routes to IL anyway.
    full_name_map = {
        "TEXAS": "TX",
        "OKLAHOMA": "OK",
        "LOUISIANA": "LA",
        "ARKANSAS": "AR",
        "NEW MEXICO": "NM",
    }
    return full_name_map.get(s)


def get_review_url_for_state(state: Optional[str]) -> str:
    """Return the right Google review URL for a customer's state.

    Routing:
      - TX, OK, LA, AR, NM -> Texas listing
      - Everything else (or unknown state) -> Illinois listing

    The Illinois listing is the safe default when state is missing,
    since it's our original and primary office.
    """
    il_url = os.environ.get("GOOGLE_REVIEW_URL_IL") or os.environ.get("GOOGLE_REVIEW_URL") or DEFAULT_IL_URL
    tx_url = os.environ.get("GOOGLE_REVIEW_URL_TX") or DEFAULT_TX_URL

    code = _normalize_state(state)
    if code in TX_REGION_STATES:
        return tx_url
    return il_url


def get_review_location_label(state: Optional[str]) -> str:
    """Returns 'Texas' or 'Illinois' — useful for log lines / debug."""
    code = _normalize_state(state)
    return "Texas" if code in TX_REGION_STATES else "Illinois"
