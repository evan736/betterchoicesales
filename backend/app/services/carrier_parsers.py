"""Carrier-specific commission statement parsers.

Each parser normalizes carrier-specific column names and formats
into a standard dict structure for the reconciliation engine.

Standard output per line:
{
    "policy_number": str,
    "insured_name": str,
    "transaction_type": TransactionType,
    "transaction_type_raw": str,
    "transaction_date": datetime | None,
    "effective_date": datetime | None,
    "premium_amount": Decimal,
    "commission_rate": Decimal,  # as decimal e.g. 0.15
    "commission_amount": Decimal,
    "producer_name": str | None,
    "product_type": str | None,
    "line_of_business": str | None,
    "state": str | None,
    "term_months": int | None,
    "raw_data": str,
}
"""
import logging
import io
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Optional
from datetime import datetime

import pandas as pd

from app.models.statement import TransactionType

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────

def _clean_currency(val) -> Optional[Decimal]:
    """Parse currency strings like '$2,677.00', '-$249.14', '1,545.00'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s or s == "nan":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        logger.warning(f"Could not parse currency: '{val}'")
        return None


def _clean_rate(val) -> Optional[Decimal]:
    """Parse rate strings like '15.00%', '0.15', '12'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("%", "").replace(",", "")
    if not s or s == "nan":
        return None
    try:
        d = Decimal(s)
        # If > 1, assume it's a percentage (15.0 -> 0.15)
        if d > 1:
            d = d / Decimal("100")
        return d
    except InvalidOperation:
        return None


def _parse_date(val) -> Optional[datetime]:
    """Try common date formats."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(s)
    except Exception:
        return None


def _parse_term(val) -> Optional[int]:
    """Parse term like 'N12', 'R6', '12', '6'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().upper()
    # Strip leading letter (N12 -> 12, R6 -> 6)
    digits = "".join(c for c in s if c.isdigit())
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def _map_transaction_type(raw: str) -> TransactionType:
    """Map carrier-specific transaction type to our enum."""
    if not raw:
        return TransactionType.OTHER
    r = raw.strip().upper()

    new_biz = ["NEW BUSINESS", "NEW BUS-A", "NEW BUS", "NB", "NEW"]
    renewal = ["RENEWAL", "RENEW", "REN", "RWL"]
    endorse = ["ENDORSEMENT", "ENDORS", "REVISION", "CHANGE", "ENDORSEMENTS"]
    cancel = ["CANCEL", "CANCELLATION", "CANCEL-NP", "CANCEL-INS", "CANCELLATIONS"]
    reinstate = ["REINSTATEMENT", "REINSTATEMENTS", "REINSTATE"]
    audit = ["AUDIT", "AUDIT PREM"]
    adjust = ["ADJUST", "ADJUSTMENT", "ADJUSTMENTS", "CHARGEBACK",
              "LOSS HIST CHARGEBACK", "VIOLATION HISTORY CHARGEBACK",
              "UNCOLLECTED PREMIUM", "UNCOLLECTED PREMIUM REIMBURSEMENT",
              "RECOUPMENTS", "APP INCENTIVE"]

    if any(r.startswith(x) or r == x for x in new_biz):
        return TransactionType.NEW_BUSINESS
    if any(r.startswith(x) or r == x for x in renewal):
        return TransactionType.RENEWAL
    if any(r.startswith(x) or r == x for x in endorse):
        return TransactionType.ENDORSEMENT
    if any(r.startswith(x) or r == x for x in cancel):
        return TransactionType.CANCELLATION
    if any(r.startswith(x) or r == x for x in reinstate):
        return TransactionType.REINSTATEMENT
    if any(r.startswith(x) or r == x for x in audit):
        return TransactionType.AUDIT
    if any(r.startswith(x) or r == x for x in adjust):
        return TransactionType.ADJUSTMENT

    return TransactionType.OTHER


# ── NATIONAL GENERAL parser ──────────────────────────────────────────

def parse_national_general(file_bytes: bytes, filename: str) -> List[Dict]:
    """Parse National General XLSX commission statement.

    Uses 'Summary Details' sheet which has per-policy detail:
    Columns: Sub Agent, Selling Producer, Policy, Product, DIV,
             Sub Product, State, Insured, Eff Date, Trans Type,
             Written Premium, Rate, Commission Paid, Term
    """
    records = []
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))

        # Primary: Summary Details sheet
        if "Summary Details" in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name="Summary Details")
        elif "All Producers" in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name="All Producers")
        else:
            # Fallback: first sheet with enough columns
            df = pd.read_excel(xls, sheet_name=0)

        logger.info(f"National General: {len(df)} rows, columns: {list(df.columns)}")

        # Column mapping (flexible matching)
        col_map = {}
        for c in df.columns:
            cl = str(c).lower().strip()
            if "policy" in cl and "number" not in cl:
                col_map["policy"] = c
            elif "insured" in cl:
                col_map["insured"] = c
            elif "selling" in cl and "producer" in cl:
                col_map["producer"] = c
            elif cl == "policy":
                col_map["policy"] = c
            elif "trans" in cl and "type" in cl:
                col_map["trans_type"] = c
            elif "written" in cl and "premium" in cl:
                col_map["premium"] = c
            elif cl == "premium":
                col_map["premium"] = c
            elif cl == "rate":
                col_map["rate"] = c
            elif "commission" in cl and ("paid" in cl or "amount" in cl):
                col_map["commission"] = c
            elif cl == "commission":
                col_map["commission"] = c
            elif cl == "term":
                col_map["term"] = c
            elif "eff" in cl and "date" in cl:
                col_map["eff_date"] = c
            elif cl == "state":
                col_map["state"] = c
            elif "sub product" in cl or "product" in cl:
                col_map["product"] = c

        logger.info(f"National General column map: {col_map}")

        for _, row in df.iterrows():
            # Extract policy - may be in format "2033396050 00"
            policy_raw = str(row.get(col_map.get("policy", ""), "")).strip()
            if not policy_raw or policy_raw == "nan":
                continue
            # Take first part before space if it has a modifier
            policy_number = policy_raw.split()[0] if " " in policy_raw else policy_raw

            raw_type = str(row.get(col_map.get("trans_type", ""), ""))

            records.append({
                "policy_number": policy_number,
                "insured_name": str(row.get(col_map.get("insured", ""), "") or "").strip(),
                "transaction_type": _map_transaction_type(raw_type),
                "transaction_type_raw": raw_type,
                "effective_date": _parse_date(row.get(col_map.get("eff_date", ""))),
                "premium_amount": _clean_currency(row.get(col_map.get("premium", ""))),
                "commission_rate": _clean_rate(row.get(col_map.get("rate", ""))),
                "commission_amount": _clean_currency(row.get(col_map.get("commission", ""))),
                "producer_name": str(row.get(col_map.get("producer", ""), "") or "").strip(),
                "product_type": str(row.get(col_map.get("product", ""), "") or "").strip(),
                "state": str(row.get(col_map.get("state", ""), "") or "").strip()[:2],
                "term_months": _parse_term(row.get(col_map.get("term", ""))),
                "raw_data": str(row.to_dict()),
            })

        # Also parse Adjustments sheet if present
        if "Adjustments" in xls.sheet_names:
            adj_df = pd.read_excel(xls, sheet_name="Adjustments")
            for _, row in adj_df.iterrows():
                quote = str(row.get("Quote Num", "") or "").strip()
                if not quote or quote == "nan":
                    continue
                raw_type = str(row.get("TransType", "") or "")
                records.append({
                    "policy_number": quote,
                    "insured_name": str(row.get("Drivers Name", "") or "").strip(),
                    "transaction_type": _map_transaction_type(raw_type),
                    "transaction_type_raw": raw_type,
                    "effective_date": _parse_date(row.get("Order Date")),
                    "premium_amount": Decimal("0"),
                    "commission_rate": None,
                    "commission_amount": _clean_currency(row.get("Amount")),
                    "producer_name": str(row.get("Quoting Producer", "") or "").strip(),
                    "product_type": str(row.get("Product", "") or "").strip(),
                    "state": str(row.get("Gov State", "") or "").strip()[:2],
                    "term_months": None,
                    "raw_data": str(row.to_dict()),
                })

    except Exception as e:
        logger.error(f"Error parsing National General: {e}", exc_info=True)
        raise

    logger.info(f"National General: parsed {len(records)} records")
    return records


# ── GRANGE parser ────────────────────────────────────────────────────

def parse_grange(file_bytes: bytes, filename: str) -> List[Dict]:
    """Parse Grange CSV commission statement.

    Columns: Date, NPN, Producer Name, Risk State,
             Policyholder Name or Description, Policy Number, MOD,
             Date Entered, Transaction Description, Premium Amount,
             Comm %, Commission Amount, Commission Rate Reason
    """
    records = []
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
        logger.info(f"Grange: {len(df)} rows, columns: {list(df.columns)}")

        for _, row in df.iterrows():
            # Policy number may have product prefix like "DF  5148587"
            policy_raw = str(row.get("Policy Number", "")).strip()
            if not policy_raw or policy_raw == "nan" or policy_raw == "0000000":
                continue

            # Clean policy number - remove product prefix
            # "DF  5148587" -> "5148587", "HM  6605796" -> "6605796"
            parts = policy_raw.split()
            if len(parts) >= 2 and len(parts[0]) <= 3:
                policy_number = parts[-1]
                product_code = parts[0]
            else:
                policy_number = policy_raw
                product_code = ""

            raw_type = str(row.get("Transaction Description", ""))

            records.append({
                "policy_number": policy_number,
                "insured_name": str(row.get("Policyholder Name or Description", "") or "").strip(),
                "transaction_type": _map_transaction_type(raw_type),
                "transaction_type_raw": raw_type,
                "transaction_date": _parse_date(row.get("Date Entered")),
                "effective_date": _parse_date(row.get("Date")),
                "premium_amount": _clean_currency(row.get("Premium Amount")),
                "commission_rate": _clean_rate(row.get("Comm %")),
                "commission_amount": _clean_currency(row.get("Commission Amount")),
                "producer_name": str(row.get("Producer Name", "") or "").strip(),
                "product_type": product_code,
                "state": str(row.get("Risk State", "") or "").strip()[:2],
                "term_months": None,  # Grange doesn't include term
                "raw_data": str(row.to_dict()),
            })

    except Exception as e:
        logger.error(f"Error parsing Grange: {e}", exc_info=True)
        raise

    logger.info(f"Grange: parsed {len(records)} records")
    return records


# ── PROGRESSIVE parser ───────────────────────────────────────────────

def parse_progressive(file_bytes: bytes, filename: str) -> List[Dict]:
    """Parse Progressive CSV commission statement.

    Columns: Agent Stat Number, Statement Date, Line of Business,
             Sub Line of Business, Product Type, Insured Name,
             Policy Number, Ren Conversion Ind, Policy Effective Date,
             State, Pay Plan, Transaction Effective Date, Term Length,
             Activity Type, Premium, Comm Rate, Comm Amount, ...
    """
    records = []
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
        logger.info(f"Progressive: {len(df)} rows, columns: {list(df.columns)}")

        for _, row in df.iterrows():
            policy_number = str(row.get("Policy Number", "")).strip()
            if not policy_number or policy_number == "nan":
                continue

            raw_type = str(row.get("Activity Type", ""))

            records.append({
                "policy_number": policy_number,
                "insured_name": str(row.get("Insured Name", "") or "").strip(),
                "transaction_type": _map_transaction_type(raw_type),
                "transaction_type_raw": raw_type,
                "transaction_date": _parse_date(row.get("Transaction Effective Date")),
                "effective_date": _parse_date(row.get("Policy Effective Date")),
                "premium_amount": _clean_currency(row.get("Premium")),
                "commission_rate": _clean_rate(row.get("Comm Rate")),
                "commission_amount": _clean_currency(row.get("Comm Amount")),
                "producer_name": None,  # Progressive doesn't include producer name
                "product_type": str(row.get("Product Type", "") or "").strip(),
                "line_of_business": str(row.get("Line of Business", "") or "").strip(),
                "state": str(row.get("State", "") or "").strip()[:2],
                "term_months": _parse_term(row.get("Term Length")),
                "raw_data": str(row.to_dict()),
            })

    except Exception as e:
        logger.error(f"Error parsing Progressive: {e}", exc_info=True)
        raise

    logger.info(f"Progressive: parsed {len(records)} records")
    return records


# ── Generic / auto-detect parser ─────────────────────────────────────

def parse_generic(file_bytes: bytes, filename: str) -> List[Dict]:
    """Attempt to auto-detect columns for unknown carrier formats."""
    records = []
    try:
        if filename.lower().endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            df = pd.read_csv(io.BytesIO(file_bytes))

        logger.info(f"Generic parser: {len(df)} rows, columns: {list(df.columns)}")

        # Auto-detect column mapping
        col_map = {}
        for c in df.columns:
            cl = str(c).lower().strip()
            if "policy" in cl and ("num" in cl or "#" in cl or cl == "policy number"):
                col_map["policy"] = c
            elif "insured" in cl or "policyholder" in cl or "name" in cl:
                if "policy" not in col_map.get("insured", "").lower():
                    col_map["insured"] = c
            elif "premium" in cl and "commission" not in cl:
                col_map["premium"] = c
            elif "commission" in cl and ("amt" in cl or "amount" in cl):
                col_map["commission"] = c
            elif "comm" in cl and "rate" in cl:
                col_map["rate"] = c
            elif "trans" in cl and ("type" in cl or "desc" in cl):
                col_map["trans_type"] = c
            elif "date" in cl and "trans" not in col_map:
                col_map["date"] = c

        if "policy" not in col_map:
            raise ValueError(f"Could not find policy number column in: {list(df.columns)}")

        for _, row in df.iterrows():
            policy = str(row.get(col_map["policy"], "")).strip()
            if not policy or policy == "nan":
                continue

            raw_type = str(row.get(col_map.get("trans_type", ""), ""))

            records.append({
                "policy_number": policy,
                "insured_name": str(row.get(col_map.get("insured", ""), "") or "").strip(),
                "transaction_type": _map_transaction_type(raw_type),
                "transaction_type_raw": raw_type,
                "premium_amount": _clean_currency(row.get(col_map.get("premium", ""))),
                "commission_rate": _clean_rate(row.get(col_map.get("rate", ""))),
                "commission_amount": _clean_currency(row.get(col_map.get("commission", ""))),
                "transaction_date": _parse_date(row.get(col_map.get("date", ""))),
                "raw_data": str(row.to_dict()),
            })

    except Exception as e:
        logger.error(f"Error in generic parser: {e}", exc_info=True)
        raise

    logger.info(f"Generic: parsed {len(records)} records")
    return records


# ── Dispatcher ───────────────────────────────────────────────────────

CARRIER_PARSERS = {
    "national_general": parse_national_general,
    "progressive": parse_progressive,
    "grange": parse_grange,
}


def parse_statement(carrier: str, file_bytes: bytes, filename: str) -> List[Dict]:
    """Route to the correct carrier parser."""
    parser = CARRIER_PARSERS.get(carrier, parse_generic)
    return parser(file_bytes, filename)
