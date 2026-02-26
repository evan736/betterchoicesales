"""Chat API — internal agency messaging + BEACON AI bot."""
import logging
import os
import re
import uuid
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db, SessionLocal
from app.core.security import get_current_user
from app.models.user import User
from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "chat-files")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _serialize_message(msg: ChatMessage, current_user_id: int = None) -> dict:
    return {
        "id": msg.id,
        "channel_id": msg.channel_id,
        "sender_id": msg.sender_id,
        "sender_name": msg.sender.full_name if msg.sender else "Unknown",
        "sender_username": msg.sender.username if msg.sender else "",
        "content": msg.content if not msg.is_deleted else "[Message deleted]",
        "message_type": msg.message_type,
        "file_name": msg.file_name,
        "file_path": f"/static/chat-files/{msg.file_path}" if msg.file_path else None,
        "file_type": msg.file_type,
        "file_size": msg.file_size,
        "mentions": msg.mentions or [],
        "reactions": msg.reactions or {},
        "reply_to_id": msg.reply_to_id,
        "is_edited": msg.is_edited,
        "is_deleted": msg.is_deleted,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _serialize_channel(channel: ChatChannel, current_user_id: int, db: Session) -> dict:
    members = db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == channel.id
    ).all()

    member_info = []
    for m in members:
        user = db.query(User).filter(User.id == m.user_id).first()
        if user:
            member_info.append({
                "user_id": user.id,
                "username": user.username,
                "full_name": user.full_name,
            })

    # Unread count
    my_membership = next((m for m in members if m.user_id == current_user_id), None)
    unread = 0
    if my_membership:
        q = db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.channel_id == channel.id,
            ChatMessage.is_deleted == False,
        )
        if my_membership.last_read_at:
            q = q.filter(ChatMessage.created_at > my_membership.last_read_at)
        unread = q.scalar() or 0

    # Channel display name
    name = channel.name
    if channel.channel_type == "dm" and not name:
        other = [m for m in member_info if m["user_id"] != current_user_id]
        name = other[0]["full_name"] if other else "Direct Message"

    return {
        "id": channel.id,
        "channel_type": channel.channel_type,
        "name": name,
        "members": member_info,
        "unread": unread,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }


# ── Channels ──

@router.get("/channels")
def list_channels(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all channels the current user is a member of."""
    my_channel_ids = db.query(ChatChannelMember.channel_id).filter(
        ChatChannelMember.user_id == current_user.id
    ).subquery()

    channels = db.query(ChatChannel).filter(
        ChatChannel.id.in_(my_channel_ids)
    ).order_by(ChatChannel.channel_type, ChatChannel.name).all()

    return [_serialize_channel(ch, current_user.id, db) for ch in channels]


@router.post("/channels/dm")
def get_or_create_dm(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get or create a DM channel with another user."""
    other_user_id = request.get("user_id")
    if not other_user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    
    other_user = db.query(User).filter(User.id == other_user_id).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if DM already exists between these two users
    my_channels = db.query(ChatChannelMember.channel_id).filter(
        ChatChannelMember.user_id == current_user.id
    ).subquery()
    
    their_channels = db.query(ChatChannelMember.channel_id).filter(
        ChatChannelMember.user_id == other_user_id
    ).subquery()

    existing = db.query(ChatChannel).filter(
        ChatChannel.id.in_(my_channels),
        ChatChannel.id.in_(their_channels),
        ChatChannel.channel_type == "dm",
    ).first()

    if existing:
        return _serialize_channel(existing, current_user.id, db)

    # Create new DM channel
    channel = ChatChannel(channel_type="dm", created_by=current_user.id)
    db.add(channel)
    db.flush()

    db.add(ChatChannelMember(channel_id=channel.id, user_id=current_user.id))
    db.add(ChatChannelMember(channel_id=channel.id, user_id=other_user_id))
    db.commit()

    return _serialize_channel(channel, current_user.id, db)


@router.post("/channels/ensure-office")
def ensure_office_channel(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ensure the office-wide channel exists and all active users are members."""
    office = db.query(ChatChannel).filter(ChatChannel.channel_type == "office").first()
    
    if not office:
        office = ChatChannel(channel_type="office", name="Office Chat", created_by=current_user.id)
        db.add(office)
        db.flush()

    # Add all active users
    all_users = db.query(User).filter(User.is_active == True).all()
    existing_members = {m.user_id for m in db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == office.id
    ).all()}

    for u in all_users:
        if u.id not in existing_members:
            db.add(ChatChannelMember(channel_id=office.id, user_id=u.id))

    db.commit()
    return _serialize_channel(office, current_user.id, db)


# ── BEACON Bot ──

BEACON_CHANNEL_NAME = "BEACON"
BEACON_BOT_USERNAME = "beacon.ai"

def _get_or_create_beacon_user(db: Session) -> User:
    """Ensure the BEACON bot system user exists."""
    bot = db.query(User).filter(User.username == BEACON_BOT_USERNAME).first()
    if not bot:
        bot = User(
            username=BEACON_BOT_USERNAME,
            full_name="BEACON",
            email="beacon@betterchoiceins.com",
            role="system",
            is_active=True,
        )
        # Set a random password hash (bot never logs in)
        bot.hashed_password = "!bot-no-login"
        db.add(bot)
        db.commit()
        db.refresh(bot)
        logger.info(f"Created BEACON bot user (id={bot.id})")
    return bot


def _get_beacon_channel(db: Session, user_id: int = None) -> Optional[ChatChannel]:
    """Get the BEACON channel for a specific user (private), or the legacy shared one."""
    if user_id:
        # Per-user private BEACON channel: name = "BEACON:<user_id>"
        return db.query(ChatChannel).filter(
            ChatChannel.name == f"BEACON:{user_id}",
            ChatChannel.channel_type == "beacon",
        ).first()
    # Legacy fallback
    return db.query(ChatChannel).filter(
        ChatChannel.name == BEACON_CHANNEL_NAME,
        ChatChannel.channel_type == "beacon",
    ).first()


def _beacon_respond_async(channel_id: int, user_message: str, sender_name: str):
    """Run BEACON AI response in a background thread (non-blocking)."""
    def _respond():
        try:
            from app.services.beacon import get_beacon_response, BEACON_USER_NAME
            db = SessionLocal()
            try:
                bot_user = _get_or_create_beacon_user(db)
                
                # Get recent messages for context
                recent = (
                    db.query(ChatMessage)
                    .options(joinedload(ChatMessage.sender))
                    .filter(ChatMessage.channel_id == channel_id)
                    .order_by(ChatMessage.id.desc())
                    .limit(20)
                    .all()
                )
                history = []
                for m in reversed(recent):
                    history.append({
                        "sender_name": m.sender.full_name if m.sender else "Unknown",
                        "content": m.content or "",
                    })
                
                # Get AI response (with knowledge base context)
                response_text, model_used = get_beacon_response(user_message, history, db_session=db)
                
                # Detect corrections: if user said "actually...", "that's wrong", "correction:" etc.
                correction_patterns = [
                    r"(?:actually|correction|that'?s (?:wrong|incorrect|not right)|you'?re wrong|no,?\s+it'?s|fyi|update:)",
                ]
                is_correction = any(re.search(p, user_message, re.IGNORECASE) for p in correction_patterns)
                if is_correction and len(user_message) > 20:
                    try:
                        from app.api.beacon_kb import BeaconKnowledge
                        # Auto-save correction as pending knowledge
                        correction = BeaconKnowledge(
                            source_type="correction",
                            title=f"Correction: {user_message[:80]}...",
                            content=f"Agent correction from {sender_name}:\n\n{user_message}",
                            summary=user_message[:200],
                            status="pending",
                            submitted_by_name=sender_name,
                        )
                        db.add(correction)
                        db.commit()
                        logger.info(f"Auto-saved correction from {sender_name}")
                    except Exception as ce:
                        logger.warning(f"Failed to save correction: {ce}")
                
                # Post response as BEACON
                bot_msg = ChatMessage(
                    channel_id=channel_id,
                    sender_id=bot_user.id,
                    content=response_text,
                    message_type="text",
                )
                db.add(bot_msg)
                db.commit()
                db.refresh(bot_msg)
                
                # Broadcast via SSE
                try:
                    from app.api.events import event_bus
                    event_bus.publish_sync("chat:message", {
                        "channel_id": channel_id,
                        "message": _serialize_message(bot_msg),
                    })
                except Exception as e:
                    logger.warning(f"BEACON SSE broadcast failed: {e}")
                
                logger.info(f"BEACON responded in channel {channel_id} using {model_used}")
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"BEACON response error: {e}", exc_info=True)
    
    thread = threading.Thread(target=_respond, daemon=True)
    thread.start()


@router.post("/channels/ensure-beacon")
def ensure_beacon_channel(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ensure a private BEACON AI channel exists for this user."""
    bot_user = _get_or_create_beacon_user(db)

    # Look for this user's private BEACON channel
    beacon = _get_beacon_channel(db, user_id=current_user.id)

    if not beacon:
        beacon = ChatChannel(
            channel_type="beacon",
            name=f"BEACON:{current_user.id}",
            created_by=bot_user.id,
        )
        db.add(beacon)
        db.flush()

        # Add bot + this user as members
        db.add(ChatChannelMember(channel_id=beacon.id, user_id=bot_user.id))
        db.add(ChatChannelMember(channel_id=beacon.id, user_id=current_user.id))

        # Post welcome message
        welcome = ChatMessage(
            channel_id=beacon.id,
            sender_id=bot_user.id,
            content="👋 Welcome to BEACON — your AI insurance knowledge assistant!\n\nI can help with:\n• **Carrier appetites & guidelines** — Who writes what, where\n• **State regulations** — All 50 states\n• **Cancellation/non-renewal processes** — By carrier\n• **Underwriter contacts** — Who to call\n• **Quoting & binding procedures** — Step by step\n• **Claims processes** — Filing & follow-up\n• **Coverage comparisons** — HO-3 vs HO-5, liability limits, etc.\n\nJust type your question and I'll respond. I use ⚡ quick mode for simple lookups and 🧠 deep mode for complex analysis.\n\nTry asking: *\"Does NatGen write homes with trampolines in Ohio?\"*",
            message_type="text",
        )
        db.add(welcome)

    db.commit()
    return _serialize_channel(beacon, current_user.id, db)


@router.post("/channels/beacon/clear")
def clear_beacon_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear all messages in this user's BEACON channel (except welcome)."""
    beacon = _get_beacon_channel(db, user_id=current_user.id)
    if not beacon:
        return {"cleared": 0}

    bot_user = _get_or_create_beacon_user(db)

    # Delete all messages except the first one (welcome)
    first_msg = db.query(ChatMessage).filter(
        ChatMessage.channel_id == beacon.id,
    ).order_by(ChatMessage.id.asc()).first()

    if first_msg:
        deleted = db.query(ChatMessage).filter(
            ChatMessage.channel_id == beacon.id,
            ChatMessage.id != first_msg.id,
        ).delete(synchronize_session=False)
    else:
        deleted = 0

    db.commit()
    logger.info(f"Cleared {deleted} BEACON messages for user {current_user.username}")
    return {"cleared": deleted}


# ── Messages ──

@router.get("/channels/{channel_id}/messages")
def get_messages(
    channel_id: int,
    before: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get messages for a channel (paginated, newest first)."""
    # Verify membership
    member = db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == channel_id,
        ChatChannelMember.user_id == current_user.id,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this channel")

    q = db.query(ChatMessage).options(
        joinedload(ChatMessage.sender)
    ).filter(ChatMessage.channel_id == channel_id)

    if before:
        q = q.filter(ChatMessage.id < before)

    messages = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    
    return [_serialize_message(m, current_user.id) for m in reversed(messages)]


@router.post("/channels/{channel_id}/messages")
def send_message(
    channel_id: int,
    content: str = Form(None),
    message_type: str = Form("text"),
    mentions: str = Form(None),  # comma-separated user IDs
    reply_to_id: int = Form(None),
    file: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message (text, file, or both)."""
    member = db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == channel_id,
        ChatChannelMember.user_id == current_user.id,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this channel")

    if not content and not file:
        raise HTTPException(status_code=400, detail="Message must have content or a file")

    # Handle file upload
    file_name = None
    file_path = None
    file_type = None
    file_size = None

    if file:
        ext = os.path.splitext(file.filename)[1].lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        
        file_bytes = file.file.read()
        file_size = len(file_bytes)
        
        if file_size > 25 * 1024 * 1024:  # 25MB limit
            raise HTTPException(status_code=400, detail="File too large (max 25MB)")

        with open(save_path, "wb") as f:
            f.write(file_bytes)

        file_name = file.filename
        file_path = unique_name
        file_type = ext.lstrip(".")
        if not message_type or message_type == "text":
            message_type = "file"

    # Parse mentions
    mention_ids = None
    if mentions:
        try:
            mention_ids = [int(x.strip()) for x in mentions.split(",") if x.strip()]
        except ValueError:
            mention_ids = None

    msg = ChatMessage(
        channel_id=channel_id,
        sender_id=current_user.id,
        content=content,
        message_type=message_type,
        file_name=file_name,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        mentions=mention_ids,
        reply_to_id=reply_to_id,
    )
    db.add(msg)

    # Update sender's last_read_at
    member.last_read_at = datetime.utcnow()
    
    db.commit()
    db.refresh(msg)

    # Broadcast via SSE for live chat
    try:
        from app.api.events import event_bus
        event_bus.publish_sync("chat:message", {
            "channel_id": channel_id,
            "message": _serialize_message(msg, current_user.id),
        })
    except Exception as e:
        logger.warning(f"SSE chat broadcast failed: {e}")

    # BEACON auto-response: if this is the BEACON channel, trigger AI response
    try:
        channel = db.query(ChatChannel).filter(ChatChannel.id == channel_id).first()
        if channel and channel.channel_type == "beacon" and current_user.username != BEACON_BOT_USERNAME:
            _beacon_respond_async(channel_id, content or "", current_user.full_name or current_user.username)
    except Exception as e:
        logger.warning(f"BEACON trigger failed: {e}")

    return _serialize_message(msg, current_user.id)
def mark_read(
    channel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark channel as read."""
    member = db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == channel_id,
        ChatChannelMember.user_id == current_user.id,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member")
    
    member.last_read_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ── Reactions ──

@router.post("/messages/{message_id}/react")
def toggle_reaction(
    message_id: int,
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle a reaction emoji on a message."""
    emoji = request.get("emoji", "")
    if not emoji:
        raise HTTPException(status_code=400, detail="emoji required")

    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    reactions = msg.reactions or {}
    users_for_emoji = reactions.get(emoji, [])

    if current_user.id in users_for_emoji:
        users_for_emoji.remove(current_user.id)
    else:
        users_for_emoji.append(current_user.id)

    if users_for_emoji:
        reactions[emoji] = users_for_emoji
    else:
        reactions.pop(emoji, None)

    msg.reactions = reactions
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(msg, "reactions")
    db.commit()

    return {"reactions": msg.reactions}


# ── Delete / Edit ──

@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a message (sender or admin only)."""
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if msg.sender_id != current_user.id and current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Can only delete your own messages")

    msg.is_deleted = True
    db.commit()
    return {"ok": True}


@router.patch("/messages/{message_id}")
def edit_message(
    message_id: int,
    request: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a message (sender only)."""
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only edit your own messages")

    msg.content = request.get("content", msg.content)
    msg.is_edited = True
    db.commit()

    return _serialize_message(msg, current_user.id)


# ── Notifications / Unread ──

@router.get("/unread")
def get_unread_counts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get unread message counts per channel + mention alerts."""
    memberships = db.query(ChatChannelMember).filter(
        ChatChannelMember.user_id == current_user.id
    ).all()

    channels = []
    total_unread = 0
    total_mentions = 0

    for m in memberships:
        q = db.query(ChatMessage).filter(
            ChatMessage.channel_id == m.channel_id,
            ChatMessage.is_deleted == False,
            ChatMessage.sender_id != current_user.id,
        )
        if m.last_read_at:
            q = q.filter(ChatMessage.created_at > m.last_read_at)

        unread = q.count()
        
        # Count mentions specifically
        mention_count = 0
        if unread > 0:
            unread_msgs = q.all()
            for msg in unread_msgs:
                if msg.mentions and current_user.id in msg.mentions:
                    mention_count += 1

        total_unread += unread
        total_mentions += mention_count

        if unread > 0:
            channels.append({
                "channel_id": m.channel_id,
                "unread": unread,
                "mentions": mention_count,
            })

    return {
        "total_unread": total_unread,
        "total_mentions": total_mentions,
        "channels": channels,
    }


# ── Admin: All Chat History ──

@router.get("/admin/history")
def admin_chat_history(
    channel_id: Optional[int] = None,
    user_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin-only: view all chat history across channels with search."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    q = db.query(ChatMessage).options(joinedload(ChatMessage.sender))

    if channel_id:
        q = q.filter(ChatMessage.channel_id == channel_id)
    if user_id:
        q = q.filter(ChatMessage.sender_id == user_id)
    if search:
        q = q.filter(ChatMessage.content.ilike(f"%{search}%"))

    total = q.count()
    messages = q.order_by(ChatMessage.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # Get channel info
    channel_map = {}
    for msg in messages:
        if msg.channel_id not in channel_map:
            ch = db.query(ChatChannel).filter(ChatChannel.id == msg.channel_id).first()
            channel_map[msg.channel_id] = ch.name or f"DM #{ch.id}" if ch else "Unknown"

    return {
        "total": total,
        "page": page,
        "messages": [{
            **_serialize_message(m),
            "channel_name": channel_map.get(m.channel_id, "Unknown"),
        } for m in messages],
    }


# ── Search messages (user-facing) ──

@router.get("/search")
def search_messages(
    q: str = Query("", min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search messages across all channels the user is a member of."""
    my_channel_ids = [cid for (cid,) in db.query(ChatChannelMember.channel_id).filter(
        ChatChannelMember.user_id == current_user.id
    ).all()]

    if not my_channel_ids:
        return {"results": []}

    messages = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.sender))
        .filter(
            ChatMessage.channel_id.in_(my_channel_ids),
            ChatMessage.is_deleted == False,
            ChatMessage.content.ilike(f"%{q}%"),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(30)
        .all()
    )

    # Get channel names
    channel_map = {}
    for msg in messages:
        if msg.channel_id not in channel_map:
            ch = db.query(ChatChannel).filter(ChatChannel.id == msg.channel_id).first()
            if ch:
                if ch.channel_type == "office":
                    channel_map[msg.channel_id] = ch.name or "Office Chat"
                else:
                    members = db.query(ChatChannelMember).filter(ChatChannelMember.channel_id == ch.id).all()
                    names = []
                    for m in members:
                        u = db.query(User).filter(User.id == m.user_id).first()
                        if u and u.id != current_user.id:
                            names.append(u.full_name)
                    channel_map[msg.channel_id] = " & ".join(names) if names else "DM"

    return {
        "results": [{
            **_serialize_message(m, current_user.id),
            "channel_name": channel_map.get(m.channel_id, "Unknown"),
        } for m in messages]
    }


# ── Users list for DM ──

@router.get("/users")
def list_chat_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active users for starting DMs."""
    users = db.query(User).filter(User.is_active == True, User.id != current_user.id).all()
    return [{
        "id": u.id,
        "username": u.username,
        "full_name": u.full_name,
        "role": u.role,
    } for u in users]


@router.get("/admin/channels")
def admin_list_channels(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: list ALL channels with member info and message counts."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    channels = db.query(ChatChannel).order_by(ChatChannel.channel_type, ChatChannel.id).all()
    result = []
    for ch in channels:
        members = db.query(ChatChannelMember).filter(ChatChannelMember.channel_id == ch.id).all()
        member_names = []
        for m in members:
            u = db.query(User).filter(User.id == m.user_id).first()
            if u:
                member_names.append({"user_id": u.id, "full_name": u.full_name, "username": u.username})

        msg_count = db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.channel_id == ch.id
        ).scalar() or 0

        last_msg = db.query(ChatMessage).filter(
            ChatMessage.channel_id == ch.id, ChatMessage.is_deleted == False
        ).order_by(ChatMessage.created_at.desc()).first()

        name = ch.name
        if ch.channel_type == "dm" and not name:
            name = " & ".join(m["full_name"] for m in member_names)

        result.append({
            "id": ch.id,
            "channel_type": ch.channel_type,
            "name": name,
            "members": member_names,
            "message_count": msg_count,
            "last_message_at": last_msg.created_at.isoformat() if last_msg else None,
            "last_message_preview": (last_msg.content or "")[:80] if last_msg else None,
            "last_sender": last_msg.sender.full_name if last_msg and last_msg.sender else None,
        })

    return result


@router.get("/admin/channels/{channel_id}/messages")
def admin_channel_messages(
    channel_id: int,
    search: Optional[str] = None,
    before: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: get all messages for a specific channel (chat-style view)."""
    if current_user.role.lower() not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")

    q = db.query(ChatMessage).options(
        joinedload(ChatMessage.sender)
    ).filter(ChatMessage.channel_id == channel_id)

    if search:
        q = q.filter(ChatMessage.content.ilike(f"%{search}%"))
    if before:
        q = q.filter(ChatMessage.id < before)

    messages = q.order_by(ChatMessage.id.desc()).limit(limit).all()

    return [_serialize_message(m) for m in reversed(messages)]
