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


# Full 50-state + DC routing for the TX vs IL Google review listings.
#
# The split is based on geographic proximity / regional identity. A
# customer in a state we route to TX is more likely to feel a regional
# tie to the Texas office (and accrue the review to the right local
# Google profile). Everyone else goes to IL.
#
# TX bucket: Texas + the broader South & Southwest. Anchored on Texas
# and extends through the Gulf Coast (LA/MS/AL/FL), Deep South (GA/SC),
# Mid-South (TN/AR/NC), Plains-South (OK), and Southwest (NM/AZ).
#
# IL bucket: Everything else. This includes the Midwest (where IL sits),
# the Northeast, the Mid-Atlantic, the Plains states north of OK, the
# entire Mountain West, the West Coast, and AK/HI.
#
# Edge calls worth knowing:
#   - KS, MO, KY, VA, WV  -> IL (more northern than southern in feel)
#   - NC, SC              -> TX (Deep South, paired with GA)
#   - All Mountain/Western states -> IL by default (IL is the primary
#     office; western states are far from both, so default applies)
TX_REGION_STATES = {
    # Anchor + immediate neighbors
    "TX", "OK", "LA", "AR", "NM",
    # Gulf Coast / Deep South
    "MS", "AL", "FL", "GA",
    # Mid-South / Southeast
    "TN", "SC", "NC",
    # Southwest
    "AZ",
}

# All US states + DC + territories — for the full-name normalizer below.
# Used so a record that stored "Texas" instead of "TX" still routes
# correctly. We list all 50 (not just TX-region) because a "California"
# or "New York" record should still resolve to a 2-letter code so we
# can log it consistently, even though both route to IL.
_FULL_NAME_TO_CODE = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE",
    "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI",
    "WYOMING": "WY",
}

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
    return _FULL_NAME_TO_CODE.get(s)


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
