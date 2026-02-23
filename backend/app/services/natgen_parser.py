"""National General Policy Activity email parser.

Parses the daily Policy Activity email from Reports@NGIC.com into structured
data from three tables: Outstanding To Dos, Pending Cancellations, Undeliverable Mail.
"""
import logging
import re
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_natgen_policy_activity(html_body: str) -> dict:
    """Parse National General Policy Activity email into categorized rows.
    
    Returns:
        {
            "outstanding_todos": [
                {"policy": "...", "insured_name": "...", "todo_type": "GoPaperless|ProofOfContinuousInsurance|NoPOP|...",
                 "next_action_date": "...", "action": "...", "status": "...", "policy_type": "..."}
            ],
            "pending_cancellations": [
                {"policy": "...", "insured_name": "...", "phone": "...", "product": "...",
                 "reason": "...", "cancel_date": "...", "amount_due": "...", "cancel_type": "non_pay|nsf|underwriting|voluntary|other"}
            ],
            "undeliverable_mail": [
                {"policy": "...", "insured_name": "...", "phone": "...", 
                 "mail_description": "...", "additional_products": "..."}
            ],
        }
    """
    soup = BeautifulSoup(html_body, "html.parser")
    
    result = {
        "outstanding_todos": [],
        "pending_non_renewals": [],
        "pending_cancellations": [],
        "undeliverable_mail": [],
    }
    
    # Find all tables
    tables = soup.find_all("table")
    
    # Strategy: look for section headers then grab the next table
    all_text = soup.get_text(" ", strip=True).lower()
    
    # Find section headers by scanning text nodes
    current_section = None
    
    for table in tables:
        # Check text immediately before this table to determine section
        prev = table.find_previous(string=True)
        # Also check parent elements for section titles
        section = _detect_section(table, soup)
        
        if section:
            current_section = section
        
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
            
        # Get headers from first row
        headers = []
        for cell in rows[0].find_all(["th", "td"]):
            headers.append(cell.get_text(strip=True).lower())
        
        if not headers:
            continue
        
        # Parse based on detected section or header content
        if current_section == "outstanding_todos" or _is_todo_table(headers):
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 4:
                    continue
                entry = _parse_todo_row(headers, cells)
                if entry and entry.get("policy"):
                    result["outstanding_todos"].append(entry)

        elif current_section == "pending_non_renewals" or _is_non_renewal_table(headers):
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 4:
                    continue
                entry = _parse_non_renewal_row(headers, cells)
                if entry and entry.get("policy"):
                    result["pending_non_renewals"].append(entry)
                    
        elif current_section == "pending_cancellations" or _is_cancellation_table(headers):
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 4:
                    continue
                entry = _parse_cancellation_row(headers, cells)
                if entry and entry.get("policy"):
                    result["pending_cancellations"].append(entry)
                    
        elif current_section == "undeliverable_mail" or _is_undeliverable_table(headers):
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 3:
                    continue
                entry = _parse_undeliverable_row(headers, cells)
                if entry and entry.get("policy"):
                    result["undeliverable_mail"].append(entry)
    
    logger.info(
        "NatGen parser: %d todos, %d cancellations, %d undeliverable",
        len(result["outstanding_todos"]),
        len(result["pending_cancellations"]),
        len(result["undeliverable_mail"]),
    )
    return result


def _detect_section(table, soup) -> Optional[str]:
    """Detect which section a table belongs to by looking at preceding text."""
    # Walk backwards from the table to find section header
    for prev in table.previous_siblings:
        if prev.name in ("p", "div", "h1", "h2", "h3", "h4", "b", "strong", "span"):
            text = prev.get_text(strip=True).lower()
            if "outstanding to do" in text:
                return "outstanding_todos"
            if "pending non-renewal" in text or "pending non renewal" in text:
                return "pending_non_renewals"
            if "pending cancellation" in text:
                return "pending_cancellations"
            if "undeliverable mail" in text:
                return "undeliverable_mail"
        elif hasattr(prev, "get_text"):
            text = prev.get_text(strip=True).lower() if prev.get_text else ""
            if text:
                if "outstanding to do" in text:
                    return "outstanding_todos"
                if "pending non-renewal" in text or "pending non renewal" in text:
                    return "pending_non_renewals"
                if "pending cancellation" in text:
                    return "pending_cancellations"
                if "undeliverable mail" in text:
                    return "undeliverable_mail"
    
    # Also check parent's previous siblings
    parent = table.parent
    if parent:
        for prev in parent.previous_siblings:
            if hasattr(prev, "get_text"):
                text = prev.get_text(strip=True).lower()
                if "outstanding to do" in text:
                    return "outstanding_todos"
                if "pending non-renewal" in text or "pending non renewal" in text:
                    return "pending_non_renewals"
                if "pending cancellation" in text:
                    return "pending_cancellations"
                if "undeliverable mail" in text:
                    return "undeliverable_mail"
    return None


def _is_todo_table(headers: list) -> bool:
    h = " ".join(headers)
    return "to do description" in h or "action to be taken" in h


def _is_non_renewal_table(headers: list) -> bool:
    h = " ".join(headers)
    return ("effective" in h and "premium" in h and "producer" in h) or "non-renewal" in h


def _is_cancellation_table(headers: list) -> bool:
    h = " ".join(headers)
    return "cancel date" in h or ("reason" in h and "amount" in h)


def _is_undeliverable_table(headers: list) -> bool:
    h = " ".join(headers)
    return "mail description" in h or "undeliverable" in h


def _get_cell(headers: list, cells: list, *possible_names) -> str:
    """Get cell value by header name."""
    for name in possible_names:
        for i, h in enumerate(headers):
            if name in h and i < len(cells):
                return cells[i]
    return ""


def _parse_todo_row(headers: list, cells: list) -> dict:
    policy = _get_cell(headers, cells, "policy")
    insured = _get_cell(headers, cells, "named insured", "insured")
    todo_desc = _get_cell(headers, cells, "to do description", "description")
    next_date = _get_cell(headers, cells, "next action date", "action date")
    action = _get_cell(headers, cells, "action to be taken", "action")
    status = _get_cell(headers, cells, "status")
    policy_type = _get_cell(headers, cells, "policy type")
    
    # Classify the todo type
    desc_lower = todo_desc.lower()
    action_lower = action.lower()
    if "gopaperless" in desc_lower or "gopaperless" in action_lower:
        todo_type = "go_paperless"
    elif "proof of continuous" in desc_lower:
        todo_type = "proof_of_continuous_insurance"
    elif "nopop" in desc_lower or "nopop" in action_lower or "no pop" in desc_lower:
        todo_type = "nopop"
    elif "changepriorbi" in action_lower or "change prior bi" in action_lower or "changepriorbi" in desc_lower:
        todo_type = "change_prior_bi"
    elif "proof of prior bi" in desc_lower or "proof of prior bl" in desc_lower:
        todo_type = "proof_of_prior_bi"
    else:
        todo_type = "other"
    
    return {
        "policy": policy.strip(),
        "insured_name": insured.strip(),
        "todo_type": todo_type,
        "todo_description": todo_desc,
        "next_action_date": next_date,
        "action": action,
        "status": status,
        "policy_type": policy_type,
    }


def _parse_cancellation_row(headers: list, cells: list) -> dict:
    policy = _get_cell(headers, cells, "policy")
    insured = _get_cell(headers, cells, "named insured", "insured")
    phone = _get_cell(headers, cells, "phone")
    product = _get_cell(headers, cells, "product")
    reason = _get_cell(headers, cells, "reason")
    cancel_date = _get_cell(headers, cells, "cancel date")
    amount_due = _get_cell(headers, cells, "amount due", "amount")
    
    # Classify cancellation type
    reason_lower = reason.lower()
    if "non payment" in reason_lower or "non-payment" in reason_lower:
        cancel_type = "non_pay"
    elif "nsf" in reason_lower:
        cancel_type = "nsf"
    elif "underwriting" in reason_lower:
        cancel_type = "underwriting"
    elif "policyholder" in reason_lower or "insured request" in reason_lower:
        cancel_type = "voluntary"
    else:
        cancel_type = "other"
    
    # Clean amount
    amount_clean = None
    if amount_due:
        try:
            amount_clean = float(amount_due.replace("$", "").replace(",", ""))
        except (ValueError, AttributeError):
            pass
    
    return {
        "policy": policy.strip(),
        "insured_name": insured.strip(),
        "phone": phone.strip() if phone else "",
        "product": product,
        "reason": reason,
        "cancel_date": cancel_date,
        "amount_due": amount_clean,
        "amount_due_str": amount_due,
        "cancel_type": cancel_type,
    }


def _parse_undeliverable_row(headers: list, cells: list) -> dict:
    policy = _get_cell(headers, cells, "policy")
    insured = _get_cell(headers, cells, "named insured", "insured")
    phone = _get_cell(headers, cells, "phone one", "phone")
    phone2 = _get_cell(headers, cells, "phone two")
    phone3 = _get_cell(headers, cells, "phone three")
    mail_desc = _get_cell(headers, cells, "mail description", "description")
    
    return {
        "policy": policy.strip(),
        "insured_name": insured.strip(),
        "phone": phone.strip() if phone else "",
        "phone2": phone2.strip() if phone2 else "",
        "phone3": phone3.strip() if phone3 else "",
        "mail_description": mail_desc,
    }


def _parse_non_renewal_row(headers: list, cells: list) -> dict:
    policy = _get_cell(headers, cells, "policy")
    insured = _get_cell(headers, cells, "named insured", "insured")
    phone = _get_cell(headers, cells, "phone")
    product = _get_cell(headers, cells, "product")
    div = _get_cell(headers, cells, "div")
    processed = _get_cell(headers, cells, "processed")
    effective = _get_cell(headers, cells, "effective")
    description = _get_cell(headers, cells, "description")
    premium_str = _get_cell(headers, cells, "premium")
    producer = _get_cell(headers, cells, "producer")
    
    # Clean premium
    premium = None
    if premium_str:
        try:
            premium = float(premium_str.replace("$", "").replace(",", ""))
        except (ValueError, AttributeError):
            pass
    
    return {
        "policy": policy.strip(),
        "insured_name": insured.strip(),
        "phone": phone.strip() if phone else "",
        "product": product,
        "div": div,
        "processed_date": processed,
        "effective_date": effective,
        "description": description,
        "premium": premium,
        "premium_str": premium_str,
        "producer_name": producer.strip() if producer else "",
    }
