"""
Smart Inbox Batch Report Parser — handles carrier emails that contain
multiple customers/policies in a single email (e.g. NatGen daily reports).

Supported report types:
  - NatGen "Policy Activity" (Outstanding To Dos: GoPaperless, UW items, etc.)
  - NatGen "Billing Activity" / "Reinstatements - Daily" (NonPayCanc, Cancel - NonRenewal)

Detection → HTML table parsing → one child InboundEmail per row → each processed individually.
"""
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ── Report Type Detection ────────────────────────────────────────────────────

# Patterns that identify batch report emails (subject + from combinations)
BATCH_REPORT_PATTERNS = [
    {
        "name": "natgen_policy_activity",
        "from_pattern": r"Reports@NGIC\.com|NGIC|NatGen|National General",
        "subject_pattern": r"\d{5,10}:\s*Policy Activity\s+\d{2}/\d{2}/\d{4}",
        "report_type": "policy_activity",
        "carrier": "National General",
        "subject_only_match": True,  # Agent code + "Policy Activity" is unique enough
    },
    {
        "name": "natgen_billing_activity",
        "from_pattern": r"Reports@NGIC\.com|NGIC|NatGen|National General",
        "subject_pattern": r"\d{5,10}:\s*Billing Activity\s+\d{2}/\d{2}/\d{4}",
        "report_type": "reinstatement",
        "carrier": "National General",
        "subject_only_match": True,
    },
    {
        "name": "natgen_reinstatements",
        "from_pattern": r"Reports@NGIC\.com|NGIC|NatGen|National General",
        "subject_pattern": r"Reinstatements?\s*[-–]\s*Daily",
        "report_type": "reinstatement",
        "carrier": "National General",
        "subject_only_match": False,
    },
    {
        "name": "natgen_daily_report",
        "from_pattern": r"Reports@NGIC\.com|NGIC|NatGen|National General",
        "subject_pattern": r"\d{5,10}:\s*Daily Report",
        "report_type": "policy_activity",
        "carrier": "National General",
        "subject_only_match": False,
    },
    {
        "name": "natgen_nonrenewal_excel",
        "from_pattern": r".*",  # Can come from anyone (forwarded)
        "subject_pattern": r"non[\s-]*renewals?\s+(?:national\s+general|natgen|NGIC)|(?:national\s+general|natgen|NGIC)\s+non[\s-]*renewals?|pending\s+non[\s-]*renewals?",
        "report_type": "nonrenewal_excel",
        "carrier": "National General",
        "subject_only_match": True,
    },
    {
        "name": "progressive_pending_cancel_renewal",
        "from_pattern": r".*",
        "subject_pattern": r"(?:policies?\s*)?pending\s*(?:cancel|cancellation|renewal)|cancel\s*(?:or|and)\s*renewal|progressive\s+non[\s-]*pay",
        "report_type": "multi_sheet_excel",
        "carrier": "Progressive",
        "subject_only_match": True,
    },
    {
        "name": "generic_carrier_nonpay_list",
        "from_pattern": r".*",
        "subject_pattern": r"non[\s-]*pay(?:ment)?\s+(?:list|report|pending)|pending\s+cancel",
        "report_type": "multi_sheet_excel",
        "carrier": "Unknown",
        "subject_only_match": True,
    },
]


def detect_batch_report(
    from_address: str, subject: str, body_plain: str = "", body_html: str = ""
) -> Optional[Dict[str, str]]:
    """
    Check if an email matches a known batch report pattern.
    Handles forwarded emails where from_address is the forwarder, not the original sender.
    Checks both from_address AND the email body for original sender references.
    Returns report info dict or None.
    """
    # Build a combined text to search for original sender clues
    body_text = (body_plain or "") + " " + (body_html or "")

    for pattern in BATCH_REPORT_PATTERNS:
        subj_match = re.search(pattern["subject_pattern"], subject or "", re.IGNORECASE)
        if not subj_match:
            continue

        # Check if from_address matches directly
        from_match = re.search(pattern["from_pattern"], from_address or "", re.IGNORECASE)
        if from_match:
            logger.info(f"Detected batch report (direct from): {pattern['name']} — {subject}")
            return pattern

        # Check if original sender appears in the email body (forwarded emails)
        body_from_match = re.search(pattern["from_pattern"], body_text[:3000], re.IGNORECASE)
        if body_from_match:
            logger.info(f"Detected batch report (forwarded, original sender in body): {pattern['name']} — {subject}")
            return pattern

        # For NatGen reports: the agent code + "Policy Activity" or "Billing Activity"
        # subject pattern is distinctive enough on its own
        if pattern.get("subject_only_match", False):
            logger.info(f"Detected batch report (subject-only): {pattern['name']} — {subject}")
            return pattern

    return None


# ── HTML Table Parsing ───────────────────────────────────────────────────────

def parse_batch_report(
    body_html: str,
    body_plain: str,
    report_type: str,
    carrier: str,
    attachment_data: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Parse the email HTML or attachments to extract individual customer rows.
    Returns a list of dicts, one per customer/policy row.
    """
    if report_type == "policy_activity":
        return _parse_policy_activity(body_html, body_plain, carrier)
    elif report_type == "reinstatement":
        return _parse_reinstatement(body_html, body_plain, carrier)
    elif report_type == "nonrenewal_excel":
        return _parse_nonrenewal_excel(attachment_data, carrier)
    elif report_type == "multi_sheet_excel":
        return _parse_multi_sheet_excel(attachment_data, carrier)
    else:
        logger.warning(f"Unknown batch report type: {report_type}")
        return []


def _parse_nonrenewal_excel(
    attachment_data: Optional[List[Dict]], carrier: str
) -> List[Dict[str, Any]]:
    """
    Parse non-renewal Excel spreadsheet attachment.
    
    Expected columns:
    Policy | Named Insured | Phone | Type | Product | DIV | Processed | Effective |
    Description | Premium | Producer | Additional Products
    """
    if not attachment_data:
        logger.warning("No attachment data for nonrenewal_excel parser")
        return []

    items = []
    for att in attachment_data:
        extracted_text = att.get("extracted_text", "")
        if not extracted_text:
            continue

        # Parse the semicolon-delimited rows from the extracted text
        for line in extracted_text.strip().split("\n"):
            if not line.strip() or line.startswith("Excel Sheet:") or line.startswith("Columns:") or line.startswith("CSV File:"):
                continue

            # Parse "Key: Value; Key: Value" format
            fields = {}
            for pair in line.split("; "):
                if ": " in pair:
                    key, val = pair.split(": ", 1)
                    fields[key.strip()] = val.strip()

            policy = fields.get("Policy", "").strip()
            insured = fields.get("Named Insured", "").strip()
            phone = fields.get("Phone", "").strip()
            effective = fields.get("Effective", "").strip()
            description = fields.get("Description", "").strip()
            premium = fields.get("Premium", "").strip()
            producer = fields.get("Producer", "").strip()
            product = fields.get("Product", "").strip()

            if not policy or not insured:
                continue

            # Clean policy number (remove spaces around dash)
            policy_clean = re.sub(r'\s*-\s*', '-', policy)

            items.append({
                "policy_number": policy_clean,
                "insured_name": insured,
                "phone": phone,
                "carrier": carrier,
                "category": "non_renewal",
                "description": description or "Non-Renewal - Underwriting Reasons",
                "effective_date": effective,
                "premium": premium,
                "producer": producer,
                "product": product,
                "action": "non_renewal_notice",
            })

    logger.info(f"Parsed {len(items)} non-renewal items from Excel attachment")
    return items


def _parse_multi_sheet_excel(
    attachment_data: Optional[List[Dict]], carrier: str
) -> List[Dict[str, Any]]:
    """
    Parse multi-sheet Excel reports (e.g. Progressive Pending Cancel/Renewal).
    
    Handles sheets with names like:
      - "Non-Payment" → category: non_payment
      - "Underwriting" → category: underwriting_requirement  
      - "Pending Renewal" → category: renewal_notice
      - "Non-Renewal" → category: non_renewal
    
    Common columns: Full Name, Policy Number, Email Address, Phone Number,
    Producer, Product, Cancel Effective Date / Renewal Effective Date, Amount Due
    """
    if not attachment_data:
        logger.warning("No attachment data for multi_sheet_excel parser")
        return []

    # Map sheet names to categories
    SHEET_CATEGORY_MAP = {
        "non-payment": "non_payment",
        "non payment": "non_payment",
        "nonpayment": "non_payment",
        "nonpay": "non_payment",
        "underwriting": "underwriting_requirement",
        "uw": "underwriting_requirement",
        "pending renewal": "renewal_notice",
        "renewal": "renewal_notice",
        "non-renewal": "non_renewal",
        "non renewal": "non_renewal",
        "nonrenewal": "non_renewal",
        "cancellation": "cancellation",
        "cancel": "cancellation",
    }

    items = []
    for att in attachment_data:
        extracted_text = att.get("extracted_text", "")
        if not extracted_text:
            continue

        current_sheet = ""
        current_category = "other"

        for line in extracted_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Detect sheet headers
            if line.startswith("Excel Sheet:"):
                current_sheet = line.replace("Excel Sheet:", "").strip()
                # Match sheet name to category
                sheet_lower = current_sheet.lower()
                current_category = "other"
                for pattern, cat in SHEET_CATEGORY_MAP.items():
                    if pattern in sheet_lower:
                        current_category = cat
                        break
                logger.info(f"Parsing sheet '{current_sheet}' as category '{current_category}'")
                continue

            if line.startswith("Columns:"):
                continue

            # Parse "Key: Value; Key: Value" format
            fields = {}
            for pair in line.split("; "):
                if ": " in pair:
                    key, val = pair.split(": ", 1)
                    fields[key.strip()] = val.strip()

            # Extract common fields (handle different column names)
            full_name = fields.get("Full Name", "").strip()
            policy = fields.get("Policy Number", "").strip()
            email = fields.get("Email Address", "").strip()
            phone = fields.get("Phone Number", "").strip()
            producer = fields.get("Producer", "").strip()
            product = fields.get("Product", "").strip()
            address = fields.get("Address", "").strip()
            city = fields.get("City", "").strip()
            state = fields.get("State", fields.get("Policy State", "")).strip()

            # Date field varies by sheet type
            effective_date = (
                fields.get("Cancel Effective Date", "") or
                fields.get("Renewal Effective Date", "") or
                fields.get("Effective", "") or
                fields.get("Effective Date", "")
            ).strip()

            # Amount field varies
            amount = (
                fields.get("Amount Due", "") or
                fields.get("Total Term Premium", "") or
                fields.get("Premium", "")
            ).strip()

            cancel_reason = fields.get("Cancel Reason", "").strip()

            if not policy or not full_name:
                continue

            # Clean name: "Last, First" → "First Last"
            insured_name = full_name
            if ", " in full_name:
                parts = full_name.split(", ", 1)
                insured_name = f"{parts[1]} {parts[0]}"

            # Build description based on category
            if current_category == "non_payment":
                description = f"Non-Payment Cancel — Amount Due: ${amount}" if amount else "Non-Payment Cancel"
            elif current_category == "underwriting_requirement":
                description = f"Underwriting Cancel — {cancel_reason}" if cancel_reason else "Underwriting Cancel"
            elif current_category == "renewal_notice":
                description = f"Pending Renewal — Premium: ${amount}" if amount else "Pending Renewal"
            elif current_category == "non_renewal":
                description = "Non-Renewal"
            else:
                description = current_sheet

            items.append({
                "policy_number": policy,
                "insured_name": insured_name,
                "email": email if email and email != "0" else "",
                "phone": phone if phone and phone != "0" else "",
                "carrier": carrier,
                "category": current_category,
                "description": description,
                "effective_date": effective_date,
                "amount": amount,
                "producer": producer,
                "product": product,
                "address": f"{address}, {city}, {state}" if address else "",
                "action": f"{current_category}_notice",
                "sheet_name": current_sheet,
            })

    logger.info(f"Parsed {len(items)} items from multi-sheet Excel ({len(set(i['category'] for i in items))} categories)")
    return items


def _parse_policy_activity(
    body_html: str, body_plain: str, carrier: str
) -> List[Dict[str, Any]]:
    """
    Parse NatGen Policy Activity report.
    
    Expected columns:
    Policy | Named Insured | DIV | To Do Description | Next Action Date |
    Action to be Taken | Vehicle | Driver | Status | Policy Type | Offer Status | Additional Products
    """
    rows = _extract_table_rows(body_html, body_plain)
    items = []

    for row in rows:
        # Need at least Policy + Named Insured + To Do Description
        if len(row) < 4:
            continue

        policy = _clean_text(row[0])
        insured = _clean_text(row[1])
        div = _clean_text(row[2]) if len(row) > 2 else ""
        todo_desc = _clean_text(row[3]) if len(row) > 3 else ""
        next_date = _clean_text(row[4]) if len(row) > 4 else ""
        action = _clean_text(row[5]) if len(row) > 5 else ""
        status = _clean_text(row[8]) if len(row) > 8 else ""
        policy_type = _clean_text(row[9]) if len(row) > 9 else ""

        # Skip header rows or empty rows
        if not policy or policy.lower() == "policy" or not insured:
            continue
        # Skip if insured looks like a header
        if insured.lower() in ("named insured", "named_insured"):
            continue

        # Determine category and sensitivity from the to-do description
        result = _categorize_policy_activity(
            todo_desc, action, status, insured, policy
        )
        if result is None:
            continue  # Skip this item (e.g. GoPaperless)
        category, sensitivity, summary = result

        items.append({
            "policy_number": policy,
            "insured_name": insured,
            "carrier": carrier,
            "category": category,
            "sensitivity": sensitivity,
            "summary": summary,
            "division": div,
            "todo_description": todo_desc,
            "next_action_date": _parse_date(next_date),
            "action_to_take": action,
            "status": status,
            "policy_type": policy_type,
        })

    logger.info(f"Parsed {len(items)} items from Policy Activity report")
    return items


def _parse_reinstatement(
    body_html: str, body_plain: str, carrier: str
) -> List[Dict[str, Any]]:
    """
    Parse NatGen Billing Activity / Reinstatement report.
    
    Expected columns:
    Policy | Named Insured | Phone # | Product | DIV | Cancel Date | Reason | Amount Due | Additional Products
    """
    rows = _extract_table_rows(body_html, body_plain)
    items = []

    for row in rows:
        if len(row) < 5:
            continue

        policy = _clean_text(row[0])
        insured = _clean_text(row[1])
        phone = _clean_text(row[2]) if len(row) > 2 else ""
        product = _clean_text(row[3]) if len(row) > 3 else ""
        div = _clean_text(row[4]) if len(row) > 4 else ""
        cancel_date = _clean_text(row[5]) if len(row) > 5 else ""
        reason = _clean_text(row[6]) if len(row) > 6 else ""
        amount = _clean_text(row[7]) if len(row) > 7 else ""

        # Skip headers
        if not policy or policy.lower() == "policy" or not insured:
            continue
        if insured.lower() in ("named insured", "named_insured"):
            continue

        # Determine category from reason
        category, sensitivity, summary = _categorize_reinstatement(
            reason, insured, policy, amount, cancel_date
        )

        items.append({
            "policy_number": policy,
            "insured_name": insured,
            "carrier": carrier,
            "category": category,
            "sensitivity": sensitivity,
            "summary": summary,
            "phone": phone,
            "product": product,
            "division": div,
            "cancel_date": _parse_date(cancel_date),
            "reason": reason,
            "amount_due": _parse_amount(amount),
        })

    logger.info(f"Parsed {len(items)} items from Reinstatement/Billing report")
    return items


# ── Table Extraction Helpers ─────────────────────────────────────────────────

def _extract_table_rows(body_html: str, body_plain: str) -> List[List[str]]:
    """
    Extract all data rows from HTML tables in the email.
    Falls back to plain text parsing if HTML fails.
    """
    rows = []

    if body_html:
        try:
            soup = BeautifulSoup(body_html, "html.parser")
            tables = soup.find_all("table")

            for table in tables:
                for tr in table.find_all("tr"):
                    cells = []
                    for td in tr.find_all(["td", "th"]):
                        cells.append(td.get_text(strip=True))
                    if cells:
                        rows.append(cells)

            if rows:
                logger.info(f"Extracted {len(rows)} rows from HTML tables")
                return rows
        except Exception as e:
            logger.warning(f"HTML table parsing failed: {e}")

    # Fallback: try plain text with pipe/tab delimiters
    if body_plain:
        for line in body_plain.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Try pipe-delimited
            if "|" in line:
                cells = [c.strip() for c in line.split("|")]
                if len(cells) >= 3:
                    rows.append(cells)
            # Try tab-delimited
            elif "\t" in line:
                cells = [c.strip() for c in line.split("\t")]
                if len(cells) >= 3:
                    rows.append(cells)

    logger.info(f"Extracted {len(rows)} rows from text fallback")
    return rows


def _clean_text(text: str) -> str:
    """Clean extracted cell text."""
    if not text:
        return ""
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove common artifacts
    text = text.replace("\xa0", " ").strip()
    return text


def _parse_date(text: str) -> Optional[str]:
    """Try to parse a date string into YYYY-MM-DD format."""
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_amount(text: str) -> Optional[float]:
    """Parse dollar amount from text like '$1,066.16'."""
    if not text:
        return None
    try:
        cleaned = re.sub(r"[^\d.]", "", text)
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


# ── Categorization Logic ─────────────────────────────────────────────────────

def _categorize_policy_activity(
    todo_desc: str, action: str, status: str, insured: str, policy: str
) -> Tuple[str, str, str]:
    """Categorize a Policy Activity row. Returns (category, sensitivity, summary)."""
    desc_lower = todo_desc.lower()
    action_lower = action.lower()

    if "gopaperless" in desc_lower:
        return (
            "underwriting_requirement",
            "routine",
            f"GoPaperless enrollment needed for {insured} (policy {policy})",
        )
    elif "umuimpd" in desc_lower or "umpd" in desc_lower:
        return (
            "underwriting_requirement",
            "routine",
            f"UM/UIMPD form change needed for {insured} (policy {policy})",
        )
    elif "proof of" in desc_lower and "insurance" in desc_lower:
        return (
            "underwriting_requirement",
            "moderate",
            f"Proof of continuous insurance needed for {insured} (policy {policy})",
        )
    elif "auto pay" in desc_lower or "autopay" in desc_lower:
        return (
            "billing_inquiry",
            "routine",
            f"Auto pay authorization to be removed for {insured} (policy {policy})",
        )
    elif "application" in desc_lower:
        if "cancel" in action_lower:
            return (
                "cancellation",
                "sensitive",
                f"Application pending cancellation for {insured} (policy {policy})",
            )
        return (
            "underwriting_requirement",
            "moderate",
            f"Application requirement for {insured} (policy {policy})",
        )
    elif "inspection" in desc_lower or "photo" in desc_lower:
        return (
            "underwriting_requirement",
            "moderate",
            f"Inspection/photo requirement for {insured} (policy {policy})",
        )
    else:
        return (
            "underwriting_requirement",
            "routine",
            f"Outstanding to-do: {todo_desc} for {insured} (policy {policy})",
        )


def _categorize_reinstatement(
    reason: str, insured: str, policy: str, amount: str, cancel_date: str
) -> Tuple[str, str, str]:
    """Categorize a Reinstatement/Billing row. Returns (category, sensitivity, summary)."""
    reason_lower = reason.lower()

    if "nonpaycanc" in reason_lower or "non pay" in reason_lower:
        return (
            "non_payment",
            "sensitive",
            f"Non-pay cancellation for {insured} (policy {policy}) — {amount} due, cancelled {cancel_date}",
        )
    elif "nonrenewal" in reason_lower or "non-renewal" in reason_lower or "non renewal" in reason_lower:
        return (
            "non_renewal",
            "sensitive",
            f"Non-renewal for {insured} (policy {policy}) — effective {cancel_date}",
        )
    elif "cancel" in reason_lower:
        return (
            "cancellation",
            "sensitive",
            f"Cancellation ({reason}) for {insured} (policy {policy}) — effective {cancel_date}",
        )
    elif "reinstate" in reason_lower:
        return (
            "billing_inquiry",
            "moderate",
            f"Eligible for reinstatement: {insured} (policy {policy}) — {amount} due",
        )
    else:
        return (
            "billing_inquiry",
            "moderate",
            f"Billing activity ({reason}) for {insured} (policy {policy}) — {amount} due",
        )


# ── Group Items by Policy Number ─────────────────────────────────────────────

def group_items_by_policy(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group parsed batch items by policy number.
    Items with the same policy number are combined into a single item
    with all tasks listed together, so the customer gets ONE email
    instead of multiple.
    """
    from collections import OrderedDict
    groups: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()

    for item in items:
        key = item.get("policy_number", "")
        if not key:
            # No policy number — keep as individual item
            groups.setdefault(f"_no_policy_{id(item)}", []).append(item)
        else:
            groups.setdefault(key, []).append(item)

    merged = []
    for policy_num, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Multiple items for same policy — combine them
        first = group[0]
        insured = first.get("insured_name", "")
        carrier = first.get("carrier", "")

        # Collect all task descriptions
        tasks = []
        all_dates = []
        highest_sensitivity = "routine"
        sensitivity_order = {"routine": 0, "moderate": 1, "sensitive": 2, "critical": 3}

        for item in group:
            desc = item.get("todo_description") or item.get("reason") or item.get("summary", "")
            action = item.get("action_to_take", "")
            date = item.get("next_action_date") or item.get("cancel_date", "")
            status = item.get("status", "")
            task_line = desc
            if action:
                task_line += f" → {action}"
            if date:
                task_line += f" (by {date})"
            if status:
                task_line += f" [{status}]"
            tasks.append(task_line)

            if date:
                all_dates.append(date)

            s = item.get("sensitivity", "routine")
            if sensitivity_order.get(s, 0) > sensitivity_order.get(highest_sensitivity, 0):
                highest_sensitivity = s

        # Pick the earliest deadline
        earliest_date = min(all_dates) if all_dates else None

        # Determine overall category — use the most important one
        categories = [it.get("category", "other") for it in group]
        cat_priority = ["cancellation", "non_payment", "non_renewal", "underwriting_requirement", "billing_inquiry", "other"]
        best_category = "other"
        for cp in cat_priority:
            if cp in categories:
                best_category = cp
                break

        task_list = "; ".join(tasks)
        summary = f"Multiple outstanding items for {insured} (policy {policy_num}): {task_list}"

        combined = {
            "policy_number": policy_num,
            "insured_name": insured,
            "carrier": carrier,
            "category": best_category,
            "sensitivity": highest_sensitivity,
            "summary": summary,
            "division": first.get("division", ""),
            "todo_description": task_list,
            "next_action_date": earliest_date,
            "action_to_take": ", ".join(filter(None, [it.get("action_to_take") for it in group])),
            "status": ", ".join(filter(None, set(it.get("status", "") for it in group))),
            "policy_type": first.get("policy_type", ""),
            "amount_due": max((it.get("amount_due") or 0 for it in group), default=None),
            "_grouped_tasks": tasks,  # Preserved for email drafting
            "_grouped_items": group,  # Full original items
        }
        merged.append(combined)

    logger.info(f"Grouped {len(items)} items into {len(merged)} combined items")
    return merged


# ── Build Child Inbound Records ─────────────────────────────────────────────

def build_child_email_data(
    parent_id: int,
    item: Dict[str, Any],
    original_from: str,
    original_subject: str,
) -> Dict[str, Any]:
    """
    Build the kwargs to create a child InboundEmail from a parsed batch item.
    This does NOT create the DB record — the caller handles that.
    """
    due_date = None
    date_str = item.get("next_action_date") or item.get("cancel_date")
    if date_str:
        try:
            due_date = datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # Build a meaningful body for the child record
    body_parts = [f"Extracted from batch report: {original_subject}"]
    for key, val in item.items():
        if val and key not in ("category", "sensitivity", "summary", "carrier"):
            body_parts.append(f"  {key}: {val}")

    return {
        "parent_email_id": parent_id,
        "from_address": original_from,
        "subject": item.get("summary", original_subject),
        "body_plain": "\n".join(body_parts),
        "category": item.get("category", "other"),
        "sensitivity": item.get("sensitivity", "moderate"),
        "ai_summary": item.get("summary"),
        "extracted_policy_number": item.get("policy_number"),
        "extracted_insured_name": item.get("insured_name"),
        "extracted_carrier": item.get("carrier"),
        "extracted_due_date": due_date,
        "extracted_amount": item.get("amount_due"),
        "confidence_score": 0.95,  # High confidence — structured data
        "is_batch_report": False,  # children are not batch reports themselves
    }
