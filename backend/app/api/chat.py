"""Chat API — internal agency messaging."""
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
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

    return _serialize_message(msg, current_user.id)


@router.post("/channels/{channel_id}/read")
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
