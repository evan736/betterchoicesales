"""Life Insurance Cross-Sell Campaign API - Back9 integration."""
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.sale import Sale
from app.models.campaign import LifeCrossSell
from app.services.back9 import (
    build_prefill_url, get_teaser_quote,
    build_crosssell_email_html, send_crosssell_email,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/life-crosssell", tags=["Life Cross-Sell"])


def _cs_dict(cs):
    d = {}
    for attr in ["id","sale_id","client_name","client_email","client_phone","state",
                  "pc_carrier","pc_policy_type","producer_name","back9_apply_link",
                  "back9_carrier","back9_product","status","campaign_batch"]:
        d[attr] = getattr(cs, attr, None)
    for attr in ["pc_premium","back9_quote_premium","back9_face_amount"]:
        v = getattr(cs, attr, None)
        d[attr] = float(v) if v else None
    for attr in ["email_sent_at","link_clicked_at","app_started_at","app_submitted_at",
                  "approved_at","inforce_at","created_at"]:
        v = getattr(cs, attr, None)
        d[attr] = v.isoformat() if v else None
    return d


@router.get("/eligible")
def list_eligible(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sales = (
        db.query(Sale)
        .filter(Sale.status == "active", Sale.client_email.isnot(None), Sale.client_email != "")
        .order_by(Sale.sale_date.desc()).all()
    )
    existing_emails = set(r[0].lower() for r in db.query(LifeCrossSell.client_email).all())
    seen, eligible = set(), []
    for s in sales:
        ek = s.client_email.lower().strip()
        if ek in seen:
            continue
        seen.add(ek)
        producer = db.query(User).filter(User.id == s.producer_id).first() if s.producer_id else None
        eligible.append({
            "sale_id": s.id, "client_name": s.client_name,
            "client_email": s.client_email, "client_phone": s.client_phone,
            "state": s.state, "carrier": s.carrier, "policy_type": s.policy_type,
            "written_premium": float(s.written_premium) if s.written_premium else None,
            "producer_name": producer.full_name if producer else None,
            "producer_id": s.producer_id,
            "already_sent": ek in existing_emails,
        })
    return {
        "total": len(eligible),
        "already_contacted": len([e for e in eligible if e["already_sent"]]),
        "ready_to_send": len([e for e in eligible if not e["already_sent"]]),
        "eligible": eligible,
    }


@router.get("/campaigns")
def list_campaigns(status: Optional[str] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(LifeCrossSell).order_by(LifeCrossSell.created_at.desc())
    if status:
        q = q.filter(LifeCrossSell.status == status)
    items = q.limit(200).all()
    return {"total": len(items), "campaigns": [_cs_dict(c) for c in items]}


@router.get("/stats")
def campaign_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.query(LifeCrossSell).count()
    sent = db.query(LifeCrossSell).filter(LifeCrossSell.status != "pending").count()
    clicked = db.query(LifeCrossSell).filter(LifeCrossSell.link_clicked_at.isnot(None)).count()
    apps = db.query(LifeCrossSell).filter(LifeCrossSell.app_started_at.isnot(None)).count()
    submitted = db.query(LifeCrossSell).filter(LifeCrossSell.app_submitted_at.isnot(None)).count()
    approved = db.query(LifeCrossSell).filter(LifeCrossSell.approved_at.isnot(None)).count()
    inforce = db.query(LifeCrossSell).filter(LifeCrossSell.inforce_at.isnot(None)).count()
    return {"total": total, "sent": sent, "clicked": clicked, "apps_started": apps,
            "submitted": submitted, "approved": approved, "inforce": inforce}


class SendRequest(BaseModel):
    sale_ids: List[int]
    fetch_teaser: bool = False


@router.post("/send")
def send_crosssell_batch(body: SendRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    batch_id = datetime.utcnow().strftime("%Y-%m-%d-%H%M")
    results = {"sent": 0, "skipped": 0, "errors": 0, "details": []}

    for sale_id in body.sale_ids:
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale or not sale.client_email:
            results["skipped"] += 1
            continue

        existing = db.query(LifeCrossSell).filter(
            LifeCrossSell.client_email.ilike(sale.client_email.strip())
        ).first()
        if existing:
            results["skipped"] += 1
            results["details"].append({"sale_id": sale_id, "reason": "already_sent"})
            continue

        producer = db.query(User).filter(User.id == sale.producer_id).first() if sale.producer_id else None
        producer_name = producer.full_name if producer else ""
        producer_email = producer.email if producer else "info@betterchoiceins.com"

        parts = (sale.client_name or "").split()
        first_name = parts[0] if parts else "there"
        last_name = parts[-1] if len(parts) > 1 else ""

        apply_url = build_prefill_url(
            first_name=first_name, last_name=last_name,
            state=sale.state or "IL", email=sale.client_email,
            phone=sale.client_phone or "",
            metadata={"source": "bci_crosssell", "sale_id": str(sale_id), "batch": batch_id},
        )

        teaser_premium = None
        teaser_benefit = 500000
        if body.fetch_teaser:
            tq = get_teaser_quote(first_name=first_name, last_name=last_name, state=sale.state or "IL")
            if tq:
                teaser_premium = tq["premium"]
                teaser_benefit = tq["death_benefit"]

        cs = LifeCrossSell(
            sale_id=sale.id, client_name=sale.client_name,
            client_email=sale.client_email, client_phone=sale.client_phone,
            state=sale.state, pc_carrier=sale.carrier,
            pc_policy_type=sale.policy_type,
            pc_premium=sale.written_premium,
            producer_id=sale.producer_id, producer_name=producer_name,
            back9_apply_link=apply_url,
            back9_quote_premium=teaser_premium,
            back9_face_amount=teaser_benefit,
            status="pending", campaign_batch=batch_id,
        )
        db.add(cs)
        db.flush()

        html = build_crosssell_email_html(
            first_name=first_name, apply_url=apply_url,
            pc_carrier=sale.carrier or "", pc_policy_type=sale.policy_type or "",
            teaser_premium=teaser_premium, teaser_death_benefit=teaser_benefit,
            producer_name=producer_name,
        )

        carrier_name = sale.carrier or "P&C"
        subject = f"{first_name}, protect your family with life insurance"

        ok = send_crosssell_email(
            to_email=sale.client_email, subject=subject, html=html,
            reply_to=producer_email,
        )

        if ok:
            cs.status = "email_sent"
            cs.email_sent_at = datetime.utcnow()
            results["sent"] += 1
            results["details"].append({"sale_id": sale_id, "crosssell_id": cs.id, "status": "sent"})
        else:
            cs.status = "error"
            results["errors"] += 1
            results["details"].append({"sale_id": sale_id, "status": "email_failed"})

    db.commit()
    return results


@router.get("/{cs_id}/click")
def track_click(cs_id: int, db: Session = Depends(get_db)):
    """Track link click and redirect to Back9 Quote & Apply."""
    from app.core.database import SessionLocal
    session = SessionLocal()
    try:
        cs = session.query(LifeCrossSell).filter(LifeCrossSell.id == cs_id).first()
        if cs:
            if not cs.link_clicked_at:
                cs.link_clicked_at = datetime.utcnow()
            cs.status = "clicked"
            session.commit()
            return RedirectResponse(url=cs.back9_apply_link)
    finally:
        session.close()
    return RedirectResponse(url="https://back9ins.com")


@router.post("/webhook")
async def back9_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Back9 eApp status updates via webhook."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    eapp_id = payload.get("id")
    status = payload.get("status", "").lower()
    metadata = payload.get("metadata") or {}
    sale_id = metadata.get("sale_id")

    cs = None
    if sale_id:
        cs = db.query(LifeCrossSell).filter(LifeCrossSell.sale_id == int(sale_id)).first()
    if not cs and eapp_id:
        cs = db.query(LifeCrossSell).filter(LifeCrossSell.back9_eapp_id == eapp_id).first()

    if not cs:
        logger.warning(f"Back9 webhook: no matching cross-sell for eapp {eapp_id}")
        return {"ok": True, "matched": False}

    # Update tracking
    if eapp_id and not cs.back9_eapp_id:
        cs.back9_eapp_id = eapp_id
    cs.back9_eapp_uuid = payload.get("uuid", cs.back9_eapp_uuid)

    named_step = payload.get("named_step", "")
    if payload.get("first_name") and not cs.app_started_at:
        cs.app_started_at = datetime.utcnow()
        cs.status = "app_started"

    if status == "completed" and not cs.app_submitted_at:
        cs.app_submitted_at = datetime.utcnow()
        cs.status = "app_submitted"

    case_data = payload.get("case") or {}
    case_status = (case_data.get("status") or "").lower()
    if case_status == "approved" and not cs.approved_at:
        cs.approved_at = datetime.utcnow()
        cs.status = "approved"
    if case_status in ("inforce", "in force") and not cs.inforce_at:
        cs.inforce_at = datetime.utcnow()
        cs.status = "inforce"

    carrier = payload.get("carrier", {})
    if carrier.get("name"):
        cs.back9_carrier = carrier["name"]
    product = payload.get("product", {})
    if product.get("name"):
        cs.back9_product = product["name"]
    if payload.get("face_amount"):
        cs.back9_face_amount = payload["face_amount"]
    if payload.get("premium"):
        cs.back9_quote_premium = payload["premium"]

    db.commit()
    logger.info(f"Back9 webhook: updated cross-sell {cs.id} -> {cs.status}")
    return {"ok": True, "matched": True, "crosssell_id": cs.id, "status": cs.status}


@router.get("/preview-email/{sale_id}")
def preview_email(sale_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Preview cross-sell email for a customer."""
    from fastapi.responses import HTMLResponse
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(404, "Sale not found")

    parts = (sale.client_name or "").split()
    first_name = parts[0] if parts else "there"
    last_name = parts[-1] if len(parts) > 1 else ""
    producer = db.query(User).filter(User.id == sale.producer_id).first() if sale.producer_id else None

    apply_url = build_prefill_url(
        first_name=first_name, last_name=last_name,
        state=sale.state or "IL", email=sale.client_email or "",
        phone=sale.client_phone or "",
    )

    html = build_crosssell_email_html(
        first_name=first_name, apply_url=apply_url,
        pc_carrier=sale.carrier or "", pc_policy_type=sale.policy_type or "",
        producer_name=producer.full_name if producer else "",
    )
    return HTMLResponse(content=html)
