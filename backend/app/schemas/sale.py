from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal
from app.models.sale import SaleStatus, LeadSource


class SaleBase(BaseModel):
    policy_number: str
    written_premium: Decimal = Field(..., ge=0, decimal_places=2)
    lead_source: LeadSource
    item_count: int = Field(default=1, ge=1)
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    notes: Optional[str] = None


class SaleCreate(SaleBase):
    effective_date: Optional[datetime] = None


class SaleUpdate(BaseModel):
    written_premium: Optional[Decimal] = Field(None, ge=0)
    recognized_premium: Optional[Decimal] = Field(None, ge=0)
    status: Optional[SaleStatus] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    notes: Optional[str] = None
    signature_status: Optional[str] = None


class SaleInDB(SaleBase):
    id: int
    producer_id: int
    recognized_premium: Optional[Decimal]
    status: SaleStatus
    application_pdf_path: Optional[str]
    signature_request_id: Optional[str]
    signature_status: str
    sale_date: datetime
    effective_date: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class Sale(SaleInDB):
    pass


class SaleWithProducer(Sale):
    producer_name: str
    producer_code: Optional[str]
