"""Payroll API — submit, lock, view history, and mark paid."""
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.payroll import PayrollRecord, PayrollAgentLine
from app.services.reconciliation import ReconciliationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payroll", tags=["payroll"])


@router.post("/submit/{period}")
def submit_payroll(
    period: str,
    body: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit/finalize payroll for a month. Snapshots current monthly pay data with overrides."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Check if already submitted
    existing = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if existing and existing.is_locked:
        raise HTTPException(status_code=400, detail=f"Payroll for {period} is already locked. Use unlock first.")

    # Parse agent overrides: { "agent_id": { "rate_adjustment": 0.005, "bonus": 100 } }
    agent_overrides = (body or {}).get("agent_overrides", {})

    # Calculate monthly pay
    service = ReconciliationService(db)
    try:
        pay_data = service.calculate_monthly_pay(period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    year, month = map(int, period.split("-"))
    period_display = datetime(year, month, 1).strftime("%B %Y")

    # Delete existing draft if any
    if existing:
        db.query(PayrollAgentLine).filter(PayrollAgentLine.payroll_record_id == existing.id).delete()
        db.delete(existing)
        db.flush()

    # Apply overrides to agent summaries for the snapshot
    total_agent_pay = 0
    for agent in pay_data.get("agent_summaries", []):
        aid = str(agent["agent_id"])
        overrides = agent_overrides.get(aid, {})
        rate_adj = float(overrides.get("rate_adjustment", 0))
        bonus = float(overrides.get("bonus", 0))
        agent["rate_adjustment"] = rate_adj
        agent["bonus"] = bonus

        if rate_adj != 0:
            base_comm = agent.get("net_agent_commission", agent.get("total_agent_commission", 0))
            base_rate = agent.get("commission_rate", 0)
            if base_rate:
                commissionable_premium = base_comm / base_rate
                adjusted_comm = commissionable_premium * (base_rate + rate_adj)
                agent["adjusted_commission"] = round(adjusted_comm, 2)
            else:
                agent["adjusted_commission"] = base_comm
        else:
            agent["adjusted_commission"] = agent.get("net_agent_commission", agent.get("total_agent_commission", 0))

        agent["grand_total"] = round(agent["adjusted_commission"] + bonus, 2)
        total_agent_pay += agent["grand_total"]

    # Create payroll record
    record = PayrollRecord(
        period=period,
        period_display=period_display,
        status="submitted",
        submitted_at=datetime.utcnow(),
        submitted_by_id=current_user.id,
        is_locked=True,
        total_agents=len(pay_data.get("agent_summaries", [])),
        total_premium=pay_data.get("totals", {}).get("total_premium", 0),
        total_agent_pay=total_agent_pay,
        total_chargebacks=pay_data.get("totals", {}).get("total_chargebacks", 0),
        total_carriers=pay_data.get("totals", {}).get("total_carriers", 0),
        snapshot_data=pay_data,
    )
    db.add(record)
    db.flush()

    # Create per-agent lines
    for agent in pay_data.get("agent_summaries", []):
        line = PayrollAgentLine(
            payroll_record_id=record.id,
            agent_id=agent["agent_id"],
            agent_name=agent["agent_name"],
            agent_role=agent.get("agent_role", "producer"),
            tier_level=agent.get("tier_level", 1),
            commission_rate=agent.get("commission_rate", 0),
            total_premium=agent.get("total_premium", 0),
            new_business_premium=agent.get("new_business_premium", 0),
            total_agent_commission=agent.get("adjusted_commission", agent.get("total_agent_commission", 0)),
            chargebacks=agent.get("chargebacks", 0),
            chargeback_premium=agent.get("chargeback_premium", 0),
            chargeback_count=agent.get("chargeback_count", 0),
            net_agent_pay=agent.get("grand_total", agent.get("total_agent_commission", 0)),
            line_count=agent.get("line_count", 0),
            carrier_breakdown=agent.get("carrier_breakdown", []),
            rate_adjustment=agent.get("rate_adjustment", 0),
            bonus=agent.get("bonus", 0),
            grand_total=agent.get("grand_total", agent.get("total_agent_commission", 0)),
            commission_status="pending",
        )
        db.add(line)

    # Mark matched sales as commission pending for this period
    _update_sales_commission_status(db, pay_data, period, "pending")

    db.commit()

    return {
        "success": True,
        "payroll_id": record.id,
        "period": period,
        "period_display": period_display,
        "status": "submitted",
        "total_agents": record.total_agents,
        "total_agent_pay": float(record.total_agent_pay or 0),
    }


@router.post("/unlock/{period}")
def unlock_payroll(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin override: unlock a submitted payroll for re-calculation."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required to unlock payroll")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record found for this period")

    record.is_locked = False
    record.status = "draft"
    db.commit()

    return {"success": True, "period": period, "status": "draft", "is_locked": False}


@router.post("/mark-paid/{period}")
def mark_payroll_paid(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark entire payroll as paid — updates all agent lines and related sales."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record found for this period")

    now = datetime.utcnow()
    record.status = "paid"
    record.paid_at = now

    # Mark all agent lines as paid
    lines = db.query(PayrollAgentLine).filter(PayrollAgentLine.payroll_record_id == record.id).all()
    for line in lines:
        line.commission_status = "paid"
        line.paid_at = now

    # Mark matching sales as commission paid
    if record.snapshot_data:
        _update_sales_commission_status(db, record.snapshot_data, period, "paid")

    db.commit()

    return {"success": True, "period": period, "status": "paid", "agents_paid": len(lines)}


@router.get("/history")
def get_payroll_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all historical payroll records."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    records = (
        db.query(PayrollRecord)
        .order_by(PayrollRecord.period.desc())
        .all()
    )

    return [
        {
            "id": r.id,
            "period": r.period,
            "period_display": r.period_display,
            "status": r.status,
            "is_locked": r.is_locked,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            "total_agents": r.total_agents,
            "total_premium": float(r.total_premium or 0),
            "total_agent_pay": float(r.total_agent_pay or 0),
            "total_chargebacks": float(r.total_chargebacks or 0),
            "total_carriers": r.total_carriers,
        }
        for r in records
    ]


@router.get("/detail/{period}")
def get_payroll_detail(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed payroll record with agent lines."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record found for this period")

    lines = (
        db.query(PayrollAgentLine)
        .filter(PayrollAgentLine.payroll_record_id == record.id)
        .order_by(PayrollAgentLine.net_agent_pay.desc())
        .all()
    )

    return {
        "id": record.id,
        "period": record.period,
        "period_display": record.period_display,
        "status": record.status,
        "is_locked": record.is_locked,
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
        "paid_at": record.paid_at.isoformat() if record.paid_at else None,
        "total_agents": record.total_agents,
        "total_premium": float(record.total_premium or 0),
        "total_agent_pay": float(record.total_agent_pay or 0),
        "total_chargebacks": float(record.total_chargebacks or 0),
        "total_carriers": record.total_carriers,
        "notes": record.notes,
        "agent_lines": [
            {
                "id": l.id,
                "agent_id": l.agent_id,
                "agent_name": l.agent_name,
                "agent_role": l.agent_role,
                "tier_level": l.tier_level,
                "commission_rate": float(l.commission_rate or 0),
                "total_premium": float(l.total_premium or 0),
                "new_business_premium": float(l.new_business_premium or 0),
                "total_agent_commission": float(l.total_agent_commission or 0),
                "chargebacks": float(l.chargebacks or 0),
                "chargeback_premium": float(l.chargeback_premium or 0),
                "chargeback_count": l.chargeback_count,
                "net_agent_pay": float(l.net_agent_pay or 0),
                "line_count": l.line_count,
                "carrier_breakdown": l.carrier_breakdown or [],
                "rate_adjustment": float(l.rate_adjustment or 0),
                "bonus": float(l.bonus or 0),
                "grand_total": float(l.grand_total or 0),
                "commission_status": l.commission_status,
                "paid_at": l.paid_at.isoformat() if l.paid_at else None,
            }
            for l in lines
        ],
    }


def _update_sales_commission_status(db: Session, pay_data: dict, period: str, status: str):
    """Update commission_status on sales that are part of this payroll."""
    from app.models.statement import StatementImport, StatementLine

    # Get all imports for this period
    imports = db.query(StatementImport).filter(StatementImport.statement_period == period).all()
    if not imports:
        return

    import_ids = [imp.id for imp in imports]

    # Get all matched lines with sales
    lines = db.query(StatementLine).filter(
        StatementLine.statement_import_id.in_(import_ids),
        StatementLine.matched_sale_id.isnot(None),
        StatementLine.is_matched == True,
    ).all()

    sale_ids = list(set(l.matched_sale_id for l in lines if l.matched_sale_id))
    if not sale_ids:
        return

    now = datetime.utcnow()
    for sale in db.query(Sale).filter(Sale.id.in_(sale_ids)).all():
        sale.commission_status = status
        if status == "paid":
            sale.commission_paid_date = now
            sale.commission_paid_period = period


# ─── Commission Sheet Email Distribution ────────────────────────────
# After payroll is locked, this lets admin email each producer their
# commission sheet PDF. Two-step: preview (returns recipients) + send
# (actually fires emails). Per Evan: lock and send are intentionally
# separate clicks so a misclick on lock doesn't blast emails.

@router.get("/{period}/commission-sheets/preview")
def preview_commission_sheet_recipients(
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the list of producers who would receive a commission sheet email
    for the given period. Used by the UI to show a recipient confirmation
    list before the admin clicks 'Send'.

    Includes:
      - agent_id, agent_name
      - email (from User.email — required to send)
      - missing_email flag if we can't email them
      - has_already_sent flag if a prior send happened for this period
      - net_pay so admin can verify the right number is going out
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"No payroll record for {period}")
    if not record.is_locked:
        raise HTTPException(status_code=400, detail="Payroll must be locked before sending commission sheets")

    lines = db.query(PayrollAgentLine).filter(
        PayrollAgentLine.payroll_record_id == record.id
    ).all()

    recipients = []
    for line in lines:
        user = db.query(User).filter(User.id == line.agent_id).first()
        recipients.append({
            "agent_id": line.agent_id,
            "agent_name": line.agent_name,
            "email": user.email if user else None,
            "missing_email": not (user and user.email),
            "net_pay": float(line.grand_total or 0),
            "has_already_sent": bool(line.commission_sheet_sent_at),
            "last_sent_at": line.commission_sheet_sent_at.isoformat() if line.commission_sheet_sent_at else None,
            "last_sent_to": line.commission_sheet_sent_to,
        })

    sendable = sum(1 for r in recipients if not r["missing_email"])
    return {
        "period": period,
        "period_display": record.period_display,
        "is_locked": record.is_locked,
        "total_recipients": len(recipients),
        "sendable_count": sendable,
        "missing_email_count": len(recipients) - sendable,
        "already_sent_count": sum(1 for r in recipients if r["has_already_sent"]),
        "recipients": recipients,
    }


class SendCommissionSheetsBody(BaseModel):
    confirm: bool = False  # MUST be true; serves as a guardrail
    agent_ids: Optional[List[int]] = None  # If provided, only send to these
    resend: bool = False  # If True, send even if already sent before
    test_mode_recipient: Optional[str] = None  # Send all PDFs to this email instead


@router.post("/{period}/commission-sheets/send")
def send_commission_sheets(
    period: str,
    body: SendCommissionSheetsBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Email each producer their commission sheet PDF for this period.

    Guardrails:
      - Period must be LOCKED (paranoid check — preview also checks)
      - Body must have confirm=true (UI-side double-click protection)
      - Skips agents already sent unless resend=true
      - Skips agents missing an email and reports them in the response
      - Per-agent failures don't abort the batch — failures are
        collected and returned

    Side effects:
      - Per-agent: PayrollAgentLine.commission_sheet_sent_at,
        commission_sheet_sent_to are set on success
      - Logs each send for audit trail
    """
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin only")

    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm=true required. Re-submit after explicit confirmation.",
        )

    record = db.query(PayrollRecord).filter(PayrollRecord.period == period).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"No payroll record for {period}")
    if not record.is_locked:
        raise HTTPException(status_code=400, detail="Payroll must be locked first")

    lines = db.query(PayrollAgentLine).filter(
        PayrollAgentLine.payroll_record_id == record.id
    ).all()

    # Filter by agent_ids if specified
    if body.agent_ids:
        target_ids = set(body.agent_ids)
        lines = [l for l in lines if l.agent_id in target_ids]

    if not lines:
        return {"sent": 0, "skipped": 0, "errors": 0, "results": [], "message": "No recipients matched"}

    # Pull the per-agent commission sheet data + PDFs
    from app.services.reconciliation import ReconciliationService
    from app.services.commission_pdf import generate_commission_pdf
    service = ReconciliationService(db)

    sent_count = 0
    skipped_count = 0
    error_count = 0
    results = []

    for line in lines:
        agent_id = line.agent_id
        agent_name = line.agent_name

        # Skip if already sent and not resending
        if line.commission_sheet_sent_at and not body.resend:
            skipped_count += 1
            results.append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "status": "skipped_already_sent",
                "last_sent_at": line.commission_sheet_sent_at.isoformat(),
            })
            continue

        user = db.query(User).filter(User.id == agent_id).first()
        target_email = body.test_mode_recipient or (user.email if user else None)

        if not target_email:
            error_count += 1
            results.append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "status": "skipped_no_email",
            })
            continue

        # Build the PDF
        try:
            sheet_data = service.get_agent_commission_sheet(
                period, agent_id,
                rate_adjustment=float(line.rate_adjustment or 0),
                bonus=float(line.bonus or 0),
            )
            pdf_bytes = generate_commission_pdf(sheet_data)
        except Exception as e:
            logger.exception("PDF generation failed for agent %s: %s", agent_id, e)
            error_count += 1
            results.append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "status": "error_pdf_generation",
                "error": str(e)[:200],
            })
            continue

        # Send the email
        try:
            send_result = _send_commission_sheet_email(
                to_email=target_email,
                agent_name=agent_name,
                period=period,
                period_display=record.period_display,
                net_pay=float(line.grand_total or 0),
                pdf_bytes=pdf_bytes,
                test_mode=bool(body.test_mode_recipient),
            )
        except Exception as e:
            logger.exception("Send failed for agent %s: %s", agent_id, e)
            error_count += 1
            results.append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "status": "error_send",
                "error": str(e)[:200],
            })
            continue

        if not send_result.get("success"):
            error_count += 1
            err = send_result.get("error", "unknown")
            if not body.test_mode_recipient:
                line.commission_sheet_send_error = err[:500]
            results.append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "status": "error_send",
                "error": err,
            })
            continue

        # Record success on the line — only when NOT in test mode
        if not body.test_mode_recipient:
            line.commission_sheet_sent_at = datetime.utcnow()
            line.commission_sheet_sent_to = target_email
            line.commission_sheet_send_error = None  # clear any prior error

        sent_count += 1
        results.append({
            "agent_id": agent_id,
            "agent_name": agent_name,
            "status": "sent",
            "to": target_email,
            "message_id": send_result.get("message_id"),
        })
        logger.info(
            "Commission sheet emailed: period=%s agent=%s (%s) to=%s test_mode=%s",
            period, agent_name, agent_id, target_email, bool(body.test_mode_recipient),
        )

    if not body.test_mode_recipient:
        db.commit()

    return {
        "period": period,
        "sent": sent_count,
        "skipped": skipped_count,
        "errors": error_count,
        "test_mode": bool(body.test_mode_recipient),
        "test_mode_recipient": body.test_mode_recipient,
        "results": results,
    }


def _send_commission_sheet_email(
    to_email: str, agent_name: str, period: str, period_display: str,
    net_pay: float, pdf_bytes: bytes, test_mode: bool = False,
) -> dict:
    """Send a single commission sheet email via Mailgun. Internal helper."""
    import requests
    from app.core.config import settings

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    first_name = (agent_name or "").split()[0] if agent_name else "there"
    subject_prefix = "[TEST] " if test_mode else ""
    subject = f"{subject_prefix}Commission Sheet — {period_display}"

    test_banner = ""
    if test_mode:
        test_banner = (
            '<div style="background:#fef3c7;border:1px solid #f59e0b;padding:12px;'
            'border-radius:8px;margin-bottom:16px;color:#92400e;font-weight:bold;">'
            "TEST MODE — This is a preview. Real send to producer was not performed."
            "</div>"
        )

    html_body = f"""\
<html><body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
                   max-width:600px;margin:auto;color:#0f172a;padding:24px;">
  {test_banner}
  <div style="background:linear-gradient(135deg,#1F3661 0%,#2d4a7a 100%);
              color:white;padding:24px;border-radius:12px 12px 0 0;">
    <h2 style="margin:0;font-size:22px;">Commission Sheet — {period_display}</h2>
    <p style="margin:8px 0 0;opacity:0.85;font-size:14px;">Better Choice Insurance Group</p>
  </div>
  <div style="background:white;border:1px solid #e5e7eb;border-top:0;
              padding:24px;border-radius:0 0 12px 12px;">
    <p>Hi {first_name},</p>
    <p>Your commission sheet for <strong>{period_display}</strong> is attached.
       Please review the details and let Evan know if you have any questions.</p>
    <div style="background:#f3f4f6;padding:16px;border-radius:8px;margin:20px 0;">
      <div style="color:#6b7280;font-size:12px;text-transform:uppercase;
                  letter-spacing:0.5px;margin-bottom:4px;">Net Pay (this period)</div>
      <div style="font-size:28px;font-weight:bold;color:#047857;">
        ${net_pay:,.2f}
      </div>
    </div>
    <p style="color:#6b7280;font-size:13px;">The attached PDF contains the full
       carrier-by-carrier breakdown of your commissions, any chargebacks, rate
       adjustments, and bonuses applied for this period.</p>
    <p style="color:#6b7280;font-size:13px;margin-top:20px;">
       Questions? Reply to this email or reach out to Evan directly.</p>
  </div>
  <p style="color:#94a3b8;font-size:11px;text-align:center;margin-top:16px;">
     Better Choice Insurance Group · 300 Cardinal Dr Suite 220, Saint Charles IL 60175
  </p>
</body></html>
"""

    filename = f"Commission_Sheet_{(agent_name or 'producer').replace(' ', '_')}_{period}.pdf"
    mail_data = {
        "from": "Better Choice Insurance <" + settings.MAILGUN_FROM_EMAIL + ">",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "h:Reply-To": "evan@betterchoiceins.com",
    }
    # BCC Evan on every send for audit trail (skipped in test mode to avoid noise)
    if not test_mode:
        mail_data["bcc"] = ["evan@betterchoiceins.com"]

    files = [("attachment", (filename, pdf_bytes, "application/pdf"))]

    resp = requests.post(
        "https://api.mailgun.net/v3/" + settings.MAILGUN_DOMAIN + "/messages",
        auth=("api", settings.MAILGUN_API_KEY),
        data=mail_data,
        files=files,
        timeout=30,
    )
    if resp.status_code == 200:
        return {"success": True, "message_id": resp.json().get("id", "")}
    return {"success": False, "error": f"Mailgun {resp.status_code}: {resp.text[:200]}"}
