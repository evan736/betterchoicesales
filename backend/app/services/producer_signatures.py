"""Producer signature helpers — shared across email types.

Centralizes the logic for "should this email show Evan's headshot?"
so we don't duplicate the same conditional inline across 6+ files.

Currently only Evan has a headshot configured. To add headshots for
other producers later, drop another file in
`/home/claude/repo/frontend/public/<slug>_headshot.jpg` and add the
producer to PRODUCER_HEADSHOTS below.
"""
from typing import Optional

# Public URL where the frontend serves the image. Cached aggressively
# by Render's CDN.
HEADSHOT_BASE_URL = "https://better-choice-web.onrender.com"

# Lookup by lowercased first/full/email so any of those forms works.
PRODUCER_HEADSHOTS: dict[str, str] = {
    "evan": "/evan_headshot.jpg",
    "evan larson": "/evan_headshot.jpg",
    "evan.larson": "/evan_headshot.jpg",
    "evan@betterchoiceins.com": "/evan_headshot.jpg",
}


def get_producer_headshot_url(producer_identifier: Optional[str]) -> Optional[str]:
    """Return the absolute headshot URL for a producer, or None.

    Accepts any of:
      - first name ("Evan")
      - full name ("Evan Larson")
      - username ("evan.larson")
      - email ("evan@betterchoiceins.com")
    """
    if not producer_identifier:
        return None
    key = producer_identifier.strip().lower()
    path = PRODUCER_HEADSHOTS.get(key)
    if not path:
        return None
    return HEADSHOT_BASE_URL + path


def producer_headshot_html(
    producer_identifier: Optional[str],
    size_px: int = 96,
    align: str = "left",
) -> str:
    """Return an <img> tag for the producer's headshot, or empty string
    if this producer doesn't have one configured.

    Designed to drop directly into existing email signature HTML without
    breaking layout. Default 96x96 round, left-aligned. Source image
    is 256x256 so it stays sharp at retina.

    Args:
      producer_identifier: name/username/email (case-insensitive)
      size_px: display size, both width and height
      align: 'left' (default) or 'center'

    Returns:
      HTML img tag, or '' if no headshot for this producer.
    """
    url = get_producer_headshot_url(producer_identifier)
    if not url:
        return ""
    margin = "0 0 10px 0" if align == "left" else "0 auto 10px auto"
    display = "block"
    return (
        f'<img src="{url}" alt="Producer headshot" '
        f'width="{size_px}" height="{size_px}" '
        f'style="width:{size_px}px;height:{size_px}px;'
        f'border-radius:50%;display:{display};margin:{margin};" />'
    )
