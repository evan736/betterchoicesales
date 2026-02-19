from sqlalchemy import Column, Integer, String, Numeric, DateTime, Enum, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class StatementFormat(str, enum.Enum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class StatementStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    MATCHED = "matched"              # was "processed" - file parsed successfully
    PARTIALLY_MATCHED = "partially_matched"  # was "reconciled" - matching done
    COMPLETED = "completed"          # was "approved"
    FAILED = "failed"


class CarrierType(str, enum.Enum):
    NATIONAL_GENERAL = "national_general"
    PROGRESSIVE = "progressive"
    GRANGE = "grange"
    SAFECO = "safeco"
    TRAVELERS = "travelers"
    GEICO = "geico"
    FIRST_CONNECT = "first_connect"
    UNIVERSAL = "universal"
    NBS = "nbs"
    HARTFORD = "hartford"
    OTHER = "other"


class TransactionType(str, enum.Enum):
    NEW_BUSINESS = "new_business"
    RENEWAL = "renewal"
    ENDORSEMENT = "endorsement"
    CANCELLATION = "cancellation"
    REINSTATEMENT = "reinstatement"
    AUDIT = "audit"
    ADJUSTMENT = "adjustment"
    OTHER = "other"


class StatementImport(Base):
    """Carrier commission statement upload"""
    __tablename__ = "statement_imports"

    id = Column(Integer, primary_key=True, index=True)

    # File info
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_format = Column(Enum(StatementFormat), nullable=False)
    file_size = Column(Integer, nullable=True)

    # Carrier & period - use String to avoid enum issues with new carriers
    carrier = Column(String, nullable=False, index=True)
    statement_period = Column(String, nullable=False, index=True)  # "2026-01"

    # Status
    status = Column(Enum(StatementStatus), default=StatementStatus.UPLOADED, nullable=False)

    # Processing results
    total_rows = Column(Integer, default=0)
    matched_rows = Column(Integer, default=0)
    unmatched_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)

    # Totals from statement
    total_premium = Column(Numeric(12, 2), default=0)
    total_commission = Column(Numeric(12, 2), default=0)

    # Timestamps
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    lines = relationship("StatementLine", back_populates="statement_import", cascade="all, delete-orphan")


class StatementLine(Base):
    """Individual line from a commission statement"""
    __tablename__ = "statement_lines"

    id = Column(Integer, primary_key=True, index=True)
    statement_import_id = Column(Integer, ForeignKey("statement_imports.id"), nullable=False, index=True)

    # Parsed fields (normalized across carriers)
    policy_number = Column(String, nullable=False, index=True)
    insured_name = Column(String, nullable=True)
    transaction_type = Column(String, nullable=True)  # normalized: new_business, renewal, etc.
    transaction_type_raw = Column(String, nullable=True)  # Original from carrier
    transaction_date = Column(DateTime(timezone=True), nullable=True)
    effective_date = Column(DateTime(timezone=True), nullable=True)

    # Financial
    premium_amount = Column(Numeric(12, 2), nullable=True)
    commission_rate = Column(Numeric(5, 4), nullable=True)  # 0.1500 = 15%
    commission_amount = Column(Numeric(12, 2), nullable=True)

    # Extra carrier-specific fields
    producer_name = Column(String, nullable=True)  # Producer name from statement
    product_type = Column(String, nullable=True)
    line_of_business = Column(String, nullable=True)
    state = Column(String(2), nullable=True)
    term_months = Column(Integer, nullable=True)  # 6 or 12

    # Matching
    is_matched = Column(Boolean, default=False)
    matched_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True, index=True)
    match_confidence = Column(String, nullable=True)  # "exact", "fuzzy", "manual"

    # Agent assignment (resolved after matching)
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    agent_commission_amount = Column(Numeric(12, 2), nullable=True)
    agent_commission_rate = Column(Numeric(5, 4), nullable=True)

    # Raw data for debugging
    raw_data = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    matched_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    statement_import = relationship("StatementImport", back_populates="lines")
    matched_sale = relationship("Sale", foreign_keys=[matched_sale_id])
    assigned_agent = relationship("User", foreign_keys=[assigned_agent_id])
