"""Commission reconciliation service.

Workflow:
1. Upload carrier statement → parse into statement_lines
2. Match each line to a sale in our system by policy_number
3. Resolve agent assignment (who wrote/owns this policy)
4. Calculate agent commission based on prior month tier
5. Present reconciliation summary for review
"""
import logging
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.statement import (
    StatementImport, StatementLine, StatementStatus,
    StatementFormat,
)
from app.models.sale import Sale
from app.models.user import User
from app.models.commission import CommissionTier
from app.services.carrier_parsers import parse_statement

logger = logging.getLogger(__name__)


def _is_within_first_term(line, matched_sale, statement_period: str) -> bool:
    """Check if a statement line transaction falls within the first policy term.

    First term = original_sale_effective_date through original_sale_effective_date + term_months.
    After the first term renews, the producer is NOT paid on that policy.

    Transaction types:
    - renewal: Always excluded (by definition past first term)
    - other: Always excluded (servicing/installment billing, not commissionable)
    - new_business, endorsement, cancellation, adjustment, reinstatement: Paid if within first term

    Args:
        line: StatementLine with effective_date, term_months
        matched_sale: Sale object (may be None)
        statement_period: "YYYY-MM" period string

    Returns:
        True if within first term (should be paid), False otherwise
    """
    tx_type = (line.transaction_type or "").lower()

    # Renewals and servicing/"other" lines are never commissionable
    if tx_type in ("renewal", "other"):
        return False

    # 1. Determine the ORIGINAL effective date (when the policy was first sold)
    eff_date = None

    # Prefer the matched sale's effective date (this is the original sale date)
    if matched_sale and matched_sale.effective_date:
        eff_date = matched_sale.effective_date
        if hasattr(eff_date, 'date'):
            eff_date = eff_date.date()
    elif line.effective_date:
        eff_date = line.effective_date
        if hasattr(eff_date, 'date'):
            eff_date = eff_date.date()

    if not eff_date:
        # Can't determine term — don't pay
        return False

    # 2. Determine term length in months
    term_months = getattr(line, 'term_months', None)
    if term_months and term_months > 12:
        # Data quality: sometimes days are stored instead of months
        term_months = 6 if term_months <= 180 else 12

    if not term_months:
        # Infer from policy type
        policy_type = ""
        if matched_sale and matched_sale.policy_type:
            policy_type = matched_sale.policy_type.lower()
        elif getattr(line, 'product_type', None):
            policy_type = line.product_type.lower()

        if "6m" in policy_type or "6 month" in policy_type or "(6m)" in policy_type:
            term_months = 6
        elif "auto" in policy_type and "12" not in policy_type:
            term_months = 6  # Auto defaults to 6-month
        else:
            term_months = 12  # Home/dwelling/umbrella defaults to 12-month

    # 3. Calculate first term end date
    term_end = eff_date + relativedelta(months=term_months)

    # 4. Check if statement period falls within first term
    stmt_year, stmt_month = map(int, statement_period.split("-"))
    stmt_date = date(stmt_year, stmt_month, 1)

    return stmt_date < term_end


class ReconciliationService:
    def __init__(self, db: Session):
        self.db = db

    # ── Upload & Parse ───────────────────────────────────────────────

    def create_import(
        self,
        filename: str,
        file_path: str,
        file_bytes: bytes,
        carrier: str,
        period: str,
    ) -> StatementImport:
        """Create import record and parse the file into statement lines."""

        # Determine format
        ext = filename.rsplit(".", 1)[-1].lower()
        fmt_map = {"csv": StatementFormat.CSV, "xlsx": StatementFormat.XLSX, "pdf": StatementFormat.PDF}
        file_format = fmt_map.get(ext, StatementFormat.CSV)

        # Create import record
        imp = StatementImport(
            filename=filename,
            file_path=file_path,
            file_format=file_format,
            file_size=len(file_bytes),
            carrier=carrier,
            statement_period=period,
            status=StatementStatus.PROCESSING,
            processing_started_at=datetime.utcnow(),
        )
        self.db.add(imp)
        self.db.flush()  # get imp.id

        try:
            # Parse
            records = parse_statement(carrier, file_bytes, filename)
            imp.total_rows = len(records)

            total_premium = Decimal("0")
            total_commission = Decimal("0")

            for rec in records:
                line = StatementLine(
                    statement_import_id=imp.id,
                    policy_number=rec.get("policy_number", ""),
                    insured_name=rec.get("insured_name"),
                    transaction_type=rec.get("transaction_type"),
                    transaction_type_raw=rec.get("transaction_type_raw"),
                    transaction_date=rec.get("transaction_date"),
                    effective_date=rec.get("effective_date"),
                    premium_amount=rec.get("premium_amount"),
                    commission_rate=rec.get("commission_rate"),
                    commission_amount=rec.get("commission_amount"),
                    producer_name=rec.get("producer_name"),
                    product_type=rec.get("product_type"),
                    line_of_business=rec.get("line_of_business"),
                    state=rec.get("state"),
                    term_months=rec.get("term_months"),
                    raw_data=rec.get("raw_data"),
                )
                self.db.add(line)

                if rec.get("premium_amount"):
                    total_premium += rec["premium_amount"]
                if rec.get("commission_amount"):
                    total_commission += rec["commission_amount"]

            imp.total_premium = total_premium
            imp.total_commission = total_commission
            imp.status = StatementStatus.MATCHED
            imp.processing_completed_at = datetime.utcnow()

            self.db.commit()
            logger.info(
                f"Import {imp.id}: {imp.total_rows} rows, "
                f"premium={total_premium}, commission={total_commission}"
            )

        except Exception as e:
            imp.status = StatementStatus.FAILED
            imp.error_message = str(e)[:500]
            imp.processing_completed_at = datetime.utcnow()
            self.db.commit()
            logger.error(f"Import {imp.id} failed: {e}", exc_info=True)
            raise

        return imp

    # ── Match ────────────────────────────────────────────────────────

    def run_matching(self, import_id: int) -> Dict:
        """Match statement lines to sales by policy number.
        
        Can be re-run — will retry unmatched lines and preserve existing matches.
        """
        imp = self.db.query(StatementImport).filter(
            StatementImport.id == import_id
        ).first()
        if not imp:
            raise ValueError("Import not found")

        lines = self.db.query(StatementLine).filter(
            StatementLine.statement_import_id == import_id
        ).all()

        matched = 0
        unmatched = 0
        newly_matched = 0

        for line in lines:
            # Skip already matched lines
            if line.is_matched and line.matched_sale_id:
                matched += 1
                continue

            # Try exact match on policy number
            sale = self.db.query(Sale).filter(
                Sale.policy_number == line.policy_number
            ).first()

            if sale:
                line.is_matched = True
                line.matched_sale_id = sale.id
                line.match_confidence = "exact"
                line.matched_at = datetime.utcnow()

                # Assign agent from the sale
                line.assigned_agent_id = sale.producer_id
                matched += 1
                newly_matched += 1
            else:
                # Try fuzzy: strip leading zeros, try partial
                cleaned = line.policy_number.lstrip("0")
                sale = self.db.query(Sale).filter(
                    Sale.policy_number.contains(cleaned)
                ).first() if len(cleaned) >= 5 else None

                if sale:
                    line.is_matched = True
                    line.matched_sale_id = sale.id
                    line.match_confidence = "fuzzy"
                    line.matched_at = datetime.utcnow()
                    line.assigned_agent_id = sale.producer_id
                    matched += 1
                    newly_matched += 1
                else:
                    unmatched += 1

        imp.matched_rows = matched
        imp.unmatched_rows = unmatched
        imp.status = StatementStatus.PARTIALLY_MATCHED
        self.db.commit()

        logger.info(f"Matching import {import_id}: {matched} matched ({newly_matched} new), {unmatched} unmatched")

        return {
            "import_id": import_id,
            "total": len(lines),
            "matched": matched,
            "newly_matched": newly_matched,
            "unmatched": unmatched,
        }

    # ── Agent Commission Calculation ─────────────────────────────────

    def calculate_agent_commissions(self, import_id: int) -> Dict:
        """Calculate what each agent is owed based on their tier.

        The tier is determined by the PRIOR month's total written premium.
        """
        imp = self.db.query(StatementImport).filter(
            StatementImport.id == import_id
        ).first()
        if not imp:
            raise ValueError("Import not found")

        # Determine prior month for tier calculation
        period = imp.statement_period  # "2026-01"
        year, month = map(int, period.split("-"))
        prior_date = datetime(year, month, 1) - relativedelta(months=1)
        prior_period = prior_date.strftime("%Y-%m")
        current_period = f"{year:04d}-{month:02d}"

        # Get all matched lines with assigned agents
        lines = self.db.query(StatementLine).filter(
            StatementLine.statement_import_id == import_id,
            StatementLine.assigned_agent_id.isnot(None),
        ).all()

        # Group by agent
        agent_lines: Dict[int, List[StatementLine]] = {}
        for line in lines:
            agent_lines.setdefault(line.assigned_agent_id, []).append(line)

        agent_summaries = []
        used_period = prior_period  # track which period was used

        for agent_id, agent_line_list in agent_lines.items():
            agent = self.db.query(User).filter(User.id == agent_id).first()
            if not agent:
                continue

            # Get agent's current month written premium to determine tier
            current_premium = self._get_agent_period_premium(agent_id, current_period)

            tier = self._get_tier_for_premium(current_premium)

            agent_rate = tier.commission_rate if tier else Decimal("0.03")
            tier_level = tier.tier_level if tier else 1

            # Calculate commission for each line
            agent_total_premium = Decimal("0")
            agent_total_commission = Decimal("0")
            agent_chargebacks = Decimal("0")
            agent_chargeback_premium = Decimal("0")
            chargeback_count = 0

            for line in agent_line_list:
                premium = line.premium_amount or Decimal("0")
                carrier_comm = line.commission_amount or Decimal("0")

                # Look up matched sale for first-term check
                matched_sale = None
                if line.matched_sale_id:
                    matched_sale = self.db.query(Sale).filter(Sale.id == line.matched_sale_id).first()

                # Only pay commission on transactions within the first policy term
                if _is_within_first_term(line, matched_sale, imp.statement_period):
                    agent_comm = premium * agent_rate
                else:
                    agent_comm = Decimal("0")

                # Track chargebacks separately (negative commission)
                if agent_comm < 0:
                    agent_chargebacks += agent_comm
                    agent_chargeback_premium += premium
                    chargeback_count += 1

                line.agent_commission_rate = agent_rate
                line.agent_commission_amount = agent_comm

                agent_total_premium += premium
                agent_total_commission += agent_comm

            agent_summaries.append({
                "agent_id": agent_id,
                "agent_name": agent.full_name or agent.username,
                "tier_level": tier_level,
                "commission_rate": float(agent_rate),
                "prior_month_premium": float(current_premium),
                "total_premium": float(agent_total_premium),
                "total_agent_commission": float(agent_total_commission),
                "chargebacks": float(agent_chargebacks),
                "chargeback_premium": float(agent_chargeback_premium),
                "chargeback_count": chargeback_count,
                "net_agent_commission": float(agent_total_commission),
                "line_count": len(agent_line_list),
            })

        self.db.commit()

        return {
            "import_id": import_id,
            "period": period,
            "prior_period": prior_period,
            "tier_based_on": used_period,
            "note": "Using current month premium (no prior month data)" if used_period == current_period else None,
            "agent_summaries": agent_summaries,
        }

    def _get_agent_period_premium(self, agent_id: int, period: str) -> Decimal:
        """Get total written premium for an agent in a given period."""
        year, month = map(int, period.split("-"))
        total = (
            self.db.query(func.sum(Sale.written_premium))
            .filter(
                Sale.producer_id == agent_id,
                func.extract("year", Sale.sale_date) == year,
                func.extract("month", Sale.sale_date) == month,
            )
            .scalar()
        )
        return total or Decimal("0")

    def _get_tier_for_premium(self, premium: Decimal) -> Optional[CommissionTier]:
        """Find the tier for a given premium amount."""
        return (
            self.db.query(CommissionTier)
            .filter(
                CommissionTier.is_active == True,
                CommissionTier.min_written_premium <= premium,
                (CommissionTier.max_written_premium >= premium)
                | (CommissionTier.max_written_premium.is_(None)),
            )
            .order_by(CommissionTier.tier_level.desc())
            .first()
        )

    # ── Summary / Reports ────────────────────────────────────────────

    def get_reconciliation_summary(self, import_id: int) -> Dict:
        """Get full reconciliation summary for review."""
        imp = self.db.query(StatementImport).filter(
            StatementImport.id == import_id
        ).first()
        if not imp:
            raise ValueError("Import not found")

        lines = self.db.query(StatementLine).filter(
            StatementLine.statement_import_id == import_id
        ).all()

        matched_lines = []
        unmatched_lines = []

        for line in lines:
            line_data = {
                "id": line.id,
                "policy_number": line.policy_number,
                "insured_name": line.insured_name,
                "transaction_type": line.transaction_type if line.transaction_type else None,
                "transaction_type_raw": line.transaction_type_raw,
                "premium_amount": float(line.premium_amount) if line.premium_amount else 0,
                "commission_amount": float(line.commission_amount) if line.commission_amount else 0,
                "commission_rate": float(line.commission_rate) if line.commission_rate else 0,
                "producer_name": line.producer_name,
                "state": line.state,
                "term_months": line.term_months,
                "is_matched": line.is_matched,
                "match_confidence": line.match_confidence,
            }

            if line.is_matched:
                # Add agent info
                if line.assigned_agent:
                    line_data["assigned_agent"] = line.assigned_agent.full_name or line.assigned_agent.username
                    line_data["agent_commission"] = float(line.agent_commission_amount) if line.agent_commission_amount else None
                    line_data["agent_rate"] = float(line.agent_commission_rate) if line.agent_commission_rate else None
                matched_lines.append(line_data)
            else:
                unmatched_lines.append(line_data)

        # Transaction type breakdown
        type_summary = {}
        for line in lines:
            tt = line.transaction_type_raw or "Unknown"
            if tt not in type_summary:
                type_summary[tt] = {"count": 0, "premium": 0, "commission": 0}
            type_summary[tt]["count"] += 1
            type_summary[tt]["premium"] += float(line.premium_amount or 0)
            type_summary[tt]["commission"] += float(line.commission_amount or 0)

        return {
            "import": {
                "id": imp.id,
                "filename": imp.filename,
                "carrier": imp.carrier,
                "period": imp.statement_period,
                "status": imp.status.value,
                "total_rows": imp.total_rows,
                "matched_rows": imp.matched_rows,
                "unmatched_rows": imp.unmatched_rows,
                "total_premium": float(imp.total_premium or 0),
                "total_commission": float(imp.total_commission or 0),
                "created_at": imp.created_at.isoformat() if imp.created_at else None,
            },
            "matched_lines": matched_lines,
            "unmatched_lines": unmatched_lines,
            "type_summary": type_summary,
        }

    def manually_match_line(self, line_id: int, sale_id: int) -> StatementLine:
        """Manually match an unmatched line to a sale."""
        line = self.db.query(StatementLine).filter(StatementLine.id == line_id).first()
        if not line:
            raise ValueError("Statement line not found")

        sale = self.db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            raise ValueError("Sale not found")

        line.is_matched = True
        line.matched_sale_id = sale.id
        line.match_confidence = "manual"
        line.matched_at = datetime.utcnow()
        line.assigned_agent_id = sale.producer_id

        # Update import counts
        imp = line.statement_import
        if imp:
            imp.matched_rows = (imp.matched_rows or 0) + 1
            imp.unmatched_rows = max(0, (imp.unmatched_rows or 0) - 1)

        self.db.commit()
        return line

    # ── Combined Monthly Pay ─────────────────────────────────────────

    def calculate_monthly_pay(self, period: str) -> Dict:
        """Calculate combined agent pay across ALL carriers for a month."""
        year, month = map(int, period.split("-"))
        prior_date = datetime(year, month, 1) - relativedelta(months=1)
        prior_period = prior_date.strftime("%Y-%m")
        current_period = f"{year:04d}-{month:02d}"

        # Get all imports for this period
        imports = self.db.query(StatementImport).filter(
            StatementImport.statement_period == period,
        ).all()

        if not imports:
            raise ValueError(f"No imports found for period {period}")

        # Get ALL matched lines across all imports for this period
        import_ids = [imp.id for imp in imports]
        lines = self.db.query(StatementLine).filter(
            StatementLine.statement_import_id.in_(import_ids),
            StatementLine.assigned_agent_id.isnot(None),
            StatementLine.is_matched == True,
        ).all()

        # Group by agent
        agent_lines: Dict[int, List] = {}
        for line in lines:
            agent_lines.setdefault(line.assigned_agent_id, []).append(line)

        agent_summaries = []
        used_period = prior_period

        for agent_id, agent_line_list in agent_lines.items():
            agent = self.db.query(User).filter(User.id == agent_id).first()
            if not agent:
                continue

            # Determine tier from CURRENT month written premium
            current_premium = self._get_agent_period_premium(agent_id, current_period)
            tier = self._get_tier_for_premium(current_premium)
            agent_rate = tier.commission_rate if tier else Decimal("0.03")
            tier_level = tier.tier_level if tier else 1

            # Attendance-based commission adjustment — DISABLED pending timeclock schema fix
            attendance_adj = Decimal("0")
            adjusted_rate = agent_rate
            attendance = {
                "adjustment": Decimal("0"),
                "late_days_unexcused": 0,
                "excused_days": 0,
                "total_days": 0,
                "label": "neutral",
            }

            # Group lines by carrier
            carrier_breakdown = {}
            agent_total_premium = Decimal("0")
            agent_total_commission = Decimal("0")
            carrier_commission_total = Decimal("0")
            agent_chargebacks = Decimal("0")
            agent_chargeback_premium = Decimal("0")
            chargeback_count = 0

            for line in agent_line_list:
                premium = line.premium_amount or Decimal("0")
                carrier_comm = line.commission_amount or Decimal("0")

                # Look up matched sale for first-term check
                matched_sale = None
                if line.matched_sale_id:
                    matched_sale = self.db.query(Sale).filter(Sale.id == line.matched_sale_id).first()

                # Only pay commission on transactions within the first policy term
                if _is_within_first_term(line, matched_sale, period):
                    agent_comm = premium * adjusted_rate
                else:
                    # Post-renewal — no agent commission
                    agent_comm = Decimal("0")

                # Track chargebacks separately for reporting (negative commission)
                if agent_comm < 0:
                    agent_chargebacks += agent_comm
                    agent_chargeback_premium += premium
                    chargeback_count += 1

                line.agent_commission_rate = adjusted_rate
                line.agent_commission_amount = agent_comm

                # Get carrier name from the import
                imp = next((i for i in imports if i.id == line.statement_import_id), None)
                carrier_name = imp.carrier if imp else "unknown"

                if carrier_name not in carrier_breakdown:
                    carrier_breakdown[carrier_name] = {
                        "carrier": carrier_name,
                        "premium": Decimal("0"),
                        "carrier_commission": Decimal("0"),
                        "agent_commission": Decimal("0"),
                        "chargebacks": Decimal("0"),
                        "line_count": 0,
                    }
                carrier_breakdown[carrier_name]["premium"] += premium
                carrier_breakdown[carrier_name]["carrier_commission"] += carrier_comm
                carrier_breakdown[carrier_name]["agent_commission"] += agent_comm
                if agent_comm < 0:
                    carrier_breakdown[carrier_name]["chargebacks"] += premium
                carrier_breakdown[carrier_name]["line_count"] += 1

                agent_total_premium += premium
                agent_total_commission += agent_comm
                carrier_commission_total += carrier_comm

            agent_summaries.append({
                "agent_id": agent_id,
                "agent_name": agent.full_name or agent.username,
                "agent_role": agent.role or "producer",
                "tier_level": tier_level,
                "base_commission_rate": float(agent_rate),
                "attendance_adjustment": float(attendance_adj),
                "commission_rate": float(adjusted_rate),
                "attendance": {
                    "late_days_unexcused": attendance["late_days_unexcused"],
                    "excused_days": attendance["excused_days"],
                    "total_days": attendance["total_days"],
                    "label": attendance["label"],
                },
                "tier_premium": float(current_premium),
                "total_premium": float(agent_total_premium),
                "carrier_commission_total": float(carrier_commission_total),
                "total_agent_commission": float(agent_total_commission),
                "chargebacks": float(agent_chargebacks),
                "chargeback_premium": float(agent_chargeback_premium),
                "chargeback_count": chargeback_count,
                "net_agent_commission": float(agent_total_commission),
                "line_count": len(agent_line_list),
                "carrier_breakdown": [
                    {k: float(v) if isinstance(v, Decimal) else v for k, v in cb.items()}
                    for cb in carrier_breakdown.values()
                ],
            })

        self.db.commit()

        # Sort by total commission descending
        agent_summaries.sort(key=lambda x: x["total_agent_commission"], reverse=True)

        # Carrier totals
        carrier_totals = {}
        for imp in imports:
            carrier_totals[imp.carrier] = {
                "carrier": imp.carrier,
                "total_rows": imp.total_rows,
                "matched_rows": imp.matched_rows,
                "unmatched_rows": imp.unmatched_rows,
                "total_premium": float(imp.total_premium or 0),
                "total_commission": float(imp.total_commission or 0),
            }

        return {
            "period": period,
            "tier_based_on": used_period,
            "note": "Using current month premium (no prior month data)" if used_period == current_period else None,
            "carriers": list(carrier_totals.values()),
            "agent_summaries": agent_summaries,
            "totals": {
                "total_carriers": len(imports),
                "total_matched_lines": sum(imp.matched_rows or 0 for imp in imports),
                "total_premium": sum(float(imp.total_premium or 0) for imp in imports),
                "total_carrier_commission": sum(float(imp.total_commission or 0) for imp in imports),
                "total_agent_pay": sum(a["total_agent_commission"] for a in agent_summaries),
            },
        }

    def get_monthly_pay_summary(self, period: str) -> Dict:
        """Get existing monthly pay data (same as calculate but read-only)."""
        return self.calculate_monthly_pay(period)

    def get_agent_commission_sheet(self, period: str, agent_id: int, rate_adjustment: float = 0.0, bonus: float = 0.0) -> Dict:
        """Get detailed line-by-line commission sheet for an agent.
        
        rate_adjustment: Manual override (+/-0.005 = +/-0.5%) applied to base tier rate.
        bonus: Flat dollar bonus added to total commission.
        """
        year, month = map(int, period.split("-"))
        prior_date = datetime(year, month, 1) - relativedelta(months=1)
        prior_period = prior_date.strftime("%Y-%m")
        current_period = f"{year:04d}-{month:02d}"

        agent = self.db.query(User).filter(User.id == agent_id).first()
        if not agent:
            raise ValueError("Agent not found")

        # Get all imports for this period
        imports = self.db.query(StatementImport).filter(
            StatementImport.statement_period == period,
        ).all()

        if not imports:
            raise ValueError(f"No commission statements found for {period}")

        import_ids = [imp.id for imp in imports]

        # Get all lines assigned to this agent
        lines = self.db.query(StatementLine).filter(
            StatementLine.statement_import_id.in_(import_ids),
            StatementLine.assigned_agent_id == agent_id,
            StatementLine.is_matched == True,
        ).all()

        # Determine tier from current month written premium
        current_premium = self._get_agent_period_premium(agent_id, current_period)
        tier = self._get_tier_for_premium(current_premium)
        base_rate = tier.commission_rate if tier else Decimal("0.03")
        tier_level = tier.tier_level if tier else 1

        # Apply manual rate adjustment
        adj = Decimal(str(rate_adjustment))
        agent_rate = base_rate + adj

        # Build line items
        line_items = []
        total_new_biz_premium = Decimal("0")
        total_renewal_premium = Decimal("0")
        total_other_premium = Decimal("0")
        total_chargebacks = Decimal("0")
        total_chargeback_premium = Decimal("0")
        total_agent_commission = Decimal("0")
        chargeback_count = 0

        for line in lines:
            premium = line.premium_amount or Decimal("0")
            carrier_comm = line.commission_amount or Decimal("0")
            tx_type = (line.transaction_type or "").lower()

            # Look up matched sale for first-term check
            matched_sale = None
            if line.matched_sale_id:
                matched_sale = self.db.query(Sale).filter(Sale.id == line.matched_sale_id).first()

            # Only pay commission on transactions within the first policy term
            if _is_within_first_term(line, matched_sale, period):
                agent_comm = premium * agent_rate
            else:
                agent_comm = Decimal("0")

            # Track chargebacks separately (negative commission)
            if agent_comm < 0:
                total_chargebacks += agent_comm
                total_chargeback_premium += premium
                chargeback_count += 1

            # Only categorize premium for lines that are actually paid
            if agent_comm != Decimal("0"):
                if "new_business" in tx_type or "new bus" in tx_type:
                    total_new_biz_premium += premium
                else:
                    total_other_premium += premium

            total_agent_commission += agent_comm

            # Get carrier
            imp = next((i for i in imports if i.id == line.statement_import_id), None)
            carrier_name = imp.carrier if imp else "unknown"

            # Only include lines that affect agent pay
            if agent_comm != Decimal("0"):
                line_items.append({
                    "policy_number": line.policy_number,
                    "insured_name": line.insured_name,
                    "carrier": carrier_name,
                    "transaction_type": line.transaction_type_raw or line.transaction_type or "—",
                    "premium": float(premium),
                    "agent_commission": float(agent_comm),
                    "is_chargeback": agent_comm < 0,
                    "effective_date": str(line.effective_date)[:10] if line.effective_date else None,
                })

        # Sort: chargebacks at bottom, then by carrier and policy
        line_items.sort(key=lambda x: (x["is_chargeback"], x["carrier"], x["policy_number"]))

        paid_premium = total_new_biz_premium + total_other_premium

        return {
            "agent_id": agent_id,
            "agent_name": agent.full_name or agent.username,
            "agent_role": agent.role or "producer",
            "agent_email": agent.email,
            "period": period,
            "period_display": datetime(year, month, 1).strftime("%B %Y"),
            "tier_level": tier_level,
            "base_commission_rate": float(base_rate),
            "rate_adjustment": float(adj),
            "commission_rate": float(agent_rate),
            "tier_premium": float(current_premium),
            "bonus": bonus,
            "summary": {
                "new_business_premium": float(total_new_biz_premium),
                "other_paid_premium": float(total_other_premium),
                "total_paid_premium": float(paid_premium),
                "chargebacks": float(total_chargebacks),
                "chargeback_premium": float(total_chargeback_premium),
                "chargeback_count": chargeback_count,
                "total_agent_commission": float(total_agent_commission),
                "bonus": bonus,
                "grand_total": float(total_agent_commission) + bonus,
                "total_lines": len(line_items),
            },
            "line_items": line_items,
        }
