from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal


class SaleBase(BaseModel):
    policy_number: str
    written_premium: Decimal = Field(..., ge=0, decimal_places=2)
    lead_source: Optional[str] = None
    policy_type: Optional[str] = None
    carrier: Optional[str] = None
    state: Optional[str] = None
    item_count: int = Field(default=1, ge=1)
    client_name: str
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    notes: Optional[str] = None


class SaleCreate(SaleBase):
    effective_date: Optional[datetime] = None
    sale_date: Optional[datetime] = None


class SaleUpdate(BaseModel):
    written_premium: Optional[Decimal] = Field(None, ge=0)
    recognized_premium: Optional[Decimal] = Field(None, ge=0)
    policy_type: Optional[str] = None
    carrier: Optional[str] = None
    state: Optional[str] = None
    status: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    notes: Optional[str] = None
    signature_status: Optional[str] = None


class SaleInDB(SaleBase):
    id: int
    producer_id: int
    recognized_premium: Optional[Decimal] = None
    status: Optional[str] = None
    commission_status: Optional[str] = None
    commission_paid_date: Optional[datetime] = None
    commission_paid_period: Optional[str] = None
    cancelled_date: Optional[datetime] = None
    days_to_cancel: Optional[int] = None
    welcome_email_sent: Optional[bool] = None
    welcome_email_sent_at: Optional[datetime] = None
    application_pdf_path: Optional[str] = None
    signature_request_id: Optional[str] = None
    signature_status: Optional[str] = None
    sale_date: Optional[datetime] = None
    effective_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Sale(SaleInDB):
    pass


class SaleWithProducer(Sale):
    producer_name: Optional[str] = None
    producer_code: Optional[str] = None
