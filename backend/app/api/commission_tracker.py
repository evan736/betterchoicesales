"""Commission Payment Tracker API.

Tracks expected vs actual commission payments across all carriers.
Automatically creates expectations from new sales and renewals,
matches them against incoming commission statements, and flags
any policies that are overdue for payment.

Special handling for Travelers:
- Pays on effective date cycle (~20th to ~20th)
- Only pays when customer makes first premium payment
- 45-day grace window before flagging as overdue
"""
import logging
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, and_, or_, extract
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.commission_tracker import CommissionExpectation
from app.models.sale import Sale
from app.models.reshop import Reshop
from app.models.statement import StatementLine, StatementImport
from app.models.user import User
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/commission-tracker", tags=["commission-tracker"])

# Default commission rates by carrier (approximate — used for estimates)
CARRIER_COMMISSION_RATES = {
    "travelers": {"new_business": Decimal("0.15"), "renewal": Decimal("0.10")},
    "grange": {"new_business": Decimal("0.10"), "renewal": Decimal("0.10")},
    "national_general": {"new_business": Decimal("0.15"), "renewal": Decimal("0.12")},
    "safeco": {"new_business": Decimal("0.15"), "renewal": Decimal("0.12")},
    "progressive": {"new_business": Decimal("0.10"), "renewal": Decimal("0.08")},
    "default": {"new_business": Decimal("0.12"), "renewal": Decimal("0.10")},
}

# Days after effective date before flagging as overdue (by carrier)
OVERDUE_THRESHOLDS = {
    "travelers": 45,  # Travelers is slow — pays on effective date, needs first payment
    "grange": 35,
    "safeco": 30,
    "default": 35,
}


def _get_carrier_rate(carrier: str, source_type: str) -> Decimal:
    carrier_key = (carrier or "").lower().replace(" ", "_")
    rates = CARRIER_COMMISSION_RATES.get(carrier_key, CARRIER_COMMISSION_RATES["default"])
    return rates.get(source_type, rates.get("new_business", Decimal("0.12")))


def _get_overdue_days(carrier: str) -> int:
    carrier_key = (carrier or "").lower().replace(" ", "_")
    return OVERDUE_THRESHOLDS.get(carrier_key, OVERDUE_THRESHOLDS["default"])


def _normalize_policy(pn: str) -> str:
    """Normalize policy number for matching."""
    return (pn or "").replace(" ", "").replace("-", "").replace("/", "").strip().upper()


# ── Scan & Create Expectations ─────────────────────────────────────

@router.post("/scan-sales")
def scan_sales_for_expectations(
    start_date: str = Query(None, description="YYYY-MM-DD, defaults to 60 days ago"),
    end_date: str = Query(None, description="YYYY-MM-DD, defaults to today"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Scan recent sales and create commission expectations for any not yet tracked."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    now = datetime.utcnow()
    sd = datetime.strptime(start_date, "%Y-%m-%d") if start_date else now - timedelta(days=60)
    ed = datetime.strptime(end_date, "%Y-%m-%d") if end_date else now

    # Get sales in date range
    sales = db.query(Sale).filter(
        Sale.effective_date >= sd,
        Sale.effective_date <= ed,
        Sale.status != "cancelled",
    ).all()

    created = 0
    skipped = 0

    for sale in sales:
        # Check if already tracked
        existing = db.query(CommissionExpectation).filter(
            CommissionExpectation.source_type == "new_business",
            CommissionExpectation.source_id == sale.id,
        ).first()
        if existing:
            skipped += 1
            continue

        carrier = (sale.carrier or "").lower()
        rate = _get_carrier_rate(carrier, "new_business")
        premium = sale.written_premium or Decimal("0")
        eff = sale.effective_date
        if not eff:
            skipped += 1
            continue

        overdue_days = _get_overdue_days(carrier)
        if hasattr(eff, 'date'):
            eff_date_val = eff
        else:
            eff_date_val = datetime.combine(eff, datetime.min.time())

        exp = CommissionExpectation(
            source_type="new_business",
            source_id=sale.id,
            policy_number=sale.policy_number,
            customer_name=sale.client_name,
            carrier=sale.carrier or "Unknown",
            policy_type=sale.policy_type,
            expected_premium=premium,
            expected_commission=premium * rate,
            expected_commission_rate=rate,
            effective_date=eff_date_val,
            expected_payment_by=eff_date_val + timedelta(days=overdue_days),
            status="pending",
            producer_id=sale.producer_id,
            producer_name=None,  # resolved via relationship
        )
        db.add(exp)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "total_sales_scanned": len(sales)}


@router.post("/scan-renewals")
def scan_renewals_for_expectations(
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Scan reshops marked as renewed/bound and create commission expectations."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    now = datetime.utcnow()
    sd = datetime.strptime(start_date, "%Y-%m-%d") if start_date else now - timedelta(days=60)
    ed = datetime.strptime(end_date, "%Y-%m-%d") if end_date else now

    # Get reshops that were renewed/bound recently
    reshops = db.query(Reshop).filter(
        Reshop.stage.in_(["bound", "renewed"]),
        Reshop.updated_at >= sd,
        Reshop.updated_at <= ed,
    ).all()

    created = 0
    skipped = 0

    for reshop in reshops:
        existing = db.query(CommissionExpectation).filter(
            CommissionExpectation.source_type == "renewal",
            CommissionExpectation.source_id == reshop.id,
        ).first()
        if existing:
            skipped += 1
            continue

        carrier = (reshop.carrier or "").lower()
        rate = _get_carrier_rate(carrier, "renewal")
        # Use quoted premium if available, else current premium
        premium = reshop.quoted_premium or reshop.current_premium or Decimal("0")
        eff = reshop.expiration_date  # renewal effective = old policy expiration
        if not eff:
            skipped += 1
            continue

        if hasattr(eff, 'date'):
            eff_date_val = eff
        else:
            eff_date_val = datetime.combine(eff, datetime.min.time())

        overdue_days = _get_overdue_days(carrier)

        exp = CommissionExpectation(
            source_type="renewal",
            source_id=reshop.id,
            policy_number=reshop.policy_number or "unknown",
            customer_name=reshop.customer_name,
            carrier=reshop.carrier or "Unknown",
            policy_type=reshop.line_of_business,
            expected_premium=premium,
            expected_commission=premium * rate,
            expected_commission_rate=rate,
            effective_date=eff_date_val,
            expected_payment_by=eff_date_val + timedelta(days=overdue_days),
            status="pending",
            producer_id=reshop.assigned_to,
        )
        db.add(exp)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "total_renewals_scanned": len(reshops)}


# ── Auto-Match Against Statements ──────────────────────────────────

@router.post("/auto-match")
def auto_match_expectations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Match pending expectations against commission statement lines."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    pending = db.query(CommissionExpectation).filter(
        CommissionExpectation.status == "pending",
    ).all()

    matched = 0
    for exp in pending:
        pn_norm = _normalize_policy(exp.policy_number)
        if len(pn_norm) < 5:
            continue

        # Search statement lines for this policy using DB query
        search_key = pn_norm[:9] if len(pn_norm) >= 9 else pn_norm

        # Find lines where policy number starts with our search key
        matching_lines = db.query(StatementLine).join(
            StatementImport, StatementLine.statement_import_id == StatementImport.id
        ).filter(
            StatementLine.policy_number.isnot(None),
            StatementImport.carrier.ilike(f"%{(exp.carrier or '')[:4]}%"),
        ).all()

        for line in matching_lines:
            line_norm = _normalize_policy(line.policy_number)
            if len(line_norm) >= 9 and line_norm[:9] == search_key:
                if line.premium_amount and abs(float(line.premium_amount)) > 1:
                    exp.status = "paid"
                    exp.matched_statement_line_id = line.id
                    exp.matched_amount = line.commission_amount or line.premium_amount
                    exp.matched_at = datetime.utcnow()
                    matched += 1
                    break

    # Also update overdue status for unmatched
    now = datetime.utcnow()
    overdue_count = 0
    still_pending = db.query(CommissionExpectation).filter(
        CommissionExpectation.status == "pending",
        CommissionExpectation.expected_payment_by < now,
    ).all()
    for exp in still_pending:
        exp.status = "overdue"
        exp.flag_reason = f"No commission payment received within {_get_overdue_days(exp.carrier)} days of effective date"
        overdue_count += 1

    db.commit()
    return {"matched": matched, "newly_overdue": overdue_count, "total_checked": len(pending)}


# ── Dashboard / List ───────────────────────────────────────────────

@router.get("/")
def get_commission_tracker_dashboard(
    status: str = Query(None, description="Filter by status: pending, paid, overdue, flagged, resolved"),
    carrier: str = Query(None),
    source_type: str = Query(None, description="new_business or renewal"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get commission tracker dashboard with summary and filtered list."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    # Summary counts
    summary = {}
    for s in ["pending", "paid", "overdue", "flagged", "resolved"]:
        q = db.query(func.count(CommissionExpectation.id)).filter(
            CommissionExpectation.status == s
        )
        summary[s] = q.scalar() or 0

    # Total expected vs paid
    total_expected = db.query(func.sum(CommissionExpectation.expected_commission)).scalar() or 0
    total_paid = db.query(func.sum(CommissionExpectation.matched_amount)).filter(
        CommissionExpectation.status == "paid"
    ).scalar() or 0
    total_overdue = db.query(func.sum(CommissionExpectation.expected_commission)).filter(
        CommissionExpectation.status == "overdue"
    ).scalar() or 0

    # Filtered list
    query = db.query(CommissionExpectation).order_by(CommissionExpectation.effective_date.desc())
    if status:
        query = query.filter(CommissionExpectation.status == status)
    if carrier:
        query = query.filter(CommissionExpectation.carrier.ilike(f"%{carrier}%"))
    if source_type:
        query = query.filter(CommissionExpectation.source_type == source_type)

    items = query.limit(200).all()

    return {
        "summary": {
            **summary,
            "total_expected_commission": float(total_expected),
            "total_paid_commission": float(total_paid),
            "total_overdue_commission": float(total_overdue),
        },
        "items": [
            {
                "id": e.id,
                "source_type": e.source_type,
                "source_id": e.source_id,
                "policy_number": e.policy_number,
                "customer_name": e.customer_name,
                "carrier": e.carrier,
                "policy_type": e.policy_type,
                "expected_premium": float(e.expected_premium or 0),
                "expected_commission": float(e.expected_commission or 0),
                "effective_date": e.effective_date.isoformat() if e.effective_date else None,
                "expected_payment_by": e.expected_payment_by.isoformat() if e.expected_payment_by else None,
                "status": e.status,
                "matched_amount": float(e.matched_amount or 0),
                "matched_at": e.matched_at.isoformat() if e.matched_at else None,
                "flag_reason": e.flag_reason,
                "resolution_notes": e.resolution_notes,
                "producer_name": e.producer_name,
                "days_since_effective": (datetime.utcnow() - e.effective_date).days if e.effective_date else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in items
        ],
    }


@router.post("/{expectation_id}/resolve")
def resolve_expectation(
    expectation_id: int,
    notes: str = Query(..., description="Resolution notes"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually resolve an overdue/flagged expectation."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    exp = db.query(CommissionExpectation).filter(CommissionExpectation.id == expectation_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Expectation not found")

    exp.status = "resolved"
    exp.resolution_notes = notes
    exp.resolved_at = datetime.utcnow()
    exp.resolved_by = current_user.id
    db.commit()
    return {"status": "resolved", "id": exp.id}


@router.post("/{expectation_id}/flag")
def flag_expectation(
    expectation_id: int,
    reason: str = Query(..., description="Flag reason"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually flag an expectation for follow-up."""
    exp = db.query(CommissionExpectation).filter(CommissionExpectation.id == expectation_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Expectation not found")

    exp.status = "flagged"
    exp.flag_reason = reason
    db.commit()
    return {"status": "flagged", "id": exp.id}


# ── Carrier-Specific Report ───────────────────────────────────────

@router.get("/carrier-report/{carrier}")
def get_carrier_commission_report(
    carrier: str,
    months: int = Query(3, description="How many months back to look"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Detailed commission tracking report for a specific carrier."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    cutoff = datetime.utcnow() - timedelta(days=months * 30)

    expectations = db.query(CommissionExpectation).filter(
        CommissionExpectation.carrier.ilike(f"%{carrier}%"),
        CommissionExpectation.effective_date >= cutoff,
    ).order_by(CommissionExpectation.effective_date.desc()).all()

    by_status = {}
    for exp in expectations:
        by_status.setdefault(exp.status, []).append(exp)

    return {
        "carrier": carrier,
        "months": months,
        "total_expectations": len(expectations),
        "by_status": {
            status: {
                "count": len(items),
                "total_expected": sum(float(e.expected_commission or 0) for e in items),
                "total_premium": sum(float(e.expected_premium or 0) for e in items),
                "policies": [
                    {
                        "id": e.id,
                        "policy_number": e.policy_number,
                        "customer_name": e.customer_name,
                        "source_type": e.source_type,
                        "expected_premium": float(e.expected_premium or 0),
                        "expected_commission": float(e.expected_commission or 0),
                        "effective_date": e.effective_date.isoformat() if e.effective_date else None,
                        "days_since_effective": (datetime.utcnow() - e.effective_date).days if e.effective_date else None,
                        "matched_amount": float(e.matched_amount or 0) if e.matched_amount else None,
                        "flag_reason": e.flag_reason,
                    }
                    for e in items
                ],
            }
            for status, items in by_status.items()
        },
    }
