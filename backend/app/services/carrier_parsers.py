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
    """Parse term like 'N12', 'R6', '12', '6', 12.0."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    # Handle numeric types directly (e.g. pandas float 12.0 -> 12)
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().upper()
    # Handle "12.0" string from pandas
    if '.' in s:
        try:
            return int(float(s))
        except ValueError:
            pass
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
    cancel = ["CANCEL", "CANCELLATION", "CANCEL-NP", "CANCEL-INS", "CANCELLATIONS",
              "CANCEL PRO RATE", "CANCEL FLAT"]
    reinstate = ["REINSTATEMENT", "REINSTATEMENTS", "REINSTATE"]
    audit = ["AUDIT", "AUDIT PREM"]
    adjust = ["ADJUST", "ADJUSTMENT", "ADJUSTMENTS", "CHARGEBACK",
              "LOSS HIST CHARGEBACK", "VIOLATION HISTORY CHARGEBACK",
              "UNCOLLECTED PREMIUM", "UNCOLLECTED PREMIUM REIMBURSEMENT",
              "RECOUPMENTS", "APP INCENTIVE",
              "CREDIT ENDORSEMENT", "UNHON", "WAIVED"]

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
                "transaction_type": _map_transaction_type(raw_type).value,
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
                    "transaction_type": _map_transaction_type(raw_type).value,
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
                "transaction_type": _map_transaction_type(raw_type).value,
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
    """Parse Progressive XLSX commission statement.

    Actual columns: Insured Name, Policy Number, Policy Effective Date,
    Policy Expiration Date, Prod, Agt Pre, Tran Code, Tran Date,
    Gross Premium, Gross Comm, Net Due Agent, Prod Name, Agent Code,
    Month End, Renewal Count
    """
    records = []
    try:
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))

        logger.info(f"Progressive: {len(df)} rows, columns: {list(df.columns)}")

        for _, row in df.iterrows():
            policy_number = str(row.get("Policy Number", "")).strip()
            if not policy_number or policy_number == "nan":
                continue

            raw_type = str(row.get("Tran Code", "")).strip()
            premium = _clean_currency(row.get("Gross Premium"))
            comm = _clean_currency(row.get("Gross Comm"))
            comm_rate = _clean_rate(row.get("Comm"))

            # Get producer name
            prod_name = str(row.get("Prod Name", "") or "").strip()

            # Determine product line
            prod_line = str(row.get("Prod", "") or "").strip()

            records.append({
                "policy_number": policy_number,
                "insured_name": str(row.get("Insured Name", "") or "").strip(),
                "transaction_type": _map_transaction_type(raw_type).value,
                "transaction_type_raw": raw_type,
                "transaction_date": _parse_date(row.get("Tran Date")),
                "effective_date": _parse_date(row.get("Policy Effective Date")),
                "premium_amount": premium,
                "commission_rate": comm_rate,
                "commission_amount": comm,
                "producer_name": prod_name if prod_name and prod_name != "nan" else None,
                "product_type": prod_line,
                "line_of_business": prod_line,
                "state": None,  # Progressive doesn't include state in this format
                "term_months": 6 if prod_line == "Auto" else 12,  # Progressive auto is 6mo
                "raw_data": str(row.to_dict()),
            })

    except Exception as e:
        logger.error(f"Error parsing Progressive: {e}", exc_info=True)
        raise

    logger.info(f"Progressive: parsed {len(records)} records")
    return records


def parse_safeco(file_bytes: bytes, filename: str) -> List[Dict]:
    """Parse Safeco (Liberty Mutual) commission statement.

    Safeco statements come as CSV or XLSX and may have columns like:
    Policy Number, Named Insured, Transaction Type, Effective Date,
    Transaction Date, Written Premium, Commission Rate, Commission Amount,
    Line of Business, State, Producer, Term
    
    Also handles alternate column names from Safeco's portal exports.
    """
    records = []
    try:
        # Try CSV first, then Excel
        if filename.lower().endswith(('.csv', '.txt')):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))

        logger.info(f"Safeco: {len(df)} rows, columns: {list(df.columns)}")

        # Flexible column mapping - Safeco has varied exports
        col_map = {}
        for c in df.columns:
            cl = str(c).strip().lower().replace(" ", "_")
            if "policy" in cl and ("num" in cl or "no" in cl or cl == "policy"):
                col_map["policy"] = c
            elif "insured" in cl or "named_insured" in cl or "name" in cl:
                col_map["insured"] = c
            elif "trans" in cl and "type" in cl:
                col_map["trans_type"] = c
            elif "activity" in cl and "type" in cl:
                col_map["trans_type"] = c
            elif "trans" in cl and "date" in cl:
                col_map["trans_date"] = c
            elif "eff" in cl and "date" in cl:
                col_map["eff_date"] = c
            elif "premium" in cl and ("written" in cl or "net" in cl or cl == "premium"):
                col_map["premium"] = c
            elif "comm" in cl and ("rate" in cl or "pct" in cl or "percent" in cl):
                col_map["comm_rate"] = c
            elif "comm" in cl and ("amt" in cl or "amount" in cl or cl == "commission"):
                col_map["comm_amount"] = c
            elif "state" in cl and "code" not in cl:
                col_map["state"] = c
            elif "producer" in cl or "agent" in cl or "writer" in cl:
                col_map["producer"] = c
            elif "line" in cl and "bus" in cl:
                col_map["lob"] = c
            elif "term" in cl:
                col_map["term"] = c
            elif "product" in cl:
                col_map["product"] = c

        logger.info(f"Safeco column map: {col_map}")

        for _, row in df.iterrows():
            policy_number = str(row.get(col_map.get("policy", "Policy Number"), "")).strip()
            if not policy_number or policy_number == "nan":
                continue

            raw_type = str(row.get(col_map.get("trans_type", "Transaction Type"), "") or "")

            records.append({
                "policy_number": policy_number,
                "insured_name": str(row.get(col_map.get("insured", "Named Insured"), "") or "").strip(),
                "transaction_type": _map_transaction_type(raw_type).value,
                "transaction_type_raw": raw_type,
                "transaction_date": _parse_date(row.get(col_map.get("trans_date", "Transaction Date"))),
                "effective_date": _parse_date(row.get(col_map.get("eff_date", "Effective Date"))),
                "premium_amount": _clean_currency(row.get(col_map.get("premium", "Written Premium"))),
                "commission_rate": _clean_rate(row.get(col_map.get("comm_rate", "Commission Rate"))),
                "commission_amount": _clean_currency(row.get(col_map.get("comm_amount", "Commission Amount"))),
                "producer_name": str(row.get(col_map.get("producer", "Producer"), "") or "").strip() or None,
                "product_type": str(row.get(col_map.get("product", "Product"), "") or "").strip(),
                "line_of_business": str(row.get(col_map.get("lob", "Line of Business"), "") or "").strip(),
                "state": str(row.get(col_map.get("state", "State"), "") or "").strip()[:2],
                "term_months": _parse_term(row.get(col_map.get("term", "Term"))),
                "raw_data": str(row.to_dict()),
            })

    except Exception as e:
        logger.error(f"Error parsing Safeco: {e}", exc_info=True)
        raise

    logger.info(f"Safeco: parsed {len(records)} records")
    return records


# ── Travelers parser ────────────────────────────────────────────────

def parse_travelers(file_bytes: bytes, filename: str) -> List[Dict]:
    """Parse Travelers PI Commission Statement XLSX.

    Travelers has a messy format:
    - Row 0 is a sub-header row (column names repeat)
    - POL-EFF-DT contains transaction codes like '012426-CONT', '013026-NEW-BUS', '081225-CANC'
    - COMM rate stored as 1500 meaning 15.00%
    - Policy numbers have spaces: '615263935 633  1'
    - PAYMENT = premium received, PAID = commission paid
    """
    records = []
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
        logger.info(f"Travelers: {len(df)} rows, columns: {list(df.columns)}")

        # Skip the sub-header row (row 0 has 'DATE', 'CDE', 'CODE' etc)
        if len(df) > 0 and str(df.iloc[0].get("STATEMENT", "")).strip() == "DATE":
            df = df.iloc[1:]

        for _, row in df.iterrows():
            insured = str(row.get("NAME OF INSURED", "") or "").strip()
            if not insured or insured == "nan" or insured == "":
                continue

            raw_policy = str(row.get("POLICY NUMBER", "") or "").strip()
            if not raw_policy or raw_policy == "nan":
                continue

            # Clean policy number — take first segment before spaces
            policy_number = raw_policy.split()[0] if raw_policy else raw_policy

            # Parse transaction type from POL-EFF-DT column
            trans_code_raw = str(row.get("POL-EFF-DT", "") or "").strip()
            raw_type = _travelers_map_trans(trans_code_raw)

            # Premium = PAYMENT column (or TRANSACTION for full premium)
            premium = _clean_currency(row.get("PAYMENT"))
            # Commission = PAID column
            commission = _clean_currency(row.get("PAID"))

            # Commission rate — stored as 1500 = 15.00%
            raw_rate = row.get("COMM")
            comm_rate = None
            if raw_rate is not None and raw_rate != "" and str(raw_rate) != "nan":
                try:
                    rate_val = float(str(raw_rate).replace(",", ""))
                    if rate_val > 100:  # Stored as 1500 = 15.00%
                        comm_rate = rate_val / 10000.0
                    elif rate_val > 1:
                        comm_rate = rate_val / 100.0
                    else:
                        comm_rate = rate_val
                except (ValueError, TypeError):
                    pass

            # Parse effective date from the trans code (e.g., '012426-CONT' -> 01/24/26)
            eff_date = _travelers_parse_date(trans_code_raw)
            stmt_date = _parse_date(row.get("STATEMENT"))

            # Sub-agent code
            sub_agent = str(row.get("SUB", "") or "").strip()

            records.append({
                "policy_number": policy_number,
                "insured_name": insured,
                "transaction_type": _map_transaction_type(raw_type).value,
                "transaction_type_raw": trans_code_raw,
                "transaction_date": stmt_date,
                "effective_date": eff_date or stmt_date,
                "premium_amount": premium,
                "commission_rate": comm_rate,
                "commission_amount": commission,
                "producer_name": sub_agent if sub_agent and sub_agent != "nan" else None,
                "product_type": None,
                "line_of_business": None,
                "state": None,
                "term_months": 12,  # Travelers is typically 12mo
                "raw_data": str(row.to_dict()),
            })

    except Exception as e:
        logger.error(f"Error parsing Travelers: {e}", exc_info=True)
        raise

    logger.info(f"Travelers: parsed {len(records)} records")
    return records


def _travelers_map_trans(code: str) -> str:
    """Map Travelers transaction codes to standard types.
    
    Format: MMDDYY-TYPE (e.g., '012426-CONT', '013026-NEW-BUS', '081225-CANC')
    """
    if not code or code == "nan":
        return "other"
    code_upper = code.upper()
    if "NEW-BUS" in code_upper or "NEW BUS" in code_upper:
        return "NEW BUSINESS"
    elif "CONT" in code_upper:
        return "RENEWAL"
    elif "CANC" in code_upper:
        return "CANCELLATION"
    elif "CHANGE" in code_upper:
        return "ENDORSEMENT"
    elif "REIN" in code_upper:
        return "REINSTATEMENT"
    elif "UNHON" in code_upper or "CHECK" in code_upper:
        return "ADJUSTMENT"
    elif "WAIVE" in code_upper:
        return "ENDORSEMENT"
    else:
        return "OTHER"


def _travelers_parse_date(code: str):
    """Try to extract a date from Travelers trans code like '012426-CONT' -> 01/24/2026."""
    if not code or code == "nan" or len(code) < 6:
        return None
    try:
        # First 6 chars are MMDDYY
        date_part = code[:6]
        mm = int(date_part[0:2])
        dd = int(date_part[2:4])
        yy = int(date_part[4:6])
        year = 2000 + yy if yy < 50 else 1900 + yy
        from datetime import datetime as dt
        return dt(year, mm, dd)
    except (ValueError, IndexError):
        return None


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
                "transaction_type": _map_transaction_type(raw_type).value,
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


# ── Auto-detect carrier from file contents ───────────────────────────

def detect_carrier(file_bytes: bytes, filename: str) -> Optional[str]:
    """Attempt to auto-detect carrier from column names in the file.
    
    Returns carrier key (e.g. 'progressive') or None if unknown.
    """
    try:
        if filename.lower().endswith(('.csv', '.txt')):
            df = pd.read_csv(io.BytesIO(file_bytes), nrows=5)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), nrows=5)
        
        cols_lower = {str(c).strip().lower() for c in df.columns}
        cols_str = " ".join(cols_lower)
        
        # Progressive: has "tran code", "gross premium", "gross comm", "prod name"
        if "tran code" in cols_lower or "gross comm" in cols_lower:
            return "progressive"
        
        # Safeco: has "activity type", or column set with "comm amount" + "term length"
        if "activity type" in cols_lower or "comm amount" in cols_lower:
            return "safeco"
        
        # Travelers: has "NAME OF INSURED", "POL-EFF-DT", "POLICY NUMBER", "PAID"
        if "name of insured" in cols_lower or "pol-eff-dt" in cols_lower:
            return "travelers"
        
        # National General: has "selling producer", "trans type", or sheet names
        if "selling producer" in cols_lower or ("trans type" in cols_lower and "written premium" in cols_str):
            return "national_general"
        
        # Grange: CSV with "Policyholder Name or Description", "Commission Amount"
        if "policyholder name or description" in cols_lower or "commission rate reason" in cols_str:
            return "grange"
        
        # Also check for National General by trying Excel sheet names
        if filename.lower().endswith(('.xlsx', '.xls')):
            try:
                xls = pd.ExcelFile(io.BytesIO(file_bytes))
                if "Summary Details" in xls.sheet_names or "All Producers" in xls.sheet_names:
                    return "national_general"
            except Exception:
                pass
        
    except Exception as e:
        logger.warning(f"Carrier auto-detect failed: {e}")
    
    return None


# ── Dispatcher ───────────────────────────────────────────────────────

CARRIER_PARSERS = {
    "national_general": parse_national_general,
    "progressive": parse_progressive,
    "safeco": parse_safeco,
    "grange": parse_grange,
    "travelers": parse_travelers,
}


def parse_statement(carrier: str, file_bytes: bytes, filename: str) -> List[Dict]:
    """Route to the correct carrier parser.
    
    Auto-detects carrier from file contents and overrides if different
    from the user selection (with a log warning).
    """
    detected = detect_carrier(file_bytes, filename)
    actual_carrier = carrier
    
    if detected and detected != carrier:
        logger.warning(
            f"Carrier mismatch: user selected '{carrier}' but file looks like '{detected}'. "
            f"Using detected carrier '{detected}'."
        )
        actual_carrier = detected
    
    parser = CARRIER_PARSERS.get(actual_carrier, parse_generic)
    return parser(file_bytes, filename)
