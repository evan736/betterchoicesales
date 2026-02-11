"""Agency configuration models — lead sources, carriers, etc."""
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class AgencyConfig(Base):
    """Key-value config store for agency settings like lead sources and carriers."""
    __tablename__ = "agency_config"

    id = Column(Integer, primary_key=True, index=True)
    config_type = Column(String, nullable=False, index=True)  # "carrier" or "lead_source"
    name = Column(String, nullable=False)  # normalized key e.g. "national_general"
    display_name = Column(String, nullable=False)  # pretty name e.g. "National General"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
