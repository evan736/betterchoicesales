"""Retention analysis service.

Analyzes commission statement data to determine true customer retention.
Key insight: a policy cancelling at one carrier but the same customer
starting at another carrier = retained (carrier move), not lost.

Runs automatically after statement upload/matching.
"""
import logging
import re
from datetime import datetime
from decimal import Decimal
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models.statement import StatementLine, StatementImport
from app.models.retention import RetentionRecord, RetentionSummary
from app.models.customer import Customer, CustomerPolicy

logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Normalize a customer name for fuzzy matching.
    
    Strips suffixes, lowercases, removes extra whitespace.
    'JOHN A SMITH JR' -> 'john smith'
    'Smith, John' -> 'john smith'
    """
    if not name:
        return ""
    n = name.strip().upper()
    # Remove common suffixes
    for suffix in [" JR", " SR", " III", " II", " IV", " MD", " DDS"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)]
    # Handle "Last, First" format
    if "," in n:
        parts = n.split(",", 1)
        n = f"{parts[1].strip()} {parts[0].strip()}"
    # Remove middle initials (single letters between spaces)
    n = re.sub(r'\b[A-Z]\b', '', n)
    # Remove extra whitespace, lowercase
    n = re.sub(r'\s+', ' ', n).strip().lower()
    return n


def normalize_policy_number(pn: str) -> str:
    """Strip spaces, dashes, tabs for comparison."""
    if not pn:
        return ""
    return pn.replace(" ", "").replace("-", "").replace("\t", "").strip().upper()


def run_retention_analysis(db: Session) -> dict:
    """Analyze all statement data to build retention records.
    
    Logic:
    1. Find all policies that appeared on statements (any transaction type)
    2. Group by insured name (normalized) to identify unique customers
    3. For each policy with a new_business or first appearance:
       - Look for a renewal transaction in later periods
       - If no renewal found, check if same customer has a NEW policy at different carrier
       - If neither, check NowCerts for active policies
       - If nothing found, mark as lost
    """
    
    stats = {"created": 0, "updated": 0, "renewed": 0, "carrier_moved": 0, "lost": 0, "pending": 0}
    
    # Get all statement lines grouped by policy number
    all_lines = db.query(
        StatementLine.policy_number,
        StatementLine.insured_name,
        StatementLine.transaction_type,
        StatementLine.premium_amount,
        StatementLine.effective_date,
        StatementLine.term_months,
        StatementLine.is_renewal_term,
        StatementImport.carrier,
        StatementImport.statement_period,
    ).join(
        StatementImport, StatementLine.statement_import_id == StatementImport.id
    ).order_by(
        StatementImport.statement_period
    ).all()

    if not all_lines:
        return {"status": "no_data", "stats": stats}

    # Build a map of all policies: policy_number -> list of appearances
    policy_map = defaultdict(list)
    for line in all_lines:
        pn_norm = normalize_policy_number(line.policy_number)
        policy_map[pn_norm].append({
            "policy_number": line.policy_number,
            "insured_name": line.insured_name,
            "transaction_type": (line.transaction_type or "").lower(),
            "premium": line.premium_amount,
            "effective_date": line.effective_date,
            "term_months": line.term_months or 12,
            "is_renewal_term": line.is_renewal_term,
            "carrier": line.carrier,
            "period": line.statement_period,
        })

    # Build customer name -> set of policy numbers (normalized)
    customer_policies = defaultdict(set)
    name_to_carriers = defaultdict(set)
    name_to_policies_by_carrier = defaultdict(lambda: defaultdict(set))
    policy_to_name = {}

    for pn_norm, appearances in policy_map.items():
        for app in appearances:
            norm_name = normalize_name(app["insured_name"])
            if norm_name:
                customer_policies[norm_name].add(pn_norm)
                name_to_carriers[norm_name].add(app["carrier"])
                name_to_policies_by_carrier[norm_name][app["carrier"]].add(pn_norm)
                policy_to_name[pn_norm] = norm_name

    # Determine all periods we have data for
    all_periods = sorted(set(line.statement_period for line in all_lines))
    latest_period = all_periods[-1] if all_periods else None
    
    # Find policies that are "up for renewal" — they appeared as new_business
    # or had a first appearance, and we want to see if they renewed
    for pn_norm, appearances in policy_map.items():
        # Sort appearances by period
        appearances.sort(key=lambda x: x["period"])
        
        first_app = appearances[0]
        latest_app = appearances[-1]
        carrier = first_app["carrier"]
        insured = first_app["insured_name"]
        norm_name = normalize_name(insured)
        premium = first_app["premium"] or Decimal("0")
        term = first_app["term_months"] or 12
        
        # Determine if this policy has renewed
        has_renewal = any(
            a["transaction_type"] in ("renewal", "ren", "renl")
            for a in appearances
        )
        
        # Check if there's a newer new_business at the same carrier (rewrite)
        has_new_biz = [
            a for a in appearances
            if a["transaction_type"] in ("new_business", "new business", "nb")
        ]
        
        # Determine the period this policy should renew
        first_period = first_app["period"]
        
        # Skip if this is a renewal-only policy (we're tracking from original)
        if first_app["transaction_type"] in ("renewal", "ren", "renl") and not has_new_biz:
            # This is a renewal of an older policy — track it but differently
            pass
        
        # Check or create retention record
        existing = db.query(RetentionRecord).filter(
            RetentionRecord.policy_number == first_app["policy_number"],
            RetentionRecord.original_period == first_period,
        ).first()

        if not existing:
            existing = RetentionRecord(
                policy_number=first_app["policy_number"],
                insured_name=insured,
                carrier=carrier,
                original_period=first_period,
                original_premium=abs(premium) if premium else None,
                term_months=term,
                customer_name_normalized=norm_name,
            )
            db.add(existing)
            stats["created"] += 1
        else:
            stats["updated"] += 1

        # Calculate expected renewal period
        try:
            year, month = int(first_period.split("-")[0]), int(first_period.split("-")[1])
            renew_month = month + term
            renew_year = year + (renew_month - 1) // 12
            renew_month = ((renew_month - 1) % 12) + 1
            expected_renewal = f"{renew_year:04d}-{renew_month:02d}"
            existing.expected_renewal_period = expected_renewal
        except (ValueError, IndexError):
            expected_renewal = None

        # Determine outcome
        if has_renewal:
            # Find the renewal line
            renewal_app = next(
                (a for a in appearances if a["transaction_type"] in ("renewal", "ren", "renl")),
                None
            )
            existing.outcome = "renewed"
            if renewal_app:
                existing.renewal_period = renewal_app["period"]
                existing.renewal_premium = abs(renewal_app["premium"]) if renewal_app["premium"] else None
                if existing.original_premium and existing.renewal_premium:
                    existing.premium_change = existing.renewal_premium - existing.original_premium
                    if existing.original_premium > 0:
                        existing.premium_change_pct = (
                            existing.premium_change / existing.original_premium * 100
                        )
            stats["renewed"] += 1

        elif expected_renewal and latest_period and expected_renewal > latest_period:
            # Renewal period hasn't arrived yet
            existing.outcome = "pending"
            stats["pending"] += 1

        else:
            # Policy didn't renew — check if customer moved carriers
            if norm_name and len(name_to_carriers.get(norm_name, set())) > 1:
                # Customer has policies at multiple carriers
                other_carriers = name_to_carriers[norm_name] - {carrier}
                # Check if there's a newer policy at another carrier
                other_policy_periods = []
                for other_carrier in other_carriers:
                    for other_pn in name_to_policies_by_carrier[norm_name][other_carrier]:
                        other_apps = policy_map.get(other_pn, [])
                        for oa in other_apps:
                            if oa["period"] >= first_period:
                                other_policy_periods.append(oa)
                
                if other_policy_periods:
                    # Customer moved to another carrier — not lost
                    newest = max(other_policy_periods, key=lambda x: x["period"])
                    existing.outcome = "carrier_move"
                    existing.new_carrier = newest["carrier"]
                    existing.new_policy_number = newest["policy_number"]
                    existing.new_premium = abs(newest["premium"]) if newest["premium"] else None
                    stats["carrier_moved"] += 1
                else:
                    # Check NowCerts for active policies
                    active = _check_nowcerts_active(db, norm_name, insured)
                    if active:
                        existing.outcome = "carrier_move"
                        existing.new_carrier = active.get("carrier")
                        existing.new_policy_number = active.get("policy_number")
                        existing.new_premium = active.get("premium")
                        stats["carrier_moved"] += 1
                    else:
                        existing.outcome = "lost"
                        stats["lost"] += 1
            else:
                # Only one carrier seen — check NowCerts for active policies
                active = _check_nowcerts_active(db, norm_name, insured)
                if active:
                    if active.get("carrier", "").lower() != (carrier or "").lower():
                        existing.outcome = "carrier_move"
                        existing.new_carrier = active.get("carrier")
                    else:
                        existing.outcome = "rewritten_same_carrier"
                        existing.new_carrier = active.get("carrier")
                    existing.new_policy_number = active.get("policy_number")
                    existing.new_premium = active.get("premium")
                    stats["carrier_moved"] += 1
                else:
                    existing.outcome = "lost"
                    stats["lost"] += 1

        existing.last_analyzed_at = datetime.utcnow()

    db.commit()

    # Rebuild summaries
    _rebuild_summaries(db)

    return {"status": "success", "stats": stats, "periods_analyzed": all_periods}


def _check_nowcerts_active(db: Session, norm_name: str, raw_name: str) -> Optional[dict]:
    """Check if customer has any active policies in NowCerts (customer_policies table)."""
    if not norm_name and not raw_name:
        return None

    # Try matching by name parts
    parts = (raw_name or "").strip().split()
    if len(parts) < 2:
        return None

    last_name = parts[-1]
    first_name = parts[0]

    # Find customer by name
    customer = db.query(Customer).filter(
        Customer.last_name.ilike(f"%{last_name}%"),
        Customer.first_name.ilike(f"%{first_name}%"),
    ).first()

    if not customer:
        # Try just last name
        customer = db.query(Customer).filter(
            Customer.last_name.ilike(f"%{last_name}%"),
        ).first()

    if not customer:
        return None

    # Check for active policies
    active_policy = db.query(CustomerPolicy).filter(
        CustomerPolicy.customer_id == customer.id,
        CustomerPolicy.status.in_(["Active", "active", "In Force", "in force"]),
    ).first()

    if active_policy:
        return {
            "carrier": active_policy.carrier,
            "policy_number": active_policy.policy_number,
            "premium": active_policy.premium,
        }

    return None


def _rebuild_summaries(db: Session):
    """Rebuild retention summaries from retention records."""
    # Get all periods with records
    periods = db.query(
        RetentionRecord.original_period
    ).distinct().all()

    for (period,) in periods:
        records = db.query(RetentionRecord).filter(
            RetentionRecord.original_period == period
        ).all()

        if not records:
            continue

        total = len(records)
        renewed = sum(1 for r in records if r.outcome == "renewed")
        carrier_moved = sum(1 for r in records if r.outcome == "carrier_move")
        rewritten = sum(1 for r in records if r.outcome in ("rewritten_same_carrier",))
        lost = sum(1 for r in records if r.outcome == "lost")
        pending = sum(1 for r in records if r.outcome == "pending")

        resolved = total - pending
        true_retained = renewed + carrier_moved + rewritten
        true_retention_rate = (true_retained / resolved * 100) if resolved > 0 else None
        policy_retention_rate = (renewed / resolved * 100) if resolved > 0 else None

        orig_premium = sum(float(r.original_premium or 0) for r in records)
        renewed_premium = sum(float(r.renewal_premium or r.new_premium or 0) 
                             for r in records if r.outcome in ("renewed", "carrier_move", "rewritten_same_carrier"))
        lost_premium = sum(float(r.original_premium or 0) for r in records if r.outcome == "lost")

        changes = [float(r.premium_change_pct) for r in records 
                   if r.premium_change_pct is not None and r.outcome == "renewed"]
        avg_change = sum(changes) / len(changes) if changes else None

        # Upsert summary
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
        summary.policies_lost = lost
        summary.policies_pending = pending
        summary.true_retention_rate = true_retention_rate
        summary.policy_retention_rate = policy_retention_rate
        summary.original_total_premium = orig_premium
        summary.renewed_total_premium = renewed_premium
        summary.lost_premium = lost_premium
        summary.avg_premium_change_pct = avg_change

    db.commit()
