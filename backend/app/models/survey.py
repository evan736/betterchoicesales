"""Survey/feedback models for post-sale rating."""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class SurveyResponse(Base):
    """Customer rating/feedback from welcome email survey."""
    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)
    
    # Rating 1-5
    rating = Column(Integer, nullable=False)
    
    # Optional feedback text (shown for <5 stars)
    feedback = Column(Text, nullable=True)
    
    # Tracking
    redirected_to_google = Column(Boolean, default=False)
    ip_address = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    sale = relationship("Sale", foreign_keys=[sale_id])
