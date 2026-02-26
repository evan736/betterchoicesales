"""
Smart Inbox API — Mailgun inbound webhook receiver + management endpoints.

Endpoints:
  POST /api/smart-inbox/inbound          — Mailgun inbound webhook (receives forwarded emails)
  GET  /api/smart-inbox/emails           — List all inbound emails (with filters)
  GET  /api/smart-inbox/emails/{id}      — Get single email detail
  GET  /api/smart-inbox/queue            — List outbound queue (pending approval)
  POST /api/smart-inbox/queue/{id}/approve — Approve & send a queued message
  POST /api/smart-inbox/queue/{id}/reject  — Reject a queued message
  POST /api/smart-inbox/queue/{id}/edit    — Edit before approving
  GET  /api/smart-inbox/stats            — Dashboard statistics
  POST /api/smart-inbox/reprocess/{id}   — Reprocess a failed email
"""
import os
import json
import hmac
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_

from app.core.database import get_db
from app.models.smart_inbox import (
    InboundEmail, OutboundQueue,
    EmailCategory, SensitivityLevel, ProcessingStatus, OutboundStatus,
)
from app.services.smart_inbox_ai import classify_email, draft_response, determine_auto_send
from app.services.smart_inbox_nowcerts import (
    lookup_customer, log_note_to_customer,
    format_inbound_note, format_outbound_note,
)
from app.services.smart_inbox_batch import (
    detect_batch_report, parse_batch_report, build_child_email_data,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/smart-inbox", tags=["smart-inbox"])

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_WEBHOOK_SIGNING_KEY = os.getenv("MAILGUN_WEBHOOK_SIGNING_KEY", "")  # separate from API key
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
AGENCY_FROM_EMAIL = os.getenv("AGENCY_FROM_EMAIL", "service@betterchoiceins.com")
AGENCY_REPLY_TO = os.getenv("AGENCY_REPLY_TO", "service@betterchoiceins.com")
AGENCY_BCC = os.getenv("SMART_INBOX_BCC", "evan@betterchoiceins.com")
SMART_INBOX_ADDRESS = os.getenv("SMART_INBOX_ADDRESS", "process@mail.betterchoiceins.com")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _verify_mailgun_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify Mailgun webhook signature using the webhook signing key."""
    signing_key = MAILGUN_WEBHOOK_SIGNING_KEY or MAILGUN_API_KEY
    if not signing_key:
        return True  # Skip verification if no key configured
    hmac_digest = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(str(signature), str(hmac_digest))


async def _send_via_mailgun(to: str, subject: str, html: str, cc: Optional[str] = None) -> Optional[str]:
    """Send email via Mailgun. Returns message ID or None."""
    import httpx
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        logger.error("Mailgun not configured")
        return None

    data = {
        "from": f"Better Choice Insurance <{AGENCY_FROM_EMAIL}>",
        "h:Reply-To": AGENCY_REPLY_TO,
        "to": to,
        "subject": subject,
        "html": html,
    }
    if cc:
        data["cc"] = cc
    if AGENCY_BCC:
        data["bcc"] = AGENCY_BCC

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                auth=("api", MAILGUN_API_KEY),
                data=data,
            )
            if resp.status_code == 200:
                msg_id = resp.json().get("id")
                logger.info(f"Email sent via Mailgun: {msg_id}")
                return msg_id
            else:
                logger.error(f"Mailgun send failed: {resp.status_code} — {resp.text[:200]}")
                return None
    except Exception as e:
        logger.error(f"Mailgun send error: {e}")
        return None


async def _send_evan_alert(inbound: InboundEmail, outbound: Optional[OutboundQueue] = None):
    """Send alert to Evan for sensitive/critical items."""
    import httpx
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        return

    alert_html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px;">
        <div style="background: #0f172a; color: #22d3ee; padding: 16px 24px; border-radius: 8px 8px 0 0;">
            <h2 style="margin:0;">🚨 Smart Inbox Alert</h2>
        </div>
        <div style="background: #1e293b; color: #e2e8f0; padding: 24px; border-radius: 0 0 8px 8px;">
            <p><strong>Category:</strong> {(inbound.category or 'unknown').replace('_', ' ').title()}</p>
            <p><strong>Sensitivity:</strong> <span style="color: #f87171;">{(inbound.sensitivity or 'unknown').upper()}</span></p>
            <p><strong>From:</strong> {inbound.from_address}</p>
            <p><strong>Subject:</strong> {inbound.subject}</p>
            <p><strong>Customer:</strong> {inbound.customer_name or 'Not matched'}</p>
            <p><strong>Policy:</strong> {inbound.extracted_policy_number or 'N/A'}</p>
            <p><strong>AI Summary:</strong> {inbound.ai_summary or 'N/A'}</p>
            <hr style="border-color: #334155;">
            <p style="font-size: 13px; color: #94a3b8;">
                {'A draft response is waiting for your approval in ORBIT Smart Inbox.' if outbound else 'This email requires your attention.'}
            </p>
            <a href="https://better-choice-web.onrender.com/smart-inbox"
               style="display: inline-block; background: #22d3ee; color: #0f172a; padding: 10px 24px; border-radius: 6px; text-decoration: none; font-weight: 600;">
                Review in ORBIT →
            </a>
        </div>
    </div>
    """

    data = {
        "from": f"ORBIT Smart Inbox <{AGENCY_FROM_EMAIL}>",
        "to": "evan@betterchoiceins.com",
        "subject": f"🚨 Smart Inbox: {(inbound.category or 'email').replace('_', ' ').title()} — {inbound.extracted_insured_name or inbound.subject}",
        "html": alert_html,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                auth=("api", MAILGUN_API_KEY),
                data=data,
            )
    except Exception as e:
        logger.error(f"Failed to send Evan alert: {e}")


# ── Background Processing Pipeline ──────────────────────────────────────────

async def process_inbound_email(email_id: int, db_url: str):
    """
    Full async pipeline: classify → match customer → log note → draft response → send/queue.
    Runs as a background task.
    """
    from app.core.database import SessionLocal
    db = SessionLocal()

    try:
        email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
        if not email:
            logger.error(f"InboundEmail {email_id} not found")
            return

        # ── Step 1: AI Classification ────────────────────────────────────
        email.status = ProcessingStatus.PARSING
        db.commit()

        classification = await classify_email(
            from_address=email.from_address,
            subject=email.subject,
            body=email.body_plain or email.body_html or "",
            attachments=email.attachment_data,
        )

        if "error" in classification:
            email.error_message = classification["error"]
            # Still use fallback values
        
        email.category = classification.get("category", "other")
        email.sensitivity = classification.get("sensitivity", "sensitive")
        email.ai_summary = classification.get("summary")
        email.ai_analysis = classification
        email.confidence_score = classification.get("confidence", 0.5)

        extracted = classification.get("extracted", {})
        email.extracted_policy_number = extracted.get("policy_number")
        email.extracted_insured_name = extracted.get("insured_name")
        email.extracted_carrier = extracted.get("carrier")
        if extracted.get("due_date"):
            try:
                email.extracted_due_date = datetime.strptime(extracted["due_date"], "%Y-%m-%d")
            except ValueError:
                pass
        email.extracted_amount = extracted.get("amount")

        email.status = ProcessingStatus.PARSED
        db.commit()

        # ── Step 2: Customer Matching ────────────────────────────────────
        customer, match_method, match_confidence = await lookup_customer(
            policy_number=email.extracted_policy_number,
            email=extracted.get("email"),
            phone=extracted.get("phone"),
            name=email.extracted_insured_name,
        )

        if customer:
            email.nowcerts_insured_id = str(customer.get("database_id") or "") or None
            email.customer_name = customer.get("commercial_name") or f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
            email.customer_email = customer.get("email")
            email.match_method = match_method
            email.match_confidence = match_confidence
            email.status = ProcessingStatus.CUSTOMER_MATCHED
        else:
            email.status = ProcessingStatus.CUSTOMER_NOT_FOUND

        db.commit()

        # ── Step 3: Log Note to Customer File ────────────────────────────
        # Attempt note logging if we have a customer match (even without NowCerts ID)
        # insert_note() will search NowCerts by name/email when insured_database_id is empty
        if customer:
            note_body = format_inbound_note(
                subject=email.subject or "(no subject)",
                from_address=email.from_address,
                category=email.category or "other",
                summary=email.ai_summary or "No summary",
                body_preview=email.body_plain or "",
                carrier=email.extracted_carrier or "",
                policy_number=email.extracted_policy_number or "",
                due_date=email.extracted_due_date or "",
                amount=str(email.extracted_amount) if email.extracted_amount else "",
            )
            # Use AI summary as the note subject — much more useful than raw email subject
            note_subject = f"{(email.category or 'other').replace('_', ' ').title()}: {email.ai_summary or email.subject or 'Forwarded Email'}"
            note_id = await log_note_to_customer(
                insured_id=email.nowcerts_insured_id or "",
                subject=note_subject[:200],
                note_body=note_body,
                customer_name=email.customer_name or "",
                customer_email=email.customer_email or "",
            )
            if note_id:
                email.nowcerts_note_logged = True
                email.nowcerts_note_id = note_id
                email.status = ProcessingStatus.LOGGED
                db.commit()
            else:
                email.nowcerts_note_logged = False
                db.commit()
                logger.warning(f"NowCerts note logging failed for {email.customer_name} (email #{email.id})")

        # ── Step 4: Draft Client Communication ───────────────────────────
        needs_comm = classification.get("needs_client_communication", False)
        if needs_comm and email.customer_email:
            draft = await draft_response(
                summary=email.ai_summary or "",
                category=email.category or "other",
                carrier=email.extracted_carrier,
                policy_number=email.extracted_policy_number,
                customer_name=email.customer_name or "Valued Customer",
                original_body=email.body_plain or "",
            )

            if "error" not in draft:
                auto_send = determine_auto_send(
                    category=email.category or "other",
                    sensitivity=email.sensitivity or "sensitive",
                )

                outbound = OutboundQueue(
                    inbound_email_id=email.id,
                    to_email=email.customer_email,
                    to_name=email.customer_name,
                    subject=draft.get("subject", f"Update on your policy — {email.extracted_policy_number or ''}"),
                    body_html=draft.get("body_html", ""),
                    body_plain=draft.get("body_plain", ""),
                    ai_rationale=draft.get("rationale"),
                    sensitivity=email.sensitivity,
                    status=OutboundStatus.AUTO_SENT if auto_send else OutboundStatus.PENDING_APPROVAL,
                )
                db.add(outbound)
                db.commit()

                # Auto-send routine ones
                if auto_send:
                    msg_id = await _send_via_mailgun(
                        to=outbound.to_email,
                        subject=outbound.subject,
                        html=outbound.body_html,
                    )
                    if msg_id:
                        outbound.sent_at = datetime.utcnow()
                        outbound.mailgun_message_id = msg_id
                        email.status = ProcessingStatus.OUTBOUND_SENT

                        # Log outbound to NowCerts too
                        if email.customer_name:
                            out_note = format_outbound_note(
                                to_email=outbound.to_email,
                                subject=outbound.subject,
                                status="sent",
                                body_preview=outbound.body_plain or "",
                            )
                            await log_note_to_customer(
                                insured_id=email.nowcerts_insured_id or "",
                                subject=f"Smart Inbox: Sent — {outbound.subject}",
                                note_body=out_note,
                                customer_name=email.customer_name or "",
                                customer_email=email.customer_email or "",
                            )
                    else:
                        outbound.send_error = "Mailgun send failed"
                        outbound.status = OutboundStatus.PENDING_APPROVAL
                else:
                    email.status = ProcessingStatus.OUTBOUND_QUEUED
                    # Alert Evan for sensitive items
                    if email.sensitivity in ("sensitive", "critical"):
                        await _send_evan_alert(email, outbound)

                db.commit()
            else:
                email.processing_notes = f"Draft failed: {draft.get('error')}"
                db.commit()
        elif needs_comm and not email.customer_email:
            email.processing_notes = "Client communication needed but no customer email found"
            email.status = ProcessingStatus.CUSTOMER_NOT_FOUND
            db.commit()
        else:
            email.status = ProcessingStatus.COMPLETED
            db.commit()

        # Broadcast SSE event for live updates
        try:
            from app.api.events import event_bus
            event_bus.publish_sync("smart_inbox:new", {
                "id": email.id,
                "status": email.status.value if email.status else None,
                "category": email.category,
                "customer_name": email.customer_name,
            })
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"Processing pipeline failed for email {email_id}")
        try:
            email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
            if email:
                email.status = ProcessingStatus.FAILED
                email.error_message = str(e)[:500]
                email.retry_count = (email.retry_count or 0) + 1
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ── Inbound Webhook ──────────────────────────────────────────────────────────


async def process_batch_report(email_id: int, db_url: str, batch_info: dict):
    """
    Process a batch report email: parse table rows → create child InboundEmail
    per customer → process each child through the normal pipeline.
    """
    from app.core.database import SessionLocal
    db = SessionLocal()

    try:
        email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
        if not email:
            logger.error(f"Batch report InboundEmail {email_id} not found")
            return

        # Mark parent as batch report
        email.is_batch_report = True
        email.status = ProcessingStatus.PARSING
        email.extracted_carrier = batch_info.get("carrier")
        email.category = "other"
        email.sensitivity = "routine"
        db.commit()

        # Parse the report table
        items = parse_batch_report(
            body_html=email.body_html or "",
            body_plain=email.body_plain or "",
            report_type=batch_info["report_type"],
            carrier=batch_info.get("carrier", "Unknown"),
        )

        if not items:
            email.ai_summary = f"Batch report detected ({batch_info['name']}) but no items parsed"
            email.status = ProcessingStatus.COMPLETED
            email.batch_item_count = 0
            db.commit()
            logger.warning(f"Batch report {email_id} had no parseable items")
            return

        email.batch_item_count = len(items)
        email.ai_summary = f"Batch report: {len(items)} items from {batch_info.get('carrier', 'carrier')} {batch_info['report_type'].replace('_', ' ')} report"
        email.status = ProcessingStatus.COMPLETED
        db.commit()

        # Create child InboundEmail records
        child_ids = []
        for item in items:
            child_data = build_child_email_data(
                parent_id=email.id,
                item=item,
                original_from=email.from_address,
                original_subject=email.subject or "",
            )

            child = InboundEmail(
                message_id=f"{email.message_id or email.id}_child_{len(child_ids)}",
                to_address=email.to_address,
                status=ProcessingStatus.PARSED,  # skip AI classification — we already parsed it
                is_read=False,
                is_archived=False,
                **child_data,
            )
            db.add(child)
            db.flush()
            child_ids.append(child.id)

        db.commit()
        logger.info(f"Batch report {email_id}: created {len(child_ids)} child records")

        # Process each child through the pipeline (customer matching + drafting)
        for child_id in child_ids:
            await _process_batch_child(child_id, db)

        # Broadcast SSE
        try:
            from app.api.events import event_bus
            event_bus.publish_sync("smart_inbox:batch", {
                "parent_id": email.id,
                "child_count": len(child_ids),
                "report_type": batch_info["report_type"],
            })
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"Batch report processing failed for email {email_id}")
        try:
            email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
            if email:
                email.status = ProcessingStatus.FAILED
                email.error_message = f"Batch parsing failed: {str(e)[:400]}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _process_batch_child(child_id: int, db):
    """
    Process a single child item from a batch report:
    customer match → NowCerts note → draft response if needed.
    Skips AI classification (already done by the parser).
    """
    try:
        child = db.query(InboundEmail).filter(InboundEmail.id == child_id).first()
        if not child:
            return

        # ── Customer Matching ────────────────────────────────────────────
        customer, match_method, match_confidence = await lookup_customer(
            policy_number=child.extracted_policy_number,
            name=child.extracted_insured_name,
        )

        if customer:
            child.nowcerts_insured_id = str(customer.get("database_id") or "") or None
            child.customer_name = (
                customer.get("commercial_name")
                or f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
            )
            child.customer_email = customer.get("email")
            child.match_method = match_method
            child.match_confidence = match_confidence
            child.status = ProcessingStatus.CUSTOMER_MATCHED
        else:
            child.status = ProcessingStatus.CUSTOMER_NOT_FOUND

        db.commit()

        # ── Log Note to NowCerts ─────────────────────────────────────────
        if customer:
            note_body = format_inbound_note(
                subject=child.subject or "(batch item)",
                from_address=child.from_address,
                category=child.category or "other",
                summary=child.ai_summary or "Batch report item",
                body_preview=child.body_plain or "",
                carrier=child.extracted_carrier or "",
                policy_number=child.extracted_policy_number or "",
                due_date=child.extracted_due_date or "",
                amount=str(child.extracted_amount) if child.extracted_amount else "",
            )
            note_subject = f"{(child.category or 'other').replace('_', ' ').title()}: {child.ai_summary or 'Batch Report Item'}"
            note_id = await log_note_to_customer(
                insured_id=child.nowcerts_insured_id or "",
                subject=note_subject[:200],
                note_body=note_body,
                customer_name=child.customer_name or "",
                customer_email=child.customer_email or "",
            )
            if note_id:
                child.nowcerts_note_logged = True
                child.nowcerts_note_id = note_id
                child.status = ProcessingStatus.LOGGED
                db.commit()

        # ── Draft Response (for sensitive items like non-pay cancellations) ──
        sensitivity = child.sensitivity or "routine"
        category = child.category or "other"

        # Only draft responses for items that need client action
        needs_response = category in (
            "non_payment", "cancellation", "non_renewal",
        ) or sensitivity in ("sensitive", "critical")

        if needs_response and child.customer_email:
            draft = await draft_response(
                summary=child.ai_summary or "",
                category=category,
                carrier=child.extracted_carrier,
                policy_number=child.extracted_policy_number,
                customer_name=child.customer_name or "Valued Customer",
                original_body=child.body_plain or "",
            )

            if "error" not in draft:
                auto_send = determine_auto_send(category, sensitivity)

                outbound = OutboundQueue(
                    inbound_email_id=child.id,
                    to_email=child.customer_email,
                    to_name=child.customer_name,
                    subject=draft.get("subject", f"Update on your policy — {child.extracted_policy_number or ''}"),
                    body_html=draft.get("body_html", ""),
                    body_plain=draft.get("body_plain", ""),
                    ai_rationale=draft.get("rationale"),
                    sensitivity=sensitivity,
                    status=OutboundStatus.AUTO_SENT if auto_send else OutboundStatus.PENDING_APPROVAL,
                )
                db.add(outbound)
                db.commit()

                if auto_send:
                    msg_id = await _send_via_mailgun(
                        to=outbound.to_email,
                        subject=outbound.subject,
                        html=outbound.body_html,
                    )
                    if msg_id:
                        outbound.sent_at = datetime.utcnow()
                        outbound.mailgun_message_id = msg_id
                        child.status = ProcessingStatus.OUTBOUND_SENT
                    else:
                        outbound.send_error = "Mailgun send failed"
                        outbound.status = OutboundStatus.PENDING_APPROVAL
                else:
                    child.status = ProcessingStatus.OUTBOUND_QUEUED

                db.commit()
        elif not needs_response:
            child.status = ProcessingStatus.COMPLETED
            db.commit()

    except Exception as e:
        logger.error(f"Batch child {child_id} processing failed: {e}")
        try:
            child = db.query(InboundEmail).filter(InboundEmail.id == child_id).first()
            if child:
                child.status = ProcessingStatus.FAILED
                child.error_message = str(e)[:400]
                db.commit()
        except Exception:
            pass

@router.post("/inbound")
async def receive_inbound_email(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Mailgun inbound webhook — receives forwarded emails.
    Stores the raw email and kicks off background AI processing.
    """
    form = await request.form()

    # Verify Mailgun signature if present (inbound route forwards may not include signature)
    token = form.get("token", "")
    timestamp = form.get("timestamp", "")
    signature = form.get("signature", "")
    if token and timestamp and signature:
        if not _verify_mailgun_signature(token, timestamp, signature):
            logger.warning(f"Mailgun signature mismatch — may need MAILGUN_WEBHOOK_SIGNING_KEY env var. Accepting anyway.")
    else:
        logger.info("Inbound email received without Mailgun signature (normal for route forwards)")

    # Parse email data
    message_id = form.get("Message-Id") or form.get("message-id")
    from_addr = form.get("from", "")
    sender = form.get("sender", "")
    to_addr = form.get("To") or form.get("recipient", "")
    subject = form.get("subject", "")
    body_plain = form.get("body-plain", "")
    body_html = form.get("body-html", "")

    # Count attachments and save PDF/image content for AI analysis
    attachment_count = int(form.get("attachment-count", 0))
    attachment_names = []
    attachment_data = []  # list of {filename, content_type, base64_data}
    for i in range(1, attachment_count + 1):
        att = form.get(f"attachment-{i}")
        if att and hasattr(att, "filename"):
            attachment_names.append(att.filename)
            content_type = getattr(att, "content_type", "") or ""
            # Save PDFs and images for AI vision analysis
            if content_type in ("application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"):
                try:
                    import base64
                    raw = await att.read()
                    if len(raw) <= 10_000_000:  # 10MB limit
                        b64 = base64.b64encode(raw).decode("utf-8")
                        attachment_data.append({
                            "filename": att.filename,
                            "content_type": content_type,
                            "base64_data": b64,
                        })
                        logger.info(f"Saved attachment for AI: {att.filename} ({content_type}, {len(raw)} bytes)")
                    else:
                        logger.warning(f"Attachment too large for AI: {att.filename} ({len(raw)} bytes)")
                except Exception as e:
                    logger.warning(f"Failed to read attachment {att.filename}: {e}")

    # Detect who forwarded it (the X-Forwarded-To or the actual sender)
    forwarded_by = sender or from_addr

    # Check for duplicate
    if message_id:
        existing = db.query(InboundEmail).filter(InboundEmail.message_id == message_id).first()
        if existing:
            return {"status": "duplicate", "id": existing.id}

    # Store raw email
    inbound = InboundEmail(
        message_id=message_id,
        from_address=from_addr,
        to_address=to_addr,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
        sender_name=sender,
        forwarded_by=forwarded_by,
        attachment_count=attachment_count,
        attachment_names=attachment_names if attachment_names else None,
        attachment_data=attachment_data if attachment_data else None,
        status=ProcessingStatus.RECEIVED,
    )
    db.add(inbound)
    db.commit()
    db.refresh(inbound)

    # Kick off async processing
    db_url = os.getenv("DATABASE_URL", "")

    # Check if this is a batch report (multiple customers in one email)
    batch_info = detect_batch_report(from_addr, subject)
    if batch_info:
        background_tasks.add_task(
            process_batch_report, inbound.id, db_url, batch_info
        )
    else:
        background_tasks.add_task(process_inbound_email, inbound.id, db_url)

    return {"status": "received", "id": inbound.id, "batch": batch_info is not None}


# ── Email List & Detail ──────────────────────────────────────────────────────

@router.get("/emails")
def list_inbound_emails(
    status: Optional[str] = None,
    category: Optional[str] = None,
    sensitivity: Optional[str] = None,
    search: Optional[str] = None,
    archived: Optional[bool] = Query(default=None),
    is_read: Optional[bool] = Query(default=None),
    view: Optional[str] = Query(default=None),  # "needs_attention", "completed", "all"
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List inbound emails with optional filters."""
    q = db.query(InboundEmail).filter(
        InboundEmail.created_at >= datetime.utcnow() - timedelta(days=days)
    )

    # By default, hide archived
    if archived is not None:
        q = q.filter(InboundEmail.is_archived == archived)
    else:
        q = q.filter(InboundEmail.is_archived == False)

    if is_read is not None:
        q = q.filter(InboundEmail.is_read == is_read)

    # View presets
    if view == "needs_attention":
        q = q.filter(InboundEmail.status.in_([
            "received", "parsing", "outbound_queued", "failed", "customer_not_found"
        ]))
    elif view == "completed":
        q = q.filter(InboundEmail.status.in_([
            "completed", "outbound_sent", "outbound_approved", "outbound_rejected", "skipped"
        ]))

    if status:
        q = q.filter(InboundEmail.status == status)
    if category:
        q = q.filter(InboundEmail.category == category)
    if sensitivity:
        q = q.filter(InboundEmail.sensitivity == sensitivity)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            (InboundEmail.subject.ilike(pattern)) |
            (InboundEmail.customer_name.ilike(pattern)) |
            (InboundEmail.extracted_policy_number.ilike(pattern)) |
            (InboundEmail.from_address.ilike(pattern))
        )

    total = q.count()
    unread_count = q.filter(InboundEmail.is_read == False).count() if is_read is None else 0
    emails = q.order_by(desc(InboundEmail.created_at)).offset(offset).limit(limit).all()

    return {
        "total": total,
        "unread_count": unread_count,
        "emails": [_serialize_inbound(e) for e in emails],
    }


@router.get("/emails/{email_id}")
def get_inbound_email(email_id: int, db: Session = Depends(get_db)):
    """Get full detail for a single inbound email."""
    email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    result = _serialize_inbound(email)
    result["body_plain"] = email.body_plain
    result["body_html"] = email.body_html
    result["ai_analysis"] = email.ai_analysis
    result["outbound_messages"] = [_serialize_outbound(o) for o in email.outbound_messages]

    # Include child items if this is a batch report
    if getattr(email, "is_batch_report", False):
        children = (
            db.query(InboundEmail)
            .filter(InboundEmail.parent_email_id == email.id)
            .order_by(InboundEmail.id)
            .all()
        )
        result["child_items"] = [_serialize_inbound(c) for c in children]

    return result


@router.get("/emails/{email_id}/children")
def list_batch_children(email_id: int, db: Session = Depends(get_db)):
    """List all child items for a batch report email."""
    children = (
        db.query(InboundEmail)
        .filter(InboundEmail.parent_email_id == email_id)
        .order_by(InboundEmail.id)
        .all()
    )
    return {
        "parent_id": email_id,
        "count": len(children),
        "items": [_serialize_inbound(c) for c in children],
    }


# ── Outbound Queue Management ───────────────────────────────────────────────

@router.get("/queue")
def list_outbound_queue(
    status: Optional[str] = Query(default="pending_approval"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List outbound messages (default: pending approval)."""
    q = db.query(OutboundQueue)
    if status:
        q = q.filter(OutboundQueue.status == status)

    items = q.order_by(desc(OutboundQueue.created_at)).limit(limit).all()
    return {"queue": [_serialize_outbound(o) for o in items]}


@router.post("/queue/{item_id}/approve")
async def approve_outbound(item_id: int, db: Session = Depends(get_db)):
    """Approve and send a queued outbound message."""
    item = db.query(OutboundQueue).filter(OutboundQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    if item.status not in (OutboundStatus.PENDING_APPROVAL, OutboundStatus.DRAFT):
        raise HTTPException(status_code=400, detail=f"Cannot approve item in status: {item.status}")

    # Send via Mailgun
    msg_id = await _send_via_mailgun(
        to=item.to_email,
        subject=item.subject,
        html=item.body_html,
    )

    if msg_id:
        item.status = OutboundStatus.SENT
        item.sent_at = datetime.utcnow()
        item.mailgun_message_id = msg_id
        item.approved_by = "evan"
        item.approved_at = datetime.utcnow()

        # Update parent email status
        inbound = db.query(InboundEmail).filter(InboundEmail.id == item.inbound_email_id).first()
        if inbound:
            inbound.status = ProcessingStatus.OUTBOUND_SENT
            # Log to NowCerts
            if inbound.customer_name:
                out_note = format_outbound_note(
                    to_email=item.to_email,
                    subject=item.subject,
                    status="sent",
                    body_preview=item.body_plain or "",
                )
                await log_note_to_customer(
                    insured_id=inbound.nowcerts_insured_id or "",
                    subject=f"Smart Inbox: Sent — {item.subject}",
                    note_body=out_note,
                    customer_name=inbound.customer_name or "",
                    customer_email=inbound.customer_email or "",
                )

        db.commit()
        # Broadcast SSE event
        try:
            from app.api.events import event_bus
            event_bus.publish_sync("smart_inbox:updated", {"id": item_id, "action": "approved"})
        except Exception:
            pass
        return {"status": "sent", "mailgun_id": msg_id}
    else:
        item.send_error = "Mailgun send failed"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to send email")


@router.post("/queue/{item_id}/reject")
def reject_outbound(
    item_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Reject a queued outbound message."""
    item = db.query(OutboundQueue).filter(OutboundQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    item.status = OutboundStatus.REJECTED
    item.rejected_reason = reason or "Rejected by admin"

    inbound = db.query(InboundEmail).filter(InboundEmail.id == item.inbound_email_id).first()
    if inbound:
        inbound.status = ProcessingStatus.OUTBOUND_REJECTED

    db.commit()
    # Broadcast SSE event
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("smart_inbox:updated", {"id": item_id, "action": "rejected"})
    except Exception:
        pass
    return {"status": "rejected"}


@router.post("/queue/{item_id}/edit")
async def edit_and_approve(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Edit an outbound message body/subject, then optionally send."""
    item = db.query(OutboundQueue).filter(OutboundQueue.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    body = await request.json()
    if "subject" in body:
        item.subject = body["subject"]
    if "body_html" in body:
        item.body_html = body["body_html"]
    if "body_plain" in body:
        item.body_plain = body["body_plain"]

    send_now = body.get("send", False)
    if send_now:
        msg_id = await _send_via_mailgun(to=item.to_email, subject=item.subject, html=item.body_html)
        if msg_id:
            item.status = OutboundStatus.SENT
            item.sent_at = datetime.utcnow()
            item.mailgun_message_id = msg_id
            item.approved_by = "evan"
            item.approved_at = datetime.utcnow()
        else:
            item.send_error = "Mailgun send failed"
    else:
        item.status = OutboundStatus.DRAFT

    db.commit()
    return {"status": item.status, "id": item.id}


# ── Batch Actions ─────────────────────────────────────────────────────────

@router.post("/emails/{email_id}/read")
def mark_email_read(email_id: int, db: Session = Depends(get_db)):
    """Mark a single email as read."""
    email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.is_read = True
    db.commit()
    return {"status": "ok"}


@router.post("/emails/{email_id}/unread")
def mark_email_unread(email_id: int, db: Session = Depends(get_db)):
    """Mark a single email as unread."""
    email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.is_read = False
    db.commit()
    return {"status": "ok"}


@router.post("/emails/{email_id}/archive")
def archive_email(email_id: int, db: Session = Depends(get_db)):
    """Archive a single email."""
    email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.is_archived = True
    db.commit()
    return {"status": "ok"}


@router.post("/emails/{email_id}/unarchive")
def unarchive_email(email_id: int, db: Session = Depends(get_db)):
    """Unarchive a single email."""
    email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.is_archived = False
    db.commit()
    return {"status": "ok"}


@router.post("/batch")
async def batch_action(request: Request, db: Session = Depends(get_db)):
    """
    Batch actions on multiple emails.
    Body: { "ids": [1,2,3], "action": "read"|"unread"|"archive"|"unarchive" }
    """
    body = await request.json()
    ids = body.get("ids", [])
    action = body.get("action", "")

    if not ids or action not in ("read", "unread", "archive", "unarchive"):
        raise HTTPException(status_code=400, detail="Provide ids[] and action (read/unread/archive/unarchive)")

    emails = db.query(InboundEmail).filter(InboundEmail.id.in_(ids)).all()
    count = 0
    for email in emails:
        if action == "read":
            email.is_read = True
        elif action == "unread":
            email.is_read = False
        elif action == "archive":
            email.is_archived = True
        elif action == "unarchive":
            email.is_archived = False
        count += 1
    db.commit()
    return {"status": "ok", "affected": count}


@router.post("/batch/approve")
async def batch_approve(request: Request, db: Session = Depends(get_db)):
    """
    Batch approve multiple outbound queue items.
    Body: { "ids": [1,2,3] }
    """
    body = await request.json()
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="Provide ids[]")

    results = []
    for item_id in ids:
        item = db.query(OutboundQueue).filter(
            OutboundQueue.id == item_id,
            OutboundQueue.status.in_([OutboundStatus.PENDING_APPROVAL, OutboundStatus.DRAFT]),
        ).first()
        if not item:
            results.append({"id": item_id, "status": "not_found"})
            continue

        msg_id = await _send_via_mailgun(to=item.to_email, subject=item.subject, html=item.body_html)
        if msg_id:
            item.status = OutboundStatus.SENT
            item.sent_at = datetime.utcnow()
            item.mailgun_message_id = msg_id
            item.approved_by = "evan"
            item.approved_at = datetime.utcnow()

            inbound = db.query(InboundEmail).filter(InboundEmail.id == item.inbound_email_id).first()
            if inbound:
                inbound.status = ProcessingStatus.OUTBOUND_SENT

                if inbound.customer_name:
                    out_note = format_outbound_note(
                        to_email=item.to_email,
                        subject=item.subject,
                        status="sent",
                        body_preview=item.body_plain or "",
                    )
                    await log_note_to_customer(
                        insured_id=inbound.nowcerts_insured_id or "",
                        subject=f"Smart Inbox: Sent — {item.subject}",
                        note_body=out_note,
                        customer_name=inbound.customer_name or "",
                        customer_email=inbound.customer_email or "",
                    )

            results.append({"id": item_id, "status": "sent"})
        else:
            item.send_error = "Mailgun send failed"
            results.append({"id": item_id, "status": "send_failed"})

    db.commit()
    return {"results": results}


# ── Reprocess ────────────────────────────────────────────────────────────────

@router.post("/reprocess/{email_id}")
async def reprocess_email(
    email_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Reprocess a failed email through the AI pipeline."""
    email = db.query(InboundEmail).filter(InboundEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    email.status = ProcessingStatus.RECEIVED
    email.error_message = None
    db.commit()

    db_url = os.getenv("DATABASE_URL", "")
    background_tasks.add_task(process_inbound_email, email.id, db_url)
    return {"status": "reprocessing", "id": email.id}


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_inbox_stats(db: Session = Depends(get_db)):
    """Dashboard statistics for Smart Inbox."""
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    total_24h = db.query(func.count(InboundEmail.id)).filter(InboundEmail.created_at >= last_24h).scalar()
    total_7d = db.query(func.count(InboundEmail.id)).filter(InboundEmail.created_at >= last_7d).scalar()
    pending_approval = db.query(func.count(OutboundQueue.id)).filter(OutboundQueue.status == OutboundStatus.PENDING_APPROVAL).scalar()
    auto_sent_24h = db.query(func.count(OutboundQueue.id)).filter(
        and_(OutboundQueue.status == OutboundStatus.AUTO_SENT, OutboundQueue.created_at >= last_24h)
    ).scalar()
    failed = db.query(func.count(InboundEmail.id)).filter(InboundEmail.status == ProcessingStatus.FAILED).scalar()
    matched = db.query(func.count(InboundEmail.id)).filter(
        and_(InboundEmail.nowcerts_insured_id.isnot(None), InboundEmail.created_at >= last_7d)
    ).scalar()
    unmatched = db.query(func.count(InboundEmail.id)).filter(
        and_(InboundEmail.status == ProcessingStatus.CUSTOMER_NOT_FOUND, InboundEmail.created_at >= last_7d)
    ).scalar()

    # Category breakdown (last 7 days)
    cat_breakdown = (
        db.query(InboundEmail.category, func.count(InboundEmail.id))
        .filter(InboundEmail.created_at >= last_7d)
        .group_by(InboundEmail.category)
        .all()
    )

    return {
        "received_24h": total_24h or 0,
        "received_7d": total_7d or 0,
        "pending_approval": pending_approval or 0,
        "auto_sent_24h": auto_sent_24h or 0,
        "failed": failed or 0,
        "matched_7d": matched or 0,
        "unmatched_7d": unmatched or 0,
        "category_breakdown": {cat: count for cat, count in cat_breakdown if cat},
    }


# ── Serializers ──────────────────────────────────────────────────────────────

def _serialize_inbound(e: InboundEmail) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "from_address": e.from_address,
        "subject": e.subject,
        "category": e.category,
        "sensitivity": e.sensitivity,
        "ai_summary": e.ai_summary,
        "confidence_score": e.confidence_score,
        "extracted_policy_number": e.extracted_policy_number,
        "extracted_insured_name": e.extracted_insured_name,
        "extracted_carrier": e.extracted_carrier,
        "customer_name": e.customer_name,
        "customer_email": e.customer_email,
        "match_method": e.match_method,
        "match_confidence": e.match_confidence,
        "status": e.status,
        "nowcerts_note_logged": e.nowcerts_note_logged,
        "error_message": e.error_message,
        "attachment_count": e.attachment_count,
        "has_outbound": len(e.outbound_messages) > 0 if e.outbound_messages else False,
        "is_read": getattr(e, "is_read", False) or False,
        "is_archived": getattr(e, "is_archived", False) or False,
        "is_batch_report": getattr(e, "is_batch_report", False) or False,
        "batch_item_count": getattr(e, "batch_item_count", None),
        "parent_email_id": getattr(e, "parent_email_id", None),
    }


def _serialize_outbound(o: OutboundQueue) -> dict:
    return {
        "id": o.id,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "to_email": o.to_email,
        "to_name": o.to_name,
        "subject": o.subject,
        "body_html": o.body_html,
        "body_plain": o.body_plain,
        "ai_rationale": o.ai_rationale,
        "status": o.status,
        "sensitivity": o.sensitivity,
        "sent_at": o.sent_at.isoformat() if o.sent_at else None,
        "approved_by": o.approved_by,
        "rejected_reason": o.rejected_reason,
        "send_error": o.send_error,
    }


# ── Debug / Test Endpoint ────────────────────────────────────────────────────

@router.get("/debug/lookup/{policy_number}")
def debug_lookup(policy_number: str, db: Session = Depends(get_db)):
    """Debug endpoint: test customer lookup by policy number."""
    from app.models.customer import Customer, CustomerPolicy
    from sqlalchemy import func as sqlfunc

    # Direct query
    pattern = f"%{policy_number.strip()}%"
    policies = db.query(CustomerPolicy).filter(
        CustomerPolicy.policy_number.ilike(pattern)
    ).limit(5).all()

    results = []
    for p in policies:
        customer = db.query(Customer).filter(Customer.id == p.customer_id).first()
        results.append({
            "policy_number": p.policy_number,
            "customer_id": p.customer_id,
            "customer_name": customer.full_name if customer else None,
            "customer_email": customer.email if customer else None,
            "nowcerts_id": customer.nowcerts_insured_id if customer else None,
        })

    # Also try the lookup_customer_sync function
    from app.services.smart_inbox_nowcerts import lookup_customer_sync
    match, method, conf = lookup_customer_sync(db, policy_number=policy_number)

    return {
        "query": policy_number,
        "pattern": pattern,
        "direct_policy_matches": results,
        "lookup_result": {
            "customer": match,
            "method": method,
            "confidence": conf,
        },
    }
