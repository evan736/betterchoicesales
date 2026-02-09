from sqlalchemy import Column, Integer, String, Numeric, DateTime, Enum, Text, Boolean
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
    MATCHED = "matched"
    PARTIALLY_MATCHED = "partially_matched"
    FAILED = "failed"
    COMPLETED = "completed"


class CarrierType(str, enum.Enum):
    NATIONAL_GENERAL = "national_general"
    PROGRESSIVE = "progressive"
    OTHER = "other"


class StatementImport(Base):
    """Staging table for carrier commission statement imports"""
    __tablename__ = "statement_imports"

    id = Column(Integer, primary_key=True, index=True)
    
    # File information
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_format = Column(Enum(StatementFormat), nullable=False)
    file_size = Column(Integer, nullable=True)
    
    # Carrier information
    carrier = Column(Enum(CarrierType), nullable=False)
    statement_period = Column(String, nullable=True)  # e.g., "2024-01" for January 2024
    
    # Processing status
    status = Column(Enum(StatementStatus), default=StatementStatus.UPLOADED, nullable=False)
    
    # Processing results
    total_rows = Column(Integer, default=0)
    matched_rows = Column(Integer, default=0)
    unmatched_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    
    # Metadata
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class StatementLine(Base):
    """Individual lines from commission statements before matching"""
    __tablename__ = "statement_lines"

    id = Column(Integer, primary_key=True, index=True)
    
    # Link to import batch
    statement_import_id = Column(Integer, nullable=False, index=True)
    
    # Raw data from statement
    policy_number = Column(String, index=True, nullable=False)
    premium_amount = Column(Numeric(10, 2), nullable=True)
    commission_amount = Column(Numeric(10, 2), nullable=True)
    transaction_type = Column(String, nullable=True)  # new_business, renewal, cancellation, etc.
    transaction_date = Column(DateTime(timezone=True), nullable=True)
    
    # Matching status
    is_matched = Column(Boolean, default=False)
    matched_sale_id = Column(Integer, nullable=True, index=True)
    
    # Raw data (JSON-like text field for flexibility)
    raw_data = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    matched_at = Column(DateTime(timezone=True), nullable=True)
