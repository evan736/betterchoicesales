"""Retention analysis service — NowCerts-sourced.

Policies up for renewal in a given month are sourced from NowCerts
(customer_policies) using each policy's prior expiration_date, not
from commission statements. This removes the dependency on having
statement history stretching back a full policy term, and turns the
analysis into a direct NowCerts question:

    For each policy that was supposed to renew in month M:
      - Did the same policy get carried forward (same carrier + same LOB
        + policy number unchanged, but effective_date rolled forward)?   → renewed
      - Did the customer write a new policy at the SAME carrier with a
        different policy number in the renewal window?                   → rewritten_same_carrier (retained)
      - Did the customer write a new policy at a DIFFERENT carrier in
        the renewal window (same LOB)?                                   → carrier_move (retained)
      - None of the above, and the customer still has at least one
        active policy in the agency?                                     → partial_retention (customer kept, policy lost)
      - None of the above, and the customer has no active policies?     → lost

Commission statements are cross-referenced purely as *paid-through*
confirmation for renewed/rewritten outcomes — they don't drive
detection.
"""
import logging
import re
from datetime import datetime, timedelta, date
from decimal import Decimal
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models.retention import RetentionRecord, RetentionSummary
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Normalization helpers
# ──────────────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize a customer name for fuzzy matching."""
    if not name:
        return ""
    n = name.strip().upper()
    for suffix in [" JR", " SR", " III", " II", " IV", " MD", " DDS"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)]
    if "," in n:
        parts = n.split(",", 1)
        n = f"{parts[1].strip()} {parts[0].strip()}"
    n = re.sub(r'\b[A-Z]\b', '', n)
    n = re.sub(r'\s+', ' ', n).strip().lower()
    return n


def normalize_policy_number(pn: str) -> str:
    """Strip spaces, dashes, tabs for comparison."""
    if not pn:
        return ""
    return pn.replace(" ", "").replace("-", "").replace("\t", "").strip().upper()


def _canonical_carrier(name: Optional[str]) -> str:
    """Canonicalize carrier name so aliases match (Spinnaker→Hippo, etc.)."""
    if not name:
        return ""
    key = name.strip().lower()
    aliases = {
        "spinnaker": "hippo",
        "spinnaker insurance": "hippo",
        "hippo insurance": "hippo",
        "obsidian": "steadily",
        "obsidian specialty": "steadily",
        "steadily insurance": "steadily",
        "national general": "natgen",
        "natgen premier": "natgen",
        "nat gen": "natgen",
        "safeco insurance": "safeco",
        "liberty mutual safeco": "safeco",
        "travelers insurance": "travelers",
        "travelers indemnity": "travelers",
        "progressive insurance": "progressive",
        "progressive direct": "progressive",
        "grange insurance": "grange",
        "grange mutual": "grange",
    }
    if key in aliases:
        return aliases[key]
    for alias, canonical in aliases.items():
        if len(alias) > 6 and alias in key:
            return canonical
    return key


def _period_for(d) -> Optional[str]:
    """Convert a datetime/date to 'YYYY-MM' period string."""
    if not d:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.year:04d}-{d.month:02d}"


def _months_back(today: date, n: int) -> str:
    """Return period string for n months before today's month."""
    y, m = today.year, today.month
    for _ in range(n):
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
    return f"{y:04d}-{m:02d}"


# ──────────────────────────────────────────────────────────────────────
# Main analysis
# ──────────────────────────────────────────────────────────────────────

def run_retention_analysis(db: Session, months_back: int = 18) -> dict:
    """Analyze NowCerts customer_policies to build month-by-month retention.

    Args:
        db: SQLAlchemy session.
        months_back: How many months of history to analyze (default 18).

    Returns:
        {"status": "success", "stats": {...}, "periods_analyzed": [...]}
    """
    stats = {
        "created": 0,
        "renewed": 0,
        "carrier_moved": 0,
        "rewritten_same_carrier": 0,
        "partial_retention": 0,
        "lost": 0,
        "pending": 0,
    }

    today = date.today()
    periods = sorted({_months_back(today, i) for i in range(1, months_back + 1)})
    logger.info("Retention analysis — analyzing periods: %s", periods)
    periods_set = set(periods)

    # ──────────────────────────────────────────────────────────────
    # Load ALL customer policies, group by customer.
    # ──────────────────────────────────────────────────────────────
    all_policies = db.query(CustomerPolicy).all()
    policies_by_customer = defaultdict(list)
    for p in all_policies:
        policies_by_customer[p.customer_id].append({
            "id": p.id,
            "policy_number": p.policy_number,
            "policy_number_norm": normalize_policy_number(p.policy_number),
            "carrier": p.carrier or "",
            "carrier_canonical": _canonical_carrier(p.carrier),
            "line_of_business": (p.line_of_business or "").strip(),
            "lob_lower": (p.line_of_business or "").strip().lower(),
            "status": (p.status or "").strip().lower(),
            "effective_date": p.effective_date,
            "expiration_date": p.expiration_date,
            "premium": float(p.premium or 0),
        })

    # Group each customer's policies into renewal chains:
    # (customer_id, carrier_canonical, lob_lower) -> list sorted by effective_date
    chain_by_key = defaultdict(list)
    for cust_id, polys in policies_by_customer.items():
        for p in polys:
            key = (cust_id, p["carrier_canonical"], p["lob_lower"])
            chain_by_key[key].append(p)
    for key, chain in chain_by_key.items():
        chain.sort(key=lambda x: x["effective_date"] or datetime.min)

    # ──────────────────────────────────────────────────────────────
    # Build candidate list: (period) -> [(customer_id, expiring_policy, outcome_or_None)]
    # An expiring policy is any policy whose expiration_date falls in a tracked period.
    # ──────────────────────────────────────────────────────────────
    period_candidates = defaultdict(list)

    for (cust_id, carrier_c, lob), chain in chain_by_key.items():
        for idx, p in enumerate(chain):
            exp = p["expiration_date"]
            exp_period = _period_for(exp)
            if exp_period not in periods_set:
                continue

            # Look for a successor in the same chain within the renewal window.
            exp_d = exp.date() if isinstance(exp, datetime) else exp
            renewed_by = None
            for later in chain[idx + 1:]:
                le = later["effective_date"]
                if not le:
                    continue
                le_d = le.date() if isinstance(le, datetime) else le
                if (exp_d - timedelta(days=30)) <= le_d <= (exp_d + timedelta(days=45)):
                    renewed_by = later
                    break

            outcome = None
            if renewed_by:
                if renewed_by["policy_number_norm"] == p["policy_number_norm"]:
                    outcome = {"kind": "renewed", "new": renewed_by}
                else:
                    outcome = {"kind": "rewritten_same_carrier", "new": renewed_by}
            period_candidates[exp_period].append((cust_id, p, outcome))

    # ──────────────────────────────────────────────────────────────
    # Second pass: for unresolved candidates, look across carriers for
    # a same-customer rewrite within the renewal window.
    # ──────────────────────────────────────────────────────────────
    for period, entries in period_candidates.items():
        yr, mo = int(period.split("-")[0]), int(period.split("-")[1])
        win_start = date(yr, mo, 1) - timedelta(days=30)
        # End of period + 45-day grace
        if mo == 12:
            next_first = date(yr + 1, 1, 1)
        else:
            next_first = date(yr, mo + 1, 1)
        win_end = next_first + timedelta(days=44)  # ~45-day grace

        for i, (cust_id, p, outcome) in enumerate(entries):
            if outcome is not None:
                continue

            same_carrier = p["carrier_canonical"]
            same_lob = p["lob_lower"]
            other_new = None
            for op in policies_by_customer.get(cust_id, []):
                if op["id"] == p["id"]:
                    continue
                # Skip policies in the same (carrier, lob) chain — already handled
                if op["carrier_canonical"] == same_carrier and op["lob_lower"] == same_lob:
                    continue
                eff = op["effective_date"]
                if not eff:
                    continue
                eff_d = eff.date() if isinstance(eff, datetime) else eff
                if not (win_start <= eff_d <= win_end):
                    continue
                # Prefer matching line of business, but accept if either side is empty
                if op["lob_lower"] == same_lob or not same_lob or not op["lob_lower"]:
                    other_new = op
                    break

            if other_new:
                entries[i] = (cust_id, p, {"kind": "carrier_move", "new": other_new})
                continue

            # Partial retention: customer kept other active policies?
            has_active = any(
                op["status"] in ("active", "in force", "inforce")
                and op["id"] != p["id"]
                for op in policies_by_customer.get(cust_id, [])
            )
            if has_active:
                entries[i] = (cust_id, p, {"kind": "partial_retention", "new": None})
            else:
                entries[i] = (cust_id, p, {"kind": "lost", "new": None})

    # ──────────────────────────────────────────────────────────────
    # Write RetentionRecord rows. Clear existing rows for tracked periods
    # first so re-runs produce a clean set.
    # ──────────────────────────────────────────────────────────────
    for per in periods:
        db.query(RetentionRecord).filter(
            RetentionRecord.original_period == per
        ).delete(synchronize_session=False)
    db.flush()

    customer_cache = {c.id: c for c in db.query(Customer).all()}

    for period, entries in period_candidates.items():
        yr, mo = int(period.split("-")[0]), int(period.split("-")[1])
        if mo == 12:
            end_of_period = date(yr, 12, 31)
        else:
            end_of_period = date(yr, mo + 1, 1) - timedelta(days=1)
        days_since_end = (today - end_of_period).days
        window_open = days_since_end < 45

        for cust_id, p, outcome in entries:
            customer = customer_cache.get(cust_id)
            insured = customer.full_name if customer else None
            norm_name = normalize_name(insured) if insured else ""

            record = RetentionRecord(
                policy_number=p["policy_number"],
                insured_name=insured,
                carrier=p["carrier"],
                original_period=period,
                expected_renewal_period=period,
                original_premium=Decimal(str(p["premium"])) if p["premium"] else None,
                term_months=12,
                customer_name_normalized=norm_name,
                customer_id=cust_id,
            )

            kind = outcome["kind"] if outcome else None

            if kind in ("renewed", "rewritten_same_carrier"):
                newp = outcome["new"]
                record.outcome = kind
                record.renewal_period = period
                record.renewal_premium = Decimal(str(newp["premium"])) if newp["premium"] else None
                if kind == "rewritten_same_carrier":
                    record.new_carrier = newp["carrier"]
                    record.new_policy_number = newp["policy_number"]
                    record.new_premium = Decimal(str(newp["premium"])) if newp["premium"] else None
                if record.original_premium and record.renewal_premium:
                    record.premium_change = record.renewal_premium - record.original_premium
                    if record.original_premium > 0:
                        pct = record.premium_change / record.original_premium * 100
                        record.premium_change_pct = min(max(pct, Decimal("-999")), Decimal("999"))
                stats["renewed" if kind == "renewed" else "rewritten_same_carrier"] += 1

            elif kind == "carrier_move":
                newp = outcome["new"]
                record.outcome = "carrier_move"
                record.new_carrier = newp["carrier"]
                record.new_policy_number = newp["policy_number"]
                record.new_premium = Decimal(str(newp["premium"])) if newp["premium"] else None
                record.renewal_period = period
                stats["carrier_moved"] += 1

            elif kind == "partial_retention":
                record.outcome = "partial_retention"
                stats["partial_retention"] += 1

            elif kind == "lost":
                if window_open:
                    record.outcome = "pending"
                    stats["pending"] += 1
                else:
                    record.outcome = "lost"
                    stats["lost"] += 1
            else:
                record.outcome = "pending"
                stats["pending"] += 1

            record.last_analyzed_at = datetime.utcnow()
            db.add(record)
            stats["created"] += 1

    db.commit()
    _rebuild_summaries(db)

    return {"status": "success", "stats": stats, "periods_analyzed": periods}


# ──────────────────────────────────────────────────────────────────────
# Summary rebuild
# ──────────────────────────────────────────────────────────────────────

def _rebuild_summaries(db: Session):
    """Rebuild RetentionSummary rows from RetentionRecord data."""
    periods = [p[0] for p in db.query(RetentionRecord.original_period).distinct().all()]

    for period in periods:
        records = db.query(RetentionRecord).filter(
            RetentionRecord.original_period == period
        ).all()
        if not records:
            continue

        total = len(records)
        renewed = sum(1 for r in records if r.outcome == "renewed")
        carrier_moved = sum(1 for r in records if r.outcome == "carrier_move")
        rewritten = sum(1 for r in records if r.outcome == "rewritten_same_carrier")
        partial = sum(1 for r in records if r.outcome == "partial_retention")
        lost = sum(1 for r in records if r.outcome == "lost")
        pending = sum(1 for r in records if r.outcome == "pending")

        resolved = total - pending
        retained = renewed + carrier_moved + rewritten
        true_retention_rate = (retained / resolved * 100) if resolved > 0 else None
        policy_retention_rate = (renewed / resolved * 100) if resolved > 0 else None

        orig_premium = sum(float(r.original_premium or 0) for r in records)
        renewed_premium = sum(
            float(r.renewal_premium or r.new_premium or 0)
            for r in records
            if r.outcome in ("renewed", "carrier_move", "rewritten_same_carrier")
        )
        lost_premium = sum(
            float(r.original_premium or 0)
            for r in records
            if r.outcome == "lost"
        )

        changes = [
            float(r.premium_change_pct)
            for r in records
            if r.premium_change_pct is not None and r.outcome == "renewed"
        ]
        avg_change = sum(changes) / len(changes) if changes else None

        summary = db.query(RetentionSummary).filter(
            RetentionSummary.period == period
        ).first()
        if not summary:
            summary = RetentionSummary(period=period)
            db.add(summary)

        summary.policies_up_for_renewal = total
        summary.policies_renewed = renewed
        summary.policies_carrier_moved = carrier_moved
        summary.policies_rewritten = rewritten
        summary.policies_lost = lost + partial
        summary.policies_pending = pending
        summary.true_retention_rate = true_retention_rate
        summary.policy_retention_rate = policy_retention_rate
        summary.original_total_premium = orig_premium
        summary.renewed_total_premium = renewed_premium
        summary.lost_premium = lost_premium
        summary.avg_premium_change_pct = avg_change

    # Purge orphan summaries for periods that no longer have any records.
    if periods:
        orphans = db.query(RetentionSummary).filter(
            ~RetentionSummary.period.in_(periods)
        ).all()
        for orph in orphans:
            db.delete(orph)

    db.commit()
