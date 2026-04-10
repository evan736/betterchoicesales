"""Internal agency chat — messages, channels, read receipts."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ChatChannel(Base):
    """Chat channel — 'office' for group, or DM channels."""
    __tablename__ = "chat_channels"

    id = Column(Integer, primary_key=True, index=True)
    channel_type = Column(String, nullable=False, default="office")  # office, dm
    name = Column(String, nullable=True)  # "Office Chat", or null for DMs
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    messages = relationship("ChatMessage", back_populates="channel", cascade="all, delete-orphan")
    members = relationship("ChatChannelMember", back_populates="channel", cascade="all, delete-orphan")


class ChatChannelMember(Base):
    """Channel membership — tracks who's in each channel + last read."""
    __tablename__ = "chat_channel_members"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    last_read_at = Column(DateTime(timezone=True), nullable=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    channel = relationship("ChatChannel", back_populates="members")
    user = relationship("User")


class ChatMessage(Base):
    """Individual chat message."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=True)  # Text content (can be null if file-only)
    message_type = Column(String, default="text")  # text, file, gif, system
    
    # File attachment
    file_name = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    file_type = Column(String, nullable=True)  # pdf, image, etc.
    file_size = Column(Integer, nullable=True)
    # NOTE: file_data BYTEA column exists in DB but NOT on model —
    # read/write via raw SQL only to avoid SQLAlchemy INSERT issues

    # @mentions — list of user IDs mentioned
    mentions = Column(JSON, nullable=True)  # [1, 3, 5]
    
    # Reactions — {emoji: [user_id, ...]}
    reactions = Column(JSON, nullable=True)  # {"👍": [1, 2], "🎉": [3]}

    # Reply threading
    reply_to_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=True)
    
    is_edited = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    channel = relationship("ChatChannel", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    reply_to = relationship("ChatMessage", remote_side=[id], foreign_keys=[reply_to_id])


class ChatMessageRead(Base):
    """Tracks per-message read receipts for DMs and @mentions."""
    __tablename__ = "chat_message_reads"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), server_default=func.now())
