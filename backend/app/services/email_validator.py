"""Local email validation — regex syntax + DNS MX lookup.

Used to scrub the cold prospect list before any send. Avoids paying for
NeverBounce / etc. Local-only, no third-party dependency.

LIMITATIONS (be honest about what this does NOT catch):
  - It cannot tell you if a real mailbox exists at that address (would
    require SMTP probing which is unreliable + risks getting our IP
    blacklisted)
  - It cannot detect spam-traps or honeypots
  - It cannot detect role addresses (info@, sales@) which often have
    poor deliverability
  - DNS results are cached for 24 hours so they may be stale

What it DOES catch:
  - Syntactically invalid addresses (typos, missing @, etc.)
  - Domains that don't exist or have no MX records (the most common
    cause of hard bounces from old lists like ours)
  - Common known-disposable domains (mailinator, guerrillamail)
  - Common typos in popular domains (gmial.com, yaho.com)

Result: should reduce bounce rate from ~5-15% (typical for old cold
lists) down to ~2-5% which Mailgun can absorb without reputation damage.
"""
import re
import socket
import time
from typing import Optional, Tuple

try:
    import dns.resolver
    DNS_AVAILABLE = True
except ImportError:
    DNS_AVAILABLE = False
    dns = None

# RFC 5322 simplified — covers 99% of real-world addresses
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+$"
)

# Known disposable/throwaway providers — rejecting outright
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com",
    "tempmail.com", "throwawaymail.com", "yopmail.com",
    "trashmail.com", "fakeinbox.com", "spamgourmet.com",
}

# Common typo fixes for popular email providers — flag as invalid + suggest
TYPO_DOMAINS = {
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmal.com": "gmail.com",
    "gnail.com": "gmail.com",
    "gmail.co": "gmail.com",
    "yaho.com": "yahoo.com",
    "yhoo.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "yahoo.co": "yahoo.com",
    "hotmial.com": "hotmail.com",
    "hotmai.com": "hotmail.com",
    "hotmal.com": "hotmail.com",
    "outlok.com": "outlook.com",
    "outloo.com": "outlook.com",
    "icloud.co": "icloud.com",
    "aol.co": "aol.com",
}

# Module-level DNS-MX cache (key=domain, value=(has_mx, expires_at_ts))
_MX_CACHE: dict[str, Tuple[bool, float]] = {}
_MX_CACHE_TTL_SECONDS = 86400  # 24h


def _check_mx(domain: str) -> bool:
    """Return True if domain has at least one MX or A record (i.e., it
    can receive email). Falls back to A-record lookup since some small
    domains don't have explicit MX records but accept SMTP on the A-record IP.

    Uses module-level cache with 24h TTL to avoid hammering DNS.
    """
    domain = domain.lower().strip()
    cached = _MX_CACHE.get(domain)
    if cached and cached[1] > time.time():
        return cached[0]

    has_mx = False
    if DNS_AVAILABLE:
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=3.0)
            if answers:
                has_mx = True
        except Exception:
            # Fall through to A-record lookup
            pass
    if not has_mx:
        # Cheap A-record fallback via socket.gethostbyname
        try:
            socket.setdefaulttimeout(3.0)
            socket.gethostbyname(domain)
            has_mx = True
        except (socket.gaierror, socket.timeout):
            has_mx = False

    _MX_CACHE[domain] = (has_mx, time.time() + _MX_CACHE_TTL_SECONDS)
    return has_mx


def validate_email(email: str, check_mx: bool = True) -> dict:
    """Run validation checks on an email address.

    Returns dict with:
      - valid: bool — overall verdict
      - reason: str — short reason if invalid
      - normalized: str — lowercased + trimmed (None if invalid syntax)

    Pass check_mx=False to skip the DNS lookup (fast, syntax-only).
    """
    if not email:
        return {"valid": False, "reason": "empty", "normalized": None}

    email = email.strip().lower()
    # Strip "Name <email>" wrapper if present
    if "<" in email and ">" in email:
        email = email[email.find("<") + 1:email.rfind(">")].strip()

    # Length check (RFC 5321 max 254)
    if len(email) > 254:
        return {"valid": False, "reason": "too_long", "normalized": None}

    if "@" not in email:
        return {"valid": False, "reason": "no_at_sign", "normalized": None}

    # Syntax check
    if not EMAIL_REGEX.match(email):
        return {"valid": False, "reason": "syntax", "normalized": None}

    local, _, domain = email.rpartition("@")
    if not local or not domain:
        return {"valid": False, "reason": "syntax", "normalized": None}

    # Disposable
    if domain in DISPOSABLE_DOMAINS:
        return {"valid": False, "reason": "disposable", "normalized": email}

    # Common typo
    if domain in TYPO_DOMAINS:
        return {
            "valid": False,
            "reason": f"typo_likely_meant_{TYPO_DOMAINS[domain]}",
            "normalized": email,
        }

    # Single-character TLD (must be at least 2 chars per IANA)
    parts = domain.split(".")
    if len(parts[-1]) < 2:
        return {"valid": False, "reason": "tld_too_short", "normalized": email}

    # MX/A record check (most expensive — opt-out via check_mx=False)
    if check_mx:
        if not _check_mx(domain):
            return {"valid": False, "reason": "no_mx_record", "normalized": email}

    return {"valid": True, "reason": "ok", "normalized": email}
