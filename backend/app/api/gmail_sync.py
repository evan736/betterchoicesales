"""Gmail Workspace Sync — pull email history from Google Workspace into ORBIT inbox.

Two authentication methods supported:
1. OAuth2 (user-initiated): User authorizes via Google, we get an access token
2. App Password (simpler): Use Gmail IMAP with app-specific password

This module uses the Gmail API (OAuth2) for the cleanest integration.
"""
import logging
import os
import base64
import email
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.email import EmailThread, EmailMessage
from app.models.customer import Customer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/email/gmail", tags=["gmail-sync"])

# Store OAuth tokens in memory (per-user, session-only)
_oauth_tokens: dict = {}

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT_URI = "https://better-choice-api.onrender.com/api/email/gmail/oauth-callback"


# ══════════════════════════════════════════════════════════════════════
# OAUTH2 FLOW
# ══════════════════════════════════════════════════════════════════════

@router.get("/oauth-start")
def gmail_oauth_start(
    current_user: User = Depends(get_current_user),
):
    """Start OAuth2 flow — redirects user to Google consent screen."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not configured")
    
    from google_auth_oauthlib.flow import Flow
    
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=str(current_user.id),
    )
    
    return {"auth_url": auth_url}


@router.get("/oauth-callback")
def gmail_oauth_callback(
    code: str = Query(...),
    state: str = Query(""),
):
    """Handle OAuth2 callback from Google."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    from google_auth_oauthlib.flow import Flow
    
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    user_id = state
    _oauth_tokens[user_id] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
    }
    
    logger.info(f"Gmail OAuth complete for user {user_id}")
    return RedirectResponse(url="https://better-choice-web.onrender.com/inbox?gmail_connected=true")


# ══════════════════════════════════════════════════════════════════════
# SYNC ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@router.post("/sync")
def sync_gmail(
    gmail_address: str = Query(..., description="Gmail address to sync, e.g. evan@betterchoiceins.com"),
    days: int = Query(30, description="How many days back to sync"),
    max_messages: int = Query(200, description="Max messages to pull"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync email history from a Gmail/Workspace account into ORBIT inbox.
    
    Requires either:
    - OAuth2 token (from /oauth-start flow)
    - GOOGLE_SERVICE_ACCOUNT_JSON env var (for domain-wide delegation)
    """
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    service = _get_gmail_service(str(current_user.id), gmail_address)
    if not service:
        raise HTTPException(
            status_code=401,
            detail="Gmail not connected. Visit /api/email/gmail/oauth-start to authorize, or configure GOOGLE_SERVICE_ACCOUNT_JSON for domain-wide delegation."
        )
    
    after_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"after:{after_date}"
    
    synced = 0
    skipped = 0
    errors = 0
    
    try:
        # List messages
        next_page = None
        fetched = 0
        
        while fetched < max_messages:
            result = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=min(50, max_messages - fetched),
                pageToken=next_page,
            ).execute()
            
            msg_list = result.get("messages", [])
            if not msg_list:
                break
            
            for msg_ref in msg_list:
                try:
                    r = _sync_gmail_message(service, db, msg_ref["id"], gmail_address)
                    if r == "synced":
                        synced += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Gmail sync message error: {e}")
                fetched += 1
            
            db.commit()
            
            next_page = result.get("nextPageToken")
            if not next_page:
                break
        
        return {
            "status": "complete",
            "gmail_address": gmail_address,
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "total_checked": fetched,
        }
        
    except Exception as e:
        logger.error(f"Gmail sync failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gmail sync failed: {str(e)}")


@router.get("/status")
def gmail_status(
    current_user: User = Depends(get_current_user),
):
    """Check if Gmail is connected for the current user."""
    token_data = _oauth_tokens.get(str(current_user.id))
    has_service_account = bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    
    return {
        "oauth_connected": token_data is not None,
        "service_account_configured": has_service_account,
        "user_email": current_user.email,
    }


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _get_gmail_service(user_id: str, gmail_address: str):
    """Get Gmail API service using OAuth2 token or service account."""
    from googleapiclient.discovery import build
    
    # Try OAuth2 token first
    token_data = _oauth_tokens.get(user_id)
    if token_data:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=token_data["token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
        )
        return build("gmail", "v1", credentials=creds)
    
    # Try service account with domain-wide delegation
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        import json
        from google.oauth2 import service_account
        
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        ).with_subject(gmail_address)
        return build("gmail", "v1", credentials=creds)
    
    return None


def _sync_gmail_message(service, db: Session, msg_id: str, gmail_address: str) -> str:
    """Fetch and sync a single Gmail message into ORBIT inbox."""
    from app.api.email_inbox import (
        _parse_email_address, _parse_email_list,
        _determine_mailbox, _find_or_create_thread, _link_customer,
    )
    
    # Fetch full message
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    
    message_id = headers.get("message-id", "")
    if not message_id:
        message_id = f"gmail-{msg_id}"
    
    # Duplicate check
    existing = db.query(EmailMessage).filter(
        EmailMessage.mailgun_message_id == message_id
    ).first()
    if existing:
        return "skipped"
    
    from_raw = headers.get("from", "")
    to_raw = headers.get("to", "")
    cc_raw = headers.get("cc", "")
    subject = headers.get("subject", "(No Subject)")
    date_str = headers.get("date", "")
    in_reply_to = headers.get("in-reply-to", "")
    references = headers.get("references", "")
    
    from_name, from_addr = _parse_email_address(from_raw)
    to_list = _parse_email_list(to_raw)
    cc_list = _parse_email_list(cc_raw)
    
    # Parse date
    created_at = datetime.utcnow()
    if date_str:
        try:
            from email.utils import parsedate_to_datetime
            created_at = parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            pass
    
    # Internal timestamp from Gmail
    internal_date = msg.get("internalDate")
    if internal_date:
        try:
            created_at = datetime.utcfromtimestamp(int(internal_date) / 1000)
        except Exception:
            pass
    
    # Determine direction
    is_outbound = gmail_address.lower() in from_addr.lower()
    direction = "outbound" if is_outbound else "inbound"
    
    # Mailbox
    if direction == "inbound":
        mailbox = _determine_mailbox(to_list + cc_list)
    else:
        # For outbound, determine by who it was sent TO
        mailbox = _determine_mailbox(to_list)
        if mailbox == "service":
            # Map based on sender's email prefix
            prefix = gmail_address.split("@")[0].lower()
            mailbox = prefix
    
    # Extract body
    body_text = _extract_gmail_body(msg.get("payload", {}))
    
    # Thread
    thread = _find_or_create_thread(
        db, subject=subject, from_email=from_addr, from_name=from_name,
        to_emails=to_list, cc_emails=cc_list, mailbox=mailbox,
        in_reply_to=in_reply_to, references=references,
    )
    
    # Create message
    email_msg = EmailMessage(
        thread_id=thread.id,
        direction=direction,
        from_email=from_addr,
        from_name=from_name,
        to_emails=to_list,
        cc_emails=cc_list,
        subject=subject,
        body_text=body_text,
        body_html="",
        attachments=[],
        mailgun_message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        read_by={},
        created_at=created_at,
    )
    db.add(email_msg)
    
    if not thread.last_message_at or created_at > thread.last_message_at:
        thread.last_message_at = created_at
    
    if direction == "inbound":
        _link_customer(db, thread, from_addr)
    
    return "synced"


def _extract_gmail_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    # Direct body
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    
    # Multipart — recurse
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    
    # Try nested multipart
    for part in parts:
        if part.get("mimeType", "").startswith("multipart/"):
            result = _extract_gmail_body(part)
            if result:
                return result
    
    # Fallback: try HTML
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            # Strip tags for plain text
            import re
            return re.sub(r'<[^>]+>', '', html)[:2000]
    
    return ""
